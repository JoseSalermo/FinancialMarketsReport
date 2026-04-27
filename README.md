# Financial Market Report

Internal market-report application for generating and emailing a daily HTML summary of financial market activity.

The current implementation is still based on the legacy notebook in the project root. The target implementation will move the report logic into importable Python modules, run as a containerized internal web app, store report settings in local storage, and read credentials from Vault.

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
