#!/usr/bin/env python3

APP_NAME = "Wordpot"
APP_VERSION = "3.0.0"
APP_DISPLAY_NAME = "%s %s" % (APP_NAME, APP_VERSION)

ASCII_ART = r"""
 __        __            _             _      _____
 \ \      / /__  _ __ __| |_ __   ___ | |_   |___ / 
  \ \ /\ / / _ \| '__/ _` | '_ \ / _ \| __|    |_ \ 
   \ V  V / (_) | | | (_| | |_) | (_) | |_    ___) |
    \_/\_/ \___/|_|  \__,_| .__/ \___/ \__|  |____/ 
                           |_|                       
"""


def startup_banner(profile_id=None, log_dir=None):
    lines = [ASCII_ART.strip("\n"), APP_DISPLAY_NAME]
    if profile_id:
        lines.append("profile: %s" % profile_id)
    if log_dir:
        lines.append("log_dir: %s" % log_dir)
    return "\n".join(lines)


def emit_startup_banner(logger=None, profile_id=None, log_dir=None):
    banner = startup_banner(profile_id=profile_id, log_dir=log_dir)
    print(banner, flush=True)
    if logger:
        for line in banner.splitlines():
            logger.info(line)
