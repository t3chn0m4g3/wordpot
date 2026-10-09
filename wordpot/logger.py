#!/usr/bin/env python3

import logging
import logging.handlers
import os

LOGGER = logging.getLogger('wordpot-logger')


def log_dir():
    configured = os.environ.get('WORDPOT_LOG_DIR')
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend([
        '/opt/wordpot/logs',
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs')),
    ])

    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            if os.access(candidate, os.W_OK):
                return candidate
        except OSError:
            continue

    return os.getcwd()


def _log_dir():
    return log_dir()


def _add_rotating_handler(logger, filename):
    if logger.handlers:
        return
    formatter = logging.Formatter('%(message)s')
    logfile = os.path.join(_log_dir(), filename)
    handler = logging.handlers.RotatingFileHandler(logfile, 'a', 2097152, 10)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

def logging_setup():
    _add_rotating_handler(LOGGER, 'wordpot-runtime.log')
    return True
