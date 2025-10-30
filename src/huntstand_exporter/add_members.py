"""Add members to HuntStand hunt areas via CSV lists.

Features:
 - Cookie-first auth (HUNTSTAND_SESSIONID + HUNTSTAND_CSRFTOKEN or --cookies-file)
 - Optional login fallback (HUNTSTAND_USER + HUNTSTAND_PASS) reusing exporter logic
 - CSV inputs:
     members.csv, admin.csv, view_only.csv, huntareas.csv (column headers optional)
 - Role toggles via CLI flags (--role-member / --role-admin / --role-view)
 - Retry/backoff for transient errors (429/5xx) with exponential backoff
 - Dry-run mode to show planned additions without network calls
 - Timestamped output CSV summarizing results
 - Structured JSON logging option (--log-json) like exporter

Usage examples:
  export HUNTSTAND_SESSIONID="..."; export HUNTSTAND_CSRFTOKEN="..."
  huntstand-add-members --roles member admin --dry-run

  huntstand-add-members --members-file path/to/members.csv --huntareas-file huntareas.csv

Security: Prefer cookie-based auth; login fallback is flaky.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

# Reuse environment and helpers from exporter when available
try:
    from .exporter import (
        ENV_SESSIONID,
        ENV_CSRFTOKEN,
        ENV_USER,
        ENV_PASS,
        BASE_URL,
        LOGIN_POST_PATH,
        ROOT_PATH,
        make_session_with_retries,
        set_ca_bundle,
        fallback_disable_verify,
        attempt_login,
    )
except Exception:  # fallback minimal env if importer fails
    ENV_SESSIONID = os.getenv("HUNTSTAND_SESSIONID")
    ENV_CSRFTOKEN = os.getenv("HUNTSTAND_CSRFTOKEN")
    ENV_USER = os.getenv("HUNTSTAND_USER")
    ENV_PASS = os.getenv("HUNTSTAND_PASS")
    BASE_URL = os.getenv("HUNTSTAND_BASE_URL", "https://app.huntstand.com")
    LOGIN_POST_PATH = "/login"
    ROOT_PATH = "/"

# optional .env load
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

RETRIABLE_STATUSES = {429, 500, 502, 503, 504, 522}
DEFAULT_BACKOFF = 1.0
DEFAULT_RETRIES = 3
API_SHARE_URL = f"{BASE_URL}/api/v2/huntarea/share/"
MEMBERS_URL = f"{BASE_URL}/api/v1/clubmember/?huntarea_id={{}}"
INVITES_URL = f"{BASE_URL}/api/v1/membershipemailinvite/?huntarea={{}}"


def _configure_logger(structured: bool = False) -> logging.Logger:
    level = os.getenv("HUNTSTAND_LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger("huntstand-add-members")
    if logger.handlers:
        for h in list(logger.handlers):
            logger.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stdout)
    if structured:
        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
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


def load_cookies_file(path: str) -> tuple[str | None, str | None]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        sid = data.get("sessionid") or data.get("session_id")
        csrft = data.get("csrftoken") or data.get("csrf")
        return sid, csrft
    except Exception as e:
        logger.error("Failed to load cookies file %s: %s", path, e)
        return None, None


def create_session(sessionid: str | None, csrftoken: str | None) -> requests.Session:
    s = make_session_with_retries(total_retries=3, backoff=0.3)
    try:
        set_ca_bundle(s)
    except Exception:
        pass
    domain = BASE_URL.split("//", 1)[1].split("/", 1)[0]
    if sessionid:
        s.cookies.set("sessionid", sessionid, domain=domain, path="/")
        logger.info("Loaded sessionid cookie (domain=%s)", domain)
    if csrftoken:
        s.cookies.set("csrftoken", csrftoken, domain=domain, path="/")
        logger.info("Loaded csrftoken cookie (domain=%s)", domain)
    return s


def safe_load_single_column(path: str, header_names: Iterable[str]) -> list[str]:
    items: list[str] = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            for row in reader:
                if not row:
                    continue
                cell = row[0].strip()
                if not cell:
                    continue
                if cell.lower() in {h.lower() for h in header_names}:
                    continue
                items.append(cell)
    except FileNotFoundError:
        logger.debug("File not found (treated as empty): %s", path)
        return []
    except Exception as e:
        logger.error("Error reading %s: %s", path, e)
    return items


def exponential_sleep(attempt: int, base: float) -> None:
    time.sleep(base * (2 ** attempt))


@dataclass
class ShareResult:
    email: str
    huntarea_id: str
    role: str
    status_code: int | str
    response: Any

    def as_row(self) -> dict[str, Any]:
        body = self.response
        if isinstance(body, (dict, list)):
            try:
                body = json.dumps(body)[:500]
            except Exception:
                body = str(body)
        return {
            "email": self.email,
            "huntarea_id": self.huntarea_id,
            "role": self.role,
            "status_code": self.status_code,
            "response": body,
        }


def post_share(session: requests.Session, email: str, huntarea_id: str, role: str, retries: int, backoff: float) -> ShareResult:
    data = {"email": email, "huntarea_id": huntarea_id, "rank": role}
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = session.post(API_SHARE_URL, data=data, timeout=15)
            ctype = resp.headers.get("Content-Type", "")
            body: Any
            if ctype.startswith("application/json"):
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text
            else:
                body = resp.text
            result = ShareResult(email=email, huntarea_id=huntarea_id, role=role, status_code=resp.status_code, response=body)
            # success or non-retriable
            if resp.status_code < 400 or resp.status_code not in RETRIABLE_STATUSES:
                return result
            exponential_sleep(attempt, backoff)
            continue
        except Exception as e:  # broad catch to continue on errors
            last_exc = e
            exponential_sleep(attempt, backoff)
    return ShareResult(email=email, huntarea_id=huntarea_id, role=role, status_code="error", response=str(last_exc) if last_exc else "Max retries exhausted")


def write_results_csv(rows: list[ShareResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["email", "huntarea_id", "role", "status_code", "response"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r.as_row())
    logger.info("Wrote results CSV: %s (%d rows)", out_path, len(rows))


def plan_additions(emails_by_role: dict[str, list[str]], huntareas: list[str]) -> list[tuple[str, str, str]]:
    plans: list[tuple[str, str, str]] = []
    for role, emails in emails_by_role.items():
        for ha in huntareas:
            for em in emails:
                plans.append((role, ha, em))
    return plans


@dataclass
class VerificationResult:
    email: str
    huntarea_id: str
    expected_role: str
    found: bool
    actual_role: str | None
    status: str  # "verified", "missing", "role_mismatch", "error"
    notes: str

    def as_row(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "huntarea_id": self.huntarea_id,
            "expected_role": self.expected_role,
            "found": "Yes" if self.found else "No",
            "actual_role": self.actual_role or "",
            "status": self.status,
            "notes": self.notes,
        }


def fetch_hunt_area_members(session: requests.Session, huntarea_id: str) -> dict[str, str]:
    """Fetch current members and invites for a hunt area, return {email: role} mapping."""
    members_map: dict[str, str] = {}

    # Fetch active members
    try:
        resp = session.get(MEMBERS_URL.format(huntarea_id), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Handle different response formats
        if isinstance(data, dict) and "objects" in data:
            members_list = data["objects"]
        elif isinstance(data, list):
            members_list = data
        else:
            members_list = []

        for m in members_list:
            if isinstance(m, dict):
                email = (m.get("email") or "").strip().lower()
                # Try to get rank from member object
                rank_obj = m.get("rank")
                if isinstance(rank_obj, dict):
                    role = rank_obj.get("name", "member")
                else:
                    role = str(rank_obj or "member")
                if email:
                    members_map[email] = role.lower()
    except Exception as e:
        logger.debug("Error fetching members for hunt area %s: %s", huntarea_id, e)

    # Fetch pending invites
    try:
        resp = session.get(INVITES_URL.format(huntarea_id), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict) and "objects" in data:
            invites_list = data["objects"]
        elif isinstance(data, list):
            invites_list = data
        else:
            invites_list = []

        for inv in invites_list:
            if isinstance(inv, dict):
                email = (inv.get("email") or "").strip().lower()
                rank_obj = inv.get("rank")
                if isinstance(rank_obj, dict):
                    role = rank_obj.get("name", "member")
                else:
                    role = str(rank_obj or "member")
                if email:
                    members_map[email] = role.lower()
    except Exception as e:
        logger.debug("Error fetching invites for hunt area %s: %s", huntarea_id, e)

    return members_map


def verify_additions(session: requests.Session, results_csv_path: str) -> list[VerificationResult]:
    """Read results CSV and verify each successful addition exists in hunt area."""
    verifications: list[VerificationResult] = []

    try:
        with open(results_csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                email = row.get("email", "").strip().lower()
                huntarea_id = row.get("huntarea_id", "").strip()
                expected_role = row.get("role", "").strip().lower()
                status_code = row.get("status_code", "")

                # Only verify successful additions (2xx status codes)
                try:
                    if not status_code.isdigit() or not (200 <= int(status_code) < 300):
                        verifications.append(VerificationResult(
                            email=email,
                            huntarea_id=huntarea_id,
                            expected_role=expected_role,
                            found=False,
                            actual_role=None,
                            status="skipped",
                            notes=f"Original status was {status_code}, not verified"
                        ))
                        continue
                except (ValueError, TypeError):
                    verifications.append(VerificationResult(
                        email=email,
                        huntarea_id=huntarea_id,
                        expected_role=expected_role,
                        found=False,
                        actual_role=None,
                        status="skipped",
                        notes=f"Invalid status code: {status_code}"
                    ))
                    continue

                # Fetch current members for this hunt area
                try:
                    members_map = fetch_hunt_area_members(session, huntarea_id)

                    if email in members_map:
                        actual_role = members_map[email]
                        if actual_role == expected_role:
                            verifications.append(VerificationResult(
                                email=email,
                                huntarea_id=huntarea_id,
                                expected_role=expected_role,
                                found=True,
                                actual_role=actual_role,
                                status="verified",
                                notes="Member found with correct role"
                            ))
                        else:
                            verifications.append(VerificationResult(
                                email=email,
                                huntarea_id=huntarea_id,
                                expected_role=expected_role,
                                found=True,
                                actual_role=actual_role,
                                status="role_mismatch",
                                notes=f"Expected {expected_role}, found {actual_role}"
                            ))
                    else:
                        verifications.append(VerificationResult(
                            email=email,
                            huntarea_id=huntarea_id,
                            expected_role=expected_role,
                            found=False,
                            actual_role=None,
                            status="missing",
                            notes="Member not found in hunt area"
                        ))
                except Exception as e:
                    verifications.append(VerificationResult(
                        email=email,
                        huntarea_id=huntarea_id,
                        expected_role=expected_role,
                        found=False,
                        actual_role=None,
                        status="error",
                        notes=f"Verification error: {str(e)[:100]}"
                    ))

                time.sleep(0.2)  # Gentle rate limiting during verification

    except FileNotFoundError:
        logger.error("Results CSV not found: %s", results_csv_path)
    except Exception as e:
        logger.error("Error reading results CSV: %s", e)

    return verifications


def write_verification_csv(rows: list[VerificationResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["email", "huntarea_id", "expected_role", "found", "actual_role", "status", "notes"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r.as_row())
    logger.info("Wrote verification CSV: %s (%d rows)", out_path, len(rows))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="huntstand-add-members", description="Add members to HuntStand hunt areas from CSV lists")
    ap.add_argument("--cookies-file", help="JSON file containing sessionid/csrftoken", default=None)
    ap.add_argument("--members-file", default="members.csv", help="CSV file of member emails")
    ap.add_argument("--admin-file", default="admin.csv", help="CSV file of admin emails")
    ap.add_argument("--view-file", default="view_only.csv", help="CSV file of view-only emails")
    ap.add_argument("--huntareas-file", default="huntareas.csv", help="CSV file of hunt area IDs")
    ap.add_argument("--roles", nargs="+", choices=["member", "admin", "view"], default=["member"], help="Roles to import (subset of member/admin/view)")
    ap.add_argument("--dry-run", action="store_true", help="Show planned additions and exit without network calls")
    ap.add_argument("--verify-results", metavar="CSV_PATH", help="Verify additions from a previous results CSV file")
    ap.add_argument("--log-json", action="store_true", help="Emit structured JSON logs to stdout")
    ap.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="Retries for transient errors (default 3)")
    ap.add_argument("--backoff", type=float, default=DEFAULT_BACKOFF, help="Base backoff seconds (default 1.0)")
    ap.add_argument("--delay", type=float, default=0.25, help="Delay between successful calls (default 0.25s)")
    ap.add_argument("--no-login-fallback", action="store_true", help="Disable login fallback; require cookies")
    ap.add_argument("--output-dir", default="exports", help="Directory for output results CSV (default exports/)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.log_json:
        global logger
        logger = _configure_logger(structured=True)

    # Load cookies first, possibly overriding env
    sessionid = ENV_SESSIONID
    csrftoken = ENV_CSRFTOKEN
    if args.cookies_file:
        sidf, csrff = load_cookies_file(args.cookies_file)
        sessionid = sidf or sessionid
        csrftoken = csrff or csrftoken

    session = create_session(sessionid, csrftoken)

    # TLS reachability check; fallback disable on SSL error
    try:
        session.get(BASE_URL + ROOT_PATH, timeout=10)
    except Exception as e:
        if "SSL" in str(type(e).__name__) or "ssl" in str(e).lower():
            logger.warning("SSL verification issue: %s", e)
            fallback_disable_verify(session)
        else:
            logger.debug("Root GET warning: %s", e)

    if not session.cookies.get("sessionid"):
        if args.no_login_fallback:
            logger.error("No session cookie and login fallback disabled.")
            return 2
        if ENV_USER and ENV_PASS:
            try:
                ok = attempt_login(session, ENV_USER, ENV_PASS)
                if not ok:
                    logger.warning("Login attempt did not yield session cookie; proceeding may fail.")
            except Exception as e:
                logger.error("Login fallback raised: %s", e)
        else:
            logger.warning("No session cookie and no credentials configured; calls may fail.")

    # Verification mode: validate previous results
    if args.verify_results:
        logger.info("Verification mode: checking results from %s", args.verify_results)
        verifications = verify_additions(session, args.verify_results)

        # Count statuses
        verified = sum(1 for v in verifications if v.status == "verified")
        missing = sum(1 for v in verifications if v.status == "missing")
        role_mismatch = sum(1 for v in verifications if v.status == "role_mismatch")
        errors = sum(1 for v in verifications if v.status == "error")
        skipped = sum(1 for v in verifications if v.status == "skipped")

        logger.info("Verification summary: %d verified, %d missing, %d role mismatch, %d errors, %d skipped",
                    verified, missing, role_mismatch, errors, skipped)

        # Write verification report
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"members_verification_{ts}.csv"
        write_verification_csv(verifications, out_file)

        # Return non-zero if any issues found
        if missing > 0 or role_mismatch > 0 or errors > 0:
            logger.warning("Verification found issues. Check %s for details.", out_file)
            return 1

        logger.info("Verification complete. All additions confirmed.")
        return 0

    # Load CSV data
    emails_by_role: dict[str, list[str]] = {
        "member": safe_load_single_column(args.members_file, ["email", "member_email"]),
        "admin": safe_load_single_column(args.admin_file, ["email", "admin_email"]),
        "view": safe_load_single_column(args.view_file, ["email", "view_email"]),
    }
    # Filter roles according to args.roles
    for r in list(emails_by_role.keys()):
        if r not in args.roles:
            emails_by_role[r] = []

    huntareas = safe_load_single_column(args.huntareas_file, ["huntarea_id", "id"])
    if not huntareas:
        logger.error("No hunt area IDs loaded (file: %s)", args.huntareas_file)
        return 3

    plans = plan_additions({k: v for k, v in emails_by_role.items() if v}, huntareas)
    logger.info("Planned additions: %d", len(plans))
    for role, ha, em in plans[:20]:  # sample
        logger.debug("Sample plan: role=%s huntarea=%s email=%s", role, ha, em)
    if len(plans) > 20:
        logger.debug("%d additional plans omitted from sample", len(plans) - 20)

    # Dry-run exit
    if args.dry_run:
        logger.info("Dry-run requested; skipping network. Planned operations: %d", len(plans))
        return 0

    results: list[ShareResult] = []
    for role, ha, em in plans:
        res = post_share(session, email=em, huntarea_id=ha, role=role, retries=args.retries, backoff=args.backoff)
        results.append(res)
        time.sleep(args.delay)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"members_added_results_{ts}.csv"
    write_results_csv(results, out_file)
    logger.info("All done. Added members attempts: %d", len(results))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
