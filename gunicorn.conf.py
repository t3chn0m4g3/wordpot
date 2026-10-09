#!/usr/bin/env python3
"""Gunicorn settings for the Wordpot container."""

import gunicorn.http.wsgi as gunicorn_wsgi


bind = "0.0.0.0:80"
workers = 2
threads = 4
preload_app = True
accesslog = "-"
errorlog = "-"


# Gunicorn always emits its own "Server: gunicorn" header in addition to the
# one set by the application. A real WordPress host sends exactly one Server
# header, so drop gunicorn's and keep the profile's.
_default_headers = gunicorn_wsgi.Response.default_headers


def _default_headers_without_server(self):
    return [header for header in _default_headers(self) if not header.lower().startswith("server:")]


gunicorn_wsgi.Response.default_headers = _default_headers_without_server
