#!/usr/bin/env python3

import base64
import os
import re

from flask import make_response, send_file
from werkzeug.utils import safe_join


STATIC_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "static")

TEXT_TYPES = {
    "css": "text/css",
    "js": "application/javascript",
    "map": "application/json",
    "json": "application/json",
    "txt": "text/plain",
    "xml": "application/xml",
}

# Smallest valid 1x1 images, so the bytes match the advertised Content-Type.
IMAGE_TYPES = {
    "png": ("image/png", base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")),
    "gif": ("image/gif", base64.b64decode("R0lGODlhAQABAPAAAP///wAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw==")),
    "jpg": ("image/jpeg", base64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")),
    "webp": ("image/webp", base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")),
    "svg": ("image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" viewBox="0 0 1 1"></svg>\n'),
}
IMAGE_TYPES["jpeg"] = IMAGE_TYPES["jpg"]

IMAGE_RE = re.compile(r"\.(?:%s)$" % "|".join(sorted(IMAGE_TYPES)), re.I)
ASSET_RE = re.compile(r"\.(?:%s)$" % "|".join(sorted(TEXT_TYPES)), re.I)


def extension(path):
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def is_static_asset(path):
    return bool(IMAGE_RE.search(path) or ASSET_RE.search(path))


def _bundled_file(url_path):
    candidate = safe_join(STATIC_DIR, url_path.lstrip("/"))
    if candidate and os.path.isfile(candidate):
        return candidate
    return None


def asset_response(url_path, label="WordPress"):
    """Serve a bundled file when present, otherwise a typed placeholder."""
    ext = extension(url_path)
    bundled = _bundled_file(url_path)
    if bundled:
        mimetype = IMAGE_TYPES.get(ext, (TEXT_TYPES.get(ext, "application/octet-stream"),))[0]
        return send_file(bundled, mimetype=mimetype, conditional=True, max_age=31536000)

    if ext in IMAGE_TYPES:
        mimetype, body = IMAGE_TYPES[ext]
        response = make_response(body, 200)
        response.mimetype = mimetype
        return response

    mimetype = TEXT_TYPES.get(ext, "text/plain")
    if ext == "css":
        body = "/*! %s */\n" % label
    elif ext == "js":
        body = "/*! %s */\n" % label
    elif ext in {"json", "map"}:
        body = "{}\n"
    elif ext == "xml":
        body = '<?xml version="1.0" encoding="UTF-8"?>\n'
    else:
        body = "%s\n" % label
    response = make_response(body, 200)
    response.headers["Content-Type"] = "%s; charset=UTF-8" % mimetype
    return response
