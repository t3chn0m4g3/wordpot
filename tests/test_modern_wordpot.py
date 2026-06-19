import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import pytest
from flask import request

os.environ.setdefault("WORDPOT_LOG_DIR", "/tmp/wordpot-test-logs")

from wordpot import app  # noqa: E402
import wordpot.events as events_module  # noqa: E402
from wordpot.branding import emit_startup_banner  # noqa: E402
from wordpot.events import build_event_dict, log_event  # noqa: E402
from wordpot.profiles import DEFAULT_PROFILES, current_profile, initialize_startup_profile  # noqa: E402


DOCUMENTED_EVENT_FIELDS = {
    "timestamp",
    "request_id",
    "profile_id",
    "src_ip",
    "src_port",
    "dest_ip",
    "dest_port",
    "user_agent",
    "browser_family",
    "browser_version",
    "os_family",
    "os_version",
    "device_family",
    "url",
    "method",
    "path",
    "query",
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
    "username",
    "password",
    "credentials_observed",
    "response_status",
    "details",
}

DOCUMENTED_CONFIG_FIELDS = {
    "HOST",
    "PORT",
    "THEME",
    "SERVER",
    "INTERACTION_DEPTH",
    "MAX_CONTENT_LENGTH",
    "PAYLOAD_EXCERPT_BYTES",
    "PAYLOAD_STORAGE_ENABLED",
    "PAYLOAD_STORAGE_MAX_BYTES",
    "PAYLOAD_DIR_MODE",
    "PAYLOAD_FILE_MODE",
    "PAYLOAD_DIR",
    "EVENT_LOG_FILE",
    "EVENT_LOG_EXCLUDE_HEALTHCHECKS",
    "EVENT_LOG_EXCLUDE_PATHS",
    "EVENT_DEST_IP",
    "EVENT_DEST_PORT",
    "PROFILE_ROTATION",
    "PROFILE_ID",
    "PROFILE_STATE_FILE",
    "TRUST_PROXY_HEADERS",
    "BLOGTITLE",
    "BLOGSUBTITLE",
    "VERSION",
    "AUTHORS",
    "PROFILES",
    "HPFEEDS_ENABLED",
    "HPFEEDS_HOST",
    "HPFEEDS_PORT",
    "HPFEEDS_IDENT",
    "HPFEEDS_SECRET",
    "HPFEEDS_TOPIC",
}


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_homepage_exposes_modern_wordpress_fingerprint(client):
    response = client.get("/", environ_base={"REMOTE_ADDR": "203.0.113.10"})

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "WordPress" in body
    assert "wp-json" in body
    assert "/wp-content/themes/" in body
    assert "wp-site-blocks" in body
    assert "wp-block-navigation" in body
    assert "wp-block-template-part" in body
    assert "global-styles-inline-css" in body
    assert "June 12, 2026" in body
    assert "June 28, 2012" not in body
    assert "two-column right-sidebar" not in body
    assert response.headers["X-Request-ID"]


def test_front_page_personas_are_profile_aware(client):
    old_profile_id = app.config.get("PROFILE_ID")
    expected = {
        "modern-business": "Summit &amp; Co Advisory",
        "commerce": "woocommerce-js",
        "maintenance-lag": "City Desk Journal",
        "agency-builder": "elementor-page",
    }

    try:
        for profile in DEFAULT_PROFILES:
            app.config["PROFILE_ID"] = profile["id"]
            response = client.get("/", environ_base={"REMOTE_ADDR": "203.0.113.11"})
            body = response.get_data(as_text=True)

            assert response.status_code == 200
            assert expected[profile["id"]] in body
            assert profile["theme"] in body
    finally:
        if old_profile_id is None:
            app.config.pop("PROFILE_ID", None)
        else:
            app.config["PROFILE_ID"] = old_profile_id


def test_profile_selection_is_sticky_for_same_source_ip(client):
    first = client.get("/wp-json/", environ_base={"REMOTE_ADDR": "203.0.113.20"}).get_json()
    second = client.get("/wp-json/", environ_base={"REMOTE_ADDR": "203.0.113.20"}).get_json()

    assert first["name"] == second["name"]
    assert first["namespaces"] == second["namespaces"]


def test_rest_users_and_posts_are_wordpress_shaped(client):
    users = client.get("/wp-json/wp/v2/users", environ_base={"REMOTE_ADDR": "203.0.113.30"})
    posts = client.get("/wp-json/wp/v2/posts", environ_base={"REMOTE_ADDR": "203.0.113.30"})

    assert users.status_code == 200
    assert isinstance(users.get_json(), list)
    assert {"id", "slug", "name", "_links"}.issubset(users.get_json()[0])
    assert posts.status_code == 200
    assert posts.get_json()[0]["title"]["rendered"] == "Hello world!"


def test_login_and_author_inputs_do_not_500(client):
    malformed_author = client.get("/?author=not-a-number")
    missing_credentials = client.post("/wp-login.php", data={})

    assert malformed_author.status_code == 200
    assert missing_credentials.status_code == 200
    assert "Invalid username" in missing_credentials.get_data(as_text=True)
    assert "wordpress_test_cookie" in missing_credentials.headers.get("Set-Cookie", "")


def test_login_page_uses_modern_wordpress_markup(client):
    response = client.get("/wp-login.php?action=lostpassword&redirect_to=/wp-admin/edit.php")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "wp-core-ui" in body
    assert "login-action-lostpassword" in body
    assert "login-css" in body
    assert "forms-css" in body
    assert "buttons-css" in body
    assert "Username or Email Address" in body
    assert "wp-hide-pw" in body
    assert "language-switcher" in body
    assert 'value="/wp-admin/edit.php"' in body
    assert "colors-fresh-css" not in body
    assert "tabindex=" not in body


def test_xmlrpc_behaves_like_wordpress_endpoint(client):
    get_response = client.get("/xmlrpc.php")
    post_response = client.post(
        "/xmlrpc.php",
        data="<methodCall><methodName>system.multicall</methodName></methodCall>",
        content_type="text/xml",
    )

    assert get_response.status_code == 405
    assert "POST requests only" in get_response.get_data(as_text=True)
    assert post_response.status_code == 200
    assert "Incorrect username or password" in post_response.get_data(as_text=True)


def test_plugin_and_theme_fingerprints_are_differentiated(client):
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.40"}):
        profile = current_profile()
        plugin_slug = profile["plugins"][0]["slug"]
        plugin_version = profile["plugins"][0]["version"]

    plugin = client.get("/wp-content/plugins/%s/readme.txt" % plugin_slug, environ_base={"REMOTE_ADDR": "203.0.113.40"})
    missing = client.get("/wp-content/plugins/definitely-not-installed/readme.txt", environ_base={"REMOTE_ADDR": "203.0.113.40"})
    homepage = client.get("/", environ_base={"REMOTE_ADDR": "203.0.113.40"}).get_data(as_text=True)
    theme_slug = re.search(r"/wp-content/themes/([^/]+)/style.css", homepage).group(1)
    theme = client.get("/wp-content/themes/%s/style.css" % theme_slug, environ_base={"REMOTE_ADDR": "203.0.113.40"})

    assert plugin.status_code == 200
    assert "Stable tag: %s" % plugin_version in plugin.get_data(as_text=True)
    assert missing.status_code == 404
    assert theme.status_code == 200
    assert "Theme Name:" in theme.get_data(as_text=True)


def test_lure_endpoints_capture_but_do_not_accept_real_actions(client):
    ajax = client.post(
        "/wp-admin/admin-ajax.php",
        data={"action": "elementor_upload_and_install_pro", "file": "http://169.254.169.254/latest/meta-data/"},
    )
    rest_write = client.post("/wp-json/wp/v2/posts", json={"title": "owned"})
    upload = client.post("/wp-content/uploads/2026/06/shell.php", data=b"<?php system($_GET['x']); ?>")

    assert ajax.status_code == 200
    assert ajax.get_json()["success"] is False
    assert rest_write.status_code == 401
    assert upload.status_code == 404


def test_timthumb_probe_is_modern_lure_event(client, monkeypatch):
    captured = []
    monkeypatch.setattr(events_module, "publish_event", lambda event: captured.append(event))

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.41"}):
        profile = current_profile()
        plugin_slug = profile["plugins"][0]["slug"]

    response = client.get(
        "/wp-content/plugins/%s/timthumb.php?src=http://169.254.169.254/latest/meta-data/" % plugin_slug,
        environ_base={"REMOTE_ADDR": "203.0.113.41"},
    )

    assert response.status_code == 404
    event = next(item for item in captured if item.get("technique") == "timthumb_probe")
    assert event["component_type"] == "plugin"
    assert event["component_slug"] == plugin_slug
    assert event["details"]["matched_pattern"] == "timthumb_uploadify"
    assert event["details"]["lure_params"]["src"] == "http://169.254.169.254/latest/meta-data/"


def test_no_legacy_plugin_events_are_emitted(client, monkeypatch):
    captured = []
    monkeypatch.setattr(events_module, "publish_event", lambda event: captured.append(event))

    client.get("/?author=1")
    client.get("/readme.html")

    assert captured
    assert all(item.get("component_type") != "legacy-plugin" for item in captured)


def test_form_payload_is_captured_before_form_parsing(client, tmp_path, monkeypatch):
    captured = []
    old_config = {
        "PAYLOAD_DIR": app.config.get("PAYLOAD_DIR"),
        "PAYLOAD_STORAGE_ENABLED": app.config.get("PAYLOAD_STORAGE_ENABLED"),
    }
    app.config["PAYLOAD_DIR"] = str(tmp_path)
    app.config["PAYLOAD_STORAGE_ENABLED"] = True
    monkeypatch.setattr(events_module, "publish_event", lambda event: captured.append(event))

    try:
        body = b"action=wordpot_form_payload&marker=form-body-check"
        response = client.post(
            "/wp-admin/admin-ajax.php",
            data=body,
            content_type="application/x-www-form-urlencoded",
        )
    finally:
        app.config.update(old_config)

    assert response.status_code == 200
    event = next(item for item in captured if item.get("technique") == "admin_ajax_action")
    assert event["payload_sha256"] == hashlib.sha256(body).hexdigest()
    assert event["payload_size"] == len(body)
    assert event["payload_stored"] is True
    assert os.path.exists(event["payload_path"])


def test_login_credentials_are_available_as_compatibility_fields(client, monkeypatch):
    captured = []
    monkeypatch.setattr(events_module, "publish_event", lambda event: captured.append(event))

    response = client.post(
        "/wp-login.php",
        data={"log": "admin", "pwd": "secret"},
        headers={"User-Agent": "pytest"},
    )

    assert response.status_code == 200
    event = next(item for item in captured if item.get("technique") == "credential_attempt")
    assert event["username"] == "admin"
    assert event["password"] == "secret"
    assert event["credentials_observed"]["log"] == "admin"
    assert event["credentials_observed"]["pwd"] == "secret"


def test_basic_auth_credentials_are_available_as_compatibility_fields():
    with app.test_request_context(
        "/wp-json/",
        headers={"Authorization": "Basic YXBpLXVzZXI6YXBpLXBhc3M=", "User-Agent": "pytest"},
    ):
        event = build_event_dict(
            request,
            current_profile(),
            component_type="core",
            component_slug="wp-json",
            technique="rest_index",
            response_status=200,
        )

    assert event["username"] == "api-user"
    assert event["password"] == "api-pass"
    assert event["credentials_observed"]["basic_username"] == "api-user"
    assert event["credentials_observed"]["basic_password"] == "api-pass"


def test_destination_ip_skips_container_wildcard_bind_address():
    with app.test_request_context(
        "/wp-json/",
        headers={"Host": "honeypot.example"},
        environ_overrides={
            "SERVER_ADDR": "0.0.0.0",
            "LOCAL_ADDR": "0.0.0.0",
            "SERVER_NAME": "0.0.0.0",
            "SERVER_PORT": "80",
        },
    ):
        event = build_event_dict(
            request,
            current_profile(),
            component_type="core",
            component_slug="wp-json",
            technique="rest_index",
            response_status=200,
        )

    assert event["dest_ip"] == "honeypot.example"


def test_large_payload_is_rejected(client):
    response = client.post("/wp-login.php", data=b"A" * 70000, content_type="application/octet-stream")

    assert response.status_code == 413


def test_healthcheck_endpoint_is_quiet(client):
    response = client.get("/healthz", headers={"X-Wordpot-Healthcheck": "1"})

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok\n"


def test_event_schema_payload_truncation_and_payload_storage(tmp_path):
    old_config = {
        "PAYLOAD_EXCERPT_BYTES": app.config.get("PAYLOAD_EXCERPT_BYTES"),
        "PAYLOAD_DIR": app.config.get("PAYLOAD_DIR"),
        "PAYLOAD_STORAGE_ENABLED": app.config.get("PAYLOAD_STORAGE_ENABLED"),
        "PAYLOAD_DIR_MODE": app.config.get("PAYLOAD_DIR_MODE"),
        "PAYLOAD_FILE_MODE": app.config.get("PAYLOAD_FILE_MODE"),
    }
    app.config["PAYLOAD_EXCERPT_BYTES"] = 16
    app.config["PAYLOAD_DIR"] = str(tmp_path)
    app.config["PAYLOAD_STORAGE_ENABLED"] = True
    app.config["PAYLOAD_DIR_MODE"] = 0o750
    app.config["PAYLOAD_FILE_MODE"] = 0o640

    try:
        body = b"A" * 128
        with app.test_request_context(
            "/wp-admin/admin-ajax.php?action=test&file=/etc/passwd",
            method="POST",
            data=body,
            headers={
                "Host": "honeypot.example",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            },
            environ_overrides={
                "REMOTE_ADDR": "198.51.100.77",
                "REMOTE_PORT": "54321",
                "SERVER_NAME": "192.0.2.10",
                "SERVER_PORT": "8080",
            },
        ):
            event = build_event_dict(
                request,
                current_profile(),
                component_type="core",
                component_slug="admin-ajax.php",
                technique="admin_ajax_action",
                response_status=200,
            )

        assert {
            "timestamp",
            "request_id",
            "profile_id",
            "src_ip",
            "src_port",
            "dest_ip",
            "dest_port",
            "user_agent",
            "browser_family",
            "browser_version",
            "os_family",
            "os_version",
            "device_family",
            "url",
            "method",
            "path",
            "query",
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
        }.issubset(event)
        assert event["src_ip"] == "198.51.100.77"
        assert event["src_port"] == 54321
        assert event["dest_ip"] == "192.0.2.10"
        assert event["dest_port"] == 8080
        assert "Chrome" in event["user_agent"]
        assert event["browser_family"] == "Chrome"
        assert event["browser_version"] == "126.0.0"
        assert event["os_family"] == "Windows"
        assert event["os_version"] == "10"
        assert event["device_family"] == "Other"
        assert event["url"] == "http://honeypot.example/wp-admin/admin-ajax.php?action=test&file=/etc/passwd"
        assert "username" not in event
        assert "password" not in event
        assert "credentials_observed" not in event
        assert all(value is not None for value in event.values())
        assert len(event["payload_excerpt"]) == 16
        assert event["payload_size"] == len(body)
        assert event["payload_stored"] is True
        assert event["payload_ref"].endswith("%s.bin" % event["payload_sha256"])
        assert os.path.exists(event["payload_path"])
        assert os.stat(os.path.dirname(event["payload_path"])).st_mode & 0o777 == 0o750
        assert os.stat(event["payload_path"]).st_mode & 0o777 == 0o640
        with open(event["payload_path"], "rb") as handle:
            assert handle.read() == body
    finally:
        app.config.update(old_config)


def test_healthcheck_event_filter():
    with app.test_request_context("/wp-json/", headers={"X-Wordpot-Healthcheck": "1"}):
        event = log_event(
            request,
            current_profile(),
            component_type="core",
            component_slug="wp-json",
            technique="rest_index",
            response_status=200,
        )

    assert event is None


def test_null_and_empty_string_event_fields_are_omitted():
    with app.test_request_context(
        "/wp-json/wp/v2/posts",
        headers={"User-Agent": "pytest"},
        environ_overrides={"REMOTE_PORT": ""},
    ):
        event = build_event_dict(
            request,
            current_profile(),
            component_type="core",
            component_slug=None,
            technique="rest_index",
            response_status=200,
            details={"action": None, "lure_params": {"file": None, "q": ""}},
            include_payload=False,
        )

    assert "component_slug" not in event
    assert "src_port" not in event
    assert "browser_version" not in event
    assert "os_version" not in event
    assert "query" not in event
    assert "payload_sha256" not in event
    assert "payload_excerpt" not in event
    assert "payload_ref" not in event
    assert "payload_path" not in event
    assert "username" not in event
    assert "password" not in event
    assert "credentials_observed" not in event
    assert "action" not in event["details"]
    assert "file" not in event["details"]["lure_params"]
    assert "q" not in event["details"]["lure_params"]
    assert event["payload_size"] == 0
    assert event["payload_stored"] is False


def test_publish_event_writes_configured_json_event_file(tmp_path):
    old_event_log_file = app.config.get("EVENT_LOG_FILE")
    event_path = tmp_path / "wordpot.json"
    app.config["EVENT_LOG_FILE"] = str(event_path)

    try:
        events_module.publish_event({"request_id": "write-check", "technique": "unit_test"})
    finally:
        app.config["EVENT_LOG_FILE"] = old_event_log_file

    assert event_path.exists()
    assert os.stat(event_path).st_mode & 0o777 == 0o640
    with event_path.open("r", encoding="utf-8") as handle:
        line = handle.readline()
    assert json.loads(line) == {"request_id": "write-check", "technique": "unit_test"}


def test_cli_version_outputs_version_without_startup_banner():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    result = subprocess.run(
        [sys.executable, "wordpot.py", "--version"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.stdout.strip() == "Wordpot 3.0.0"


def test_startup_banner_flushes_stdout(monkeypatch):
    printed = []

    def fake_print(*args, **kwargs):
        printed.append((args, kwargs))

    monkeypatch.setattr("builtins.print", fake_print)

    emit_startup_banner(profile_id="agency-builder", log_dir="/opt/wordpot/logs")

    assert printed
    assert printed[0][1]["flush"] is True
    assert "Wordpot 3.0.0" in printed[0][0][0]


def test_readme_documents_config_and_event_fields():
    readme_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "README.md"))
    with open(readme_path, "r", encoding="utf-8") as handle:
        readme = handle.read()

    for field in sorted(DOCUMENTED_CONFIG_FIELDS | DOCUMENTED_EVENT_FIELDS):
        assert "| `%s` |" % field in readme


def test_startup_rotation_cycles_profiles(tmp_path):
    class FakeApp:
        config = {
            "PROFILE_ROTATION": "startup",
            "PROFILE_STATE_FILE": str(tmp_path / "profile-state.json"),
            "PROFILES": [
                {"id": "one", "plugins": [], "themes": ["twentytwentyfive"], "theme": "twentytwentyfive"},
                {"id": "two", "plugins": [], "themes": ["twentytwentyfive"], "theme": "twentytwentyfive"},
            ],
        }

    first = initialize_startup_profile(FakeApp())
    second = initialize_startup_profile(FakeApp())
    third = initialize_startup_profile(FakeApp())

    assert first == "one"
    assert second == "two"
    assert third == "one"


@pytest.mark.skipif(
    not os.environ.get("WPSCAN_URL") or not shutil.which("wpscan"),
    reason="Set WPSCAN_URL and install wpscan to run the scanner smoke test.",
)
def test_wpscan_smoke_detects_wordpress_surface():
    result = subprocess.run(
        ["wpscan", "--url", os.environ["WPSCAN_URL"], "--force", "--no-update", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "WordPress" in result.stdout or "wordpress" in result.stdout
