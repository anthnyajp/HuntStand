# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Planned: SQLite output option
- Planned: Geodata/asset export endpoints
- Planned: Parallel fetch for large hunt area counts
- Planned: Warning when SSL fallback used (enhanced message with mitigation tips)
- Planned: Rate limiting / polite backoff for large hunts

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
