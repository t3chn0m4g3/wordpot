# Wordpot 3.0.0

Wordpot 3.0.0 is a safe WordPress honeypot. It emulates enough of a real WordPress
installation to attract scanners, credential attacks, XML-RPC probes, REST API
enumeration, plugin and theme fingerprinting, and common payload delivery
attempts. It does not run PHP, does not connect to a database, does not fetch
attacker-supplied URLs, and does not persist uploaded files into a web-served
uploads tree. Raw request bodies can optionally be spooled into a dedicated
payload directory for analysis.

This project is a Python 3 and Flask continuation of the original Wordpot
project by Gianluca Brindisi:

https://github.com/gbrindisi/wordpot

## What it emulates

Wordpot exposes a modern WordPress-like surface:

- A themed home page with WordPress generator, REST API, feed, pingback, and
  theme stylesheet fingerprints.
- `/wp-login.php` with test-cookie behavior and credential-attempt collection.
- `/wp-admin/` redirects and `/wp-admin/admin-ajax.php` action lures.
- `/xmlrpc.php` with WordPress method discovery, credential faults, batched
  login attempts, pingback faults, and an RSD document at `?rsd`.
- `/wp-json/`, `/wp-json/wp/v2/users`, `/wp-json/wp/v2/posts`, and
  application-password endpoints.
- `/readme.html`, `/license.txt`, `/robots.txt`, `/sitemap.xml`,
  `/wp-sitemap.xml`, feeds, and oEmbed.
- `/wp-content/plugins/<slug>/...` and `/wp-content/themes/<slug>/...`
  fingerprints, including `readme.txt`, main plugin files, `style.css`,
  assets, images, and differentiated 200/403/404 behavior.
- `/wp-content/uploads/...` lures for web shells and suspicious upload probes.
- Config-file baits for `/.env`, `/.git/config`, `/.git/HEAD`, and common
  `wp-config.php` backup names.
- Static login masks for known webshell probe names; submitted values are
  logged as probes, and commands are never run.

The goal is realism for scanners and bots, not vulnerability. Payloads are
captured, hashed, truncated in JSONL, and optionally stored as raw files in a
non-web-served payload directory.

## Safety model

The default configuration is intentionally conservative:

- `MAX_CONTENT_LENGTH = 1048576` rejects request bodies larger than 1 MiB.
- `PAYLOAD_STORAGE_MAX_BYTES = 1048576` caps each raw body stored in the payload spool.
- `PAYLOAD_EXCERPT_BYTES = 4096` stores only a small excerpt of each payload.
- Full payloads are hashed with SHA-256 for correlation.
- Raw request bodies are stored only when `PAYLOAD_STORAGE_ENABLED = True`.
- Payload files use SHA-256 based names below `PAYLOAD_DIR`; request paths and
  upload filenames never influence the storage path.
- Uploaded files are never written into `/wp-content/uploads/` or executed.
  A bounded literal from a simple `echo '...';` payload may be returned as
  plain text on a later request for the uploaded basename.
- SSRF-looking parameters are logged but never fetched.
- XML-RPC pingback URLs are recorded but never fetched.
- LFI/path parameters are logged but never read from the local filesystem.
- REST, XML-RPC, admin-ajax, and login flows never authenticate a user.
- Profile plugin metadata is fake; no PHP plugin code is executed.

The normal write targets are log files, the startup profile state file, and the
payload spool. In Docker these live below `/opt/wordpot/logs`; payloads use the
host-backed `/opt/wordpot/logs/payloads` subdirectory by default.

## Profiles

Wordpot uses profiles to decide what kind of WordPress site it should look like.
A profile contains:

- `id`: stable profile identifier.
- `blog_title` and `blog_subtitle`: visible site branding.
- `core_version`: WordPress version to advertise.
- `server_header`: Apache, nginx, LiteSpeed, or other plausible web server.
- `theme`: active theme slug.
- `themes`: installed theme slugs.
- `plugins`: installed plugin slugs.
- `authors`: public author IDs, slugs, and names.
- `locale`, `site_type`, and `exposed_files`: extra profile context.

Built-in profiles:

| Profile | Shape | Typical stack |
| --- | --- | --- |
| `modern-business` | WordPress 7.0 business site | Twenty Twenty-Five, Elementor, Yoast, Contact Form 7, WPForms, Site Kit, MonsterInsights, ACF, WPCode, Wordfence, Really Simple Security, Akismet |
| `commerce` | WordPress 7.0 shop | Astra, WooCommerce, Elementor, Contact Form 7, Yoast, LiteSpeed Cache, WP Mail SMTP, UpdraftPlus, Duplicator, ACF, Redirection |
| `maintenance-lag` | Slightly lagging publisher site | WordPress 6.9.2, Hello Elementor, Jetpack, All-in-One WP Migration, UpdraftPlus, Duplicate Post/Page, Classic Editor, Classic Widgets, Advanced Editor Tools, WordPress Importer, WP Super Cache |
| `agency-builder` | Elementor agency build | Hello Elementor, Astra, Elementor add-ons, Starter Templates, WPForms, Rank Math, Mailchimp, Loco Translate, Limit Login Attempts, Code Snippets, Duplicator |

## Profile rotation

The default is:

```python
PROFILE_ROTATION = 'startup'
```

In this mode Wordpot chooses one profile when the app starts and keeps that
profile for all clients. On the next process or container start, the next
profile is selected. This avoids contradictory fingerprints during one runtime
while still changing the honeypot persona over time.

Startup rotation stores the last selected profile in:

```python
PROFILE_STATE_FILE = None
```

When `None`, Wordpot uses `<log-dir>/profile-state.json`. In the Docker setup
that means `/opt/wordpot/logs/profile-state.json`, so the profile cycle survives
container restarts if the log volume is persistent.

Available rotation modes:

| Mode | Behavior |
| --- | --- |
| `startup` | Pick one profile at startup; next start uses the next profile. Recommended. |
| `per_ip_day` | Pick one profile per source IP and UTC day. |
| `per_ip` | Pick a stable profile per source IP. |
| `first` | Always use the first configured profile. |

To force a single profile:

```python
PROFILE_ID = 'commerce'
```

You can also set `WORDPOT_PROFILE_ID` in the environment.

## Plugin catalog

The plugin catalog in `wordpot/profiles.py` includes popular and useful
fingerprint targets from the WordPress.org plugin directory, especially plugins
that attackers often enumerate because they imply forms, ecommerce, builders,
SEO, imports, backups, SMTP, code snippets, security controls, cache layers, or
login hardening.

Current catalog highlights:

- Builders and themes: `elementor`, `header-footer-elementor`,
  `essential-addons-for-elementor-lite`, `elementskit-lite`, `astra-sites`.
- Forms and marketing: `contact-form-7`, `wpforms-lite`, `mailchimp-for-wp`.
- Ecommerce: `woocommerce`.
- SEO and analytics: `wordpress-seo`, `seo-by-rank-math`,
  `all-in-one-seo-pack`, `google-site-kit`,
  `google-analytics-for-wordpress`.
- Backup, import, migration: `updraftplus`, `all-in-one-wp-migration`,
  `duplicator`, `wordpress-importer`, `duplicate-post`, `duplicate-page`.
- Security and login: `wordfence`, `really-simple-ssl`,
  `limit-login-attempts-reloaded`, `wps-hide-login`, `akismet`.
- Site operations: `litespeed-cache`, `wp-super-cache`, `wp-mail-smtp`,
  `advanced-custom-fields`, `insert-headers-and-footers`, `code-snippets`,
  `redirection`, `loco-translate`, `classic-editor`, `classic-widgets`,
  `tinymce-advanced`, `disable-comments`, `hostinger`.

Do not put every catalog plugin into every profile. Real WordPress sites usually
have a recognizable stack, not the whole plugin directory. A believable profile
uses a coherent mix of 6 to 12 plugins.

## Custom profiles

You can define custom profiles in `wordpot.conf`:

```python
PROFILES = [
    {
        'id': 'example-site',
        'blog_title': 'Example Site',
        'blog_subtitle': 'Just another WordPress site',
        'core_version': '7.0',
        'server_header': 'Apache/2.4.58 (Ubuntu)',
        'theme': 'twentytwentyfive',
        'themes': ['twentytwentyfive', 'twentytwentyfour'],
        'plugins': [
            'elementor',
            'contact-form-7',
            'wordpress-seo',
            'wpforms-lite',
        ],
        'authors': [
            {'id': 1, 'slug': 'admin', 'name': 'Admin'},
            {'id': 2, 'slug': 'editor', 'name': 'Editor'},
        ],
        'locale': 'en_US',
        'site_type': 'business',
        'exposed_files': ['readme.html', 'license.txt', 'robots.txt'],
    },
]
```

Plugin and theme strings are resolved through the built-in catalogs. Unknown
plugin slugs still work, but their metadata falls back to generic values.

## Configuration

Main configuration lives in `wordpot.conf`.

Configuration reference:

| Setting | Description |
| --- | --- |
| `HOST` | Listen address used by `wordpot.py` when running without Gunicorn. |
| `PORT` | Listen port used by `wordpot.py` when running without Gunicorn. |
| `THEME` | Fallback theme slug when no profile supplies a theme. |
| `SERVER` | Fallback `Server` header when no profile supplies one. |
| `INTERACTION_DEPTH` | Interaction policy. The default `medium` captures modern WordPress probes without executing attacker input. |
| `MAX_CONTENT_LENGTH` | Maximum accepted request body size in bytes. Default `1048576` (1 MiB); larger bodies are rejected before route handling. |
| `PAYLOAD_EXCERPT_BYTES` | Maximum number of request-body bytes stored inline in the JSONL event log as `payload_excerpt`. |
| `PAYLOAD_STORAGE_ENABLED` | Enables raw request-body spooling into the configured payload directory. |
| `PAYLOAD_STORAGE_MAX_BYTES` | Maximum body size that will be written to the payload spool. Default `1048576` (1 MiB); keep this at or below `MAX_CONTENT_LENGTH`. |
| `PAYLOAD_DIR_MODE` | Octal mode for payload directories. Default `0o750` lets the container user and group traverse/read metadata while keeping access closed to others. |
| `PAYLOAD_FILE_MODE` | Octal mode for payload body files. Default `0o640` lets the container user and group read captured payloads while keeping access closed to others. |
| `PAYLOAD_DIR` | Payload spool directory. `None` means `<log-dir>/payloads`; Docker sets `WORDPOT_PAYLOAD_DIR=/opt/wordpot/logs/payloads`. |
| `EVENT_LOG_FILE` | Structured JSONL event destination. Relative paths are written below the Wordpot log directory. Default: `wordpot.json`. Can also be set with `WORDPOT_EVENT_LOG_FILE`. |
| `EVENT_LOG_MAX_BYTES` | Optional maximum size of `EVENT_LOG_FILE` before rotating it. Default `0` disables in-process rotation. |
| `EVENT_LOG_BACKUP_COUNT` | Number of numbered JSONL backups retained when size-based rotation is enabled. Default `0`. |
| `EVENT_LOG_EXCLUDE_HEALTHCHECKS` | Filters healthcheck requests from the JSONL event log when enabled. |
| `EVENT_LOG_EXCLUDE_PATHS` | Paths treated as healthcheck/noise paths by the event logger. Default: `['/healthz']`. |
| `EVENT_DEST_IP` | Optional override for the event `dest_ip` field. Useful behind NAT or a reverse proxy. Without an override, wildcard bind addresses such as `0.0.0.0` are skipped. |
| `EVENT_DEST_PORT` | Optional override for the event `dest_port` field. Useful behind NAT or a reverse proxy. |
| `PROFILE_ROTATION` | Profile selection mode: `startup`, `per_ip_day`, `per_ip`, or `first`. |
| `PROFILE_ID` | Optional fixed profile id. When set, it overrides rotation. Can also be set with `WORDPOT_PROFILE_ID`. |
| `PROFILE_STATE_FILE` | Path for startup rotation state. `None` means `<log-dir>/profile-state.json`. |
| `TRUST_PROXY_HEADERS` | Enables trusted proxy parsing via Werkzeug `ProxyFix`. Only enable behind a proxy you control. |
| `BLOGTITLE` | Fallback blog title when no profile supplies one. |
| `BLOGSUBTITLE` | Fallback blog subtitle when no profile supplies one. |
| `VERSION` | Fallback WordPress version when no profile supplies `core_version`. |
| `AUTHORS` | Fallback author slugs. Profiles should use structured author objects. |
| `PROFILES` | Optional custom profile list. Leave unset to use the built-in rotating personas. |
| `HPFEEDS_ENABLED` | Enables optional hpfeeds forwarding for JSONL event lines. |
| `HPFEEDS_HOST` | hpfeeds broker host. |
| `HPFEEDS_PORT` | hpfeeds broker port. |
| `HPFEEDS_IDENT` | hpfeeds identity. |
| `HPFEEDS_SECRET` | hpfeeds secret. |
| `HPFEEDS_TOPIC` | hpfeeds topic used for published Wordpot events. |

Plugin and theme installation is controlled by profiles. Requests for plugin or
theme slugs not present in the active profile return 404.

## Running locally

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Run with the Flask development server:

```bash
.venv/bin/python wordpot.py --host 0.0.0.0 --port 8080
```

Show the project version:

```bash
.venv/bin/python wordpot.py --version
```

Run with Gunicorn:

```bash
.venv/bin/gunicorn --preload --bind 0.0.0.0:8080 --workers 2 --threads 4 wordpot:app
```

`--preload` is recommended because the startup profile is selected once before
workers are forked, so every worker serves the same profile.

At startup Wordpot prints a small ASCII banner with the Wordpot version, active
startup profile, and log directory. The same lines are also written to the
runtime log.

## Running with Docker Compose

```bash
docker compose up --build
```

The compose file keeps the container read-only, drops all capabilities except
`NET_BIND_SERVICE`, uses `no-new-privileges`, limits memory and process count,
and mounts only the log tree as writable storage. The payload spool is a
`payloads` subdirectory inside that host-mounted tree:

- `$HOME/tpotce/data/wordpot/log` -> `/opt/wordpot/logs/`
- `$HOME/tpotce/data/wordpot/log/payloads` -> `/opt/wordpot/logs/payloads/`

The Docker image healthcheck calls `/healthz`. Wordpot answers quietly only to
loopback clients; remote requests receive a logged 404. No healthcheck header
is needed.

## Logs and events

Wordpot writes:

- `wordpot.json`: structured honeypot events in JSONL format, one JSON object per line. This is controlled by `EVENT_LOG_FILE`.
- `wordpot-runtime.log`: operational messages.
- `profile-state.json`: last profile used by startup rotation.
- `payloads/<sha256-prefix>/<sha256>.bin`: raw request bodies, when enabled.
- `state/uploads.jsonl`: short-lived upload basenames, hashes, and inert marker
  strings used for follow-up responses; entries expire after 24 hours.

Loopback healthchecks on `/healthz` are not written to the event log. Other
requests to that path are treated as ordinary remote traffic and receive a 404.

Event field reference:

Fields whose value would be JSON `null` or an empty string are omitted from the
event. Optional fields below therefore appear only when Wordpot observed or
derived a non-empty value for them. Boolean `false`, numeric `0`, and empty
objects remain present because they are explicit values rather than empty text.

| Field | Description |
| --- | --- |
| `timestamp` | UTC ISO-8601 event creation time. |
| `request_id` | Per-request UUID recorded in the event log. |
| `profile_id` | Active honeypot profile id, such as `modern-business` or `commerce`. |
| `src_ip` | Source IP used for attribution and profile stickiness. Honors trusted proxy handling only when configured. |
| `src_port` | Source TCP port from WSGI `REMOTE_PORT`; omitted when unavailable. |
| `dest_ip` | Destination IP from `EVENT_DEST_IP` or the local listening socket when available. It is never derived from the client supplied `Host` header. Use `EVENT_DEST_IP` when Docker, NAT, or a proxy hides the public listener. |
| `dest_port` | Destination port as seen by the app. Use `EVENT_DEST_PORT` when Docker, NAT, or a proxy hides the public listener. |
| `user_agent` | Raw `User-Agent` header value, duplicated from `headers_subset` for easier indexing. |
| `browser_family` | Parsed browser family from the `User-Agent` header. |
| `browser_version` | Parsed browser version string from the `User-Agent` header; omitted when the parser has no version. |
| `os_family` | Parsed operating-system family from the `User-Agent` header. |
| `os_version` | Parsed operating-system version string from the `User-Agent` header; omitted when the parser has no version. |
| `device_family` | Parsed device family from the `User-Agent` header. |
| `url` | Full request URL as seen by Flask, including query string. |
| `method` | HTTP method, for example `GET`, `HEAD`, `POST`, or `OPTIONS`. |
| `path` | Request path without query string. |
| `query` | Raw query string decoded as UTF-8 with replacement for invalid bytes; omitted when the request has no query string. |
| `headers_subset` | Small allowlist of useful headers: `Accept`, `Authorization`, `Content-Type`, `Referer`, `User-Agent`, `X-Forwarded-For`, and `X-Real-IP`. |
| `component_type` | WordPress surface category, for example `core`, `plugin`, `theme`, `upload`, or `unknown`. |
| `component_slug` | Specific component being probed, such as `xmlrpc.php`, `wp/v2/users`, `woocommerce`, or a theme slug. |
| `technique` | Normalized lure or probe classification, such as `credential_attempt`, `config_bait_served`, `webshell_probe`, `webshell_login`, `webshell_command`, `upload_followup`, `xmlrpc_list_methods`, `xmlrpc_login`, `xmlrpc_multicall`, `xmlrpc_pingback`, or `admin_ajax_action`. |
| `payload_sha256` | SHA-256 of the full request body; omitted for empty/no-body requests. |
| `payload_excerpt` | Truncated UTF-8-safe request-body excerpt limited by `PAYLOAD_EXCERPT_BYTES`; omitted when empty. |
| `payload_size` | Full request-body size in bytes. |
| `payload_stored` | `true` when the raw request body was written to the payload spool. |
| `payload_ref` | Portable relative payload path below `PAYLOAD_DIR`, for example `ab/abcdef....bin`; omitted when no payload file was stored. |
| `payload_path` | Absolute payload path as seen by the running process. In Docker this is usually below `/opt/wordpot/logs/payloads`; omitted when no payload file was stored. |
| `username` | Normalized observed username from WordPress login fields, generic form fields, or Basic Auth; omitted when not observed. |
| `password` | Normalized observed password from WordPress login fields, generic form fields, or Basic Auth; omitted when not observed. Treat this as sensitive. |
| `credentials_observed` | Extracted login/basic-auth fields when present; omitted when not observed. Treat this as sensitive. |
| `response_status` | HTTP status code that Wordpot intended to return for this event. |
| `details` | Optional route-specific dictionary. Config baits may include `bait_file`; webshell probes include `webshell_probe`; XML-RPC may include `credential_pairs`, `credential_pair_count`, `pingback_source`, and `pingback_target`; upload events may include `uploaded_files`, `upload_sha256`, and `marker`; requests also record a supplied `http_host` here. |

Profile identity settings (`THEME`, `SERVER`, `BLOGTITLE`, `BLOGSUBTITLE`,
`VERSION`, and `AUTHORS`) override the corresponding value in every profile
when set in `wordpot.conf`. Supported identity command-line options apply the
same overrides at startup.
`gunicorn.conf.py` holds the container's Gunicorn bind/worker settings and
removes Gunicorn's duplicate `Server` header while preserving the profile's
header.

The checked T-Pot CE logrotate config targets `/data/wordpot/log/*.log`, so it
does not rotate `wordpot.json`. Keep Wordpot's in-process rotation disabled
when ewsposter is consuming the file by line number; otherwise configure an
external JSONL-aware rotation workflow that also coordinates its reader offset.

Payload storage uses `payload_ref` as the portable identifier. For example, a
payload with SHA-256 `abcdef...` is written below the configured payload
directory as `ab/abcdef....bin`. `payload_path` contains the absolute path as
seen by the running process. Empty GET-style probes have no payload file; their
interesting query parameters are captured in event `details`.

Example event types include `credential_attempt`, `xmlrpc_multicall`,
`rest_user_enumeration`, `admin_ajax_action`, `plugin_lure_payload`,
`upload_lure_payload`, and `interesting_file_probe`.

## Testing

Run the normal test suite:

```bash
.venv/bin/python -m pytest -q
```

Run the HTTP and volume smoke test against a running Docker Compose container:

```bash
docker compose up --build -d
WORDPOT_CONTAINER_SMOKE_URL=http://127.0.0.1 \
WORDPOT_CONTAINER_LOG_DIR=$HOME/tpotce/data/wordpot/log \
WORDPOT_CONTAINER_PAYLOAD_DIR=$HOME/tpotce/data/wordpot/log/payloads \
.venv/bin/python -m pytest -q tests/test_container_smoke.py
```

The smoke test checks `/healthz`, the home page, REST users/posts, XML-RPC,
login, admin-ajax, upload lures, the JSONL event schema, and the host-mounted
payload spool. It is skipped unless `WORDPOT_CONTAINER_SMOKE_URL` is set.

There is an optional WPScan smoke test. It runs only when `wpscan` is installed
and `WPSCAN_URL` points to a running Wordpot instance:

```bash
WPSCAN_URL=http://127.0.0.1:8080 .venv/bin/python -m pytest -q
```

## Extending lures

There are three extension points:

- Add profile metadata or plugin catalog entries in `wordpot/profiles.py`.
- Add path and parameter lures in `wordpot/lures.py`.
- Add route behavior in `wordpot/views.py` when a lure needs a new WordPress endpoint.

When adding a lure, keep these rules:

- Never execute attacker input.
- Never fetch attacker-provided URLs.
- Never read local files based on request parameters.
- Persist raw request bodies only in the configured payload spool.
- Prefer logging payload hashes and short excerpts.
- Return WordPress-like errors such as invalid nonce, auth required, or no route.

## License

ISC License.

> Copyright (c) 2012, Gianluca Brindisi < g@brindi.si >
>
> Permission to use, copy, modify, and/or distribute this software for any
> purpose with or without fee is hereby granted, provided that the above
> copyright notice and this permission notice appear in all copies.
>
> THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
> REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
> AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
> INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
> LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
> OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
> PERFORMANCE OF THIS SOFTWARE.
