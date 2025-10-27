# HuntStand Membership Exporter

A CLI tool that exports HuntStand hunt area membership data (active members, invites, join requests) into structured CSV and JSON files.

## Features

- Cookie-first authentication (recommended) using `sessionid` and `csrftoken`.
- Fallback username/password login (less reliable — uses both `login` and `username` keys).
- Robust retry logic for transient HTTP failures.
- TLS verification with `certifi` and auto fallback to `verify=False` (with warning) if SSL errors occur.
- Normalization of inconsistent API shapes (lists, `{objects: [...]}` wrappers, or dict maps).
- Generates:
  - Detailed CSV (`huntstand_members_detailed.csv`)
  - Membership matrix CSV (`huntstand_membership_matrix.csv`)
  - JSON summary (`huntstand_summary.json`)
  - Optional per-hunt CSVs (`huntstand_per_hunt_csvs/`)

## Quick Start

```powershell
# 1. Clone
git clone https://github.com/YOUR_USERNAME/huntstand-exporter.git
cd huntstand-exporter

# 2. (Optional) create virtual environment
python -m venv .venv
./.venv/Scripts/Activate.ps1

# 3. Install (editable for development)
pip install -e .

# 4. Set authentication cookies (preferred)
$env:HUNTSTAND_SESSIONID = "<sessionid_from_browser>"
$env:HUNTSTAND_CSRFTOKEN = "<csrftoken_from_browser>"

# 5. Run exporter
huntstand-exporter --per-hunt
```

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

Run with: `python huntstand.py --cookies-file cookies.json`

## Fallback Login

If cookies are not available:

```powershell
$env:HUNTSTAND_USER = "you@example.com"
$env:HUNTSTAND_PASS = "hunter2"
python huntstand.py
```

The script will attempt both `login` and `username` fields; this endpoint can be flaky.

## CLI Options

```text
--cookies-file <path>     # JSON file with sessionid/csrftoken
--profile-id <id>         # Fallback profile ID for hunt areas if /myprofile/ empty
--outfile-csv <path>      # Detailed CSV output path
--outfile-json <path>     # JSON summary output path
--outfile-matrix <path>   # Membership matrix CSV path
--per-hunt                # Also write per-hunt CSV files
--no-login-fallback       # Require cookies, do not attempt login
```

## Output Files

| File | Description |
|------|-------------|
| `huntstand_members_detailed.csv` | One row per active member, invite, request |
| `huntstand_membership_matrix.csv` | Email vs hunt area status (Active/Invited/Requested/No) |
| `huntstand_summary.json` | Aggregated metadata + samples per hunt area |
| `huntstand_per_hunt_csvs/` | Optional per-area breakdown |

## Development

```powershell
# Install with dev dependencies
pip install -e ".[dev]"

# Run with debug logging
$env:HUNTSTAND_LOG_LEVEL = "DEBUG"
huntstand-exporter --per-hunt

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

# Run with coverage
pytest --cov=huntstand_exporter --cov-report=html
```

## Environment Template

See `.env.example` for suggested variables. Never commit real cookie/session values.

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

## Roadmap Ideas

- Optional output to SQLite
- Add export for asset/geodata endpoints
- Parallelization for large club counts

---
Maintained with a defensive, continue-on-error philosophy to maximize partial data extraction.
