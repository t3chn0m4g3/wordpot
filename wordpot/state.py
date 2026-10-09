"""Worker-safe state for inert upload follow-up responses."""

import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import time

from wordpot.logger import log_dir


UPLOAD_TTL_SECONDS = 24 * 60 * 60
_MARKER_RE = re.compile(r"\becho\s*(['\"])([^'\"\r\n]{1,256})\1\s*;", re.I)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UPLOAD_CACHE = {}
_UPLOAD_CACHE_LOCK = threading.Lock()


def _uploads_path():
    directory = os.path.join(log_dir(), "state")
    os.makedirs(directory, mode=0o750, exist_ok=True)
    try:
        os.chmod(directory, 0o750)
    except OSError:
        pass
    return os.path.join(directory, "uploads.jsonl")


def _safe_basename(filename):
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or any(ord(char) < 32 for char in name):
        return None
    return name[:255]


def _extract_marker(data):
    source = data.decode("utf-8", errors="replace")
    match = _MARKER_RE.search(source)
    if not match:
        return ""
    marker = match.group(2).strip()
    if len(marker) > 256 or not all(char.isprintable() for char in marker):
        return ""
    return marker


def _valid_records(path, now):
    records = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                basename = _safe_basename(record.get("basename"))
                ts = record.get("ts")
                digest = record.get("sha256")
                marker = record.get("marker")
                if (
                    basename is None
                    or not isinstance(ts, (int, float))
                    or ts > now
                    or now - ts > UPLOAD_TTL_SECONDS
                    or not isinstance(digest, str)
                    or not _SHA256_RE.fullmatch(digest)
                    or not isinstance(marker, str)
                ):
                    continue
                records[basename] = {
                    "basename": basename,
                    "sha256": digest,
                    "marker": marker[:256],
                    "ts": ts,
                }
    except FileNotFoundError:
        pass
    return records


def _lock_file(path, mode):
    lock = open(path + ".lock", "a", encoding="utf-8")
    fcntl.flock(lock, mode)
    return lock


def record_multipart_uploads(req):
    """Persist sanitized multipart upload metadata; never execute uploaded bytes."""
    try:
        files = req.files.items(multi=True)
    except Exception:
        return []

    candidates = []
    for _field, uploaded in files:
        basename = _safe_basename(uploaded.filename)
        if basename is None:
            continue
        try:
            data = uploaded.stream.read()
            uploaded.stream.seek(0)
        except (AttributeError, OSError):
            continue
        candidates.append(
            {
                "basename": basename,
                "sha256": hashlib.sha256(data).hexdigest(),
                "marker": _extract_marker(data),
                "ts": time.time(),
            }
        )

    if not candidates:
        return []

    path = _uploads_path()
    lock = _lock_file(path, fcntl.LOCK_EX)
    try:
        records = _valid_records(path, time.time())
        records.update((record["basename"], record) for record in candidates)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=os.path.dirname(path),
                prefix=".uploads-", suffix=".tmp", delete=False,
            ) as handle:
                temp_path = handle.name
                for record in records.values():
                    handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o640)
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        stat = os.stat(path)
        with _UPLOAD_CACHE_LOCK:
            _UPLOAD_CACHE[path] = (stat.st_mtime_ns, stat.st_size, dict(records))
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return candidates


def lookup_upload(basename):
    basename = _safe_basename(basename)
    if basename is None:
        return None
    path = _uploads_path()
    try:
        os.stat(path)
    except FileNotFoundError:
        return None
    now = time.time()

    lock = _lock_file(path, fcntl.LOCK_SH)
    try:
        # Re-stat after acquiring the lock so cached snapshots correspond to a
        # complete writer transaction, even when another worker just updated it.
        stat = os.stat(path)
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        with _UPLOAD_CACHE_LOCK:
            cached = _UPLOAD_CACHE.get(path)
            records = cached[2] if cached and cached[:2] == fingerprint else None
        if records is None:
            records = _valid_records(path, now)
            with _UPLOAD_CACHE_LOCK:
                _UPLOAD_CACHE[path] = (fingerprint[0], fingerprint[1], records)
        record = records.get(basename)
        if record and now - record["ts"] <= UPLOAD_TTL_SECONDS:
            return dict(record)
        return None
    except FileNotFoundError:
        return None
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
