#!/usr/bin/env python3

import os
import sys

# Parse CLI options before the startup profile is chosen, so --version has no
# side effects and --profile applies to the startup selection.
os.environ['WORDPOT_DEFER_STARTUP'] = '1'

try:
    from flask import Flask
except ImportError:
    print ("\n[X] Please install Flask:")
    print ("   $ pip install flask\n")
    exit()

from wordpot import app, parse_options, check_options, startup
from wordpot.branding import APP_DISPLAY_NAME
from wordpot.logger import *

check_options()

if __name__ == '__main__':
    parse_options()
    LOGGER.info('Checking command line options')
    check_options()
    startup()

    LOGGER.info('%s started on %s:%s', APP_DISPLAY_NAME, app.config['HOST'], app.config['PORT'])
    app.run(debug=app.debug, host=app.config['HOST'], port=int(app.config['PORT']))
    
