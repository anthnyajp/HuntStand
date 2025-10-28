# Contributing

Thanks for your interest in improving the HuntStand Membership Exporter!

## Development Setup

```powershell
git clone https://github.com/anthnyajp/HuntStand.git
cd HuntStand
python -m venv .venv
./.venv/Scripts/Activate.ps1
pip install -e ".[dev]"
```

This installs the package in editable mode with dev dependencies (pytest, ruff, mypy).

## Project Structure

```text
huntstand-exporter/
├── src/
│   └── huntstand_exporter/
│       ├── __init__.py       # Package exports
│       ├── __main__.py       # CLI entry point
│       └── exporter.py       # Main logic
├── tests/
│   ├── __init__.py
│   └── test_normalize.py     # Unit tests
├── .github/
│   └── workflows/
│       └── ci.yml            # GitHub Actions CI
├── pyproject.toml            # Package metadata & dependencies
├── ruff.toml                 # Linter configuration
├── mypy.ini                  # Type checker configuration
└── README.md
```

## Running

```powershell
$env:HUNTSTAND_SESSIONID = "..."
$env:HUNTSTAND_CSRFTOKEN = "..."
huntstand-exporter --per-hunt
```

## Testing

```powershell
# Run all tests
pytest -v

# Run with coverage
pytest --cov=huntstand_exporter --cov-report=html

# Run specific test file
pytest tests/test_normalize.py -v
```

Add tests under `tests/` for new behaviors. Favor small, deterministic unit tests.

## Code Quality

### Linting

```powershell
# Check code style
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/
```

### Type Checking

```powershell
# Run type checker
mypy src/huntstand_exporter/
```

### Pre-commit Checks

Before committing, run:

```powershell
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/huntstand_exporter/
pytest -v
```

## Code Style & Patterns

- Maintain defensive helpers: `as_dict`, `json_or_list_to_objects`.
- Continue-on-error: log and move on; never crash entire export for a single area.
- Avoid printing secrets (cookies, raw auth headers).
- Keep functions small and focused; add docstrings for new public helpers.
- Follow PEP 8 style (enforced by ruff).
- Add type hints where practical (checked by mypy).

## Security & Privacy

- Do NOT commit real cookies, member PII, or generated CSV/JSON outputs.
- Respect HuntStand Terms of Service.
- Minimize request rate; batching / caching acceptable.

## Issues & Feature Requests

Open a GitHub Issue with:

- Description
- Steps to reproduce (if bug)
- Sample sanitized logs (`HUNTSTAND_LOG_LEVEL=DEBUG`)
- Proposed solution outline (if enhancement)

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run quality checks (lint, type check, tests)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Release Process (Manual for now)

1. Update version in `pyproject.toml` and `src/huntstand_exporter/__init__.py`.
2. Update CHANGELOG (if exists) with release notes.
3. Commit: `git commit -m "Release vX.Y.Z"`.
4. Tag: `git tag vX.Y.Z && git push --tags`.
5. Draft GitHub Release with changelog.
6. (Optional) Build and publish to PyPI.

## Roadmap Guidelines

Keep scope narrow: membership export and related metadata. Larger API surface additions should include clear normalization strategy.

## License

Contributions are under MIT License.
