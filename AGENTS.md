# Repository Guidelines

## Project Structure & Module Organization

Root-level `NostalgiaForInfinityX*.py` files implement Freqtrade strategies; `NostalgiaForInfinityX8.py` is the current default. Older strategies live in `legacy/`. Exchange settings, pairlists, and blacklists are in `configs/`. Tests are split into `tests/unit/`, `tests/tools/`, and `tests/backtests/`, with shared fixtures in `conftest.py` files. Utilities live in `tools/`; Docker definitions live in `docker/` and the Compose files. Documentation and visual assets are under `docs/` and `docs/assets/`. Local market data, logs, and results belong in `user_data/`.

## Build, Test, and Development Commands

Use Python 3.12 or newer. See `docs/installation-and-setup.md` for Freqtrade and TA-Lib prerequisites.

- `python -m pip install -r tests/requirements.txt pre-commit`: install test dependencies and contributor tooling in a virtual environment.
- `python -m pytest tests/unit tests/tools --junitxml=artifacts/unit-report.xml`: run the suites used by unit-test CI; `pytest.ini` enables parallel execution.
- `pre-commit run --all-files`: run Ruff linting/formatting and repository hygiene checks.
- `docker compose -f docker-compose.tests.yml run --rm --build backtesting`: build the test image and backtest with configured market data. Set `EXCHANGE`, `TRADING_MODE`, and `TIMERANGE` as needed.
- `freqtrade trade --config user_data/config.json --strategy-path . --strategy NostalgiaForInfinityX8 --dry-run`: run locally with your configuration.

## Coding Style & Naming Conventions

Follow `.editorconfig` and `pyproject.toml`: two-space indentation, LF endings, double-quoted Python strings, and a 119-character line limit. Ruff runs through pre-commit. Use `snake_case` for functions and variables, preserve strategy class/file names, and follow existing signal numbering and indicator naming.

## Testing Guidelines

Use pytest, pytest-mock, and pytest-xdist. Name files `test_*.py` and functions `test_*`; follow patterns such as `test_NFIX8_<behavior>.py`. Add focused regression tests for strategy behavior changes and reuse fixtures. No numeric coverage threshold is configured. Trading changes should include comparable backtests with the same exchange, mode, pairlist, and timerange.

## Commit & Pull Request Guidelines

Use concise, scoped subjects matching history, such as `X8: signal 562: add protection.` or `blacklist: ...`. Keep commits focused. PR descriptions should explain the behavior change, identify affected strategies/signals, link relevant issues, and report checks run. Include backtest comparisons for trading changes.

## Security & Configuration

Keep credentials in ignored `.env` or private configuration files. Exclude downloaded candles, databases, logs, and generated results from commits. Validate with dry runs; preserve the required `5m` timeframe and documented exit settings.
