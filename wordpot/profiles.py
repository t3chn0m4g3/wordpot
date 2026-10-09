#!/usr/bin/env python3

import copy
import hashlib
import json
import os
from datetime import datetime, timezone

from flask import g, request


PLUGIN_CATALOG = {
    "elementor": {
        "name": "Elementor Website Builder",
        "version": "4.1.3",
        "requires": "6.6",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "elementor.php",
        "rest_namespaces": ["elementor/v1"],
    },
    "wordpress-seo": {
        "name": "Yoast SEO",
        "version": "27.8",
        "requires": "6.8",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "wp-seo.php",
        "rest_namespaces": ["yoast/v1"],
    },
    "contact-form-7": {
        "name": "Contact Form 7",
        "version": "6.1.6",
        "requires": "6.7",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "wp-contact-form-7.php",
        "rest_namespaces": ["contact-form-7/v1"],
    },
    "woocommerce": {
        "name": "WooCommerce",
        "version": "10.8.1",
        "requires": "6.9",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "woocommerce.php",
        "rest_namespaces": ["wc/v3", "wc/store/v1"],
    },
    "wpforms-lite": {
        "name": "WPForms Lite",
        "version": "1.10.2",
        "requires": "5.5",
        "tested": "7.0",
        "requires_php": "7.2",
        "main_file": "wpforms.php",
        "rest_namespaces": ["wpforms/v1"],
    },
    "google-site-kit": {
        "name": "Site Kit by Google",
        "version": "1.181.0",
        "requires": "5.2",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "google-site-kit.php",
        "rest_namespaces": ["google-site-kit/v1"],
    },
    "wordfence": {
        "name": "Wordfence Security",
        "version": "8.2.2",
        "requires": "4.7",
        "tested": "7.0",
        "requires_php": "7.0",
        "main_file": "wordfence.php",
        "rest_namespaces": ["wordfence/v1"],
    },
    "all-in-one-wp-migration": {
        "name": "All-in-One WP Migration and Backup",
        "version": "7.105",
        "requires": "3.3",
        "tested": "7.0",
        "requires_php": "5.3",
        "main_file": "all-in-one-wp-migration.php",
        "rest_namespaces": ["ai1wm/v1"],
    },
    "updraftplus": {
        "name": "UpdraftPlus: WP Backup & Migration Plugin",
        "version": "1.26.5",
        "requires": "3.2",
        "tested": "7.0",
        "requires_php": "5.6",
        "main_file": "updraftplus.php",
        "rest_namespaces": ["updraftplus/v1"],
    },
    "litespeed-cache": {
        "name": "LiteSpeed Cache",
        "version": "7.8.1",
        "requires": "5.3",
        "tested": "6.9.4",
        "requires_php": "7.2",
        "main_file": "litespeed-cache.php",
        "rest_namespaces": ["litespeed/v1"],
    },
    "jetpack": {
        "name": "Jetpack",
        "version": "15.9",
        "requires": "6.9",
        "tested": "7.0",
        "requires_php": "7.2",
        "main_file": "jetpack.php",
        "rest_namespaces": ["jetpack/v4"],
    },
    "really-simple-ssl": {
        "name": "Really Simple Security",
        "version": "9.6.0",
        "requires": "6.6",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "rlrsssl-really-simple-ssl.php",
        "rest_namespaces": ["really-simple-ssl/v1"],
    },
    "wp-mail-smtp": {
        "name": "WP Mail SMTP",
        "version": "4.8.0",
        "requires": "5.5",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "wp_mail_smtp.php",
        "rest_namespaces": ["wp-mail-smtp/v1"],
    },
    "duplicate-post": {
        "name": "Yoast Duplicate Post",
        "version": "4.6",
        "requires": "6.8",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "duplicate-post.php",
        "rest_namespaces": [],
    },
    "classic-editor": {
        "name": "Classic Editor",
        "version": "1.7.0",
        "requires": "4.9",
        "tested": "7.0",
        "requires_php": "5.2.4",
        "main_file": "classic-editor.php",
        "rest_namespaces": [],
    },
    "akismet": {
        "name": "Akismet Anti-spam",
        "version": "5.7",
        "requires": "5.8",
        "tested": "7.0",
        "requires_php": "7.2",
        "main_file": "akismet.php",
        "rest_namespaces": ["akismet/v1"],
    },
    "seo-by-rank-math": {
        "name": "Rank Math SEO",
        "version": "1.0.272",
        "requires": "6.3",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "seo-by-rank-math.php",
        "rest_namespaces": ["rankmath/v1"],
    },
    "duplicate-page": {
        "name": "Duplicate Page",
        "version": "4.5.9",
        "requires": "3.4",
        "tested": "6.9.4",
        "requires_php": "5.6",
        "main_file": "duplicate-page.php",
        "rest_namespaces": [],
    },
    "hostinger": {
        "name": "Hostinger Tools",
        "version": "3.0.68",
        "requires": "5.5",
        "tested": "6.9.4",
        "requires_php": "8.1",
        "main_file": "hostinger.php",
        "rest_namespaces": ["hostinger/v1"],
    },
    "insert-headers-and-footers": {
        "name": "WPCode",
        "version": "2.3.6",
        "requires": "5.0",
        "tested": "7.0",
        "requires_php": "7.0",
        "main_file": "insert-headers-and-footers.php",
        "rest_namespaces": ["wpcode/v1"],
    },
    "all-in-one-seo-pack": {
        "name": "All in One SEO",
        "version": "4.9.8",
        "requires": "5.3",
        "tested": "7.0",
        "requires_php": "7.2",
        "main_file": "all_in_one_seo_pack.php",
        "rest_namespaces": ["aioseo/v1"],
    },
    "wordpress-importer": {
        "name": "WordPress Importer",
        "version": "0.9.5",
        "requires": "5.2",
        "tested": "6.8.5",
        "requires_php": "7.2",
        "main_file": "wordpress-importer.php",
        "rest_namespaces": [],
    },
    "redirection": {
        "name": "Redirection",
        "version": "5.8.0",
        "requires": "5.9",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "redirection.php",
        "rest_namespaces": ["redirection/v1"],
    },
    "google-analytics-for-wordpress": {
        "name": "MonsterInsights",
        "version": "10.2.2",
        "requires": "5.6",
        "tested": "7.0",
        "requires_php": "7.2",
        "main_file": "googleanalytics.php",
        "rest_namespaces": ["monsterinsights/v1"],
    },
    "classic-widgets": {
        "name": "Classic Widgets",
        "version": "0.3",
        "requires": "4.9",
        "tested": "6.9.4",
        "requires_php": "5.6",
        "main_file": "classic-widgets.php",
        "rest_namespaces": [],
    },
    "header-footer-elementor": {
        "name": "Ultimate Addons for Elementor",
        "version": "2.8.8",
        "requires": "5.5",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "header-footer-elementor.php",
        "rest_namespaces": ["hfe/v1"],
    },
    "wps-hide-login": {
        "name": "WPS Hide Login",
        "version": "1.9.18",
        "requires": "4.1",
        "tested": "6.9.4",
        "requires_php": "7.0",
        "main_file": "wps-hide-login.php",
        "rest_namespaces": [],
    },
    "advanced-custom-fields": {
        "name": "Advanced Custom Fields",
        "version": "6.8.4",
        "requires": "6.0",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "acf.php",
        "rest_namespaces": ["acf/v3"],
    },
    "essential-addons-for-elementor-lite": {
        "name": "Essential Addons for Elementor",
        "version": "6.6.7",
        "requires": "5.8",
        "tested": "7.0",
        "requires_php": "7.0",
        "main_file": "essential_adons_elementor.php",
        "rest_namespaces": ["essential-addons/v1"],
    },
    "astra-sites": {
        "name": "Starter Templates",
        "version": "4.6.2",
        "requires": "5.5",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "astra-sites.php",
        "rest_namespaces": ["starter-templates/v1"],
    },
    "tinymce-advanced": {
        "name": "Advanced Editor Tools",
        "version": "5.9.2",
        "requires": "5.9",
        "tested": "6.9.4",
        "requires_php": "5.6",
        "main_file": "tinymce-advanced.php",
        "rest_namespaces": [],
    },
    "elementskit-lite": {
        "name": "ElementsKit Elementor Addons",
        "version": "3.9.8",
        "requires": "5.8",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "elementskit-lite.php",
        "rest_namespaces": ["elementskit/v1"],
    },
    "limit-login-attempts-reloaded": {
        "name": "Limit Login Attempts Reloaded",
        "version": "3.3.1",
        "requires": "5.0",
        "tested": "7.0",
        "requires_php": "5.6",
        "main_file": "limit-login-attempts-reloaded.php",
        "rest_namespaces": ["llar/v1"],
    },
    "mailchimp-for-wp": {
        "name": "MC4WP: Mailchimp for WordPress",
        "version": "4.13.0",
        "requires": "4.6",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "mailchimp-for-wp.php",
        "rest_namespaces": ["mc4wp/v1"],
    },
    "loco-translate": {
        "name": "Loco Translate",
        "version": "2.8.5",
        "requires": "5.7",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "loco.php",
        "rest_namespaces": ["loco/v1"],
    },
    "disable-comments": {
        "name": "Disable Comments",
        "version": "2.7.0",
        "requires": "5.0",
        "tested": "7.0",
        "requires_php": "7.0",
        "main_file": "disable-comments.php",
        "rest_namespaces": [],
    },
    "wp-super-cache": {
        "name": "WP Super Cache",
        "version": "3.1.1",
        "requires": "5.2",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "wp-cache.php",
        "rest_namespaces": [],
    },
    "duplicator": {
        "name": "Duplicator",
        "version": "1.5.16.1",
        "requires": "5.3",
        "tested": "7.0",
        "requires_php": "7.4",
        "main_file": "duplicator.php",
        "rest_namespaces": ["duplicator/v1"],
    },
    "code-snippets": {
        "name": "Code Snippets",
        "version": "3.9.6",
        "requires": "5.0",
        "tested": "6.9.4",
        "requires_php": "7.4",
        "main_file": "code-snippets.php",
        "rest_namespaces": ["code-snippets/v1"],
    },
}


THEME_CATALOG = {
    "twentytwentyfive": {
        "name": "Twenty Twenty-Five",
        "version": "1.5",
        "author": "the WordPress team",
        "requires": "6.7",
        "requires_php": "7.2",
    },
    "hello-elementor": {
        "name": "Hello Elementor",
        "version": "3.4.9",
        "author": "Elementor Team",
        "requires": "6.0",
        "requires_php": "7.4",
    },
    "astra": {
        "name": "Astra",
        "version": "4.13.4",
        "author": "Brainstorm Force",
        "requires": "5.3",
        "requires_php": "5.3",
    },
    "twentytwentyfour": {
        "name": "Twenty Twenty-Four",
        "version": "1.5",
        "author": "the WordPress team",
        "requires": "6.4",
        "requires_php": "7.0",
    },
    "twentyeleven": {
        "name": "Twenty Eleven",
        "version": "4.8",
        "author": "the WordPress team",
        "requires": "3.2",
        "requires_php": "5.2.4",
    },
}


DEFAULT_PROFILES = [
    {
        "id": "modern-business",
        "blog_title": "Summit & Co Advisory",
        "blog_subtitle": "Insights, services, updates",
        "core_version": "7.0",
        "server_header": "Apache/2.4.58 (Ubuntu)",
        "theme": "twentytwentyfive",
        "themes": ["twentytwentyfive", "twentytwentyfour"],
        "plugins": [
            "elementor",
            "wordpress-seo",
            "contact-form-7",
            "wpforms-lite",
            "google-site-kit",
            "google-analytics-for-wordpress",
            "advanced-custom-fields",
            "insert-headers-and-footers",
            "wordfence",
            "really-simple-ssl",
            "akismet",
        ],
        "authors": [
            {"id": 1, "slug": "admin", "name": "Admin"},
            {"id": 2, "slug": "maria-keller", "name": "Maria Keller"},
        ],
        "locale": "en_US",
        "site_type": "business",
        "exposed_files": ["readme.html", "license.txt", "robots.txt", "sitemap.xml"],
    },
    {
        "id": "commerce",
        "blog_title": "Northline Shop",
        "blog_subtitle": "News, offers and product updates",
        "core_version": "7.0",
        "server_header": "nginx/1.24.0",
        "theme": "astra",
        "themes": ["astra", "twentytwentyfive"],
        "plugins": [
            "woocommerce",
            "elementor",
            "contact-form-7",
            "wordpress-seo",
            "litespeed-cache",
            "wp-mail-smtp",
            "updraftplus",
            "duplicator",
            "advanced-custom-fields",
            "redirection",
        ],
        "authors": [
            {"id": 1, "slug": "admin", "name": "Store Admin"},
            {"id": 3, "slug": "shop-manager", "name": "Shop Manager"},
        ],
        "locale": "en_US",
        "site_type": "commerce",
        "exposed_files": ["readme.html", "license.txt", "wp-sitemap.xml"],
    },
    {
        "id": "maintenance-lag",
        "blog_title": "City Desk Journal",
        "blog_subtitle": "Local updates and notes",
        "core_version": "6.9.2",
        "server_header": "Apache/2.4.52 (Ubuntu)",
        "theme": "hello-elementor",
        "themes": ["hello-elementor", "twentytwentyfour", "twentyeleven"],
        "plugins": [
            "elementor",
            "jetpack",
            "all-in-one-wp-migration",
            "updraftplus",
            "duplicate-post",
            "duplicate-page",
            "contact-form-7",
            "wordfence",
            "classic-editor",
            "classic-widgets",
            "tinymce-advanced",
            "wordpress-importer",
            "wp-super-cache",
        ],
        "authors": [
            {"id": 1, "slug": "admin", "name": "Admin"},
            {"id": 4, "slug": "editor", "name": "Editorial Team"},
        ],
        "locale": "en_US",
        "site_type": "publisher",
        "exposed_files": ["readme.html", "license.txt", "wp-sitemap.xml"],
    },
    {
        "id": "agency-builder",
        "blog_title": "Pixel Harbor Studio",
        "blog_subtitle": "Design notes, campaigns and landing pages",
        "core_version": "7.0",
        "server_header": "LiteSpeed",
        "theme": "hello-elementor",
        "themes": ["hello-elementor", "astra", "twentytwentyfive"],
        "plugins": [
            "elementor",
            "header-footer-elementor",
            "essential-addons-for-elementor-lite",
            "elementskit-lite",
            "astra-sites",
            "wpforms-lite",
            "seo-by-rank-math",
            "mailchimp-for-wp",
            "loco-translate",
            "limit-login-attempts-reloaded",
            "code-snippets",
            "duplicator",
        ],
        "authors": [
            {"id": 1, "slug": "admin", "name": "Admin"},
            {"id": 5, "slug": "creative", "name": "Creative Team"},
        ],
        "locale": "en_US",
        "site_type": "agency",
        "exposed_files": ["readme.html", "license.txt", "robots.txt", "wp-sitemap.xml"],
    },
]


def _plugin_from_slug(slug):
    plugin = copy.deepcopy(PLUGIN_CATALOG.get(slug, {}))
    plugin.setdefault("slug", slug)
    plugin.setdefault("name", slug.replace("-", " ").title())
    plugin.setdefault("version", "1.0.0")
    plugin.setdefault("requires", "5.0")
    plugin.setdefault("tested", "7.0")
    plugin.setdefault("requires_php", "7.4")
    plugin.setdefault("main_file", "%s.php" % slug)
    plugin.setdefault("rest_namespaces", [])
    return plugin


def _theme_from_slug(slug):
    theme = copy.deepcopy(THEME_CATALOG.get(slug, {}))
    theme.setdefault("slug", slug)
    theme.setdefault("name", slug.replace("-", " ").title())
    theme.setdefault("version", "1.0.0")
    theme.setdefault("author", "WordPress.org")
    theme.setdefault("requires", "5.0")
    theme.setdefault("requires_php", "7.4")
    return theme


def normalize_profile(raw):
    profile = copy.deepcopy(raw)
    profile.setdefault("id", "default")
    profile.setdefault("blog_title", "WordPress Site")
    profile.setdefault("blog_subtitle", "Just another WordPress site")
    profile.setdefault("core_version", "7.0")
    profile.setdefault("server_header", "Apache/2.4.58 (Ubuntu)")
    profile.setdefault("theme", "twentytwentyfive")
    profile.setdefault("themes", [profile["theme"]])
    profile.setdefault("plugins", [])
    profile.setdefault("authors", [{"id": 1, "slug": "admin", "name": "Admin"}])
    profile.setdefault("locale", "en_US")
    profile.setdefault("site_type", "blog")
    profile.setdefault("exposed_files", [])

    profile["plugins"] = [
        _plugin_from_slug(item) if isinstance(item, str) else {**_plugin_from_slug(item.get("slug", "")), **item}
        for item in profile["plugins"]
    ]
    profile["themes"] = [
        _theme_from_slug(item) if isinstance(item, str) else {**_theme_from_slug(item.get("slug", "")), **item}
        for item in profile["themes"]
    ]
    if not any(theme["slug"] == profile["theme"] for theme in profile["themes"]):
        profile["themes"].insert(0, _theme_from_slug(profile["theme"]))
    profile["authors"] = [normalize_author(author, index + 1) for index, author in enumerate(profile["authors"])]
    return profile


def normalize_author(author, default_id):
    if isinstance(author, str):
        return {"id": default_id, "slug": author, "name": author.replace("-", " ").title()}
    normalized = dict(author)
    normalized.setdefault("id", default_id)
    normalized.setdefault("slug", str(normalized.get("name", "admin")).lower().replace(" ", "-"))
    normalized.setdefault("name", normalized["slug"].replace("-", " ").title())
    return normalized


def configured_profiles(app):
    profiles = app.config.get("PROFILES") or DEFAULT_PROFILES
    if isinstance(profiles, dict):
        profiles = list(profiles.values())
    return [normalize_profile(profile) for profile in profiles]


def client_ip_from_request(req):
    # Only the direct peer is trusted. Behind a trusted proxy, ProxyFix
    # (TRUST_PROXY_HEADERS) rewrites remote_addr before we get here.
    if req is None:
        return "0.0.0.0"
    return req.remote_addr or "0.0.0.0"


def _profile_by_id(profiles, profile_id):
    for profile in profiles:
        if profile["id"] == profile_id:
            return profile
    return None


def _profile_state_path(app):
    configured = app.config.get("PROFILE_STATE_FILE") or os.environ.get("WORDPOT_PROFILE_STATE_FILE")
    if configured:
        return configured

    try:
        from wordpot.logger import _log_dir

        return os.path.join(_log_dir(), "profile-state.json")
    except Exception:
        return os.path.join(os.getcwd(), "profile-state.json")


def _read_profile_state(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _write_profile_state(path, state):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = "%s.tmp" % path
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
    os.replace(tmp_path, path)


def _next_startup_profile_id(app, profiles):
    state_path = _profile_state_path(app)
    lock_path = "%s.lock" % state_path

    try:
        import fcntl

        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = _read_profile_state(state_path)
            last_id = state.get("profile_id")
            last_index = next((index for index, profile in enumerate(profiles) if profile["id"] == last_id), -1)
            next_index = (last_index + 1) % len(profiles)
            selected = profiles[next_index]
            _write_profile_state(
                state_path,
                {
                    "profile_id": selected["id"],
                    "profile_index": next_index,
                    "profile_count": len(profiles),
                    "selected_at": datetime.now(timezone.utc).isoformat(),
                    "pid": os.getpid(),
                },
            )
            return selected["id"]
    except Exception:
        seed = "%s:%s" % (os.getpid(), datetime.now(timezone.utc).isoformat())
        return profiles[int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(profiles)]["id"]


def initialize_startup_profile(app):
    profiles = configured_profiles(app)
    if not profiles:
        app.config["_STARTUP_PROFILE_ID"] = normalize_profile(DEFAULT_PROFILES[0])["id"]
        return app.config["_STARTUP_PROFILE_ID"]

    fixed_profile_id = app.config.get("PROFILE_ID") or os.environ.get("WORDPOT_PROFILE_ID")
    if fixed_profile_id and _profile_by_id(profiles, fixed_profile_id):
        app.config["_STARTUP_PROFILE_ID"] = fixed_profile_id
        return fixed_profile_id

    mode = str(app.config.get("PROFILE_ROTATION", "startup")).lower()
    if mode in {"startup", "start", "boot"}:
        app.config["_STARTUP_PROFILE_ID"] = _next_startup_profile_id(app, profiles)
    elif mode in {"first", "none", "off"}:
        app.config["_STARTUP_PROFILE_ID"] = profiles[0]["id"]
    else:
        app.config["_STARTUP_PROFILE_ID"] = None

    return app.config["_STARTUP_PROFILE_ID"]


def select_profile(app, req=None):
    profiles = configured_profiles(app)
    if not profiles:
        return normalize_profile(DEFAULT_PROFILES[0])

    fixed_profile_id = app.config.get("PROFILE_ID") or os.environ.get("WORDPOT_PROFILE_ID")
    if fixed_profile_id:
        profile = _profile_by_id(profiles, fixed_profile_id)
        if profile:
            return profile

    mode = str(app.config.get("PROFILE_ROTATION", "startup")).lower()
    if mode in {"startup", "start", "boot", "first", "none", "off"}:
        profile_id = app.config.get("_STARTUP_PROFILE_ID")
        if profile_id is None:
            profile_id = initialize_startup_profile(app)
        profile = _profile_by_id(profiles, profile_id)
        if profile:
            return profile

    if mode in {"daily", "per_ip_day"}:
        rotation_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif mode in {"per_ip", "sticky"}:
        rotation_key = "sticky"
    else:
        rotation_key = "sticky"
    seed = "%s:%s" % (client_ip_from_request(req), rotation_key)
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(profiles)
    return profiles[index]


def current_profile(req=None):
    if hasattr(g, "wordpot_profile"):
        return g.wordpot_profile
    from wordpot import app

    g.wordpot_profile = select_profile(app, req or request)
    return g.wordpot_profile


def plugin_for_slug(profile, slug):
    for plugin in profile.get("plugins", []):
        if plugin.get("slug") == slug:
            return plugin
    return None


def theme_for_slug(profile, slug):
    for theme in profile.get("themes", []):
        if theme.get("slug") == slug:
            return theme
    return None


def profile_template_vars(profile, **extra):
    authors = profile.get("authors") or [{"id": 1, "slug": "admin", "name": "Admin"}]
    values = {
        "BLOGTITLE": profile["blog_title"],
        "BLOGSUBTITLE": profile["blog_subtitle"],
        "VERSION": profile["core_version"],
        "THEME": profile["theme"],
        "AUTHORS": [author["slug"] for author in authors],
        "AUTHOR_OBJECTS": authors,
        "AUTHORPAGE": False,
        "CURRENTAUTHOR": None,
    }
    values.update(extra)
    return values
