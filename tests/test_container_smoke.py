import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest


BASE_URL = os.environ.get("WORDPOT_CONTAINER_SMOKE_URL")
USER_AGENT = "wordpot-container-smoke/1.0"
EVENT_LOG_NAME = "wordpot.json"

EVENT_FIELDS = {
    "timestamp",
    "request_id",
    "profile_id",
    "src_ip",
    "src_port",
    "dest_ip",
    "dest_port",
    "user_agent",
    "browser_family",
    "os_family",
    "device_family",
    "url",
    "method",
    "path",
    "headers_subset",
    "component_type",
    "component_slug",
    "technique",
    "payload_sha256",
    "payload_excerpt",
    "payload_size",
    "payload_stored",
    "payload_ref",
    "payload_path",
    "response_status",
}

pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="Set WORDPOT_CONTAINER_SMOKE_URL to run the container smoke test.",
)


def smoke_url(path):
    return "%s/%s" % (BASE_URL.rstrip("/"), path.lstrip("/"))


def http_request(path, method="GET", data=None, headers=None, timeout=5):
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    request = Request(smoke_url(path), data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


@pytest.fixture(scope="session")
def ready_container():
    deadline = time.time() + 30
    last_error = None
    while time.time() < deadline:
        try:
            status, _, _ = http_request("/readme.html", timeout=2)
            if status == 200:
                return True
        except URLError as exc:
            last_error = exc
        time.sleep(0.5)

    pytest.fail("Wordpot container did not become healthy at %s: %s" % (BASE_URL, last_error))


def test_running_container_http_surface(ready_container):
    # /healthz is reserved for the in-container healthcheck on 127.0.0.1.
    status, headers, body = http_request("/healthz")
    assert status == 404
    assert body != b"ok\n"

    status, headers, body = http_request("/")
    text = body.decode("utf-8", errors="replace")
    assert status == 200
    assert "WordPress" in text
    assert "wp-json" in text
    assert "/wp-content/themes/" in text
    assert "X-Request-ID" not in headers

    status, _, body = http_request("/wp-json/")
    rest_index = json.loads(body.decode("utf-8"))
    assert status == 200
    assert "wp/v2" in rest_index["namespaces"]

    status, _, body = http_request("/wp-json/wp/v2/users")
    users = json.loads(body.decode("utf-8"))
    assert status == 200
    assert isinstance(users, list)
    assert {"id", "slug", "name", "_links"}.issubset(users[0])

    status, _, body = http_request("/xmlrpc.php")
    assert status == 405
    assert b"POST requests only" in body

    login_body = urlencode({"log": "admin", "pwd": "wordpot-smoke"}).encode("utf-8")
    status, headers, body = http_request(
        "/wp-login.php",
        method="POST",
        data=login_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert status == 200
    assert b"Invalid username" in body
    assert "wordpress_test_cookie" in headers.get("Set-Cookie", "")

    ajax_body = urlencode({"action": "wordpot_smoke_test", "file": "http://169.254.169.254/"}).encode("utf-8")
    status, _, body = http_request(
        "/wp-admin/admin-ajax.php",
        method="POST",
        data=ajax_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert status == 200
    assert json.loads(body.decode("utf-8"))["success"] is False

    status, _, _ = http_request(
        "/wp-content/uploads/2026/06/smoke.php",
        method="POST",
        data=b"<?php echo 'smoke'; ?>",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert status == 404


def host_path_from_env(name, default):
    return Path(os.path.expandvars(os.environ.get(name, default))).expanduser()


def require_existing_host_path(path, env_name):
    if path.exists():
        return
    if env_name in os.environ:
        pytest.fail("%s points to a missing path: %s" % (env_name, path))
    pytest.skip("%s is not mounted on the host: %s" % (env_name, path))


def wait_for_event(event_file, marker, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if event_file.exists():
            with event_file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle.readlines()[-500:]:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if marker in event.get("payload_excerpt", "") or marker in event.get("query", ""):
                        return event
        time.sleep(0.25)

    pytest.fail("No JSONL event found for marker=%s in %s" % (marker, event_file))


def assert_payload_file_matches(payload_file, body):
    try:
        assert payload_file.exists()
        assert payload_file.read_bytes() == body
    except PermissionError as exc:
        pytest.fail(
            "Payload file exists but is not readable from the host: %s. "
            "Rebuild/restart the container so payload files use group-readable "
            "permissions, and ensure the test user can read the mounted log tree. "
            "Original error: %s" % (payload_file, exc)
        )


def assert_no_none_or_empty_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            assert_no_none_or_empty_strings(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_none_or_empty_strings(item)
    else:
        assert value is not None
        assert value != ""


def test_running_container_event_log_and_payload_volume(ready_container):
    log_dir = host_path_from_env(
        "WORDPOT_CONTAINER_LOG_DIR",
        "$HOME/tpotce/data/wordpot/log",
    )
    payload_dir = host_path_from_env(
        "WORDPOT_CONTAINER_PAYLOAD_DIR",
        "$HOME/tpotce/data/wordpot/log/payloads",
    )
    require_existing_host_path(log_dir, "WORDPOT_CONTAINER_LOG_DIR")
    if not payload_dir.parent.exists():
        if "WORDPOT_CONTAINER_PAYLOAD_DIR" in os.environ:
            pytest.fail("Parent of WORDPOT_CONTAINER_PAYLOAD_DIR is missing: %s" % payload_dir.parent)
        pytest.skip("Payload volume parent is not mounted on the host: %s" % payload_dir.parent)

    marker = "wordpot-smoke-%s" % uuid.uuid4().hex
    body = urlencode(
        {
            "action": "wordpot_smoke_payload",
            "marker": marker,
            "file": "http://169.254.169.254/latest/meta-data/",
        }
    ).encode("utf-8")
    status, headers, _ = http_request(
        "/wp-admin/admin-ajax.php",
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert status == 200

    event = wait_for_event(log_dir / EVENT_LOG_NAME, marker)
    assert EVENT_FIELDS.issubset(event)
    assert event["user_agent"] == USER_AGENT
    assert event["dest_ip"] not in {"0.0.0.0", "::"}
    assert event["browser_family"]
    assert event["os_family"]
    assert event["device_family"]
    assert event["url"].endswith("/wp-admin/admin-ajax.php")
    assert event["method"] == "POST"
    assert event["path"] == "/wp-admin/admin-ajax.php"
    assert event["component_type"] == "core"
    assert event["component_slug"] == "admin-ajax.php"
    assert event["technique"] == "admin_ajax_action"
    assert event["response_status"] == 200
    assert event["payload_sha256"] == hashlib.sha256(body).hexdigest()
    assert event["payload_size"] == len(body)
    assert marker in event["payload_excerpt"]
    assert event["payload_stored"] is True
    assert "username" not in event
    assert "password" not in event
    assert "credentials_observed" not in event
    assert "query" not in event
    assert_no_none_or_empty_strings(event)
    assert re.match(r"^[0-9a-f]{2}/[0-9a-f]{64}\.bin$", event["payload_ref"])

    payload_file = payload_dir / event["payload_ref"]
    assert payload_dir.exists()
    assert_payload_file_matches(payload_file, body)
