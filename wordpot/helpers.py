#!/usr/bin/env python3

from wordpot.profiles import current_profile, plugin_for_slug, theme_for_slug


def is_plugin_whitelisted(plugin):
    profile = current_profile()
    return plugin_for_slug(profile, plugin) is not None


def is_theme_whitelisted(theme):
    profile = current_profile()
    return theme_for_slug(profile, theme) is not None
