# TLDR-The-World

## Overview

TLDR-The-World is a Python 3.11 pipeline that collects RSS feeds, filters and
summarizes them with GitHub Models, and delivers the briefing through Telegram.

## Local Checks

Use the project virtual environment and run the same checks that CI uses:

```bash
python -m black --check .
python -m isort --check-only .
python -m flake8
python -m pylint src/ config/ tests/
pyright
python -m pytest -q
```

## Pylint

The repository includes a `.pylintrc` file that:

- adds the project root to `sys.path` so imports under `src/` and `config/` resolve correctly
- disables `missing-docstring`, `line-too-long`, and `protected-access` for this codebase
- aligns the line length with the formatter settings

If you run pylint manually, execute it from the repository root so it picks up
the bundled configuration automatically.
