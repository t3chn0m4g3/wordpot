from xmlrpc.client import dumps

import pytest

from wordpot import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _call(client, method, params=()):
    body = dumps(params, methodname=method, allow_none=True)
    return client.post("/xmlrpc.php", data=body, content_type="text/xml")


def test_xmlrpc_lists_wordpress_methods(client):
    response = _call(client, "system.listMethods")

    assert response.status_code == 200
    assert "wp.getUsersBlogs" in response.get_data(as_text=True)
    assert "system.multicall" in response.get_data(as_text=True)


def test_xmlrpc_demo_say_hello(client):
    response = _call(client, "demo.sayHello")

    assert response.status_code == 200
    assert "Hello!" in response.get_data(as_text=True)


def test_xmlrpc_login_fault_and_event_credentials(client, monkeypatch):
    events = []
    monkeypatch.setattr("wordpot.views.log_event", lambda *args, **kwargs: events.append(kwargs))

    response = _call(client, "wp.getUsersBlogs", ("alice", "secret"))

    assert "Incorrect username or password." in response.get_data(as_text=True)
    assert events[-1]["technique"] == "xmlrpc_login"
    assert events[-1]["details"]["credential_pairs"] == [{"username": "alice", "password": "secret"}]


def test_xmlrpc_multicall_collects_capped_credential_pairs(client, monkeypatch):
    events = []
    monkeypatch.setattr("wordpot.views.log_event", lambda *args, **kwargs: events.append(kwargs))
    calls = [
        {"methodName": "wp.getUsersBlogs", "params": ["user%d" % i, "pass%d" % i]}
        for i in range(55)
    ]

    response = _call(client, "system.multicall", (calls,))
    event = events[-1]

    assert response.status_code == 200
    assert response.get_data(as_text=True).count("faultCode") == 55
    assert event["technique"] == "xmlrpc_multicall"
    assert len(event["details"]["credential_pairs"]) == 50
    assert event["details"]["credential_pair_count"] == 55


def test_xmlrpc_multicall_faults_every_call(client):
    calls = [
        {"methodName": "blogger.deletePost", "params": [1, "user", "pass"]},
        {"methodName": "wp.getUsersBlogs", "params": ["user", "pass"]},
    ]

    response = _call(client, "system.multicall", (calls,))

    assert response.get_data(as_text=True).count("faultCode") == 2


def test_xmlrpc_pingback_is_logged_without_fetching(client, monkeypatch):
    events = []
    monkeypatch.setattr("wordpot.views.log_event", lambda *args, **kwargs: events.append(kwargs))

    response = _call(client, "pingback.ping", ("http://source.invalid/post", "http://target.invalid/"))

    event = events[-1]
    assert "faultCode" in response.get_data(as_text=True)
    assert event["technique"] == "xmlrpc_pingback"
    assert event["details"]["pingback_source"] == "http://source.invalid/post"
    assert event["details"]["pingback_target"] == "http://target.invalid/"


def test_xmlrpc_rsd_document_remains_available(client):
    response = client.get("/xmlrpc.php?rsd")

    assert response.status_code == 200
    assert "<api name=\"WordPress\"" in response.get_data(as_text=True)


def test_xmlrpc_rejects_entity_expansion_payload(client):
    body = """<!DOCTYPE methodCall [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<methodCall><methodName>demo.sayHello</methodName><params><param><value><string>&xxe;</string></value></param></params></methodCall>"""

    response = client.post("/xmlrpc.php", data=body, content_type="text/xml")

    assert response.status_code == 200
    assert "faultCode" in response.get_data(as_text=True)
    assert "root:" not in response.get_data(as_text=True)


def test_request_body_limits_default_to_one_mib():
    assert app.config["MAX_CONTENT_LENGTH"] == 1024 * 1024
    assert app.config["PAYLOAD_STORAGE_MAX_BYTES"] == 1024 * 1024


def _logged_events(monkeypatch):
    from wordpot import events as event_module

    logged = []
    monkeypatch.setattr(event_module, "publish_event", logged.append)
    return logged


def test_xmlrpc_login_sets_username_and_password(client, monkeypatch):
    logged = _logged_events(monkeypatch)

    _call(client, "wp.getUsersBlogs", ("alice", "secret"))

    event = logged[-1]
    assert event["technique"] == "xmlrpc_login"
    assert event["username"] == "alice"
    assert event["password"] == "secret"


def test_xmlrpc_multicall_with_several_pairs_sets_no_username(client, monkeypatch):
    logged = _logged_events(monkeypatch)
    calls = [
        {"methodName": "wp.getUsersBlogs", "params": ["user%d" % i, "pass%d" % i]}
        for i in range(2)
    ]

    _call(client, "system.multicall", (calls,))

    event = logged[-1]
    assert event["technique"] == "xmlrpc_multicall"
    assert len(event["details"]["credential_pairs"]) == 2
    assert "username" not in event
    assert "password" not in event
