import json
import os
import subprocess
import sys

import pytest

os.environ.setdefault("WORDPOT_LOG_DIR", "/tmp/wordpot-test-logs")

from wordpot import app  # noqa: E402
from wordpot.profiles import configured_profiles  # noqa: E402


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    return read


@pytest.mark.parametrize(
    "path",
    [
        "/wp-content/plugins/elementor/readme.txt",
        "/wp-content/plugins/elementor/includes/upload-handler.php",
        "/wp-content/plugins/not-installed/readme.txt",
        "/wp-content/plugins/not-installed/includes/ajax-upload.php",
        "/wp-content/themes/twentytwentyfive/style.css",
        "/wp-content/themes/twentytwentyfive/inc/backup.php",
        "/wp-content/uploads/2026/10/shell.php",
        "/wp-content/uploads/2026/10/photo.png",
    ],
)
def test_component_requests_log_exactly_one_event(client, events, path):
    response = client.get(path)
    logged = events()

    assert len(logged) == 1
    assert logged[0]["response_status"] == response.status_code


def test_lure_on_missing_plugin_is_classified(client, events):
    client.post("/wp-content/plugins/not-installed/includes/ajax-upload.php", data={"file": "x"})

    assert events()[0]["technique"] == "plugin_lure_payload"


def test_profile_overrides_from_config():
    old = {key: app.config.get(key) for key in ("BLOGTITLE", "SERVER", "VERSION")}
    app.config.update({"BLOGTITLE": "Corp Blog", "SERVER": "nginx/1.26.0", "VERSION": "6.8.3"})
    try:
        profiles = configured_profiles(app)
    finally:
        app.config.update(old)

    assert {profile["blog_title"] for profile in profiles} == {"Corp Blog"}
    assert {profile["server_header"] for profile in profiles} == {"nginx/1.26.0"}
    assert {profile["core_version"] for profile in profiles} == {"6.8.3"}


def test_profiles_keep_own_values_without_overrides():
    titles = {profile["blog_title"] for profile in configured_profiles(app)}

    assert len(titles) > 1


def test_cli_version_does_not_rotate_profile(tmp_path):
    state = tmp_path / "profile-state.json"
    env = dict(os.environ, WORDPOT_PROFILE_STATE_FILE=str(state), WORDPOT_LOG_DIR=str(tmp_path))
    subprocess.run([sys.executable, "wordpot.py", "--version"], cwd=REPO_ROOT, check=True, capture_output=True, env=env, timeout=10)

    assert not state.exists()


def test_admin_redirect_to_is_url_encoded(client):
    response = client.get("/wp-admin/")

    assert response.status_code == 302
    assert "redirect_to=http%3A%2F%2F" in response.headers["Location"]


def test_broken_user_agent_parser_does_not_drop_event(client, events, monkeypatch):
    import wordpot.events as events_module

    def broken(_):
        raise ValueError("boom")

    monkeypatch.setattr(events_module, "parse_user_agent", broken)
    client.get("/wp-login.php")

    assert events()[0]["technique"] == "login_page"
