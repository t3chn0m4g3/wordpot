"""Safe, static response baits for common configuration and shell probes."""

import hashlib
import re

from flask import render_template, request

from wordpot.events import log_event


CONFIG_PATH_RE = re.compile(
    r"^(?:/\.env|/\.git/(?:config|HEAD)|/wp-config\.php(?:\.(?:bak|save|old|swp)|~))$",
    re.IGNORECASE,
)
WEBSHELL_PATH_RE = re.compile(
    r"(?:^|/)(?:alfa|c99|r57|b374k|wso|webshell|shell|cmd|mini|filesman|adminer)\.php$",
    re.IGNORECASE,
)
COMMAND_FIELDS = {"cmd", "command", "exec", "execute", "shell"}
LOGIN_FIELDS = {"login", "user", "username", "pass", "password"}

_SAFE_CONFIG_VARIANTS = (
    {
        ".env": "# Application settings\nAPP_ENV=production\nAPP_DEBUG=false\nLOG_LEVEL=warning\nCACHE_DRIVER=file\n",
        ".git/config": "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n",
        ".git/HEAD": "ref: refs/heads/main\n",
        "wp-config": "<?php\n// Local site options\ndefine('WP_DEBUG', false);\ndefine('WP_CACHE', true);\n",
    },
    {
        ".env": "# Runtime options\nAPP_ENV=production\nAPP_DEBUG=false\nLOG_LEVEL=error\nCACHE_DRIVER=file\n",
        ".git/config": "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = true\n",
        ".git/HEAD": "ref: refs/heads/stable\n",
        "wp-config": "<?php\n// WordPress runtime options\ndefine('WP_DEBUG', false);\ndefine('WP_CACHE', false);\n",
    },
)


def _profile_variant(profile):
    profile_id = str(profile.get("id", "default"))
    return int(hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:8], 16) % len(_SAFE_CONFIG_VARIANTS)


def config_bait_for_path(path, profile):
    if not CONFIG_PATH_RE.fullmatch(path or ""):
        return None
    normalized = path.lower()
    variant = _SAFE_CONFIG_VARIANTS[_profile_variant(profile)]
    key = ".git/config" if normalized.endswith("/.git/config") else ".git/HEAD" if normalized.endswith("/.git/head") else ".env" if normalized == "/.env" else "wp-config"
    return variant[key]


def webshell_probe_kind(path, req):
    if not WEBSHELL_PATH_RE.search(path or ""):
        return None
    keys = {key.lower() for key in req.values}
    if keys & COMMAND_FIELDS:
        return "webshell_command"
    if req.method == "POST" or keys & LOGIN_FIELDS:
        return "webshell_login"
    return "webshell_probe"


def serve_config_bait(req, profile):
    body = config_bait_for_path(req.path, profile)
    if body is None:
        return None
    from wordpot.views import text_response

    log_event(
        req,
        profile,
        component_type="core",
        component_slug=req.path.lstrip("/"),
        technique="config_bait_served",
        response_status=200,
        details={"bait_file": req.path},
        include_payload=False,
    )
    return text_response(body, mimetype="text/plain; charset=UTF-8", profile=profile)


def serve_webshell_bait(req, profile, component_type="unknown", component_slug=None):
    kind = webshell_probe_kind(req.path, req)
    if kind is None:
        return None
    from wordpot.views import text_response

    log_event(
        req,
        profile,
        component_type=component_type,
        component_slug=component_slug or req.path.rsplit("/", 1)[-1],
        technique=kind,
        response_status=200,
        details={"webshell_probe": req.path},
    )
    body = render_template("webshell_login.html", invalid=kind != "webshell_probe")
    return text_response(body, profile=profile, noindex=True)
