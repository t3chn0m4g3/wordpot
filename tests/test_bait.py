import json

import pytest

from wordpot import app


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
        return [json.loads(line) for line in (tmp_path / "wordpot.json").read_text().splitlines()]

    return read


@pytest.mark.parametrize("path", ["/.env", "/.git/config", "/.git/HEAD", "/wp-config.php.bak", "/wp-config.php~", "/wp-config.php.save", "/wp-config.php.old", "/wp-config.php.swp"])
def test_config_baits_are_served_and_logged(client, events, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert events()[-1]["technique"] == "config_bait_served"
    assert "password" not in response.get_data(as_text=True).lower()
    assert "secret" not in response.get_data(as_text=True).lower()


@pytest.mark.parametrize("path", ["/alfa.php", "/c99.php", "/wp-content/uploads/shell.php"])
def test_webshell_probe_get_returns_static_login_mask(client, events, path):
    response = client.get(path)

    assert response.status_code == 200
    assert "Web File Manager" in response.get_data(as_text=True)
    assert events()[-1]["technique"] == "webshell_probe"


def test_webshell_login_submission_does_not_authenticate(client, events):
    response = client.post("/alfa.php", data={"username": "operator", "password": "bad"})

    assert response.status_code == 200
    assert "Invalid credentials" in response.get_data(as_text=True)
    assert events()[-1]["technique"] == "webshell_login"


@pytest.mark.parametrize("field", ["cmd", "command", "exec"])
def test_webshell_command_probe_is_never_executed(client, events, field):
    response = client.get("/shell.php", query_string={field: "id"})

    assert response.status_code == 200
    assert "Invalid credentials" in response.get_data(as_text=True)
    assert events()[-1]["technique"] == "webshell_command"
