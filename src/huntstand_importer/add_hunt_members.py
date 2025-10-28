import csv
import os
import time
from pathlib import Path
from datetime import datetime
import requests
from dotenv import load_dotenv

# ----------------------------
# Config defaults
# ----------------------------
RETRIES = 3                # Number of retries on 429/5xx
BASE_BACKOFF = 1.0         # Seconds; doubles each retry (1s, 2s, 4s…)
DELAY_BETWEEN_CALLS = 0.25 # Seconds between calls

# Role toggles
IMPORT_ROLES = {
    "member": True,
    "admin": False,
    "view": False,
}

FILES = {
    "member": "members.csv",
    "admin": "admin.csv",
    "view": "view_only.csv",
    "huntareas": "huntareas.csv",
}

API_URL = "https://app.huntstand.com/api/v2/huntarea/share/"
RETRIABLE_STATUSES = {429, 500, 502, 503, 504, 522}


# ----------------------------
# Env & headers
# ----------------------------
def load_env():
    env_path = Path(".") / ".env"
    load_dotenv(dotenv_path=env_path)

    session_id = os.getenv("HUNTSTAND_SESSIONID")
    csrf_token = os.getenv("HUNTSTAND_CSRFTOKEN")

    if not session_id or not csrf_token:
        raise ValueError("HUNTSTAND_SESSIONID and HUNTSTAND_CSRFTOKEN must be set in .env")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-CSRFToken": csrf_token,
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
    }
    cookies = {
        "sessionid": session_id,
        "csrftoken": csrf_token,
    }
    return headers, cookies


# ----------------------------
# CSV loaders
# ----------------------------
def safe_load_csv_emails(path: str):
    emails = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                cell = row[0].strip()
                if not cell or cell.lower() == "email":
                    continue
                emails.append(cell)
    except FileNotFoundError:
        return []
    return emails


def safe_load_huntareas(path: str):
    ids = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            cell = row[0].strip()
            if not cell or cell.lower() == "huntarea_id":
                continue
            ids.append(cell)
    if not ids:
        raise ValueError("huntareas.csv is empty.")
    return ids


# ----------------------------
# API call with retry/backoff
# ----------------------------
def post_share(headers, cookies, email, huntarea_id, role):
    data = {"email": email, "huntarea_id": huntarea_id, "rank": role}
    last_exc = None
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.post(API_URL, headers=headers, cookies=cookies, data=data, timeout=15)
            body = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else resp.text
            result = {
                "email": email,
                "huntarea_id": huntarea_id,
                "role": role,
                "status_code": resp.status_code,
                "response": body,
            }
            if resp.status_code < 400 or resp.status_code not in RETRIABLE_STATUSES:
                time.sleep(DELAY_BETWEEN_CALLS)
                return result
            sleep_for = BASE_BACKOFF * (2 ** attempt)
            time.sleep(sleep_for)
        except Exception as e:
            last_exc = e
            sleep_for = BASE_BACKOFF * (2 ** attempt)
            time.sleep(sleep_for)

    return {
        "email": email,
        "huntarea_id": huntarea_id,
        "role": role,
        "status_code": "error",
        "response": str(last_exc) if last_exc else "Max retries exhausted",
    }


# ----------------------------
# Main
# ----------------------------
def main():
    headers, cookies = load_env()

    role_lists = {
        "member": safe_load_csv_emails(FILES["member"]) if IMPORT_ROLES["member"] else [],
        "admin": safe_load_csv_emails(FILES["admin"]) if IMPORT_ROLES["admin"] else [],
        "view": safe_load_csv_emails(FILES["view"]) if IMPORT_ROLES["view"] else [],
    }
    huntareas = safe_load_huntareas(FILES["huntareas"])

    results = []

    for ha in huntareas:
        for role, enabled in IMPORT_ROLES.items():
            if not enabled:
                continue
            for email in role_lists.get(role, []):
                res = post_share(headers, cookies, email, ha, role)
                results.append(res)

    # Build output path
    exports_dir = Path(__file__).parent / "exports"
    exports_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = exports_dir / f"members_added_results_{timestamp}.csv"

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "huntarea_id", "role", "status_code", "response"])
        writer.writeheader()
        writer.writerows(results)

    print(f"Done. Results written to {out_file}")


if __name__ == "__main__":
    main()
