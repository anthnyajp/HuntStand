# HuntStand Membership Exporter

A CLI tool that exports HuntStand hunt area membership data (active members, invites, join requests) into structured CSV and JSON files.

> IMPORTANT: All output filenames are **always timestamped** and written under a base `exports/` directory (or a custom `--output-dir`). Legacy wrapper `huntstand.py` has been removed; use the `huntstand-exporter` console command.

## Features

- Cookie-first authentication (recommended) using `sessionid` and `csrftoken`.
- Fallback username/password login (less reliable — uses both `login` and `username` keys).
- Robust retry logic for transient HTTP failures.
- TLS verification with `certifi` and auto fallback to `verify=False` (with warning) if SSL errors occur.
- Normalization of inconsistent API shapes (lists, `{objects: [...]}` wrappers, or dict maps).
- Generates (all timestamped now):
  - Detailed CSV (`exports/huntstand_members_detailed_<YYYYMMDD_HHMMSS>.csv`)
  - Membership matrix CSV (`exports/huntstand_membership_matrix_<YYYYMMDD_HHMMSS>.csv`)
  - JSON summary (`exports/huntstand_summary_<YYYYMMDD_HHMMSS>.json`)
  - Optional per-hunt CSVs (`exports/huntstand_per_hunt_csvs_<YYYYMMDD_HHMMSS>/`)

### New: Add Members Command

The companion command `huntstand-add-members` lets you bulk invite/add emails to hunt areas based on CSV inputs.

Input CSV files (single-column, header optional):

- `members.csv` — standard member emails
- `admin.csv` — admin emails
- `view_only.csv` — view-only emails
- `huntareas.csv` — hunt area IDs (numeric or UUID-like)

Basic usage:

```powershell
# Dry-run (shows planned operations; no network calls)
huntstand-add-members --dry-run

# Import only member + admin roles
huntstand-add-members --roles member admin

# Custom file paths
huntstand-add-members --members-file data/members.csv --admin-file data/admins.csv --huntareas-file data/huntareas.csv
```

CLI options:

```text
--cookies-file <path>     JSON file with sessionid/csrftoken (overridden by env)
--members-file <path>     Members emails CSV (default members.csv)
--admin-file <path>       Admin emails CSV (default admin.csv)
--view-file <path>        View-only emails CSV (default view_only.csv)
--huntareas-file <path>   Hunt area IDs CSV (default huntareas.csv)
--roles <list>            Subset of roles to import (member/admin/view); default member
--dry-run                 Show planned additions and exit (no network)
--retries <int>           Retries for transient errors (default 3)
--backoff <float>         Base backoff seconds (default 1.0)
--delay <float>           Delay between successful calls (default 0.25s)
--no-login-fallback       Do not attempt login fallback; require cookies
--output-dir <dir>        Directory for result CSV (default exports/)
--log-json                Emit structured JSON logs
```

Output:

- `exports/members_added_results_<YYYYMMDD_HHMMSS>.csv` with columns: `email,huntarea_id,role,status_code,response`

Notes:

- Responses longer than 500 chars are truncated for readability.
- Dry-run prints the total planned operations and sample entries (first 20).
- The command uses the same cookie-first, login-fallback pattern as the exporter.

## Quick Start

```powershell
# 1. Clone
git clone https://github.com/anthnyajp/HuntStand.git
cd HuntStand

# 2. (Optional) create virtual environment
python -m venv .venv
./.venv/Scripts/Activate.ps1

# 3. Install (editable for development)
pip install -e .

# 4. Set authentication cookies (preferred)
$env:HUNTSTAND_SESSIONID = "<sessionid_from_browser>"
$env:HUNTSTAND_CSRFTOKEN = "<csrftoken_from_browser>"

# 5. Run exporter (auto timestamped outputs in ./exports)
huntstand-exporter --per-hunt
```

### Shell Differences (PowerShell vs Bash)

PowerShell uses `$env:VAR = "value"` while Bash uses `export VAR="value"`.

| Purpose | PowerShell | Bash |
|---------|------------|------|
| Set sessionid | `$env:HUNTSTAND_SESSIONID = "abc123"` | `export HUNTSTAND_SESSIONID="abc123"` |
| Set csrftoken | `$env:HUNTSTAND_CSRFTOKEN = "def456"` | `export HUNTSTAND_CSRFTOKEN="def456"` |
| Run exporter | `huntstand-exporter` | `huntstand-exporter` |

Environment cookies override values provided via `--cookies-file` if both are present (env > file > login fallback).

## Obtaining Cookies

Use browser dev tools on <https://app.huntstand.com> while logged in:

1. Open DevTools → Network tab
2. Refresh; select any authenticated request
3. Copy `sessionid` and `csrftoken` from Cookie header
4. Export (optional) to a JSON file like:

```json
{
  "sessionid": "abc123...",
  "csrftoken": "def456..."
}
```

Run with: `huntstand-exporter --cookies-file cookies.json`

You can also keep this as `cookies.example.json` in version control and copy to a real `cookies.json` locally (never commit real cookie values).

### Using a .env File

Create a `.env` file (not committed) to avoid retyping variables:

```env
HUNTSTAND_SESSIONID=abc123
HUNTSTAND_CSRFTOKEN=def456
HUNTSTAND_LOG_LEVEL=INFO
```

Then use a loader (already supported via `python-dotenv`) automatically when running the console script from within the project directory. If you move the `.env` file elsewhere, load manually:

```powershell
pip install python-dotenv  # already in dependencies, only if missing
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('HUNTSTAND_SESSIONID'))"
```

### Order of Authentication Attempts

1. Explicit environment variables
2. Values from `--cookies-file`
3. Username/password fallback (`HUNTSTAND_USER`, `HUNTSTAND_PASS`)
4. Continue (some endpoints may fail) if none provided

## Fallback Login

If cookies are not available (less reliable):

```powershell
$env:HUNTSTAND_USER = "you@example.com"
$env:HUNTSTAND_PASS = "hunter2"
huntstand-exporter
```

The tool will attempt both `login` and `username` fields; this endpoint can be flaky. Prefer cookies.

Bash equivalent:

```bash
export HUNTSTAND_USER="you@example.com"
export HUNTSTAND_PASS="hunter2"
huntstand-exporter
```

## CLI Options

```text
--cookies-file <path>      JSON file with sessionid/csrftoken
--profile-id <id>          Fallback profile ID for hunt areas if /myprofile/ empty
--per-hunt                 Also write per-hunt CSV files (timestamped directory)
--no-login-fallback        Require cookies; do not attempt login fallback
--dry-run                  Show planned outputs; skip network and file writes
--output-dir <dir>         Base directory for outputs (default: exports/)
--format {all,csv,json}    Select outputs: all (default), csv, or json
--log-json                 Emit structured JSON log lines
```

Behavior details:

- `--dry-run` lists planned timestamped output paths then exits 0 (no network/file I/O).
- Timestamping is unconditional: filenames always include a `YYYYMMDD_HHMMSS` component.
- `--output-dir` chooses/creates the base directory (defaults to `exports/`).
- `--format=csv` writes detailed + matrix CSVs (plus per-hunt if `--per-hunt`).
- `--format=json` writes only the JSON summary.
- `--format=all` writes all CSVs and JSON.
- `--log-json` emits structured JSON lines (schema: `{ts, level, msg, name}`).

## Output Files

| File Pattern | Description |
|--------------|-------------|
| `huntstand_members_detailed_<ts>.csv` | One row per active member, invite, request |
| `huntstand_membership_matrix_<ts>.csv` | Email vs hunt area status (Active/Invited/Requested/No) |
| `huntstand_summary_<ts>.json` | Aggregated metadata + samples per hunt area |
| `huntstand_per_hunt_csvs_<ts>/` | Optional per-area breakdown (one CSV per hunt area) |

All outputs are timestamped regardless of flags. Example (format=all, per-hunt):

```text
exports/
  huntstand_members_detailed_20250101_123045.csv
  huntstand_membership_matrix_20250101_123045.csv
  huntstand_summary_20250101_123045.json
  huntstand_per_hunt_csvs_20250101_123045/
    hunt_<id>_<sanitized_name>.csv
```

Custom `--output-dir mydata` relocates these under `mydata/` with identical naming.

## Development

```powershell
# Install with dev dependencies
pip install -e ".[dev]"

# Run with debug logging
$env:HUNTSTAND_LOG_LEVEL = "DEBUG"
huntstand-exporter --per-hunt

# Example: JSON-only batch into custom directory
huntstand-exporter --output-dir exports/batch1 --format json

# Run linter
ruff check src/ tests/

# Run formatter
ruff format src/ tests/

# Run type checker
mypy src/huntstand_exporter/
```

## Testing

```powershell
# Run all tests
pytest -v

# Focus on new format flag behaviors
pytest tests/test_format_flag.py -q

# Run with coverage
pytest --cov=huntstand_exporter --cov-report=html
```

## Environment Template

Below is a suggested template you can copy into a local `.env` (do NOT commit real values):

```env
HUNTSTAND_SESSIONID=
HUNTSTAND_CSRFTOKEN=
HUNTSTAND_USER=
HUNTSTAND_PASS=
HUNTSTAND_LOG_LEVEL=INFO
```

`HUNTSTAND_USER` / `HUNTSTAND_PASS` are only used if cookies are absent.

## Responsible Use Notice

This tool interacts with HuntStand's private web APIs using your authenticated session.

- Only access data you are authorized to view.
- Respect HuntStand Terms of Service.
- Avoid high-frequency automated polling.
- Do NOT publish real cookies or personal member data.

## License

MIT — see `LICENSE`.

## Contributing

See `CONTRIBUTING.md` for guidelines.

## Deprecation & Removal

- Removed legacy wrapper script `huntstand.py` (use `huntstand-exporter`).
- Removed deprecated flags: `--timestamped`, `--outfile-csv`, `--outfile-json`, `--outfile-matrix` (timestamping & internal naming policy are now unconditional).
- Added new `huntstand-add-members` bulk invitation/role assignment command in 0.3.0.

## Roadmap Ideas

- Optional output to SQLite
- Add export for asset/geodata endpoints
- Parallelization for large club counts

---
Maintained with a defensive, continue-on-error philosophy to maximize partial data extraction.
