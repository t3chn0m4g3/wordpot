#!/usr/bin/env python3

import json
import re
from datetime import datetime, timezone

from flask import abort, make_response, redirect, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from wordpot import app
from wordpot.assets import ASSET_RE, IMAGE_RE, asset_response
from wordpot.events import is_loopback_request, log_event
from wordpot.helpers import is_plugin_whitelisted, is_theme_whitelisted
from wordpot.lures import detect_common_file_lure, detect_path_lure, lure_details
from wordpot.profiles import (
    current_profile,
    plugin_for_slug,
    profile_template_vars,
    theme_for_slug,
)


ALL_METHODS = ["GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"]
READ_METHODS = ["GET", "HEAD", "OPTIONS"]
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def site_url(path="/"):
    root = request.url_root.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return root + path


def wp_headers(response, profile, noindex=False):
    response.headers.setdefault("X-Powered-By", "PHP/8.3.8")
    response.headers.setdefault("X-Pingback", site_url("/xmlrpc.php"))
    response.headers.setdefault("Link", '<%s>; rel="https://api.w.org/"' % site_url("/wp-json/"))
    if noindex:
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    return response


def text_response(body="", status=200, mimetype="text/html; charset=UTF-8", profile=None, noindex=False):
    response = make_response(body, status)
    response.mimetype = mimetype.split(";", 1)[0]
    if "charset=" in mimetype:
        response.headers["Content-Type"] = mimetype
    return wp_headers(response, profile or current_profile(), noindex=noindex)


def json_response(data, status=200, profile=None):
    response = text_response(
        json.dumps(data),
        status=status,
        mimetype="application/json; charset=UTF-8",
        profile=profile,
    )
    return response


def xml_response(body, status=200, profile=None):
    return text_response(body, status=status, mimetype="application/xml; charset=UTF-8", profile=profile)


def options_response(methods):
    response = text_response("", status=204, mimetype="text/plain; charset=UTF-8")
    response.headers["Allow"] = ", ".join(methods)
    response.headers["Access-Control-Allow-Methods"] = response.headers["Allow"]
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-WP-Nonce"
    return response


def render_wp_template(template, profile, status=200, noindex=False, **vars_extra):
    body = render_template(template, vars=profile_template_vars(profile, **vars_extra))
    return text_response(body, status=status, profile=profile, noindex=noindex)


def safe_author_from_request(profile):
    author_id = request.args.get("author")
    if author_id is None:
        return None
    try:
        numeric_id = int(author_id)
    except (TypeError, ValueError):
        return None
    for author in profile.get("authors", []):
        if int(author.get("id", 0)) == numeric_id:
            return author
    return None


def rest_namespaces(profile):
    namespaces = ["oembed/1.0", "wp/v2", "wp-site-health/v1", "wp-block-editor/v1"]
    for plugin in profile.get("plugins", []):
        namespaces.extend(plugin.get("rest_namespaces", []))
    return sorted(set(namespaces))


def rest_route_index(profile):
    return {
        "name": profile["blog_title"],
        "description": profile["blog_subtitle"],
        "url": site_url("/"),
        "home": site_url("/"),
        "gmt_offset": 0,
        "timezone_string": "UTC",
        "namespaces": rest_namespaces(profile),
        "authentication": {"application-passwords": {"endpoints": {"authorization": site_url("/wp-admin/authorize-application.php")}}},
        "routes": {
            "/": {"namespace": "", "methods": ["GET"]},
            "/wp/v2": {"namespace": "wp/v2", "methods": ["GET"]},
            "/wp/v2/posts": {"namespace": "wp/v2", "methods": ["GET", "POST"]},
            "/wp/v2/users": {"namespace": "wp/v2", "methods": ["GET"]},
        },
    }


def rest_author(author):
    author_id = int(author.get("id", 1))
    slug = author.get("slug", "admin")
    name = author.get("name", slug)
    return {
        "id": author_id,
        "name": name,
        "url": "",
        "description": "",
        "link": site_url("/author/%s/" % slug),
        "slug": slug,
        "avatar_urls": {
            "24": "https://secure.gravatar.com/avatar/%032d?s=24&d=mm&r=g" % author_id,
            "48": "https://secure.gravatar.com/avatar/%032d?s=48&d=mm&r=g" % author_id,
            "96": "https://secure.gravatar.com/avatar/%032d?s=96&d=mm&r=g" % author_id,
        },
        "_links": {
            "self": [{"href": site_url("/wp-json/wp/v2/users/%s" % author_id)}],
            "collection": [{"href": site_url("/wp-json/wp/v2/users")}],
        },
    }


def rest_error(code, message, status):
    return json_response({"code": code, "message": message, "data": {"status": status}}, status=status)


def home_posts(profile):
    author = profile["authors"][0]
    return [
        {
            "id": 1,
            "date": "2026-06-12T09:14:00",
            "date_gmt": "2026-06-12T09:14:00",
            "guid": {"rendered": site_url("/?p=1")},
            "modified": "2026-06-17T17:36:00",
            "modified_gmt": "2026-06-17T17:36:00",
            "slug": "hello-world",
            "status": "publish",
            "type": "post",
            "link": site_url("/?p=1"),
            "title": {"rendered": "Hello world!"},
            "content": {"rendered": "<p>Welcome to WordPress.</p>", "protected": False},
            "excerpt": {"rendered": "<p>Welcome to WordPress.</p>", "protected": False},
            "author": author["id"],
            "_links": {
                "self": [{"href": site_url("/wp-json/wp/v2/posts/1")}],
                "author": [{"href": site_url("/wp-json/wp/v2/users/%s" % author["id"])}],
            },
        }
    ]


def front_page_content(profile):
    site_type = profile.get("site_type", "business")
    author = profile.get("authors", [{"id": 1, "slug": "admin", "name": "Admin"}])[0]
    base = {
        "site_type": site_type,
        "author": author,
        "body_class": "home page-template-default wp-embed-responsive",
        "hero_label": "Latest from %s" % profile["blog_title"],
        "hero_title": "Practical updates for teams building better sites",
        "hero_text": profile["blog_subtitle"],
        "primary_action": "View services",
        "secondary_action": "Read the journal",
        "stats": [
            {"value": "24", "label": "Recent updates"},
            {"value": "7.0", "label": "WordPress ready"},
            {"value": "12", "label": "Active tools"},
        ],
        "cards": [
            {"title": "Planning notes", "text": "New rollout checklist for content, forms and analytics."},
            {"title": "Operations", "text": "Maintenance windows and platform updates for June."},
            {"title": "Support", "text": "Contact the team for onboarding, migrations and reviews."},
        ],
        "posts": [
            {"title": "Hello world!", "date": "June 12, 2026", "url": "/?p=1", "category": "Updates", "excerpt": "Welcome to WordPress. This is your first post. Edit or delete it, then start blogging!"},
            {"title": "June site maintenance window", "date": "June 17, 2026", "url": "/?p=2", "category": "Operations", "excerpt": "A short note about plugin checks, backup verification and scheduled publishing."},
            {"title": "Improving contact form deliverability", "date": "June 18, 2026", "url": "/?p=3", "category": "Guides", "excerpt": "A practical checklist for forms, SMTP settings and analytics events."},
        ],
        "products": [],
        "plugins": profile.get("plugins", []),
    }

    if site_type == "commerce":
        base.update(
            {
                "body_class": "home page-template-default theme-astra woocommerce-js ast-desktop ast-page-builder-template",
                "hero_label": "Summer collection",
                "hero_title": "Everyday essentials shipped from Northline",
                "hero_text": "New arrivals, seasonal offers and store updates from the team.",
                "primary_action": "Shop new arrivals",
                "secondary_action": "Track an order",
                "stats": [
                    {"value": "42", "label": "Products"},
                    {"value": "4.8", "label": "Store rating"},
                    {"value": "24h", "label": "Dispatch target"},
                ],
                "cards": [
                    {"title": "Free shipping threshold", "text": "Orders over $75 qualify for standard shipping this week."},
                    {"title": "Secure checkout", "text": "Payments, tax and order emails are checked before launch."},
                    {"title": "Stock update", "text": "Core sizes are back in inventory after the June restock."},
                ],
                "products": [
                    {"name": "Canvas Day Pack", "price": "$68.00", "badge": "New"},
                    {"name": "Desk Organizer Set", "price": "$34.00", "badge": "Popular"},
                    {"name": "Travel Mug", "price": "$22.00", "badge": "Sale"},
                ],
            }
        )
    elif site_type == "publisher":
        base.update(
            {
                "body_class": "home blog wp-embed-responsive elementor-default elementor-kit-42",
                "hero_label": "City Desk Journal",
                "hero_title": "Local reporting, updates and notes from the desk",
                "hero_text": "A compact newsroom-style site with editorial updates and community notes.",
                "primary_action": "Latest stories",
                "secondary_action": "About the desk",
                "stats": [
                    {"value": "18", "label": "June posts"},
                    {"value": "3", "label": "Editors"},
                    {"value": "6.9", "label": "Core branch"},
                ],
                "cards": [
                    {"title": "Council notes", "text": "A short recap from this week's public meeting."},
                    {"title": "Transit update", "text": "Weekend service changes and route alerts."},
                    {"title": "Community board", "text": "Events, submissions and editorial contact details."},
                ],
            }
        )
    elif site_type == "agency":
        base.update(
            {
                "body_class": "home page-template-default elementor-default elementor-kit-8 elementor-page elementor-page-12",
                "hero_label": "Pixel Harbor Studio",
                "hero_title": "Landing pages, campaigns and launch systems",
                "hero_text": "Design notes, campaign pages and studio updates from the build team.",
                "primary_action": "Start a project",
                "secondary_action": "View work",
                "stats": [
                    {"value": "36", "label": "Launches"},
                    {"value": "12", "label": "Active clients"},
                    {"value": "4", "label": "Builder add-ons"},
                ],
                "cards": [
                    {"title": "Campaign build", "text": "A new landing page stack with forms, SEO and tracking."},
                    {"title": "Template library", "text": "Reusable sections for service pages and launch pages."},
                    {"title": "Localization", "text": "Translation workflow updates for current client sites."},
                ],
            }
        )
    return base


def plugin_readme(plugin):
    return """=== {name} ===
Contributors: wordpressdotorg
Requires at least: {requires}
Tested up to: {tested}
Requires PHP: {requires_php}
Stable tag: {version}
License: GPLv2 or later

== Description ==
{name} is installed and active on this site.

== Changelog ==
= {version} =
Maintenance and compatibility release.
""".format(**plugin)


def theme_stylesheet(theme):
    css = """/*
Theme Name: {name}
Theme URI: https://wordpress.org/themes/{slug}/
Author: {author}
Version: {version}
Requires at least: {requires}
Requires PHP: {requires_php}
License: GNU General Public License v2 or later
Text Domain: {slug}
*/

body {{ margin: 0; color: #1f2933; background: #f7f8fa; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.6; }}
a {{ color: #1d4ed8; text-decoration-thickness: .08em; text-underline-offset: .18em; }}
.wp-site-blocks {{ min-height: 100vh; }}
.wp-block-template-part {{ background: #ffffff; border-bottom: 1px solid #e3e7ee; }}
.wp-block-group.alignfull {{ width: 100%; }}
.site-header__inner, .site-footer__inner, .site-main > section {{ max-width: 1160px; margin: 0 auto; padding-left: 24px; padding-right: 24px; }}
.site-header__inner {{ min-height: 76px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }}
.site-branding a {{ color: #111827; text-decoration: none; }}
.site-title {{ margin: 0; font-size: 22px; font-weight: 700; }}
.site-description {{ margin: 2px 0 0; color: #64748b; font-size: 14px; }}
.wp-block-navigation ul {{ display: flex; gap: 18px; padding: 0; margin: 0; list-style: none; }}
.wp-block-navigation a {{ color: #334155; text-decoration: none; font-size: 14px; }}
.wp-block-cover {{ padding-top: 72px; padding-bottom: 72px; background: linear-gradient(135deg, #f8fafc 0%, #e8eef6 100%); }}
.hero-grid {{ display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(280px, .9fr); gap: 42px; align-items: center; }}
.eyebrow {{ margin: 0 0 12px; color: #0f766e; font-size: 13px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }}
.wp-block-heading {{ margin: 0; color: #111827; font-size: clamp(38px, 6vw, 70px); line-height: .98; letter-spacing: 0; }}
.hero-copy {{ max-width: 680px; color: #475569; font-size: 19px; }}
.wp-block-buttons {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }}
.wp-block-button__link {{ display: inline-flex; align-items: center; min-height: 44px; padding: 0 18px; border-radius: 4px; background: #111827; color: #ffffff; text-decoration: none; font-weight: 650; }}
.wp-block-button.is-style-outline .wp-block-button__link {{ background: transparent; color: #111827; box-shadow: inset 0 0 0 1px #111827; }}
.hero-panel {{ background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; padding: 22px; box-shadow: 0 18px 45px rgba(15, 23, 42, .08); }}
.metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 18px; }}
.metric {{ padding: 16px; border-radius: 6px; background: #f1f5f9; }}
.metric strong {{ display: block; color: #0f172a; font-size: 24px; line-height: 1; }}
.metric span {{ color: #64748b; font-size: 13px; }}
.section-band {{ padding-top: 56px; padding-bottom: 56px; }}
.section-heading {{ max-width: 760px; margin: 0 auto 28px; text-align: center; }}
.section-heading h2 {{ margin: 0; color: #111827; font-size: 34px; letter-spacing: 0; }}
.section-heading p {{ margin: 8px 0 0; color: #64748b; }}
.card-grid, .post-grid, .products {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }}
.wp-block-column, .wp-block-post, .product {{ min-width: 0; background: #ffffff; border: 1px solid #e1e7ef; border-radius: 8px; padding: 22px; }}
.wp-block-column h3, .wp-block-post-title, .woocommerce-loop-product__title {{ margin: 0 0 8px; color: #111827; font-size: 20px; line-height: 1.25; letter-spacing: 0; }}
.wp-block-post-date, .product .onsale, .product .price {{ color: #64748b; font-size: 13px; }}
.wp-block-post-excerpt, .wp-block-column p {{ color: #475569; }}
.site-footer {{ background: #111827; color: #cbd5e1; padding: 34px 0; }}
.site-footer a {{ color: #ffffff; }}
.elementor-section {{ position: relative; }}
.elementor-widget-container {{ min-width: 0; }}
.woocommerce ul.products {{ padding: 0; margin: 0; list-style: none; }}
@media (max-width: 760px) {{
  .site-header__inner, .hero-grid {{ display: block; }}
  .wp-block-navigation ul {{ flex-wrap: wrap; margin-top: 16px; }}
  .hero-panel {{ margin-top: 28px; }}
  .metric-grid, .card-grid, .post-grid, .products {{ grid-template-columns: 1fr; }}
  .wp-block-heading {{ font-size: 40px; }}
}}
""".format(**theme)
    if theme.get("slug") == "astra":
        css += "\n.ast-page-builder-template .wp-block-cover{background:#f6fbff}.woocommerce .product{border-top:3px solid #2563eb}\n"
    elif theme.get("slug") == "hello-elementor":
        css += "\n.elementor-page .wp-block-cover{background:#f7f6ff}.elementor-page .wp-block-button__link{background:#5f3dc4}\n"
    return css


def static_response(path, profile, label="WordPress"):
    return wp_headers(asset_response(path, label=label), profile)


def forbidden_page(profile):
    server = profile.get("server_header") or "Apache"
    host = request.host.split(":", 1)[0]
    port = request.environ.get("SERVER_PORT") or "80"
    if server.lower().startswith("nginx"):
        return "<html>\r\n<head><title>403 Forbidden</title></head>\r\n<body>\r\n<center><h1>403 Forbidden</h1></center>\r\n<hr><center>%s</center>\r\n</body>\r\n</html>\r\n" % server.split(" ", 1)[0]
    if server.lower().startswith("litespeed"):
        return '<!DOCTYPE html>\n<html style="height:100%%">\n<head><title> 403 Forbidden\r\n</title></head>\n<body style="color: #444; margin:0;font: normal 14px/20px Arial, Helvetica, sans-serif; height:100%%; background-color: #fff;">\n<div style="height:auto; min-height:100%%; "><div style="text-align: center; width:800px; margin-left: -400px; position:absolute; top: 30%%; left:50%%;">\n<h1 style="margin:0; font-size:150px; line-height:150px; font-weight:bold;">403</h1>\n<h2 style="margin-top:20px;font-size: 30px;">Forbidden\r\n</h2>\n<p>Access to this resource on the server is denied!</p>\n</div></div></body></html>\n'
    return """<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html><head>
<title>403 Forbidden</title>
</head><body>
<h1>Forbidden</h1>
<p>You don't have permission to access this resource.</p>
<hr>
<address>%s Server at %s Port %s</address>
</body></html>
""" % (server, host, port)


@app.errorhandler(403)
def forbidden(error):
    profile = current_profile()
    response = make_response(forbidden_page(profile), 403)
    response.headers["Content-Type"] = "text/html; charset=iso-8859-1"
    return response


@app.errorhandler(404)
@app.errorhandler(405)
def not_found(error):
    # WordPress rewrites unknown paths to index.php and renders the theme 404.
    profile = current_profile()
    response = render_wp_template("404.html", profile, status=404, noindex=True)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    return response


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
    profile = current_profile()
    log_event(request, profile, technique="request_too_large", response_status=413, include_payload=False)
    return rest_error("request_entity_too_large", "Request body is too large.", 413)


@app.route("/healthz", methods=ALL_METHODS)
def healthz():
    # Container healthchecks call 127.0.0.1; everyone else sees a normal 404.
    if not is_loopback_request(request):
        return catchall("healthz")
    if request.method == "OPTIONS":
        response = text_response("", status=204, mimetype="text/plain; charset=UTF-8")
        response.headers["Allow"] = "GET, HEAD, OPTIONS"
        return response
    return text_response("ok\n", mimetype="text/plain; charset=UTF-8")


@app.route("/", methods=ALL_METHODS)
@app.route("/index.php", methods=ALL_METHODS)
def home():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)

    if request.args.get("feed") or request.path.endswith("/feed/"):
        log_event(request, profile, component_type="core", technique="feed_probe", response_status=200)
        return feed()

    author = safe_author_from_request(profile)
    if "author" in request.args:
        details = {"author": request.args.get("author"), "resolved": bool(author)}
        log_event(request, profile, component_type="core", technique="user_enumeration", response_status=200, details=details)

    if request.method == "POST":
        log_event(request, profile, component_type="core", technique="site_post", response_status=200, details=lure_details(request))

    if not author:
        return render_wp_template("front-page.html", profile, FRONT=front_page_content(profile))

    author_vars = {}
    if author:
        author_vars = {"AUTHORPAGE": True, "CURRENTAUTHOR": (author["id"], author["slug"])}
    return render_wp_template("twentyeleven.html", profile, **author_vars)


@app.route("/feed/", methods=["GET", "HEAD", "OPTIONS"])
@app.route("/comments/feed/", methods=["GET", "HEAD", "OPTIONS"])
def feed():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS"])
    body = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{title}</title><link>{link}</link><description>{subtitle}</description><item><title>Hello world!</title><link>{link}?p=1</link></item></channel></rss>
""".format(title=profile["blog_title"], subtitle=profile["blog_subtitle"], link=site_url("/"))
    return xml_response(body, profile=profile)


@app.route("/wp-login.php", methods=ALL_METHODS)
def login():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)

    action = request.values.get("action") or "login"
    redirect_to = request.values.get("redirect_to") or "/wp-admin/"
    bad_login = False
    if request.method == "POST":
        bad_login = True
        log_event(
            request,
            profile,
            component_type="core",
            component_slug="wp-login.php",
            technique="credential_attempt",
            response_status=200,
            details={"action": action},
        )
    else:
        log_event(
            request,
            profile,
            component_type="core",
            component_slug="wp-login.php",
            technique="login_page",
            response_status=200,
            details={"action": action},
            include_payload=False,
        )

    response = render_wp_template(
        "wp-login.html",
        profile,
        noindex=True,
        BADLOGIN=bad_login,
        LOGIN_ACTION=action,
        REDIRECT_TO=redirect_to,
    )
    response.set_cookie("wordpress_test_cookie", "WP Cookie check", path="/", httponly=True, samesite="Lax")
    return response


@app.route("/wp-admin", methods=ALL_METHODS)
@app.route("/wp-admin/", methods=ALL_METHODS)
@app.route("/wp-admin/<path:subpath>", methods=ALL_METHODS)
def admin(subpath=""):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    if subpath.startswith(("css/", "images/", "js/")) and (IMAGE_RE.search(subpath) or ASSET_RE.search(subpath)):
        return static_response(request.path, profile, label="WordPress admin")
    if subpath == "admin-ajax.php":
        return admin_ajax()

    log_event(request, profile, component_type="core", component_slug="wp-admin", technique="admin_probe", response_status=302)
    target = "/wp-login.php?redirect_to=%s&reauth=1" % site_url("/wp-admin/")
    response = redirect(target, code=302)
    response.headers["X-Redirect-By"] = "WordPress"
    return wp_headers(response, profile, noindex=True)


@app.route("/wp-admin/admin-ajax.php", methods=ALL_METHODS)
def admin_ajax():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)

    action = request.values.get("action")
    technique = "admin_ajax_action" if action else "admin_ajax_probe"
    log_event(
        request,
        profile,
        component_type="core",
        component_slug="admin-ajax.php",
        technique=technique,
        response_status=200,
            details=lure_details(request),
    )

    if not action:
        return text_response("0", mimetype="text/html; charset=UTF-8", profile=profile, noindex=True)
    return json_response({"success": False, "data": {"code": "invalid_nonce", "message": "Security check failed."}}, profile=profile)


@app.route("/xmlrpc.php", methods=ALL_METHODS)
def xmlrpc():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["POST", "OPTIONS"])
    if request.method != "POST":
        log_event(request, profile, component_type="core", component_slug="xmlrpc.php", technique="xmlrpc_probe", response_status=405, include_payload=False)
        response = text_response("XML-RPC server accepts POST requests only.", status=405, mimetype="text/plain; charset=UTF-8", profile=profile)
        response.headers["Allow"] = "POST"
        return response

    body = request.get_data(cache=True, as_text=True) or ""
    technique = "xmlrpc_multicall" if "system.multicall" in body else "xmlrpc_login"
    log_event(request, profile, component_type="core", component_slug="xmlrpc.php", technique=technique, response_status=200)
    fault = """<?xml version="1.0"?>
<methodResponse><fault><value><struct><member><name>faultCode</name><value><int>403</int></value></member><member><name>faultString</name><value><string>Incorrect username or password.</string></value></member></struct></value></fault></methodResponse>
"""
    return xml_response(fault, profile=profile)


@app.route("/wp-json", methods=ALL_METHODS)
@app.route("/wp-json/", methods=ALL_METHODS)
def rest_index():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS", "POST"])
    if request.method in WRITE_METHODS:
        log_event(request, profile, component_type="core", component_slug="wp-json", technique="rest_post_probe", response_status=401)
        return rest_error("rest_cannot_access", "DRA: Only authenticated users can access the REST API.", 401)
    log_event(request, profile, component_type="core", component_slug="wp-json", technique="rest_index", response_status=200, include_payload=False)
    return json_response(rest_route_index(profile), profile=profile)


REST_USER_WRITE_ERRORS = {
    "POST": ("rest_cannot_create_user", "Sorry, you are not allowed to create new users."),
    "PUT": ("rest_cannot_edit", "Sorry, you are not allowed to edit this user."),
    "PATCH": ("rest_cannot_edit", "Sorry, you are not allowed to edit this user."),
    "DELETE": ("rest_user_cannot_delete", "Sorry, you are not allowed to delete this user."),
}

REST_POST_WRITE_ERRORS = {
    "POST": ("rest_cannot_create", "Sorry, you are not allowed to create posts as this user."),
    "PUT": ("rest_cannot_edit", "Sorry, you are not allowed to edit this post."),
    "PATCH": ("rest_cannot_edit", "Sorry, you are not allowed to edit this post."),
    "DELETE": ("rest_cannot_delete", "Sorry, you are not allowed to delete this post."),
}


@app.route("/wp-json/wp/v2/users", methods=ALL_METHODS)
@app.route("/wp-json/wp/v2/users/<int:user_id>", methods=ALL_METHODS)
def rest_users(user_id=None):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"])
    if request.method in WRITE_METHODS:
        log_event(request, profile, component_type="core", component_slug="wp/v2/users", technique="rest_user_write_attempt", response_status=401)
        code, message = REST_USER_WRITE_ERRORS[request.method]
        return rest_error(code, message, 401)

    authors = [rest_author(author) for author in profile.get("authors", [])]
    log_event(request, profile, component_type="core", component_slug="wp/v2/users", technique="rest_user_enumeration", response_status=200, include_payload=False)
    if user_id is not None:
        for author in authors:
            if author["id"] == user_id:
                return json_response(author, profile=profile)
        return rest_error("rest_user_invalid_id", "Invalid user ID.", 404)
    return json_response(authors, profile=profile)


@app.route("/wp-json/wp/v2/users/<int:user_id>/application-passwords", defaults={"tail": ""}, methods=ALL_METHODS)
@app.route("/wp-json/wp/v2/users/<int:user_id>/application-passwords/<path:tail>", methods=ALL_METHODS)
def rest_application_passwords(user_id, tail=""):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="core", component_slug="application-passwords", technique="rest_application_password_probe", response_status=401)
    return rest_error("rest_cannot_view_application_passwords", "Sorry, you are not allowed to list application passwords for this user.", 401)


@app.route("/wp-json/wp/v2/posts", methods=ALL_METHODS)
@app.route("/wp-json/wp/v2/posts/<int:post_id>", methods=ALL_METHODS)
def rest_posts(post_id=None):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"])
    if request.method in WRITE_METHODS:
        log_event(request, profile, component_type="core", component_slug="wp/v2/posts", technique="rest_post_write_attempt", response_status=401)
        code, message = REST_POST_WRITE_ERRORS[request.method]
        return rest_error(code, message, 401)

    posts = home_posts(profile)
    if post_id is not None:
        for post in posts:
            if post["id"] == post_id:
                return json_response(post, profile=profile)
        return rest_error("rest_post_invalid_id", "Invalid post ID.", 404)
    return json_response(posts, profile=profile)


@app.route("/wp-json/oembed/1.0/embed", methods=["GET", "HEAD", "OPTIONS"])
def oembed():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS"])
    return json_response(
        {
            "version": "1.0",
            "provider_name": profile["blog_title"],
            "provider_url": site_url("/"),
            "title": "Hello world!",
            "type": "rich",
            "width": 600,
            "height": 338,
            "html": '<blockquote class="wp-embedded-content"><a href="%s?p=1">Hello world!</a></blockquote>' % site_url("/"),
        },
        profile=profile,
    )


@app.route("/wp-json/<path:route>", methods=ALL_METHODS)
def rest_catchall(route):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="core", component_slug="wp-json/%s" % route, technique="rest_missing_auth_or_route", response_status=404, details=lure_details(request))
    return rest_error("rest_no_route", "No route was found matching the URL and request method.", 404)


@app.route("/wp-cron.php", methods=ALL_METHODS)
def wp_cron():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="core", component_slug="wp-cron.php", technique="cron_probe", response_status=200, details={"doing_wp_cron": request.args.get("doing_wp_cron")})
    return text_response("", mimetype="text/plain; charset=UTF-8", profile=profile)


@app.route("/robots.txt", methods=["GET", "HEAD", "OPTIONS"])
def robots():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS"])
    body = "User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\nSitemap: %s\n" % site_url("/wp-sitemap.xml")
    return text_response(body, mimetype="text/plain; charset=UTF-8", profile=profile)


@app.route("/sitemap.xml", methods=["GET", "HEAD", "OPTIONS"])
@app.route("/wp-sitemap.xml", methods=["GET", "HEAD", "OPTIONS"])
def sitemap():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS"])
    body = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{root}</loc><lastmod>{date}</lastmod></url><url><loc>{post}</loc><lastmod>{date}</lastmod></url></urlset>
""".format(root=site_url("/"), post=site_url("/?p=1"), date=datetime.now(timezone.utc).date().isoformat())
    return xml_response(body, profile=profile)


@app.route("/readme.html", methods=["GET", "HEAD", "OPTIONS"])
def readme():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS"])
    log_event(request, profile, component_type="core", component_slug="readme.html", technique="core_version_probe", response_status=200, include_payload=False)
    return render_wp_template("readme.html", profile)


@app.route("/license.txt", methods=["GET", "HEAD", "OPTIONS"])
def license_txt():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS"])
    body = "WordPress - Web publishing software\nCopyright 2011-2026 by the contributors\nLicense: GPLv2 or later\n"
    return text_response(body, mimetype="text/plain; charset=UTF-8", profile=profile)


@app.route("/wp-comments-post.php", methods=ALL_METHODS)
def comments_post():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="core", component_slug="wp-comments-post.php", technique="comment_post_attempt", response_status=302, details=lure_details(request))
    response = redirect(site_url("/?p=1#comment-1"), code=302)
    response.headers["X-Redirect-By"] = "WordPress"
    return wp_headers(response, profile)


@app.route("/wp-content/plugins", methods=ALL_METHODS)
@app.route("/wp-content/plugins/", methods=ALL_METHODS)
def plugins_directory():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="plugin", technique="plugin_directory_probe", response_status=403, include_payload=False)
    abort(403)


@app.route("/wp-content/plugins/<plugin>", defaults={"subpath": ""}, methods=ALL_METHODS)
@app.route("/wp-content/plugins/<plugin>/<path:subpath>", methods=ALL_METHODS)
def plugin(plugin, subpath=""):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="plugin", component_slug=plugin, technique="plugin_probe", response_status=None, details={"subpath": subpath})

    if not is_plugin_whitelisted(plugin):
        abort(404)

    metadata = plugin_for_slug(profile, plugin) or {"slug": plugin, "name": plugin, "version": "1.0.0", "main_file": "%s.php" % plugin}
    path = subpath.strip("/")

    if not path:
        abort(403)
    if path == "readme.txt":
        return text_response(plugin_readme(metadata), mimetype="text/plain; charset=UTF-8", profile=profile)
    if path in {metadata.get("main_file"), "%s.php" % plugin}:
        # PHP is executed, not served: the ABSPATH guard exits with an empty body.
        return text_response("", profile=profile)
    lure = detect_path_lure("plugin", plugin, path, request)
    if lure:
        log_event(
            request,
            profile,
            component_type="plugin",
            component_slug=plugin,
            technique=lure["technique"],
            response_status=lure["response_status"],
            details=lure["details"],
        )
        if lure["response_kind"] == "not_found":
            abort(404)
        if request.method == "POST":
            return json_response({"success": False, "data": {"message": "Invalid nonce."}}, profile=profile)
        return text_response("0", mimetype="text/plain; charset=UTF-8", profile=profile)
    if IMAGE_RE.search(path) or ASSET_RE.search(path):
        return static_response(request.path, profile, label=metadata.get("name", plugin))
    abort(404)


@app.route("/wp-content/themes", methods=ALL_METHODS)
@app.route("/wp-content/themes/", methods=ALL_METHODS)
def themes_directory():
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="theme", technique="theme_directory_probe", response_status=403, include_payload=False)
    abort(403)


@app.route("/wp-content/themes/<theme>", defaults={"subpath": ""}, methods=ALL_METHODS)
@app.route("/wp-content/themes/<theme>/<path:subpath>", methods=ALL_METHODS)
def theme(theme, subpath=""):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="theme", component_slug=theme, technique="theme_probe", response_status=None, details={"subpath": subpath})

    if not is_theme_whitelisted(theme):
        abort(404)

    metadata = theme_for_slug(profile, theme) or {"slug": theme, "name": theme, "version": "1.0.0", "author": "WordPress.org"}
    path = subpath.strip("/")

    if not path:
        abort(403)
    if path == "style.css":
        return text_response(theme_stylesheet(metadata), mimetype="text/css; charset=UTF-8", profile=profile)
    if path == "readme.txt":
        return text_response("%s\nStable tag: %s\n" % (metadata["name"], metadata["version"]), mimetype="text/plain; charset=UTF-8", profile=profile)
    lure = detect_path_lure("theme", theme, path, request)
    if lure:
        log_event(
            request,
            profile,
            component_type="theme",
            component_slug=theme,
            technique=lure["technique"],
            response_status=lure["response_status"],
            details=lure["details"],
        )
        if lure["response_kind"] == "not_found":
            abort(404)
        if request.method == "POST":
            return json_response({"success": False, "data": {"message": "Invalid nonce."}}, profile=profile)
        return text_response("0", mimetype="text/plain; charset=UTF-8", profile=profile)
    if IMAGE_RE.search(path) or ASSET_RE.search(path):
        return static_response(request.path, profile, label=metadata.get("name", theme))
    abort(404)


@app.route("/wp-content/uploads", methods=ALL_METHODS)
@app.route("/wp-content/uploads/", methods=ALL_METHODS)
@app.route("/wp-content/uploads/<path:subpath>", methods=ALL_METHODS)
def uploads(subpath=""):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    log_event(request, profile, component_type="upload", component_slug=subpath, technique="uploads_probe", response_status=None, details=lure_details(request))
    if not subpath:
        abort(403)
    lure = detect_path_lure("upload", subpath, subpath, request)
    if subpath.endswith(".php") or lure:
        log_event(
            request,
            profile,
            component_type="upload",
            component_slug=subpath,
            technique=lure["technique"] if lure else "upload_lure_payload",
            response_status=404,
            details=lure["details"] if lure else lure_details(request),
        )
        abort(404)
    if IMAGE_RE.search(subpath):
        return static_response(request.path, profile)
    abort(404)


@app.route("/wp-includes", methods=ALL_METHODS)
@app.route("/wp-includes/", methods=ALL_METHODS)
@app.route("/wp-includes/<path:subpath>", methods=ALL_METHODS)
def wp_includes(subpath=""):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    if not subpath:
        abort(403)
    if subpath == "wlwmanifest.xml":
        body = """<?xml version="1.0" encoding="utf-8" ?>
<manifest xmlns="http://schemas.microsoft.com/wlw/manifest/weblog"><options><clientType>WordPress</clientType></options></manifest>
"""
        return xml_response(body, profile=profile)
    if IMAGE_RE.search(subpath) or ASSET_RE.search(subpath):
        return static_response(request.path, profile)
    abort(404)


@app.route("/<filename>.<ext>", methods=ALL_METHODS)
def commons(filename=None, ext=None):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)

    if filename == "index" and ext == "php":
        return home()
    lure = detect_common_file_lure(filename, ext, request)
    if lure:
        log_event(
            request,
            profile,
            component_type="core",
            component_slug="%s.%s" % (filename, ext),
            technique=lure["technique"],
            response_status=lure["response_status"],
            details=lure["details"],
        )
        abort(404)
    log_event(request, profile, component_type="core", component_slug="%s.%s" % (filename, ext), technique="common_file_probe", response_status=404, details=lure_details(request))
    abort(404)


@app.route("/author/<slug>/", methods=["GET", "HEAD", "OPTIONS"])
def author_archive(slug):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(["GET", "HEAD", "OPTIONS"])
    author = next((item for item in profile.get("authors", []) if item["slug"] == slug), None)
    if not author:
        abort(404)
    return render_wp_template("twentyeleven.html", profile, AUTHORPAGE=True, CURRENTAUTHOR=(author["id"], author["slug"]))


@app.route("/<path:path>", methods=ALL_METHODS)
def catchall(path):
    profile = current_profile()
    if request.method == "OPTIONS":
        return options_response(ALL_METHODS)
    technique = "interesting_file_probe" if re.search(r"(wp-config|\.sql|\.zip|backup|dump|\.bak|\.old|\.swp)", path, re.I) else "catchall_probe"
    log_event(request, profile, component_type="unknown", component_slug=path, technique=technique, response_status=404, details=lure_details(request))
    abort(404)
