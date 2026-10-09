#!/usr/bin/env python3

try:
    from flask import Flask, request
except ImportError:
    print ("\n[X] Please install Flask:")
    print ("   $ pip install flask\n")
    exit()

from optparse import OptionParser 
from wordpot.branding import APP_DISPLAY_NAME, emit_startup_banner
from wordpot.logger import * 
from werkzeug.routing import BaseConverter 
from werkzeug.middleware.proxy_fix import ProxyFix
import os

# ---------------
# Regex Converter
# ---------------

class RegexConverter(BaseConverter):
    def __init__(self, url_map, *items):
        super(RegexConverter, self).__init__(url_map)
        self.regex = items[0]

# -------
# Options
# -------

REQUIRED_OPTIONS = {
        'HOST':  '127.0.0.1',
        'PORT':  '80',
        'INTERACTION_DEPTH': 'medium',
        'MAX_CONTENT_LENGTH': 65536,
        'PAYLOAD_EXCERPT_BYTES': 4096,
        'PAYLOAD_STORAGE_ENABLED': True,
        'PAYLOAD_STORAGE_MAX_BYTES': 65536,
        'PAYLOAD_DIR_MODE': 0o750,
        'PAYLOAD_FILE_MODE': 0o640,
        'PAYLOAD_DIR': None,
        'EVENT_LOG_FILE': 'wordpot.json',
        'EVENT_LOG_MAX_BYTES': 0,
        'EVENT_LOG_BACKUP_COUNT': 0,
        'EVENT_LOG_EXCLUDE_HEALTHCHECKS': True,
        'EVENT_LOG_EXCLUDE_PATHS': ['/healthz'],
        'EVENT_DEST_IP': None,
        'EVENT_DEST_PORT': None,
        'PROFILE_ROTATION': 'startup',
        'PROFILE_STATE_FILE': None,
        'TRUST_PROXY_HEADERS': False,
        }


def parse_options():
    usage = "usage: %prog [options]"

    parser = OptionParser(usage=usage)
    parser.add_option('--version', action='store_true', dest='SHOW_VERSION', help='Show Wordpot version and exit')
    parser.add_option('--host', dest='HOST', help='Host address')
    parser.add_option('--port', dest='PORT', help='Port number')
    parser.add_option('--title', dest='BLOGTITLE', help='Blog title')
    parser.add_option('--theme', dest='THEME', help='Default theme name')
    parser.add_option('--ver', dest='VERSION', help='Wordpress version')
    parser.add_option('--server', dest='SERVER', help='Custom "Server" header')
    parser.add_option('--profile', dest='PROFILE_ID', help='Fixed honeypot profile id')

    (options, args) = parser.parse_args()
    if options.SHOW_VERSION:
        print(APP_DISPLAY_NAME)
        raise SystemExit(0)
    
    # for opt, val in options.__dict__.iteritems():
    for opt, val in options.__dict__.items():
        if val is not None:
            app.config[opt] = val


def check_options():
    #for k, v in REQUIRED_OPTIONS.iteritems():
    for k, v in REQUIRED_OPTIONS.items():
        if k not in app.config:
            LOGGER.error('%s was not set. Falling back to default: %s', k, v)
            app.config[k] = v

# -------------------
# Building the Logger
# -------------------

logging_setup()

# ------------
# Building app
# ------------

# No Flask /static/ route: assets are served under WordPress paths by views.
app = Flask('wordpot', static_folder=None)
app.url_map.converters['regex'] = RegexConverter

# Import config from file
conffile = os.path.join(os.path.abspath(os.path.dirname(__file__)), '../wordpot.conf')
LOGGER.info('Loading conf file: %s', conffile) # %s doesn't work with python3
try:
    app.config.from_pyfile(conffile)
except Exception as exc:
    LOGGER.error('Can\'t load conf file %s: %s', conffile, exc)
check_options()
app.config['MAX_CONTENT_LENGTH'] = int(app.config.get('MAX_CONTENT_LENGTH', 65536))
app.config['PAYLOAD_STORAGE_MAX_BYTES'] = int(app.config.get('PAYLOAD_STORAGE_MAX_BYTES') or app.config['MAX_CONTENT_LENGTH'])


def startup():
    """Select the startup profile and print the banner (once per process tree)."""
    from wordpot.profiles import initialize_startup_profile

    initialize_startup_profile(app)
    if os.environ.get('WORDPOT_SUPPRESS_BANNER') not in {'1', 'true', 'yes'}:
        emit_startup_banner(
            LOGGER,
            profile_id=app.config.get('_STARTUP_PROFILE_ID') or app.config.get('PROFILE_ID'),
            log_dir=log_dir(),
        )


# Gunicorn imports the app once in the master (--preload), so the profile is
# chosen before workers fork. wordpot.py defers this until CLI options such as
# --version and --profile have been parsed.
if os.environ.get('WORDPOT_DEFER_STARTUP') not in {'1', 'true', 'yes'}:
    startup()

if app.config.get('TRUST_PROXY_HEADERS'):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

if app.config.get('HPFEEDS_ENABLED', False):
    # The client connects lazily per worker process, see wordpot.events.
    LOGGER.info('hpfeeds enabled for broker %s:%s', app.config['HPFEEDS_HOST'], app.config['HPFEEDS_PORT'])
else:
    LOGGER.warning('hpfeeds is disabled')


# ------------------------
# Add Custom Server Header
#-------------------------

@app.before_request
def assign_request_id():
    from wordpot.events import request_id
    request_id()
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        request.get_data(cache=True, as_text=False)


@app.after_request
def add_server_header(response):
    try:
        from wordpot.profiles import current_profile
        server_header = current_profile().get('server_header') or app.config.get('SERVER')
    except Exception:
        server_header = app.config.get('SERVER')
    if server_header:
        response.headers['Server'] = server_header
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')

    return response

import wordpot.views
