# Financial Market Report

Internal market-report application for generating and emailing a daily HTML summary of financial market activity.

The current implementation is being migrated from the legacy notebook in the project root. The report runner now has an importable Python package and CLI entry point. The target implementation will run as a containerized internal web app, store report settings in local storage, and read credentials from Vault.

## Local Layout

- `config/` stores non-secret defaults that can be committed.
- `data/` stores local SQLite data and is ignored by Git.
- `reports/` stores generated HTML reports and is ignored by Git.
- `logs/` stores runtime logs and is ignored by Git.
- `secrets/` is for local bootstrap files only and is ignored by Git.
- `src/financial_market_report/` will contain the application code.
- `notebooks/legacy/` is reserved for the sanitized notebook reference.

## Secrets

Do not commit API keys, Gmail app passwords, Vault tokens, or generated reports.

The planned runtime secret source is Vault at `VAULT_SECRET_PATH`. `.env.example` documents the variable names only.
For local Vault development, see [docs/vault.md](docs/vault.md).

## CLI

The extracted runner exposes a command:

```bash
financial-market-report run --no-email
```

For local development:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
APP_SECRETS_DIR=secrets scripts/run_report.sh --no-email --no-news --no-plots
```

Inspect the local run database:

```bash
financial-market-report runs
```

Check whether secrets are available without printing their values:

```bash
financial-market-report secrets-status --include-email
```

Start the internal web app:

```bash
financial-market-report serve --host 0.0.0.0 --port 8080
```

Required runtime secrets are read from environment variables or mounted files under `/run/secrets`:

- `FMP_API_KEY`
- `NEWS_API_KEY` when news is enabled
- `SENDER_EMAIL`, `TARGET_EMAIL`, and `GMAIL_APP_PASSWORD` when email sending is enabled

By default, run metadata is stored in `data/financial_market_report.sqlite3`.
