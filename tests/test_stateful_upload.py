import json
from io import BytesIO

import pytest

from wordpot import app
import wordpot.state as state


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORDPOT_LOG_DIR", str(tmp_path / "logs"))
    state._UPLOAD_CACHE.clear()
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


def _upload(client, filename="probe.php", contents=b"<?php echo 'FOLLOWUP_MARKER'; ?>"):
    return client.post(
        "/wp-content/uploads/",
        data={"file": (BytesIO(contents), filename)},
        content_type="multipart/form-data",
    )


def test_multipart_upload_marker_is_served_on_followup_get(client, events, tmp_path):
    upload = _upload(client, filename="nested/probe.php")
    followup = client.get("/wp-content/plugins/unknown/probe.php")

    assert upload.status_code == 403
    assert followup.status_code == 200
    assert followup.mimetype == "text/plain"
    assert followup.get_data(as_text=True) == "FOLLOWUP_MARKER"
    assert events()[-1]["technique"] == "upload_followup"
    assert events()[-1]["details"]["marker"] == "FOLLOWUP_MARKER"
    state_file = tmp_path / "logs" / "state" / "uploads.jsonl"
    record = json.loads(state_file.read_text().splitlines()[0])
    assert record["basename"] == "probe.php"
    assert record["sha256"]
    assert record["marker"] == "FOLLOWUP_MARKER"


def test_upload_filenames_are_stored_by_basename(client):
    _upload(client, filename="../../outside.php")

    record = state.lookup_upload("outside.php")
    assert record["basename"] == "outside.php"


def test_upload_followup_expires_after_24_hours(client, monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(state.time, "time", lambda: now)
    _upload(client)

    monkeypatch.setattr(state.time, "time", lambda: now + state.UPLOAD_TTL_SECONDS + 1)
    assert state.lookup_upload("probe.php") is None


def test_upload_without_echo_marker_does_not_use_uploaded_code(client):
    _upload(client, filename="data.bin", contents=b"<?php system('id'); ?>")

    response = client.get("/wp-content/uploads/data.bin")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == ""
