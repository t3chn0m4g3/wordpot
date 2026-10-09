import json
import os
import threading

import pytest
from flask import request

os.environ.setdefault("WORDPOT_LOG_DIR", "/tmp/wordpot-test-logs")

from wordpot import app  # noqa: E402
import wordpot.events as events_module  # noqa: E402
from wordpot.events import build_event_dict, log_event  # noqa: E402
from wordpot.profiles import client_ip_from_request, current_profile  # noqa: E402


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def event_log(tmp_path):
    old_event_log_file = app.config.get("EVENT_LOG_FILE")
    path = tmp_path / "wordpot.json"
    app.config["EVENT_LOG_FILE"] = str(path)
    yield path
    app.config["EVENT_LOG_FILE"] = old_event_log_file


def read_events(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_src_ip_ignores_spoofed_proxy_headers():
    with app.test_request_context(
        "/wp-login.php",
        headers={"X-Real-IP": "8.8.8.8", "X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
        environ_base={"REMOTE_ADDR": "203.0.113.50"},
    ):
        assert client_ip_from_request(request) == "203.0.113.50"
        event = build_event_dict(request, current_profile(), technique="login_page", include_payload=False)

    assert event["src_ip"] == "203.0.113.50"


def test_healthcheck_header_does_not_suppress_events():
    with app.test_request_context(
        "/wp-login.php",
        headers={"X-Wordpot-Healthcheck": "1"},
        environ_base={"REMOTE_ADDR": "203.0.113.51"},
    ):
        event = log_event(request, current_profile(), technique="login_page", include_payload=False)

    assert event is not None


def test_healthz_is_only_quiet_for_loopback(client, event_log):
    local = client.get("/healthz", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    remote = client.get("/healthz", environ_base={"REMOTE_ADDR": "203.0.113.52"})

    assert local.status_code == 200
    assert local.get_data(as_text=True) == "ok\n"
    assert remote.status_code == 404
    assert "ok" != remote.get_data(as_text=True).strip()

    events = read_events(event_log)
    assert [event["src_ip"] for event in events] == ["203.0.113.52"]


def test_dest_ip_does_not_come_from_host_header():
    with app.test_request_context(
        "/wp-json/",
        headers={"Host": "8.8.8.8:31337"},
        environ_overrides={"SERVER_NAME": "8.8.8.8", "SERVER_PORT": "31337"},
    ):
        event = build_event_dict(request, current_profile(), technique="rest_index", include_payload=False)

    assert event.get("dest_ip") != "8.8.8.8"
    assert event["details"]["http_host"] == "8.8.8.8:31337"


def test_dest_ip_uses_listening_socket_address():
    class FakeSocket:
        def getsockname(self):
            return ("198.51.100.20", 80)

    with app.test_request_context(
        "/wp-json/",
        headers={"Host": "evil.example"},
        environ_overrides={"gunicorn.socket": FakeSocket()},
    ):
        event = build_event_dict(request, current_profile(), technique="rest_index", include_payload=False)

    assert event["dest_ip"] == "198.51.100.20"


def test_dest_ip_override_wins():
    old = app.config.get("EVENT_DEST_IP")
    app.config["EVENT_DEST_IP"] = "192.0.2.10"
    try:
        with app.test_request_context("/wp-json/", headers={"Host": "evil.example"}):
            event = build_event_dict(request, current_profile(), technique="rest_index", include_payload=False)
    finally:
        app.config["EVENT_DEST_IP"] = old

    assert event["dest_ip"] == "192.0.2.10"


def test_concurrent_large_events_stay_valid_jsonl(event_log):
    excerpt = "�" * 6000

    def writer(index):
        for item in range(20):
            events_module.publish_event({"request_id": "%s-%s" % (index, item), "payload_excerpt": excerpt})

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    events = read_events(event_log)
    assert len(events) == 160
    assert len({event["request_id"] for event in events}) == 160


def test_event_log_rotation_is_optional(event_log):
    old = (app.config.get("EVENT_LOG_MAX_BYTES"), app.config.get("EVENT_LOG_BACKUP_COUNT"))
    app.config["EVENT_LOG_MAX_BYTES"] = 200
    app.config["EVENT_LOG_BACKUP_COUNT"] = 2
    try:
        for index in range(10):
            events_module.publish_event({"request_id": "rotate-%s" % index, "pad": "x" * 80})
    finally:
        app.config["EVENT_LOG_MAX_BYTES"], app.config["EVENT_LOG_BACKUP_COUNT"] = old

    assert event_log.exists()
    assert (event_log.parent / "wordpot.json.1").exists()
    assert not (event_log.parent / "wordpot.json.3").exists()


def test_hpfeeds_client_is_created_per_process(monkeypatch):
    created = []

    class FakeClient:
        def __init__(self):
            self.published = []

        def publish(self, topic, line):
            self.published.append((topic, line))

    def factory():
        client = FakeClient()
        created.append(client)
        return client

    monkeypatch.setitem(app.config, "HPFEEDS_ENABLED", True)
    monkeypatch.setattr(events_module, "_create_hpfeeds_client", factory)
    monkeypatch.setattr(events_module, "_HPFEEDS_STATE", {"pid": None, "client": None})

    events_module.publish_event({"request_id": "hp-1"})
    events_module.publish_event({"request_id": "hp-2"})

    assert len(created) == 1
    assert len(created[0].published) == 2

    monkeypatch.setitem(events_module._HPFEEDS_STATE, "pid", -1)
    events_module.publish_event({"request_id": "hp-3"})
    assert len(created) == 2
