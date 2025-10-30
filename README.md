# HuntStand Membership & Asset Exporter

A CLI tool that exports HuntStand hunt area membership data (active members, invites, join requests) and optional asset data into structured, timestamped CSV and JSON files.

> IMPORTANT: All output filenames are always timestamped and written under a base `exports/` directory (or a custom `--output-dir`). Legacy wrapper `huntstand.py` has been removed; use the `huntstand-exporter` console command.

## Features

- Cookie-first authentication (recommended) using `sessionid` and `csrftoken`.
- Fallback username/password login (less reliable — tries both `login` and `username` keys).
- Robust retry logic for transient HTTP failures (429 / 5xx) with backoff.
- TLS verification with `certifi` and automatic insecure fallback (`verify=False` with warning) on SSL errors.
- Defensive normalization of inconsistent API shapes (lists, `{objects: [...]}` wrappers, or dict maps).
- Parallel data collection (`--parallel`) for multiple hunt areas.
- Dynamic asset endpoint probing (`--dynamic-assets`) to auto-disable invalid endpoints.
- Extensible asset endpoint list via `--assets-extra` and `HUNTSTAND_ASSET_ENDPOINTS` env var.
- Generates:
  - Detailed membership CSV `huntstand_members_detailed_<ts>.csv`
  - Membership matrix CSV `huntstand_membership_matrix_<ts>.csv`
  - JSON hunt area summary `huntstand_summary_<ts>.json`
  - Optional per-hunt CSV directory `huntstand_per_hunt_csvs_<ts>/`
  - Optional assets CSV `huntstand_assets_detailed_<ts>.csv` (when `--include-assets`)

## Bulk Add Members Command (`huntstand-add-members`)

Bulk invite/add emails to hunt areas using CSV input files.

Input CSV files (single-column, header optional) located in `import/` directory:

- `import/members.csv` — standard member emails
- `import/admin.csv` — admin emails
- `import/view_only.csv` — view-only emails
- `import/huntareas.csv` — hunt area IDs (numeric or UUID-like)

Basic usage:

```powershell
# Dry-run (shows planned operations; no network calls)
huntstand-add-members --dry-run

# Import only member + admin roles
huntstand-add-members --roles member admin

# Custom file paths
huntstand-add-members --members-file data/members.csv --admin-file data/admins.csv --huntareas-file data/huntareas.csv
```

CLI options (`huntstand-add-members`):

```text
--cookies-file <path>     JSON file with sessionid/csrftoken (overridden by env)
--members-file <path>     Members emails CSV (default import/members.csv)
--admin-file <path>       Admin emails CSV (default import/admin.csv)
--view-file <path>        View-only emails CSV (default import/view_only.csv)
--huntareas-file <path>   Hunt area IDs CSV (default import/huntareas.csv)
--roles <list>            Subset of roles to import (member/admin/view); default member
--dry-run                 Show planned additions and exit (no network)
--verify-results <csv>    Verify previous additions from results CSV file
--retries <int>           Retries for transient errors (default 3)
--backoff <float>         Base backoff seconds (default 1.0)
--delay <float>           Delay between successful calls (default 0.25s)
--no-login-fallback       Do not attempt login fallback; require cookies
--output-dir <dir>        Directory for result CSV (default exports/)
--log-json                Emit structured JSON logs
```

Output:

- `exports/members_added_results_<YYYYMMDD_HHMMSS>.csv` columns: `email,huntarea_id,role,status_code,response`
- `exports/members_verification_<YYYYMMDD_HHMMSS>.csv` columns: `email,huntarea_id,expected_role,found,actual_role,status,notes` (with `--verify-results`)

Verification workflow:

```powershell
# Step 1: Add members (creates results CSV)
huntstand-add-members --roles member admin

# Step 2: Verify the additions were successful
huntstand-add-members --verify-results exports/members_added_results_20251030_091234.csv
```

Verification status codes:

- `verified` - Member found with correct role
- `missing` - Member not found in hunt area
- `role_mismatch` - Member found but with different role than expected
- `error` - API error during verification
- `skipped` - Original addition failed (non-2xx)

Notes:

- Responses longer than 500 chars are truncated for readability.
- Dry-run prints total planned operations and sample entries (first 20).
- Verification only checks successful (2xx) original additions.

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

## Shell Differences (PowerShell vs Bash)

| Purpose | PowerShell | Bash |
|---------|------------|------|
| Set sessionid | `$env:HUNTSTAND_SESSIONID = "abc123"` | `export HUNTSTAND_SESSIONID="abc123"` |
| Set csrftoken | `$env:HUNTSTAND_CSRFTOKEN = "def456"` | `export HUNTSTAND_CSRFTOKEN="def456"` |
| Run exporter | `huntstand-exporter` | `huntstand-exporter` |

Environment cookies override values provided via `--cookies-file` (env > file > login fallback).

## Obtaining Cookies

Use browser dev tools on <https://app.huntstand.com> while logged in:

1. Open DevTools → Network tab
2. Refresh; select any authenticated request
3. Copy `sessionid` and `csrftoken` from Cookie header
4. (Optional) store in JSON file:

```json
{"sessionid": "abc123...", "csrftoken": "def456..."}
```

Run with: `huntstand-exporter --cookies-file cookies.json`

### Using a .env File

```env
HUNTSTAND_SESSIONID=abc123
HUNTSTAND_CSRFTOKEN=def456
HUNTSTAND_LOG_LEVEL=INFO
```

`python-dotenv` auto-loads this when running inside the project directory.

### Order of Authentication Attempts

1. Environment cookies
2. `--cookies-file`
3. Username/password (`HUNTSTAND_USER`, `HUNTSTAND_PASS`)
4. Continue (endpoints may fail) if none provided

## Fallback Login

```powershell
$env:HUNTSTAND_USER = "you@example.com"
$env:HUNTSTAND_PASS = "hunter2"
huntstand-exporter
```

Less reliable; prefer cookies.

## Asset Export (Expanded)

When `--include-assets` is provided the exporter attempts to collect multiple asset types per hunt area from a candidate list:

```text
stand, camera, trailcam, blind, feeder, foodplot, waypoint, trail, asset (fallback)
```

`--dynamic-assets` probes each candidate endpoint using the first hunt area and drops those returning unusable shapes (not 200, not list, not dict with `objects`).

Add custom endpoints via:

```powershell
huntstand-exporter --include-assets --assets-extra mineral:https://app.huntstand.com/api/v1/mineral/?huntarea_id={} marker:https://app.huntstand.com/api/v1/marker/?huntarea_id={}
```

or environment variable:

```powershell
$env:HUNTSTAND_ASSET_ENDPOINTS = "mineral:https://app.huntstand.com/api/v1/mineral/?huntarea_id={},marker:https://app.huntstand.com/api/v1/marker/?huntarea_id={}" 
```

Normalization columns:

| Column | Description |
|--------|-------------|
| huntarea_id | Hunt area identifier |
| huntarea_name | Name |
| asset_type | Candidate type label |
| asset_id | `id` / `asset_id` / `uuid` |
| name | `name` / `title` / `label` / device-specific fallback |
| subtype | `type` / `subtype` / `category` |
| latitude / longitude | `lat`/`lon` or nested `location` dict |
| created / updated | `created` / `date_created` / `modified` / `updated` / `last_updated` |
| last_activity | `last_activity` / `last_image` / `last_check_in` / `last_seen` |
| owner_email | nested `owner`/`user`/`profile` email or username |
| visibility | boolean `public` mapped to public/private or fallback `shared` |

Endpoints returning errors/unusable JSON are skipped with DEBUG logs; processing continues.

## CLI Options (`huntstand-exporter`)

```text
--cookies-file <path>      JSON file with sessionid/csrftoken
--profile-id <id>          Fallback profile ID for hunt areas if /myprofile/ empty
--per-hunt                 Also write per-hunt CSV files (timestamped directory)
--no-login-fallback        Require cookies; do not attempt login fallback
--dry-run                  Show planned outputs; skip network and file writes
--output-dir <dir>         Base directory for outputs (default: exports/)
--format {all,csv,json}    Select outputs: all (default), csv, or json
--include-assets           Fetch assets and write assets CSV
--dynamic-assets           Probe asset endpoints with first hunt area; keep only usable responses
--assets-extra <specs>     Additional asset endpoint specs `type:urlTemplate` (space separated)
--parallel                 Enable parallel per-huntarea fetch
--parallel-workers <int>   Worker threads for parallel fetch (default 4)
--log-json                 Emit structured JSON log lines
```

Behavior details:

- `--dry-run` lists planned timestamped output paths then exits (no network/file I/O).
- Timestamping is unconditional (always appended).
- `--format=csv` → detailed + matrix (+ per-hunt if `--per-hunt`).
- `--format=json` → JSON summary only.
- `--format=all` → all CSV + JSON.
- Parallel mode clones the session per thread for safety.

## Output Files

| File Pattern | Description |
|--------------|-------------|
| `huntstand_members_detailed_<ts>.csv` | One row per member, invite, request |
| `huntstand_membership_matrix_<ts>.csv` | Email vs hunt area status (Active / Invited / Requested / No) |
| `huntstand_summary_<ts>.json` | Aggregated metadata + samples per hunt area |
| `huntstand_per_hunt_csvs_<ts>/` | Optional per-area breakdown (one CSV per hunt area) |
| `huntstand_assets_detailed_<ts>.csv` | Asset rows (stands, cameras, trailcams, blinds, feeders, foodplots, waypoints, trails, extras) when `--include-assets` |

Example (format=all + per-hunt):

```text
exports/
  huntstand_members_detailed_20250101_123045.csv
  huntstand_membership_matrix_20250101_123045.csv
  huntstand_summary_20250101_123045.json
  huntstand_per_hunt_csvs_20250101_123045/
    hunt_<id>_<sanitized_name>.csv
  huntstand_assets_detailed_20250101_123045.csv
```

Custom `--output-dir mydata` relocates these under `mydata/`.

## Development Setup

```powershell
pip install -e ".[dev]"
$env:HUNTSTAND_LOG_LEVEL = "DEBUG"
huntstand-exporter --per-hunt
ruff check src/ tests/
ruff format src/ tests/
mypy src/huntstand_exporter/
```

## Running Tests

```powershell
pytest -v
pytest --cov=huntstand_exporter --cov-report=term-missing
```

## Environment Variables Template

```env
HUNTSTAND_SESSIONID=
HUNTSTAND_CSRFTOKEN=
HUNTSTAND_USER=
HUNTSTAND_PASS=
HUNTSTAND_LOG_LEVEL=INFO
```

## Responsible Use

Interact responsibly with HuntStand's private web APIs:

- Only access data you are authorized to view.
- Respect HuntStand Terms of Service.
- Avoid high-frequency automated polling.
- Never publish real cookies or personal member data.

## Contributing Guidelines

See `docs/CONTRIBUTING.md` for guidelines.

## Deprecations & Removals

- Removed legacy wrapper script `huntstand.py` (use `huntstand-exporter`).
- Removed deprecated flags: `--timestamped`, `--outfile-csv`, `--outfile-json`, `--outfile-matrix`.
- Added bulk `huntstand-add-members` (0.3.0), verification (0.3.1), asset export & parallel/dynamic assets (0.3.3).

## Roadmap Ideas

- Optional output to SQLite
- Rich geodata export (polylines / polygons) beyond current point assets
- Caching dynamic asset refinement results between runs
- Rate limiting / polite adaptive backoff

---

**Maintained with a defensive, continue-on-error philosophy to maximize partial data extraction.**
