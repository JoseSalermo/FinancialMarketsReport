# Vault Development Setup

This project can read report secrets from HashiCorp Vault.

The included Compose file starts Vault in dev mode for local learning. Dev mode starts initialized and unsealed, mounts KV v2 at `secret/`, and stores data in memory. Secrets disappear when the container is recreated.

Do not use dev mode as the final QNAP storage model.

## Start Dev Vault

```bash
docker compose -f docker-compose.vault.dev.yml up -d
```

Vault UI:

```text
http://localhost:8200
```

Development root token:

```text
dev-only-token
```

## Write App Secrets

```bash
docker compose -f docker-compose.vault.dev.yml exec vault \
  vault kv put secret/financial-market-report \
  FMP_API_KEY="..." \
  NEWS_API_KEY="..." \
  SENDER_EMAIL="..." \
  TARGET_EMAIL="..." \
  GMAIL_APP_PASSWORD="..."
```

## Point The App At Vault

```bash
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=dev-only-token
export VAULT_SECRET_PATH=secret/data/financial-market-report
```

Check status without printing values:

```bash
.venv/bin/financial-market-report secrets-status --include-email
```

Run the report:

```bash
scripts/run_report.sh --no-email --no-news --no-plots
```

## Notes

- `VAULT_SECRET_PATH=secret/data/financial-market-report` uses Vault KV v2 API-style addressing.
- The app also accepts `secret/financial-market-report`.
- If Vault is not configured or a Vault lookup fails, the app falls back to environment variables and local mounted secret files.
- The current local fallback directory is `secrets/`, controlled by `APP_SECRETS_DIR`.
