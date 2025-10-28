# HuntStand Data Exporter - AI Coding Instructions

## Project Overview
This is a **web scraping and data extraction tool** for the HuntStand hunting club management platform. The primary implementation lives in `src/huntstand_exporter/exporter.py` and is exposed via the console command `huntstand-exporter`. It authenticates with HuntStand's web API and exports membership data across multiple hunt areas into structured CSV and JSON formats.

## Architecture & Data Flow
- **Package-based CLI application** (`huntstand_exporter`) with sophisticated session management
- **Cookie-first authentication** (sessionid + csrftoken) with username/password fallback
- **Multi-endpoint data aggregation**: Fetches from `/api/v1/myprofile/`, `/api/v1/clubmember/`, `/api/v1/membershipemailinvite/`, and `/api/v1/membershiprequest/`
- **Resilient HTTP handling**: Built-in retries, SSL fallbacks, and graceful error handling
- **Multiple output formats**: Detailed CSV, membership matrix, JSON summary, and optional per-hunt CSVs

## Authentication Patterns
The application uses a **layered authentication approach**:
1. **Primary**: Environment variables `HUNTSTAND_SESSIONID` and `HUNTSTAND_CSRFTOKEN`
2. **Alternative**: JSON cookies file via `--cookies-file cookies.json`
3. **Fallback**: Username/password login (tries both `login` and `username` fields due to HuntStand API inconsistencies)

**Critical**: Always use session cookies when possible - the login endpoint is documented as "flaky" in the code.

## Key Development Patterns

### HTTP Session Management
```python
# Standard pattern for API calls with retries and SSL handling
session = make_session_with_retries(total_retries=3, backoff=0.3)
set_ca_bundle(session)  # Uses certifi, falls back to system CA
```

### Data Normalization
```python
# Defensive programming pattern used throughout
def as_dict(obj: Any) -> Dict[str, Any]:
    return obj if isinstance(obj, dict) else {}

# API responses vary - normalize to list of objects
def json_or_list_to_objects(payload: Any) -> List[Dict[str, Any]]:
    # Handles both direct lists and {"objects": [...]} wrappers
```

### Error Handling Philosophy
- **Continue on individual failures**: Log errors but don't stop processing other hunt areas
- **SSL flexibility**: Automatically retry with `verify=False` if SSL verification fails
- **Graceful degradation**: Missing fields default to empty strings rather than causing crashes

## Output File Structure
All output filenames are timestamped (`_<YYYYMMDD_HHMMSS>` suffix) and placed under `exports/` (or `--output-dir`).

- `huntstand_members_detailed_<ts>.csv`: One row per person across all hunt areas
- `huntstand_membership_matrix_<ts>.csv`: Email-to-hunt-area matrix with Yes/No/Invited/Requested status
- `huntstand_summary_<ts>.json`: Complete API responses with metadata and sample data
- `huntstand_per_hunt_csvs_<ts>/`: Individual CSV files per hunt area (optional)

## External Dependencies
The project includes **browser capture files** (PowerShell, cURL, fetch) showing real authentication patterns:
- `huntstand_chrome_copy_as_powershell.txt`: Shows cookie structure and headers
- `HuntStand.postman_collection.json`: Complete API collection with authentication flows
- `huntstand_chrome_*_urls.txt`: Endpoint discovery data

## Development Workflow
1. **Authentication setup**: Use browser dev tools to extract `sessionid` and `csrftoken` cookies
2. **Environment variables**: Set `HUNTSTAND_SESSIONID` and `HUNTSTAND_CSRFTOKEN`
3. **Run with logging**: `HUNTSTAND_LOG_LEVEL=DEBUG huntstand-exporter`
4. **Test outputs**: Verify CSV structure matches expected membership data

## Debugging & Testing
- **Verbose logging**: Set `HUNTSTAND_LOG_LEVEL=DEBUG` to see API request/response details
- **SSL issues**: The application automatically falls back to `verify=False` with warnings
- **API inconsistencies**: Hunt area data structure varies - the code normalizes different response formats
- **Missing data**: Empty names/emails are handled gracefully in CSV output

## Key Files to Understand
- `src/huntstand_exporter/exporter.py`: Complete application logic with extensive inline documentation
- `requirements.txt`: Minimal dependencies (requests, certifi, python-dotenv, urllib3)
- `huntstand_summary.json`: Example of actual API response structure
- `huntstand_members_detailed.csv`: Example output format

When modifying this codebase, maintain the **defensive programming patterns** and **continue-on-error philosophy** that allows the tool to extract partial data even when some hunt areas fail to load.