#!/usr/bin/env python3
"""
HuntStand exporter (members / invites / requests / matrix)

Features:
- Cookie-first auth (HUNTSTAND_SESSIONID + HUNTSTAND_CSRFTOKEN via env or cookies.json)
- Login fallback (HUNTSTAND_USER + HUNTSTAND_PASS) — tries both "login" and "username"
- Uses certifi bundle for TLS, falls back to verify=False with a prominent warning
- Retries for transient HTTP errors via urllib3.Retry
- Outputs:
    1) detailed CSV (one row per person / invite / request)
    2) JSON summary of hunt areas
    3) membership matrix CSV: rows=unique emails, cols=hunt area names -> Yes/No
- Optional per-hunt CSV files (flag)
- Logging and useful debug info (no secrets printed)
- Configurable via env vars or CLI args

Usage examples:
  # prefer cookies in env
  export HUNTSTAND_SESSIONID="..."
  export HUNTSTAND_CSRFTOKEN="..."
  huntstand-exporter

  # or use login fallback (less reliable)
  export HUNTSTAND_USER="you@example.com"
  export HUNTSTAND_PASS="hunter2"
  huntstand-exporter

  # use cookies.json file
  huntstand-exporter --cookies-file cookies.json

Requirements:
  pip install requests certifi python-dotenv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from requests import RequestException, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from urllib3.exceptions import InsecureRequestWarning

# optional .env loader (not required)
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# TLS/CA
try:
    import certifi

    CERTIFI_AVAILABLE = True
except Exception:
    CERTIFI_AVAILABLE = False

# ---- Config / Endpoints ----
BASE_URL = os.getenv("HUNTSTAND_BASE_URL", "https://app.huntstand.com")
LOGIN_POST_PATH = "/login"  # POST target (flaky)
ROOT_PATH = "/"  # used to obtain csrftoken if doing login
MYPROFILE_URL = f"{BASE_URL}/api/v1/myprofile/"
REQUESTS_URL = f"{BASE_URL}/api/v2/user/requests"
INVITE_URL = f"{BASE_URL}/api/v1/membershipemailinvite/?huntarea={{}}"
MEMBERS_URL = f"{BASE_URL}/api/v1/clubmember/?huntarea_id={{}}"
REQS_URL = f"{BASE_URL}/api/v1/membershiprequest/?huntarea={{}}"
HUNTAREA_BY_PROFILE = f"{BASE_URL}/api/v1/huntarea/?profile_id={{}}"

# Candidate asset endpoints (observed / inferred from HAR patterns and common REST naming).
# We attempt each and treat non-200 / malformed responses as empty. This defensive list
# lets the tool continue working even if some endpoints change or are unavailable.
ASSET_ENDPOINT_CANDIDATES: list[tuple[str, str]] = [
    ("stand", f"{BASE_URL}/api/v1/stand/?huntarea_id={{}}"),
    ("camera", f"{BASE_URL}/api/v1/camera/?huntarea_id={{}}"),
    ("trailcam", f"{BASE_URL}/api/v1/trailcam/?huntarea={{}}"),  # observed in HAR (uses 'huntarea' param)
    ("blind", f"{BASE_URL}/api/v1/blind/?huntarea_id={{}}"),
    ("feeder", f"{BASE_URL}/api/v1/feeder/?huntarea_id={{}}"),
    ("foodplot", f"{BASE_URL}/api/v1/foodplot/?huntarea_id={{}}"),
    ("waypoint", f"{BASE_URL}/api/v1/waypoint/?huntarea_id={{}}"),
    ("trail", f"{BASE_URL}/api/v1/scouttrail/?huntarea_id={{}}"),  # speculative scouting trail
    # Fallback generic patterns (some deployments use 'asset' aggregate endpoints)
    ("asset", f"{BASE_URL}/api/v1/asset/?huntarea_id={{}}"),
]

# Environment-driven endpoint augmentation: HUNTSTAND_ASSET_ENDPOINTS="type:url_template,type2:url_template2"
_extra_assets_env = os.getenv("HUNTSTAND_ASSET_ENDPOINTS", "").strip()
if _extra_assets_env:
    for part in _extra_assets_env.split(","):
        if not part:
            continue
        if ":" not in part:
            continue
        atype, urltmpl = part.split(":", 1)
        atype = atype.strip()
        urltmpl = urltmpl.strip()
        if atype and urltmpl:
            ASSET_ENDPOINT_CANDIDATES.append((atype, urltmpl))

# Active endpoints (may be reduced by dynamic probing)
ACTIVE_ASSET_ENDPOINTS: list[tuple[str, str]] = list(ASSET_ENDPOINT_CANDIDATES)

# Default output base names (timestamping now unconditional via internal naming policy)
OUT_DETAILED_CSV = "huntstand_members_detailed.csv"
OUT_JSON = "huntstand_summary.json"
OUT_MATRIX_CSV = "huntstand_membership_matrix.csv"
OUT_PER_HUNT_DIR = "huntstand_per_hunt_csvs"
OUT_ASSETS_CSV = "huntstand_assets_detailed.csv"  # written only when --include-assets flag used

# ---- Credentials / cookies via environment ----
ENV_USER = os.getenv("HUNTSTAND_USER")
ENV_PASS = os.getenv("HUNTSTAND_PASS")
ENV_SESSIONID = os.getenv("HUNTSTAND_SESSIONID")
ENV_CSRFTOKEN = os.getenv("HUNTSTAND_CSRFTOKEN")
ENV_PROFILE_ID = os.getenv("HUNTSTAND_PROFILEID")  # optional fallback


# ---- Logging ----
def _configure_logger(structured: bool = False) -> logging.Logger:
    level = os.getenv("HUNTSTAND_LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger("huntstand-exporter")
    if logger.handlers:  # avoid duplicate handlers if reconfiguring
        for h in list(logger.handlers):
            logger.removeHandler(h)
    # NOTE: We intentionally direct all logging to stdout so that informational output
    # can be captured easily by callers (and our test suite). Errors still include level.
    handler = logging.StreamHandler(stream=sys.stdout)
    if structured:
        # Emit JSON lines: {"ts":..., "level":..., "msg":..., "name":...}
        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "ts": int(record.created * 1000),
                    "level": record.levelname,
                    "msg": record.getMessage(),
                    "name": record.name,
                }
                if record.exc_info:
                    payload["exc"] = self.formatException(record.exc_info)
                return json.dumps(payload)

        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger


logger = _configure_logger(structured=os.getenv("HUNTSTAND_LOG_FORMAT", "text").lower() == "json")


# ---- Small helper ----
def as_dict(obj: Any) -> dict[str, Any]:
    """Return obj if it's a dict, else {}. Avoids None.get(...) crashes."""
    return obj if isinstance(obj, dict) else {}


def is_safe_id(val: Any) -> bool:
    """Return True if val looks like a sane hunt area identifier.

    Accepts ints or strings composed only of hex/digits and dashes (UUID-like) to reduce
    accidental SSRF / path injection risk in formatted URLs.
    """
    if val is None:
        return False
    if isinstance(val, int):
        return True
    if isinstance(val, str):
        val = val.strip()
        return bool(val) and all(c in "0123456789abcdefABCDEF-" for c in val)
    return False


def ensure_parent_dir(out_path: str) -> None:
    """Create parent directory for an output file (best-effort)."""
    try:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.debug("Could not ensure parent directory for %s", out_path)


# ---- HTTP helper utilities ----
def make_session_with_retries(total_retries: int = 3, backoff: float = 0.3) -> Session:
    """Create HTTP session with retry logic for transient failures."""
    s = Session()
    retry_strategy = Retry(
        total=total_retries,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
        backoff_factor=backoff,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    # reasonable headers
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; HuntStandExporter/1.0)",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE_URL + "/",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
    )
    return s


def set_ca_bundle(session: Session) -> None:
    """Configure TLS certificate bundle."""
    if CERTIFI_AVAILABLE:
        session.verify = certifi.where()
        logger.debug("Using certifi CA bundle at %s", certifi.where())
    else:
        session.verify = True
        logger.debug("certifi not available; using system default CA store")


def fallback_disable_verify(session: Session) -> None:
    """Disable SSL verification (INSECURE - use only as fallback)."""
    session.verify = False
    # Suppress noisy InsecureRequestWarning once we intentionally disable verification.
    try:
        urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        logger.debug("Failed to suppress InsecureRequestWarning; continuing anyway.")
    logger.warning("SSL verification DISABLED (INSECURE). Only use this if you understand the risk.")


def get_json(session: Session, url: str, *, timeout: int = 15, normalizer: Callable[[Any], Any] | None = None) -> Any | None:
    """Generic GET returning JSON with uniform error logging.

    Args:
        session: requests Session
        url: full URL
        timeout: seconds before giving up
        normalizer: optional function applied to r.json() before returning
    Returns:
        Parsed JSON or None on error.
    """
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return normalizer(data) if normalizer else data
    except RequestException as e:
        logger.error("GET failed for %s: %s", url, e)
        return None


def json_or_list_to_objects(payload: Any) -> list[dict[str, Any]]:
    """Normalize responses that may be a list or a dict with 'objects'."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "objects" in payload and isinstance(payload["objects"], list):
        return payload["objects"]
    # If dict but not 'objects', try to treat values as list
    return list(payload.values()) if isinstance(payload, dict) else []


# ---- Authentication ----
def create_session_from_cookies(sessionid: str | None, csrftoken: str | None) -> Session:
    """Create authenticated session using cookies.

    Determines cookie domain from BASE_URL host component so alternate hosts work.
    """
    s = make_session_with_retries()
    set_ca_bundle(s)
    try:
        domain = BASE_URL.split("//", 1)[1].split("/", 1)[0]
    except Exception:
        domain = "app.huntstand.com"
    if sessionid:
        s.cookies.set("sessionid", sessionid, domain=domain, path="/")
        logger.info("Loaded sessionid cookie from environment (domain=%s).", domain)
    if csrftoken:
        s.cookies.set("csrftoken", csrftoken, domain=domain, path="/")
        logger.info("Loaded csrftoken cookie from environment (domain=%s).", domain)
    return s


def load_cookies_from_file(path: str) -> tuple[str | None, str | None]:
    """
    Expect a simple JSON like: {"sessionid":"...", "csrftoken":"..."}
    Returns (sessionid, csrftoken)
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        sid = as_dict(data).get("sessionid") or as_dict(data).get("session_id") or as_dict(data).get("sessionId")
        csrft = as_dict(data).get("csrftoken") or as_dict(data).get("csrf") or as_dict(data).get("csrftoken_cookie")
        logger.info("Loaded cookies from %s", path)
        return sid, csrft
    except Exception as e:
        logger.error("Failed to load cookies file %s: %s", path, e)
        return None, None


def attempt_login(session: Session, username: str, password: str) -> bool:
    """
    Try to login to BASE_URL + LOGIN_POST_PATH. Because HuntStand login has been flaky,
    we GET root (to get csrftoken cookie), then POST with 'login' first, then 'username'.
    Returns True if sessionid cookie appears in session.
    """
    logger.info("Attempting login fallback (username present).")
    try:
        r = session.get(BASE_URL + ROOT_PATH, timeout=15)
        r.raise_for_status()
    except RequestException as e:
        logger.warning("Root GET failed during login attempt: %s", e)
        # continue; maybe server set cookies via other means

    csrf_cookie = session.cookies.get("csrftoken", "")
    if not csrf_cookie:
        logger.warning("No csrftoken cookie available before login attempt; login may fail.")

    payload_common = {"csrfmiddlewaretoken": csrf_cookie or "", "password": password, "source": "web"}
    headers = {
        "Referer": BASE_URL + "/",
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": session.headers.get("User-Agent"),
    }

    for user_field in ("login", "username"):
        payload = dict(payload_common)
        payload[user_field] = username
        try:
            r2 = session.post(BASE_URL + LOGIN_POST_PATH, data=payload, headers=headers, timeout=15)
            # If server sets sessionid cookie we consider success; some responses can be non-200 even on success
            if session.cookies.get("sessionid"):
                logger.info("Login succeeded using key '%s'.", user_field)
                return True
            # If server returned a 2xx but no sessionid, treat as failure for this attempt
            if 200 <= r2.status_code < 300:
                logger.debug("POST to /login returned %s but no session cookie; trying next key.", r2.status_code)
            else:
                logger.debug("POST to /login returned status %s for key '%s'.", r2.status_code, user_field)
        except RequestException as e:
            logger.debug("Login attempt with key %s failed: %s", user_field, e)
        time.sleep(1)  # Wait between attempts to avoid rate limiting
    return False


# ---- Data Fetching ----
def gather_huntareas(session: Session, fallback_profile_id: str | None = None) -> list[dict[str, Any]]:
    """
    Fetch hunt areas. Prefer /api/v1/myprofile/ for the list of hunt areas.
    Fallback to /api/v1/huntarea/?profile_id= if provided and myprofile fails.
    """
    clubs: list[dict[str, Any]] = []
    logger.debug("gather_huntareas called with fallback_profile_id: %s", fallback_profile_id)

    # First, try /api/v1/myprofile/
    try:
        r = session.get(MYPROFILE_URL, timeout=15)
        r.raise_for_status()
        data = r.json()
        logger.debug("Raw myprofile response: %s", json.dumps(data, indent=2))
        data = as_dict(data)
        clubs = data.get("hunt_areas", [])
        logger.info("Fetched %d hunt areas from myprofile.", len(clubs))
        if len(clubs) == 0:
            logger.warning("No hunt areas found in myprofile response. Available keys: %s", list(data.keys()))
        logger.debug(
            "About to check fallback: fallback_profile_id=%s, clubs length=%d", fallback_profile_id, len(clubs)
        )
        # Don't return here if clubs is empty - let fallback try
    except RequestException as e:
        logger.warning("Failed to fetch hunt areas from myprofile: %s", e)

    # Fallback to profile_id if provided or if myprofile returned no hunt areas
    logger.debug(
        "Checking fallback condition: fallback_profile_id=%s, clubs length=%d", fallback_profile_id, len(clubs)
    )
    if fallback_profile_id and len(clubs) == 0:
        url = HUNTAREA_BY_PROFILE.format(fallback_profile_id)
        logger.info("Trying fallback URL for hunt areas: %s", url)
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            logger.debug("Raw huntarea fallback response: %s", json.dumps(data, indent=2))
            clubs = json_or_list_to_objects(data)
            logger.info("Fetched %d hunt areas via profile_id fallback.", len(clubs))
        except RequestException as e:
            logger.error("Fallback fetch via profile_id failed: %s", e)
    else:
        logger.debug("Skipping fallback - either no profile_id or clubs already found")

    return clubs


def fetch_members_for_area(session: Session, hunt_id: Any) -> Any | None:
    """Fetch active members for a hunt area."""
    if not is_safe_id(hunt_id):
        logger.error("Unsafe hunt_id provided to fetch_members_for_area: %r", hunt_id)
        return None
    return get_json(session, MEMBERS_URL.format(hunt_id))


def fetch_invites_for_area(session: Session, hunt_id: Any) -> list[dict[str, Any]]:
    """Fetch pending invites for a hunt area."""
    if not is_safe_id(hunt_id):
        logger.error("Unsafe hunt_id provided to fetch_invites_for_area: %r", hunt_id)
        return []
    data = get_json(session, INVITE_URL.format(hunt_id), normalizer=json_or_list_to_objects)
    return data if isinstance(data, list) else []


def fetch_requests_for_area(session: Session, hunt_id: Any) -> list[dict[str, Any]]:
    """Fetch membership requests for a hunt area."""
    if not is_safe_id(hunt_id):
        logger.error("Unsafe hunt_id provided to fetch_requests_for_area: %r", hunt_id)
        return []
    data = get_json(session, REQS_URL.format(hunt_id), normalizer=json_or_list_to_objects)
    return data if isinstance(data, list) else []


# ---- Output Writers ----
def write_detailed_csv(rows: list[dict[str, Any]], out_path: str) -> None:
    """Write detailed CSV with all members, invites, and requests."""
    fieldnames = ["huntarea_id", "huntarea_name", "name", "email", "rank", "status", "date_joined"]
    ensure_parent_dir(out_path)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote detailed CSV: %s (%d rows)", out_path, len(rows))


def write_json_summary(summary: dict[str, Any], out_path: str) -> None:
    """Write JSON summary with hunt area metadata."""
    ensure_parent_dir(out_path)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=4)
    logger.info("Wrote JSON summary: %s", out_path)


def write_membership_matrix(all_rows: list[dict[str, Any]], out_path: str) -> None:
    """Write membership matrix CSV (email x hunt area)."""
    # Collect unique emails and hunt area names
    emails = sorted({(row.get("email") or "").lower().strip() for row in all_rows if row.get("email")})
    hunt_names = sorted({row.get("huntarea_name", "") for row in all_rows if row.get("huntarea_name")})

    # Build matrix with default "No"
    # Use dict.fromkeys for inner mapping to satisfy C420 (unnecessary dict comprehension)
    matrix: dict[str, dict[str, str]] = {email: dict.fromkeys(hunt_names, "No") for email in emails}

    for row in all_rows:
        email = (row.get("email") or "").lower().strip()
        hname = row.get("huntarea_name")
        status = row.get("status", "No")
        if email and hname in matrix[email]:
            # overwrite "No" with the real status
            matrix[email][hname] = status.capitalize()

    # Write CSV
    fieldnames = ["email", *hunt_names]
    ensure_parent_dir(out_path)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for email in emails:
            row = {"email": email}
            row.update(matrix[email])
            writer.writerow(row)

    logger.info("Wrote membership matrix with statuses: %s (%d rows)", out_path, len(emails))


def write_assets_csv(asset_rows: list[dict[str, Any]], out_path: str) -> None:
    """Write assets (stands / cameras / generic) CSV.

    Columns chosen for broad usefulness; absent fields are left blank.
    """
    fieldnames = [
        "huntarea_id",
        "huntarea_name",
        "asset_type",
        "asset_id",
        "name",
        "subtype",
        "latitude",
        "longitude",
        "created",
        "updated",
        "last_activity",
        "owner_email",
        "visibility",
    ]
    ensure_parent_dir(out_path)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in asset_rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
    logger.info("Wrote assets CSV: %s (%d rows)", out_path, len(asset_rows))


def _extract_lat_lon(obj: dict[str, Any]) -> tuple[str, str]:
    """Try several patterns to extract latitude / longitude as strings."""
    lat = obj.get("lat") or obj.get("latitude")
    lon = obj.get("lon") or obj.get("longitude")
    if not lat or not lon:
        loc = obj.get("location") if isinstance(obj.get("location"), dict) else None
        if isinstance(loc, dict):
            lat = lat or loc.get("lat") or loc.get("latitude")
            lon = lon or loc.get("lon") or loc.get("longitude")
    return str(lat or ""), str(lon or "")


def _normalize_asset(raw: dict[str, Any], asset_type: str, huntarea_id: Any, huntarea_name: str) -> dict[str, Any]:
    """Produce a normalized asset dict.

    Defensive: never assume keys exist; convert values to simple scalars.
    """
    aid = raw.get("id") or raw.get("asset_id") or raw.get("uuid") or ""
    name = (
        raw.get("name")
        or raw.get("title")
        or raw.get("label")
        or raw.get("device_name")
        or raw.get("camera_name")
        or f"{asset_type.title()}-{aid}".strip("-")
    )
    subtype = raw.get("type") or raw.get("subtype") or raw.get("category") or ""
    lat, lon = _extract_lat_lon(raw)
    created = raw.get("created") or raw.get("date_created") or raw.get("timestamp") or ""
    updated = raw.get("updated") or raw.get("modified") or raw.get("last_updated") or ""
    last_activity = (
        raw.get("last_activity")
        or raw.get("last_image")
        or raw.get("last_check_in")
        or raw.get("last_seen")
        or ""
    )

    # Owner email heuristics
    owner_email = ""
    for key in ("owner", "user", "profile"):
        val = raw.get(key)
        if isinstance(val, dict):
            candidate = val.get("email") or val.get("username")
            if candidate:
                owner_email = str(candidate).strip()
                break
    visibility = raw.get("public")
    if visibility is None:
        visibility = raw.get("shared")
    if isinstance(visibility, bool):
        visibility = "public" if visibility else "private"
    else:
        visibility = str(visibility or "")

    return {
        "huntarea_id": huntarea_id,
        "huntarea_name": huntarea_name,
        "asset_type": asset_type,
        "asset_id": aid,
        "name": str(name)[:200],
        "subtype": str(subtype or "")[:100],
        "latitude": lat,
        "longitude": lon,
        "created": str(created),
        "updated": str(updated),
        "last_activity": str(last_activity),
        "owner_email": owner_email,
        "visibility": visibility,
    }


def fetch_assets_for_area(session: Session, hunt_id: Any, huntarea_name: str) -> list[dict[str, Any]]:
    """Attempt to fetch assets (stands, cameras, generic) for a hunt area.

    Iterates over candidate endpoints. Each successful response aggregated.
    Returns a list of normalized asset dicts.
    """
    if not is_safe_id(hunt_id):
        logger.error("Unsafe hunt_id provided to fetch_assets_for_area: %r", hunt_id)
        return []
    assets: list[dict[str, Any]] = []
    for atype, url_tmpl in ACTIVE_ASSET_ENDPOINTS:
        url = url_tmpl.format(hunt_id)
        try:
            r = session.get(url, timeout=15)
            if r.status_code >= 400:
                logger.debug("Asset endpoint %s returned %s; skipping", url, r.status_code)
                continue
            data = r.json()
            if isinstance(data, dict) and "objects" in data and isinstance(data["objects"], list):
                raw_list = data["objects"]
            elif isinstance(data, list):
                raw_list = data
            else:
                raw_list = []
            for raw in raw_list:
                if isinstance(raw, dict):
                    assets.append(_normalize_asset(raw, atype, hunt_id, huntarea_name))
        except Exception as e:
            logger.debug("Asset fetch failed for %s: %s", url, e)
            continue
    return assets


def refine_active_asset_endpoints(session: Session, sample_hunt_id: Any) -> None:
    """Probe asset endpoints with a single huntarea id and keep only those returning usable JSON.

    Usable JSON means a list or a dict containing an 'objects' list. Errors / non-JSON responses are discarded.
    This reduces unnecessary calls for later hunt areas.
    """
    global ACTIVE_ASSET_ENDPOINTS
    if not is_safe_id(sample_hunt_id):
        logger.debug("Skipping asset endpoint refinement; sample hunt id unsafe: %r", sample_hunt_id)
        return
    kept: list[tuple[str, str]] = []
    for atype, url_tmpl in ACTIVE_ASSET_ENDPOINTS:
        url = url_tmpl.format(sample_hunt_id)
        try:
            r = session.get(url, timeout=10)
            if r.status_code >= 400:
                logger.debug("Endpoint probe %s (%s) -> %s; dropping", atype, url, r.status_code)
                continue
            data = r.json()
            usable = False
            if isinstance(data, list):
                usable = True
            elif isinstance(data, dict) and isinstance(data.get("objects"), list):
                usable = True
            if usable:
                kept.append((atype, url_tmpl))
                logger.debug("Endpoint kept for assets: %s (%s)", atype, url)
            else:
                logger.debug("Endpoint returned unusable JSON shape; dropping: %s (%s) -> keys=%s", atype, url, list(data.keys()) if isinstance(data, dict) else type(data))
        except Exception as e:
            logger.debug("Asset endpoint probe failed (%s %s): %s", atype, url, e)
            continue
    if kept:
        ACTIVE_ASSET_ENDPOINTS = kept
        logger.info("Dynamic asset endpoints refined. Active count: %d", len(ACTIVE_ASSET_ENDPOINTS))
    else:
        logger.info("Dynamic asset refinement yielded no usable endpoints; retaining original list (%d).", len(ACTIVE_ASSET_ENDPOINTS))


def _clone_session(parent: Session) -> Session:
    """Create a shallow clone of a Session for thread use (cookies + headers)."""
    child = make_session_with_retries()
    child.headers.update(parent.headers)
    for c in parent.cookies:
        child.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    # Copy TLS verification setting
    child.verify = parent.verify
    return child


def process_hunt_area(session: Session, club: dict[str, Any], include_assets: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Collect data for a single hunt area.

    Returns (member_rows, asset_rows, summary_entry)
    """
    huntarea_obj = club.get("huntarea") if isinstance(club.get("huntarea"), dict) else None
    hid = club.get("huntarea_id") or club.get("id") or (huntarea_obj.get("id") if isinstance(huntarea_obj, dict) else None)
    hmeta = huntarea_obj or as_dict(club)
    hunt_name = (
        (hmeta.get("name") if isinstance(hmeta, dict) else None)
        or club.get("name")
        or (f"Area-{hid}" if hid is not None else "Area-Unknown")
    )
    if hid is None:
        return [], [], {}
    logger.info("Processing huntarea: %s (id=%s)", hunt_name, hid)
    members = fetch_members_for_area(session, hid)
    members_list = json_or_list_to_objects(members) if members is not None else []
    invites = fetch_invites_for_area(session, hid) or []
    reqs = fetch_requests_for_area(session, hid) or []
    rows: list[dict[str, Any]] = []
    for m in members_list:
        member_first_name = m.get("first_name", "").strip()
        member_last_name = m.get("last_name", "").strip()
        member_name = f"{member_first_name} {member_last_name}".strip()
        member_email = m.get("email", "").strip()
        rows.append({
            "huntarea_id": hid,
            "huntarea_name": hunt_name,
            "name": member_name,
            "email": member_email,
            "rank": "member",
            "status": "active",
            "date_joined": "",
        })
    for inv in invites:
        invite_name = inv.get("name") or inv.get("full_name") or ""
        invite_email = (inv.get("email") or "").strip()
        rank_obj = inv.get("rank")
        if isinstance(rank_obj, dict):
            invite_rank = rank_obj.get("name") or rank_obj.get("title") or ""
        else:
            invite_rank = str(rank_obj or "")
        if not invite_rank:
            invite_rank = inv.get("role") or inv.get("intended_rank") or ""
        invite_date = inv.get("date_joined") or inv.get("created") or inv.get("date_sent") or ""
        rows.append({
            "huntarea_id": hid,
            "huntarea_name": hunt_name,
            "name": invite_name.strip(),
            "email": invite_email,
            "rank": invite_rank.strip(),
            "status": "invited",
            "date_joined": invite_date,
        })
    for rq in reqs:
        rq = as_dict(rq)
        profile = as_dict(rq.get("profile", {}))
        user_data = as_dict(profile.get("user", {}))
        first_name = (profile.get("first_name") or user_data.get("first_name") or "").strip()
        last_name = (profile.get("last_name") or user_data.get("last_name") or "").strip()
        username = (profile.get("username") or user_data.get("username") or "").strip()
        request_name = f"{first_name} {last_name}".strip() if first_name or last_name else username
        request_email = profile.get("email", "").strip() or user_data.get("email", "").strip()
        rank_obj = rq.get("rank", {})
        request_rank = rank_obj.get("name", "").strip() if isinstance(rank_obj, dict) else ""
        request_date = rq.get("date_requested", "")
        if not request_name and not request_email:
            profile_id = profile.get("id", "") or user_data.get("id", "")
            if profile_id:
                request_name = f"Profile_{profile_id}" if profile.get("id") else f"User_{profile_id}"
        rows.append({
            "huntarea_id": hid,
            "huntarea_name": hunt_name,
            "name": request_name,
            "email": request_email,
            "rank": request_rank,
            "status": "requested",
            "date_joined": request_date,
        })
    assets_for_area: list[dict[str, Any]] = []
    if include_assets:
        try:
            assets_for_area = fetch_assets_for_area(session, hid, hunt_name)
        except Exception as e:
            logger.debug("Asset collection failed for %s: %s", hid, e)
    summary_entry = {
        "id": hid,
        "name": hunt_name,
        "meta": hmeta,
        "counts": {
            "members": len(members_list),
            "invites": len(invites),
            "requests": len(reqs),
            **({"assets": len(assets_for_area)} if include_assets else {}),
        },
        "members_sample": members_list[:10],
        "invites_sample": invites[:10],
        "requests_sample": reqs[:10],
        **({"assets_sample": assets_for_area[:10]} if include_assets else {}),
    }
    return rows, assets_for_area, summary_entry


def write_per_hunt_csvs(all_rows: list[dict[str, Any]]) -> None:
    """Write individual CSV files per hunt area."""
    os.makedirs(OUT_PER_HUNT_DIR, exist_ok=True)
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in all_rows:
        hid = row.get("huntarea_id")
        if hid is None:
            continue
        grouped.setdefault(hid, []).append(row)

    for hid, items in grouped.items():
        safe_name = (
            (items[0].get("huntarea_name") or f"Area-{hid}").replace("/", "_").replace("\\", "_")
            if items
            else f"Area-{hid}"
        )
        filename = os.path.join(OUT_PER_HUNT_DIR, f"hunt_{hid}_{safe_name}.csv")
        fieldnames = ["name", "email", "rank", "status", "date_joined"]
        ensure_parent_dir(filename)
        with open(filename, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for it in items:
                writer.writerow(
                    {
                        "name": it.get("name", ""),
                        "email": it.get("email", ""),
                        "rank": it.get("rank", ""),
                        "status": it.get("status", ""),
                        "date_joined": it.get("date_joined", ""),
                    }
                )
        logger.info("Wrote per-hunt CSV: %s (%d rows)", filename, len(items))


# ---- Main flow ----
def main(argv: list[str] | None = None) -> int:
    """Main entry point for the HuntStand exporter."""
    ap = argparse.ArgumentParser(prog="huntstand_exporter", description="Export HuntStand hunt area memberships")
    ap.add_argument("--cookies-file", help="JSON file containing sessionid/csrftoken", default=None)
    ap.add_argument(
        "--profile-id", help="Optional profile ID to fallback to /api/v1/huntarea/?profile_id=", default=ENV_PROFILE_ID
    )
    ap.add_argument("--per-hunt", action="store_true", help="Also write per-hunt CSV files (timestamped directory)")
    ap.add_argument("--no-login-fallback", action="store_true", help="Do not attempt login; require cookies")
    ap.add_argument("--dry-run", action="store_true", help="Show planned output paths and exit without network or file writes")
    ap.add_argument("--include-assets", action="store_true", help="Also fetch stands/cameras/other assets and write assets CSV + include in summary")
    ap.add_argument("--assets-extra", nargs="*", help="Additional asset endpoint specs type:urlTemplate (e.g. feeder:https://.../feeder/?huntarea_id={})", default=None)
    ap.add_argument("--dynamic-assets", action="store_true", help="Probe asset endpoints with first hunt area and keep only those returning usable JSON")
    ap.add_argument("--parallel", action="store_true", help="Fetch hunt areas in parallel (members/invites/requests/assets)")
    ap.add_argument("--parallel-workers", type=int, default=int(os.getenv("HUNTSTAND_PARALLEL_WORKERS", "4")), help="Worker threads for parallel fetch (default 4)")
    ap.add_argument("--log-json", action="store_true", help="Emit structured JSON logs to stdout")
    ap.add_argument(
        "--output-dir",
        help="Base directory for outputs (default: exports/)",
        default=None,
    )
    ap.add_argument(
        "--format",
        choices=["all", "csv", "json"],
        default="all",
        help="Select outputs: all (default), csv (detailed + matrix [+ per-hunt]), json (summary only)",
    )
    args = ap.parse_args(argv)

    # Reconfigure logger if JSON requested via CLI flag
    if args.log_json:
        _configure_logger(structured=True)

    # Always timestamp outputs and place them under exports/ (or --output-dir if provided)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir: Path = Path(args.output_dir) if args.output_dir else Path("exports")
    base_dir.mkdir(parents=True, exist_ok=True)

    out_csv = str(base_dir / f"huntstand_members_detailed_{ts}.csv")
    out_json = str(base_dir / f"huntstand_summary_{ts}.json")
    out_assets = str(base_dir / f"huntstand_assets_detailed_{ts}.csv") if args.include_assets else None
    out_matrix = str(base_dir / f"huntstand_membership_matrix_{ts}.csv")
    if args.per_hunt:
        import importlib
        mod = importlib.import_module(__name__)
        setattr(mod, "OUT_PER_HUNT_DIR", str(base_dir / f"huntstand_per_hunt_csvs_{ts}"))
    debug_paths: list[str] = []
    if args.format in ("all", "csv"):
        debug_paths.append(out_csv)
        debug_paths.append(out_matrix)
        if args.per_hunt:
            debug_paths.append(str(OUT_PER_HUNT_DIR))
        if out_assets:
            debug_paths.append(out_assets)
    if args.format in ("all", "json"):
        debug_paths.append(out_json)
    logger.debug(
        "Outputs directory: %s | timestamp applied. Planned paths (%s): %s",
        base_dir,
        args.format,
        ", ".join(debug_paths),
    )

    planned: list[str] = []
    if args.format in ("all", "csv"):
        planned.append(out_csv)
        planned.append(out_matrix)
        if args.per_hunt:
            planned.append(str(OUT_PER_HUNT_DIR))
        if out_assets:
            planned.append(out_assets)
    if args.format in ("all", "json"):
        planned.append(out_json)

    # Unconditional fast exit for dry-run (skip network & file generation entirely)
    if args.dry_run:
        if planned:
            logger.info(
                "Dry-run: skipping network and file generation. Planned outputs (%s):\n%s",
                args.format,
                "\n".join(f" - {p}" for p in planned),
            )
        else:
            logger.info("Dry-run: skipping network and file generation (no outputs selected).")
        return 0

    # create session (cookie-first)
    sessionid = ENV_SESSIONID
    csrftoken = ENV_CSRFTOKEN
    if args.cookies_file:
        sidf, csrff = load_cookies_from_file(args.cookies_file)
        sessionid = sessionid or sidf
        csrftoken = csrftoken or csrff

    session = create_session_from_cookies(sessionid, csrftoken)

    # TLS: use certifi if available; if root GET raises SSLError, optionally fallback to disable verification
    try:
        set_ca_bundle(session)
    except Exception:
        logger.debug("Could not set CA bundle cleanly; continuing with system settings.")

    # quick TLS reachability check
    try:
        session.get(BASE_URL + "/", timeout=12)
        # don't assert success; some sites return 200 with content; just check for SSL problems
    except RequestException as e:
        # Import SSLError at the top level to avoid import resolution warnings
        if "SSL" in str(type(e).__name__) or "ssl" in str(e).lower():
            logger.warning("SSL verification failed: %s", e)
            logger.warning("Will retry with verify=False (INSECURE).")
            fallback_disable_verify(session)
        else:
            logger.debug("Root GET warning: %s", e)

    # If no sessionid and user disallowed login fallback -> error out
    if not session.cookies.get("sessionid"):
        if args.no_login_fallback:
            logger.error(
                "No sessionid cookie present and login fallback disabled. Provide cookies via env or --cookies-file."
            )
            return 2
        # try login fallback if creds present
        if ENV_USER and ENV_PASS:
            try:
                ok = attempt_login(session, ENV_USER, ENV_PASS)
                if not ok:
                    logger.warning(
                        "Login attempt did not produce session cookie. You may continue if API allows cookie-less access for some endpoints, otherwise provide cookies."
                    )
            except Exception as e:
                logger.error("Login attempt raised exception: %s", e)
        else:
            logger.warning(
                "No session cookie and no credentials configured (HUNTSTAND_USER/HUNTSTAND_PASS). Attempting to proceed; some endpoints may fail."
            )

    # Gather huntareas
    clubs = gather_huntareas(session, fallback_profile_id=args.profile_id)

    # Normalize club objects to contain at least huntarea_id and huntarea metadata
    normalized_clubs: list[dict[str, Any]] = []
    for c in clubs:
        if isinstance(c, dict):
            hunt_dict = c.get("huntarea") if isinstance(c.get("huntarea"), dict) else None
            if hunt_dict is not None:
                hid = c.get("huntarea_id") or as_dict(hunt_dict).get("id")
                normalized_clubs.append({"huntarea_id": hid, "huntarea": as_dict(hunt_dict)})
            elif c.get("id") and c.get("name"):
                normalized_clubs.append({"huntarea_id": c.get("id"), "huntarea": c})
            else:
                hid = c.get("huntarea_id") or c.get("id")
                hmeta = hunt_dict or c
                normalized_clubs.append({"huntarea_id": hid, "huntarea": as_dict(hmeta)})

    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"hunt_areas": []}
    all_assets: list[dict[str, Any]] = []

    # Dynamic asset endpoint refinement (first hunt area only)
    if args.include_assets and args.dynamic_assets and normalized_clubs:
        first_club = normalized_clubs[0]
        sample_id = first_club.get("huntarea_id") or first_club.get("id") or (
            first_club.get("huntarea", {}).get("id") if isinstance(first_club.get("huntarea"), dict) else None
        )
        if sample_id:
            refine_active_asset_endpoints(session, sample_id)

    if args.assets_extra:
        for spec in args.assets_extra:
            if ":" not in spec:
                logger.warning("Ignoring malformed assets-extra spec (missing colon): %s", spec)
                continue
            atype, urltmpl = spec.split(":", 1)
            atype = atype.strip()
            urltmpl = urltmpl.strip()
            if atype and urltmpl:
                ACTIVE_ASSET_ENDPOINTS.append((atype, urltmpl))
                logger.info("Added extra asset endpoint: %s -> %s", atype, urltmpl)

    if args.parallel and len(normalized_clubs) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        workers = max(1, args.parallel_workers)
        logger.info("Parallel fetch enabled (%d workers)", workers)
        # Use separate sessions per thread for safety

        def submit_club(executor, club):
            thread_session = _clone_session(session)
            return executor.submit(process_hunt_area, thread_session, club, args.include_assets)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [submit_club(ex, club) for club in normalized_clubs]
            for fut in as_completed(futures):
                try:
                    rows, assets_for_area, summary_entry = fut.result()
                    if summary_entry:
                        summary["hunt_areas"].append(summary_entry)
                    all_rows.extend(rows)
                    all_assets.extend(assets_for_area)
                except Exception as e:
                    logger.error("Parallel worker failed: %s", e)
    else:
        for club in normalized_clubs:
            rows, assets_for_area, summary_entry = process_hunt_area(session, club, args.include_assets)
            if summary_entry:
                summary["hunt_areas"].append(summary_entry)
            all_rows.extend(rows)
            all_assets.extend(assets_for_area)

    # write outputs (filtered by --format)
    generated: list[str] = []
    if args.format in ("all", "csv"):
        write_detailed_csv(all_rows, out_path=out_csv)
        generated.append(out_csv)
    if args.format in ("all", "json"):
        write_json_summary(summary, out_path=out_json)
        generated.append(out_json)
    if args.format in ("all", "csv"):
        write_membership_matrix(all_rows, out_path=out_matrix)
        generated.append(out_matrix)
        if args.per_hunt:
            write_per_hunt_csvs(all_rows)
            generated.append(str(OUT_PER_HUNT_DIR))
        if args.include_assets and out_assets is not None:
            write_assets_csv(all_assets, out_path=out_assets)
            generated.append(out_assets)

    logger.info(
        "All done. Outputs generated (%s):\n%s", args.format, "\n".join(f" - {g}" for g in generated)
    )
    return 0
