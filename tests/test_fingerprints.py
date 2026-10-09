import importlib.util
import os
from pathlib import Path

import pytest

os.environ.setdefault("WORDPOT_LOG_DIR", "/tmp/wordpot-test-logs")

from wordpot import app  # noqa: E402
from wordpot.profiles import DEFAULT_PROFILES  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
FLASK_ERROR_MARKERS = (
    "The requested URL was not found on the server",
    "You don't have the permission to access the requested resource",
    "The method is not allowed for the requested URL",
    "Werkzeug",
)


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    old = app.config.get("PROFILE_ID")
    app.config["PROFILE_ID"] = "modern-business"
    yield app.test_client()
    app.config["PROFILE_ID"] = old


def assert_not_flask_error(response):
    body = response.get_data(as_text=True)
    for marker in FLASK_ERROR_MARKERS:
        assert marker not in body


def test_gunicorn_server_header_is_removed():
    spec = importlib.util.spec_from_file_location("wordpot_gunicorn_conf", ROOT / "gunicorn.conf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeReq:
        version = (1, 1)

    class FakeResponse:
        upgrade = False
        chunked = False
        status = "200 OK"
        version = "gunicorn"
        req = FakeReq()

        def should_close(self):
            return False

    headers = module.gunicorn_wsgi.Response.default_headers(FakeResponse())
    assert not any(header.lower().startswith("server:") for header in headers)
    assert any(header.startswith("Date:") for header in headers)
    assert module.preload_app is True


def test_flask_static_route_is_not_exposed(client):
    response = client.get("/static/wp-admin/css/wp-admin.css")

    assert response.status_code == 404
    assert_not_flask_error(response)


def test_not_found_uses_wordpress_page(client):
    response = client.get("/this-page-does-not-exist/")
    body = response.get_data(as_text=True)

    assert response.status_code == 404
    assert_not_flask_error(response)
    assert "Page not found" in body
    assert "wp-json" in body
    assert response.headers["Link"]


def test_forbidden_uses_server_style_page(client):
    response = client.get("/wp-content/plugins/")
    body = response.get_data(as_text=True)

    assert response.status_code == 403
    assert_not_flask_error(response)
    assert "Forbidden" in body


@pytest.mark.parametrize(
    "path,mimetype",
    [
        ("/wp-content/plugins/elementor/assets/css/frontend.min.css", "text/css"),
        ("/wp-content/plugins/elementor/assets/js/frontend.min.js", "application/javascript"),
        ("/wp-includes/css/dist/block-library/style.min.css", "text/css"),
        ("/wp-includes/js/jquery/jquery.min.js", "application/javascript"),
        ("/wp-content/themes/twentytwentyfive/assets/images/hero.png", "image/png"),
        ("/wp-content/themes/twentytwentyfive/assets/images/hero.webp", "image/webp"),
        ("/wp-content/themes/twentytwentyfive/assets/images/logo.svg", "image/svg+xml"),
        ("/wp-admin/images/wordpress-logo.png", "image/png"),
        ("/wp-admin/images/wordpress-logo.svg", "image/svg+xml"),
    ],
)
def test_assets_use_matching_content_types(client, path, mimetype):
    response = client.get(path)

    assert response.status_code == 200
    assert response.mimetype == mimetype


def test_image_bytes_match_content_type(client):
    png = client.get("/wp-content/themes/twentytwentyfive/assets/images/hero.png").data
    webp = client.get("/wp-content/themes/twentytwentyfive/assets/images/hero.webp").data
    gif = client.get("/wp-content/themes/twentytwentyfive/assets/images/hero.gif").data
    jpeg = client.get("/wp-content/themes/twentytwentyfive/assets/images/hero.jpg").data

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"
    assert gif.startswith(b"GIF89a")
    assert jpeg.startswith(b"\xff\xd8\xff")


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_write_methods_get_wordpress_rest_errors(client, method, tmp_path):
    old = app.config.get("EVENT_LOG_FILE")
    app.config["EVENT_LOG_FILE"] = str(tmp_path / "wordpot.json")
    try:
        response = client.open("/wp-json/wp/v2/posts/1", method=method, data=b'{"title":"x"}', content_type="application/json")
    finally:
        app.config["EVENT_LOG_FILE"] = old

    assert response.status_code == 401
    assert response.get_json()["code"].startswith("rest_cannot_")
    assert (tmp_path / "wordpot.json").read_text().count("rest_post_write_attempt") == 1


def test_put_upload_is_logged(client, tmp_path):
    old = app.config.get("EVENT_LOG_FILE")
    app.config["EVENT_LOG_FILE"] = str(tmp_path / "wordpot.json")
    try:
        response = client.put("/wp-content/uploads/2026/10/note.txt", data=b"hello")
    finally:
        app.config["EVENT_LOG_FILE"] = old

    assert response.status_code in {403, 404, 405}
    assert_not_flask_error(response)
    assert "upload" in (tmp_path / "wordpot.json").read_text()


def test_all_profiles_render_without_flask_errors():
    app.config["TESTING"] = True
    for profile in DEFAULT_PROFILES:
        app.config["PROFILE_ID"] = profile["id"]
        client = app.test_client()
        assert client.get("/").status_code == 200
        assert_not_flask_error(client.get("/missing.php"))
    app.config["PROFILE_ID"] = None


@pytest.mark.parametrize("path", ["assets/images/logo.png", "assets/js/file-upload.js", "assets/css/debug.css"])
def test_static_assets_are_not_lures(client, path, tmp_path):
    old = app.config.get("EVENT_LOG_FILE")
    app.config["EVENT_LOG_FILE"] = str(tmp_path / "wordpot.json")
    try:
        response = client.get("/wp-content/themes/twentytwentyfive/%s" % path)
    finally:
        app.config["EVENT_LOG_FILE"] = old

    assert response.status_code == 200
    assert "_lure_payload" not in (tmp_path / "wordpot.json").read_text()
