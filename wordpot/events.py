#!/usr/bin/env python3

import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import threading
import uuid
from datetime import datetime, timezone

from flask import g
from user_agents import parse as parse_user_agent

from wordpot.logger import LOGGER, log_dir
from wordpot.profiles import client_ip_from_request


EVENT_LOG_DEFAULT_NAME = "wordpot.json"

CAPTURE_HEADERS = {
    "accept",
    "authorization",
    "content-type",
    "referer",
    "user-agent",
    "x-forwarded-for",
    "x-real-ip",
}

SENSITIVE_FORM_KEYS = {
    "log",
    "pwd",
    "user",
    "pass",
    "password",
    "username",
    "user_login",
    "user_pass",
}


def request_id():
    if not hasattr(g, "request_id"):
        g.request_id = str(uuid.uuid4())
    return g.request_id


def headers_subset(req):
    return {
        key: value
        for key, value in req.headers.items()
        if key.lower() in CAPTURE_HEADERS
    }


def _safe_text(data, limit):
    if not data:
        return ""
    clipped = data[:limit]
    return clipped.decode("utf-8", errors="replace")


def _int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bool_from_env(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _host_without_port(host):
    if not host:
        return None
    host = str(host).split(",", 1)[0].strip()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host.strip("[]")
    if ":" in host:
        return host.rsplit(":", 1)[0]
    return host


def _is_unspecified_host(host):
    host = _host_without_port(host)
    if not host:
        return True
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return host in {"*", "0"}


def _first_specific_host(candidates):
    for candidate in candidates:
        host = _host_without_port(candidate)
        if host and not _is_unspecified_host(host):
            return host
    return None


def user_agent_from_request(req):
    return req.headers.get("User-Agent", "")


def user_agent_details(req):
    try:
        parsed = parse_user_agent(user_agent_from_request(req))
    except Exception as exc:
        LOGGER.warning("Unable to parse User-Agent: %s", exc)
        return {}
    return {
        "browser_family": parsed.browser.family,
        "browser_version": parsed.browser.version_string,
        "os_family": parsed.os.family,
        "os_version": parsed.os.version_string,
        "device_family": parsed.device.family,
    }


def source_port_from_request(req):
    return _int_or_none(req.environ.get("REMOTE_PORT"))


def _listening_socket_ip(req):
    sock = req.environ.get("gunicorn.socket")
    if sock is None:
        return None
    try:
        address = sock.getsockname()
    except (OSError, AttributeError):
        return None
    if isinstance(address, tuple) and address:
        return _first_specific_host([address[0]])
    return None


def destination_ip_from_request(req):
    from wordpot import app

    configured = os.environ.get("WORDPOT_EVENT_DEST_IP") or os.environ.get("WORDPOT_DEST_IP") or app.config.get("EVENT_DEST_IP")
    if configured:
        return str(configured)

    if app.config.get("TRUST_PROXY_HEADERS"):
        forwarded_host = _first_specific_host([
            req.headers.get("X-Forwarded-Host"),
            req.headers.get("X-Forwarded-Server"),
        ])
        if forwarded_host:
            return forwarded_host

    # SERVER_NAME and HTTP_HOST are derived from the client's Host header, so
    # only addresses of the local listening socket are used here.
    return _first_specific_host([
        req.environ.get("SERVER_ADDR"),
        req.environ.get("LOCAL_ADDR"),
    ]) or _listening_socket_ip(req)


def destination_port_from_request(req):
    from wordpot import app

    configured = os.environ.get("WORDPOT_EVENT_DEST_PORT") or os.environ.get("WORDPOT_DEST_PORT") or app.config.get("EVENT_DEST_PORT")
    if configured:
        return _int_or_none(configured)

    if app.config.get("TRUST_PROXY_HEADERS"):
        forwarded_port = req.headers.get("X-Forwarded-Port")
        if forwarded_port:
            return _int_or_none(forwarded_port.split(",", 1)[0])

    return _int_or_none(req.environ.get("SERVER_PORT"))


def _payload_storage_dir():
    from wordpot import app

    configured = os.environ.get("WORDPOT_PAYLOAD_DIR") or app.config.get("PAYLOAD_DIR")
    if not configured:
        configured = os.path.join(log_dir(), "payloads")

    path = os.path.abspath(os.path.expanduser(str(configured)))
    dir_mode = _payload_dir_mode()
    os.makedirs(path, mode=dir_mode, exist_ok=True)
    _chmod_best_effort(path, dir_mode)
    return path if os.access(path, os.W_OK) else None


def _payload_storage_enabled():
    from wordpot import app

    return _bool_from_env("WORDPOT_PAYLOAD_STORAGE_ENABLED", bool(app.config.get("PAYLOAD_STORAGE_ENABLED", True)))


def _payload_storage_max_bytes():
    from wordpot import app

    return int(app.config.get("PAYLOAD_STORAGE_MAX_BYTES") or app.config.get("MAX_CONTENT_LENGTH", 1048576))


def _mode_from_config(config_key, env_key, default):
    from wordpot import app

    value = os.environ.get(env_key)
    if value is None:
        value = app.config.get(config_key, default)
    if isinstance(value, int):
        return value
    return int(str(value), 8)


def _payload_dir_mode():
    return _mode_from_config("PAYLOAD_DIR_MODE", "WORDPOT_PAYLOAD_DIR_MODE", 0o750)


def _payload_file_mode():
    return _mode_from_config("PAYLOAD_FILE_MODE", "WORDPOT_PAYLOAD_FILE_MODE", 0o640)


def _chmod_best_effort(path, mode):
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _event_log_path():
    from wordpot import app

    configured = os.environ.get("WORDPOT_EVENT_LOG_FILE") or app.config.get("EVENT_LOG_FILE") or EVENT_LOG_DEFAULT_NAME
    configured = os.path.expanduser(str(configured))
    if not os.path.isabs(configured):
        configured = os.path.join(log_dir(), configured)

    path = os.path.abspath(configured)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _event_log_rotation():
    from wordpot import app

    max_bytes = _int_or_none(os.environ.get("WORDPOT_EVENT_LOG_MAX_BYTES") or app.config.get("EVENT_LOG_MAX_BYTES")) or 0
    backup_count = _int_or_none(os.environ.get("WORDPOT_EVENT_LOG_BACKUP_COUNT") or app.config.get("EVENT_LOG_BACKUP_COUNT")) or 0
    return max_bytes, backup_count


def _rotate_event_log(path, backup_count):
    if backup_count <= 0:
        os.truncate(path, 0)
        return
    for index in range(backup_count - 1, 0, -1):
        source = "%s.%s" % (path, index)
        if os.path.exists(source):
            os.replace(source, "%s.%s" % (path, index + 1))
    os.replace(path, "%s.1" % path)


def write_event_line(line):
    path = _event_log_path()
    data = (line + "\n").encode("utf-8")
    max_bytes, backup_count = _event_log_rotation()
    lock_path = "%s.lock" % path

    # One write() per event on an O_APPEND descriptor, serialized with an
    # advisory lock so gunicorn workers and threads never interleave lines.
    with open(lock_path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if max_bytes > 0 and os.path.exists(path) and os.path.getsize(path) + len(data) > max_bytes:
                _rotate_event_log(path, backup_count)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    _chmod_best_effort(path, 0o640)


def store_payload(data, payload_sha256):
    if not data or not payload_sha256 or not _payload_storage_enabled():
        return {"payload_stored": False, "payload_ref": None, "payload_path": None}

    if len(data) > _payload_storage_max_bytes():
        return {"payload_stored": False, "payload_ref": None, "payload_path": None}

    try:
        payload_dir = _payload_storage_dir()
        if not payload_dir:
            return {"payload_stored": False, "payload_ref": None, "payload_path": None}

        shard = payload_sha256[:2]
        shard_dir = os.path.join(payload_dir, shard)
        dir_mode = _payload_dir_mode()
        file_mode = _payload_file_mode()
        os.makedirs(shard_dir, mode=dir_mode, exist_ok=True)
        _chmod_best_effort(payload_dir, dir_mode)
        _chmod_best_effort(shard_dir, dir_mode)
        filename = "%s.bin" % payload_sha256
        payload_ref = os.path.join(shard, filename)
        payload_path = os.path.join(payload_dir, payload_ref)

        if not os.path.exists(payload_path):
            tmp_path = os.path.join(shard_dir, ".%s.%s.tmp" % (payload_sha256, uuid.uuid4().hex))
            with open(tmp_path, "xb") as handle:
                handle.write(data)
            os.chmod(tmp_path, file_mode)
            os.replace(tmp_path, payload_path)
        else:
            _chmod_best_effort(payload_path, file_mode)

        return {
            "payload_stored": True,
            "payload_ref": payload_ref.replace(os.sep, "/"),
            "payload_path": payload_path,
        }
    except OSError as exc:
        LOGGER.warning("Unable to store payload: %s", exc)
        return {"payload_stored": False, "payload_ref": None, "payload_path": None}


def payload_metadata(req):
    from wordpot import app

    data = req.get_data(cache=True, as_text=False) or b""
    limit = int(app.config.get("PAYLOAD_EXCERPT_BYTES", 4096))
    payload_sha256 = hashlib.sha256(data).hexdigest() if data else None
    stored = store_payload(data, payload_sha256)
    return {
        "payload_sha256": payload_sha256,
        "payload_excerpt": _safe_text(data, limit) if data else "",
        "payload_size": len(data),
        **stored,
    }


def observed_credentials(req):
    credentials = {}
    try:
        form = req.form
    except Exception:
        form = {}
    for key in SENSITIVE_FORM_KEYS:
        if key in form:
            credentials[key] = form.get(key, "")

    auth_header = req.headers.get("Authorization", "")
    if auth_header.lower().startswith("basic "):
        encoded = auth_header.split(" ", 1)[1].strip()
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8", errors="replace")
            username, _, password = decoded.partition(":")
            credentials["basic_username"] = username
            credentials["basic_password"] = password
        except Exception:
            credentials["authorization"] = "malformed-basic"

    return credentials or None


def credential_pair(credentials, details=None):
    credentials = credentials or {}
    details = details or {}

    username_sources = [
        details.get("username"),
        credentials.get("username"),
        credentials.get("user_login"),
        credentials.get("log"),
        credentials.get("user"),
        credentials.get("basic_username"),
    ]
    password_sources = [
        details.get("password"),
        credentials.get("password"),
        credentials.get("user_pass"),
        credentials.get("pwd"),
        credentials.get("pass"),
        credentials.get("basic_password"),
    ]

    username = next((value for value in username_sources if value is not None), None)
    password = next((value for value in password_sources if value is not None), None)
    return username, password


def omit_empty_fields(value):
    if isinstance(value, dict):
        return {
            key: omit_empty_fields(item)
            for key, item in value.items()
            if item is not None and item != ""
        }
    if isinstance(value, list):
        return [omit_empty_fields(item) for item in value]
    return value


def build_event_dict(
    req,
    profile,
    component_type=None,
    component_slug=None,
    technique=None,
    response_status=None,
    details=None,
    include_payload=True,
):
    user_agent = user_agent_from_request(req)
    parsed_user_agent = user_agent_details(req)
    credentials = observed_credentials(req)
    username, password = credential_pair(credentials, details)
    payload = payload_metadata(req) if include_payload else {
        "payload_sha256": None,
        "payload_excerpt": "",
        "payload_size": 0,
        "payload_stored": False,
        "payload_ref": None,
        "payload_path": None,
    }
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id(),
        "profile_id": profile.get("id"),
        "src_ip": client_ip_from_request(req),
        "src_port": source_port_from_request(req),
        "dest_ip": destination_ip_from_request(req),
        "dest_port": destination_port_from_request(req),
        "user_agent": user_agent,
        **parsed_user_agent,
        "url": req.url,
        "method": req.method,
        "path": req.path,
        "query": req.query_string.decode("utf-8", errors="replace"),
        "headers_subset": headers_subset(req),
        "component_type": component_type,
        "component_slug": component_slug,
        "technique": technique,
        "payload_sha256": payload["payload_sha256"],
        "payload_excerpt": payload["payload_excerpt"],
        "payload_size": payload["payload_size"],
        "payload_stored": payload["payload_stored"],
        "payload_ref": payload["payload_ref"],
        "payload_path": payload["payload_path"],
        "username": username,
        "password": password,
        "credentials_observed": credentials,
        "response_status": response_status,
    }
    details = dict(details or {})
    if req.headers.get("Host"):
        details.setdefault("http_host", req.headers.get("Host"))
    if details:
        event["details"] = details
    return omit_empty_fields(event)


def is_loopback_request(req):
    try:
        return ipaddress.ip_address(req.remote_addr or "").is_loopback
    except ValueError:
        return False


def should_skip_event(req):
    try:
        from wordpot import app

        if not app.config.get("EVENT_LOG_EXCLUDE_HEALTHCHECKS", True):
            return False

        excluded_paths = set(app.config.get("EVENT_LOG_EXCLUDE_PATHS", []))
        return req.path in excluded_paths and is_loopback_request(req)
    except Exception:
        return False


_HPFEEDS_STATE = {"pid": None, "client": None}
_HPFEEDS_LOCK = threading.Lock()


def _create_hpfeeds_client():
    from wordpot import app
    import hpfeeds

    client = hpfeeds.new(
        app.config["HPFEEDS_HOST"],
        app.config["HPFEEDS_PORT"],
        app.config["HPFEEDS_IDENT"],
        app.config["HPFEEDS_SECRET"],
    )
    client.s.settimeout(0.01)
    return client


def _hpfeeds_client():
    # gunicorn --preload forks after import, so a client created in the master
    # would share one socket between workers. Connect lazily per process.
    pid = os.getpid()
    if _HPFEEDS_STATE["pid"] != pid or _HPFEEDS_STATE["client"] is None:
        _HPFEEDS_STATE["client"] = _create_hpfeeds_client()
        _HPFEEDS_STATE["pid"] = pid
    return _HPFEEDS_STATE["client"]


def publish_event(event):
    from wordpot import app

    line = json.dumps(event, sort_keys=True)
    try:
        write_event_line(line)
    except Exception as exc:
        LOGGER.warning("Unable to write JSONL event: %s", exc)

    if not app.config.get("HPFEEDS_ENABLED"):
        return
    try:
        with _HPFEEDS_LOCK:
            _hpfeeds_client().publish(app.config["HPFEEDS_TOPIC"], line)
    except Exception as exc:
        _HPFEEDS_STATE["client"] = None
        LOGGER.warning("Unable to publish hpfeeds event: %s", exc)


def log_event(req, profile, **kwargs):
    if should_skip_event(req):
        return None
    event = build_event_dict(req, profile, **kwargs)
    publish_event(event)
    return event
