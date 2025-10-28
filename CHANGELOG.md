# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Planned: --dry-run flag
- Planned: Structured JSON logging option
- Planned: Additional tests for fallback/error paths

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
