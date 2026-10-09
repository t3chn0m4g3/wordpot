#!/usr/bin/env python3

import re

from wordpot.assets import is_static_asset


LURE_PARAM_RE = re.compile(
    r"(url|uri|file|path|src|dest|redirect|download|import|export|upload|backup|log|template|doc|image|callback)",
    re.I,
)
LURE_PATH_RE = re.compile(
    r"(ajax|upload|import|export|download|backup|restore|file|log|debug|installer|setup|license|connector)",
    re.I,
)
TIMTHUMB_RE = re.compile(r"(?:timthumb|thumb|phpthumb|uploadify)", re.I)
TIMTHUMB_SCRIPT_RE = re.compile(r"(?:^|/)(?:timthumb|thumb)\.php$", re.I)
COMMON_FILE_RE = re.compile(r"(wp-config|\.sql|\.zip|backup|dump|\.bak|\.old|\.swp|\.tar|\.gz)", re.I)
DEBUG_FILE_RE = re.compile(r"(debug|phpinfo|info|server-status|server-info)", re.I)


def lure_details(req):
    values = {}
    for key in req.values:
        if LURE_PARAM_RE.search(key):
            values[key] = req.values.get(key, "")
    return {"action": req.values.get("action"), "lure_params": values}


def detect_path_lure(component_type, component_slug, subpath, req):
    path = (subpath or "").strip("/")
    details = {"subpath": path, **lure_details(req)}

    if TIMTHUMB_RE.search(path):
        details["matched_pattern"] = "timthumb_uploadify"
        # timthumb.php / thumb.php answer like TimThumb so scanners follow up
        # with a src= payload; remote images are never fetched.
        is_timthumb = TIMTHUMB_SCRIPT_RE.search(path) is not None
        return {
            "technique": "timthumb_probe",
            "details": details,
            "response_status": 400 if is_timthumb else 404,
            "response_kind": "timthumb" if is_timthumb else "not_found",
        }

    # Static assets such as logo.png or file-upload.js are ordinary theme and
    # plugin files; only treat them as lures when they carry lure parameters.
    path_matches = LURE_PATH_RE.search(path) and not is_static_asset(path)
    if path_matches or details["lure_params"]:
        return {
            "technique": "%s_lure_payload" % component_type,
            "details": details,
            "response_status": 200 if component_type in {"plugin", "theme"} else 404,
            "response_kind": "invalid_nonce" if component_type in {"plugin", "theme"} else "not_found",
        }

    return None


def detect_common_file_lure(filename, ext, req):
    full_name = "%s.%s" % (filename, ext)
    details = {"filename": full_name, **lure_details(req)}

    if COMMON_FILE_RE.search(full_name):
        details["matched_pattern"] = "backup_or_config"
        return {
            "technique": "interesting_file_probe",
            "details": details,
            "response_status": 404,
            "response_kind": "not_found",
        }

    if DEBUG_FILE_RE.search(full_name):
        details["matched_pattern"] = "debug_artifact"
        return {
            "technique": "debug_artifact_probe",
            "details": details,
            "response_status": 404,
            "response_kind": "not_found",
        }

    return None
