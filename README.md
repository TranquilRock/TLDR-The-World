# TLDR-The-World

[![codecov](https://codecov.io/gh/TranquilRock/TLDR-The-World/branch/HEAD/graph/badge.svg)](https://codecov.io/gh/TranquilRock/TLDR-The-World)

## Overview

TLDR-The-World is a Python 3.11 pipeline that collects RSS feeds, filters and
summarizes them with GitHub Models, and delivers the briefing through Telegram.

The pipeline is designed to stay lightweight and readable:

- RSS feeds are fetched concurrently and capped per source before LLM processing.
- Feed items are summarised in two passes to avoid token limit issues.
- Final briefings include both source attribution and original-link citations.
- Telegram delivery uses structured MarkdownV2 rendering so the final message
 stays readable without breaking entity parsing.

## Configuration

The application reads configuration from environment variables. For GitHub
Actions, use repository secrets for sensitive values and repository variables
for non-sensitive defaults.

Required secrets:

- `MODELS_API_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional repository variables:

- `MODELS_BASE_URL` with default `https://models.inference.ai.azure.com`
- `LLM_MODEL` with default `gpt-4o-mini`
- `MODELS_MIN_INTERVAL_SECONDS` with default `4.5`
- `RSS_MAX_ITEMS_PER_SOURCE` with default `8`
- `RSS_MAX_AGE_HOURS` with default `48` (discard feed items older than this)

Rate-limit & retry settings (optional):

- `GITHUB_MODELS_RETRY_MAX_ATTEMPTS` — default `3`
- `GITHUB_MODELS_RETRY_BACKOFF_BASE_SECONDS` — default `0.5`
- `GITHUB_MODELS_RETRY_BACKOFF_MAX_SECONDS` — default `8.0`

These correspond to the `github_models_retry_*` settings in the application
configuration and control the capped exponential backoff when the Models API
returns rate-limit responses (HTTP 429). In CI/Action runners you can reduce
the base backoff for faster retries or increase attempts if you observe
transient 429s.

For local development, place the same values in your shell environment or a
`.env` file.

## Run Locally

```bash
source .venv/bin/activate
python -m src.main
```

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

## GitHub Actions

The daily workflow lives in [`.github/workflows/daily_briefing.yml`](.github/workflows/daily_briefing.yml).
It reads the required secrets above and applies repository-variable defaults for
the non-sensitive configuration values.

Post-merge checklist
---------------------

- After merging a PR, verify the CI run for the branch completed successfully and
 that `coverage.xml` was produced (artifact `coverage-xml` is uploaded).
- Visit the Codecov project page (the badge links there) to confirm the report
 for the branch/HEAD is visible.
- For private repositories: if Codecov uploads fail, add `CODECOV_TOKEN` to
 repository Secrets (Settings → Secrets) and re-run the workflow. Only enable
 the token for trusted workflows and avoid exposing it in logs.

## Pylint

The repository includes a `.pylintrc` file that:

- adds the project root to `sys.path` so imports under `src/` and `config/` resolve correctly
- disables `missing-docstring`, `line-too-long`, and `protected-access` for this codebase
- aligns the line length with the formatter settings

If you run pylint manually, execute it from the repository root so it picks up
the bundled configuration automatically.
