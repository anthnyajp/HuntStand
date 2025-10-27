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
import time
from typing import Any

from requests import RequestException, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

# Default outputs
OUT_DETAILED_CSV = "huntstand_members_detailed.csv"
OUT_JSON = "huntstand_summary.json"
OUT_MATRIX_CSV = "huntstand_membership_matrix.csv"
OUT_PER_HUNT_DIR = "huntstand_per_hunt_csvs"

# ---- Credentials / cookies via environment ----
ENV_USER = os.getenv("HUNTSTAND_USER")
ENV_PASS = os.getenv("HUNTSTAND_PASS")
ENV_SESSIONID = os.getenv("HUNTSTAND_SESSIONID")
ENV_CSRFTOKEN = os.getenv("HUNTSTAND_CSRFTOKEN")
ENV_PROFILE_ID = os.getenv("HUNTSTAND_PROFILEID")  # optional fallback

# ---- Logging ----
logging.basicConfig(level=os.getenv("HUNTSTAND_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("huntstand-exporter")


# ---- Small helper ----
def as_dict(obj: Any) -> dict[str, Any]:
    """Return obj if it's a dict, else {}. Avoids None.get(...) crashes."""
    return obj if isinstance(obj, dict) else {}


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
    logger.warning("SSL verification DISABLED (INSECURE). Only use this if you understand the risk.")


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
    """Create authenticated session using cookies."""
    s = make_session_with_retries()
    set_ca_bundle(s)
    if sessionid:
        # domain should be app.huntstand.com; requests will send cookies when domain matches
        s.cookies.set("sessionid", sessionid, domain="app.huntstand.com", path="/")
        logger.info("Loaded sessionid cookie from environment.")
    if csrftoken:
        s.cookies.set("csrftoken", csrftoken, domain="app.huntstand.com", path="/")
        logger.info("Loaded csrftoken cookie from environment.")
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
    url = MEMBERS_URL.format(hunt_id)
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except RequestException as e:
        logger.error("Failed to fetch members for hunt area %s: %s", hunt_id, e)
        return None


def fetch_invites_for_area(session: Session, hunt_id: Any) -> list[dict[str, Any]]:
    """Fetch pending invites for a hunt area."""
    url = INVITE_URL.format(hunt_id)
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return json_or_list_to_objects(r.json())
    except RequestException as e:
        logger.error("Failed to fetch invites for hunt area %s: %s", hunt_id, e)
        return []


def fetch_requests_for_area(session: Session, hunt_id: Any) -> list[dict[str, Any]]:
    """Fetch membership requests for a hunt area."""
    url = REQS_URL.format(hunt_id)
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return json_or_list_to_objects(r.json())
    except RequestException as e:
        logger.error("Failed to fetch requests for hunt area %s: %s", hunt_id, e)
        return []


# ---- Output Writers ----
def write_detailed_csv(rows: list[dict[str, Any]], out_path: str) -> None:
    """Write detailed CSV with all members, invites, and requests."""
    fieldnames = ["huntarea_id", "huntarea_name", "name", "email", "rank", "status", "date_joined"]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote detailed CSV: %s (%d rows)", out_path, len(rows))


def write_json_summary(summary: dict[str, Any], out_path: str) -> None:
    """Write JSON summary with hunt area metadata."""
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=4)
    logger.info("Wrote JSON summary: %s", out_path)


def write_membership_matrix(all_rows: list[dict[str, Any]], out_path: str) -> None:
    """Write membership matrix CSV (email x hunt area)."""
    # Collect unique emails and hunt area names
    emails = sorted({(row.get("email") or "").lower().strip() for row in all_rows if row.get("email")})
    hunt_names = sorted({row.get("huntarea_name", "") for row in all_rows if row.get("huntarea_name")})

    # Build matrix with default "No"
    matrix: dict[str, dict[str, str]] = {email: {hname: "No" for hname in hunt_names} for email in emails}

    for row in all_rows:
        email = (row.get("email") or "").lower().strip()
        hname = row.get("huntarea_name")
        status = row.get("status", "No")
        if email and hname in matrix[email]:
            # overwrite "No" with the real status
            matrix[email][hname] = status.capitalize()

    # Write CSV
    fieldnames = ["email", *hunt_names]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for email in emails:
            row = {"email": email}
            row.update(matrix[email])
            writer.writerow(row)

    logger.info("Wrote membership matrix with statuses: %s (%d rows)", out_path, len(emails))


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
    ap.add_argument("--outfile-csv", help="Detailed CSV output path", default=OUT_DETAILED_CSV)
    ap.add_argument("--outfile-json", help="JSON summary output path", default=OUT_JSON)
    ap.add_argument("--outfile-matrix", help="Membership matrix CSV path", default=OUT_MATRIX_CSV)
    ap.add_argument("--per-hunt", action="store_true", help="Also write per-hunt CSV files in " + OUT_PER_HUNT_DIR)
    ap.add_argument("--no-login-fallback", action="store_true", help="Do not attempt login; require cookies")
    args = ap.parse_args(argv)

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
        if not isinstance(c, dict):
            logger.debug("Skipping non-dict huntarea entry: %r", c)
            continue

        if isinstance(c.get("huntarea"), dict):
            # shape: {'huntarea_id': id, 'huntarea': {...}} (preferred)
            hid = c.get("huntarea_id") or as_dict(c.get("huntarea")).get("id")
            normalized_clubs.append({"huntarea_id": hid, "huntarea": as_dict(c.get("huntarea"))})
            continue

        if c.get("id") and c.get("name"):
            # maybe direct huntarea dict
            normalized_clubs.append({"huntarea_id": c.get("id"), "huntarea": c})
            continue

        # fallback keys safely
        hid = c.get("huntarea_id") or c.get("id")
        hmeta = c.get("huntarea") if isinstance(c.get("huntarea"), dict) else c if isinstance(c, dict) else {}
        normalized_clubs.append({"huntarea_id": hid, "huntarea": as_dict(hmeta)})

    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"hunt_areas": []}

    for club in normalized_clubs:
        # SAFEGUARDS: Never call .get on a non-dict
        huntarea_obj = club.get("huntarea") if isinstance(club.get("huntarea"), dict) else None

        hid = (
            club.get("huntarea_id")
            or club.get("id")
            or (huntarea_obj.get("id") if isinstance(huntarea_obj, dict) else None)
        )
        hmeta = huntarea_obj or as_dict(club)
        hunt_name = (
            (hmeta.get("name") if isinstance(hmeta, dict) else None)
            or club.get("name")
            or (f"Area-{hid}" if hid is not None else "Area-Unknown")
        )

        if hid is None:
            logger.debug("Skipping club without huntarea_id: %s", club)
            continue

        hname = hunt_name
        logger.info("Processing huntarea: %s (id=%s)", hname, hid)

        # members
        members = fetch_members_for_area(session, hid)
        members_list = json_or_list_to_objects(members) if members is not None else []

        # invites
        invites = fetch_invites_for_area(session, hid) or []

        # requests
        reqs = fetch_requests_for_area(session, hid) or []

        # Active members
        for m in members_list:
            # Extract member details based on actual API structure
            member_first_name = m.get("first_name", "").strip()
            member_last_name = m.get("last_name", "").strip()
            member_name = f"{member_first_name} {member_last_name}".strip()
            member_email = m.get("email", "").strip()

            # Members don't have rank info in this endpoint - we'll need to get it differently
            # For now, we'll set it as "member" (default) since they're active members
            member_rank = "member"  # Default for active members

            # Members don't seem to have join dates in this endpoint either
            member_date_joined = ""

            all_rows.append(
                {
                    "huntarea_id": hid,
                    "huntarea_name": hname,
                    "name": member_name,
                    "email": member_email,
                    "rank": member_rank,
                    "status": "active",
                    "date_joined": member_date_joined,
                }
            )

        # Invites
        for inv in invites:
            logger.debug(
                "Processing invite: %s",
                json.dumps(inv, indent=2)[:500] + "..." if len(str(inv)) > 500 else json.dumps(inv, indent=2),
            )

            # Extract invite details
            invite_name = inv.get("name") or inv.get("full_name") or ""
            invite_email = (inv.get("email") or "").strip()

            # Extract rank for invite
            rank_obj = inv.get("rank")
            if isinstance(rank_obj, dict):
                invite_rank = rank_obj.get("name") or rank_obj.get("title") or ""
            else:
                invite_rank = str(rank_obj or "")

            # Also check for role field
            if not invite_rank:
                invite_rank = inv.get("role") or inv.get("intended_rank") or ""

            # Extract date
            invite_date = inv.get("date_joined") or inv.get("created") or inv.get("date_sent") or ""

            all_rows.append(
                {
                    "huntarea_id": hid,
                    "huntarea_name": hname,
                    "name": invite_name.strip(),
                    "email": invite_email,
                    "rank": invite_rank.strip(),
                    "status": "invited",
                    "date_joined": invite_date,
                }
            )

        # Requests (people requesting to join)
        for rq in reqs:
            rq = as_dict(rq)

            # Extract requester details from the profile object
            profile = as_dict(rq.get("profile", {}))
            user_data = as_dict(profile.get("user", {}))

            # Get name from profile - try various fields
            profile_first_name = profile.get("first_name", "").strip() if profile.get("first_name") else ""
            profile_last_name = profile.get("last_name", "").strip() if profile.get("last_name") else ""
            profile_username = profile.get("username", "").strip() if profile.get("username") else ""

            # Also try user data
            user_first_name = user_data.get("first_name", "").strip() if user_data.get("first_name") else ""
            user_last_name = user_data.get("last_name", "").strip() if user_data.get("last_name") else ""
            user_username = user_data.get("username", "").strip() if user_data.get("username") else ""

            # Try to construct name from various sources
            first_name = profile_first_name or user_first_name
            last_name = profile_last_name or user_last_name
            username = profile_username or user_username

            request_name = f"{first_name} {last_name}".strip() if first_name or last_name else username

            # Get email from multiple sources
            request_email = profile.get("email", "").strip() or user_data.get("email", "").strip()

            # Get rank if available (some requests might have intended rank)
            rank_obj = rq.get("rank", {})
            request_rank = rank_obj.get("name", "").strip() if isinstance(rank_obj, dict) else ""

            # Extract request date
            request_date = rq.get("date_requested", "")

            # If still no identifiable info, use profile/user IDs
            if not request_name and not request_email:
                profile_id = profile.get("id", "")
                user_id = user_data.get("id", "")
                if profile_id:
                    request_name = f"Profile_{profile_id}"
                elif user_id:
                    request_name = f"User_{user_id}"

            all_rows.append(
                {
                    "huntarea_id": hid,
                    "huntarea_name": hname,
                    "name": request_name,
                    "email": request_email,
                    "rank": request_rank,
                    "status": "requested",
                    "date_joined": request_date,
                }
            )

        summary["hunt_areas"].append(
            {
                "id": hid,
                "name": hname,
                "meta": hmeta,
                "counts": {"members": len(members_list), "invites": len(invites), "requests": len(reqs)},
                "members_sample": members_list[:10],
                "invites_sample": invites[:10],
                "requests_sample": reqs[:10],
            }
        )

    # write outputs
    write_detailed_csv(all_rows, out_path=args.outfile_csv)
    write_json_summary(summary, out_path=args.outfile_json)
    write_membership_matrix(all_rows, out_path=args.outfile_matrix)
    if args.per_hunt:
        write_per_hunt_csvs(all_rows)

    logger.info(
        "All done. Files generated:\n - %s\n - %s\n - %s", args.outfile_csv, args.outfile_json, args.outfile_matrix
    )
    if args.per_hunt:
        logger.info("Per-hunt CSVs in: %s", OUT_PER_HUNT_DIR)
    return 0
