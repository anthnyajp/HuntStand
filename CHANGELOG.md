# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Planned: SQLite output option
- Planned: Rich geodata export (polylines / polygons) beyond basic stands/cameras
- Planned: Parallel fetch for large hunt area counts
- Planned: Warning when SSL fallback used (enhanced message with mitigation tips)
- Planned: Rate limiting / polite backoff for large hunts

## [0.3.2] - 2025-10-30

### Added (0.3.2 Assets Export)

### Added (Assets Export)

- New `--include-assets` flag for `huntstand-exporter` to collect stands/cameras (and future generic assets) per hunt area.
- Writes `huntstand_assets_detailed_<ts>.csv` with columns: `huntarea_id,huntarea_name,asset_type,asset_id,name,subtype,latitude,longitude,created,updated,last_activity,owner_email,visibility`.
- JSON summary now includes `counts.assets` and `assets_sample` when assets are fetched.
- Defensive multi-endpoint probing (`/api/v1/stand/?huntarea_id=`, `/api/v1/camera/?huntarea_id=`, fallback `/api/v1/asset/?huntarea_id=`) — failures logged at DEBUG and skipped without aborting export.
- Normalization handles varied key naming (lat/lon vs location dict, name/title/label, public/shared flags).

### Tests

- Added `tests/test_assets.py` covering normalization logic and safe ID rejection.

### Documentation Update

- README updated with new flag and output file description.

### Version

- Project version bumped to 0.3.2.

## [0.3.1] - 2025-10-30

### Added (Verification)

- New `--verify-results` flag for `huntstand-add-members` to validate that member additions were successful.
- Verification fetches current members/invites from hunt areas and compares against expected additions.
- Timestamped verification report CSV `members_verification_<ts>.csv` with status: verified/missing/role_mismatch/error/skipped.
- Exit code 1 if verification finds any issues (missing members, role mismatches, or errors).

## [0.3.0] - 2025-10-28

### Added (Members Import Feature)

- New `huntstand-add-members` command for bulk adding/inviting emails to hunt areas using CSV input files (members/admin/view_only/huntareas).
- Dry-run mode for new command showing planned operations without network calls.
- Timestamped results CSV `members_added_results_<ts>.csv` summarizing status codes and truncated responses.

### Changed (Version)

- Project version bumped to 0.3.0 for feature addition.

### Security / Guidance (Auth)

- Reiterated cookie-first authentication pattern for new command; login fallback remains optional and potentially flaky.

## [0.2.0] - 2025-10-28

### Removed

- Legacy wrapper script `huntstand.py` (replaced fully by console entry point `huntstand-exporter`).
- Deprecated flags: `--timestamped`, `--outfile-csv`, `--outfile-json`, `--outfile-matrix`.

### Changed (Behavior)

- Mandatory timestamped output policy documented (already enforced in 0.1.x, flags now removed).
- Simplified CLI surface; clearer help texts.

### Added (Docs)

- Documentation updates reflecting removals.

### Security (Guidance)

- Reinforced guidance to prefer cookie-based auth.

## [0.1.0] - 2025-10-27

### Added

- Initial public release of HuntStand Membership Exporter.
- Core exporter logic (`exporter.py`) with cookie-first authentication and login fallback.
- CSV outputs (detailed, per-hunt optional, membership matrix) and JSON summary.
- Defensive normalization helpers `as_dict` and `json_or_list_to_objects`.
- Retry logic and TLS handling with certifi fallback.
- Console script entry point `huntstand-exporter` via `pyproject.toml`.
- Basic test coverage for normalization and membership matrix generation.

### Changed

- Deprecated legacy `huntstand.py` script retained as thin wrapper.

### Security

- Encourages cookie-first authentication; warns when TLS verification disabled.

[0.1.0]: https://github.com/anthnyajp/HuntStand/releases/tag/v0.1.0
[0.2.0]: https://github.com/anthnyajp/HuntStand/releases/tag/v0.2.0
