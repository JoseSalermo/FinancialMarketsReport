# Vault Integration

This app is a Vault client. The shared Vault server belongs in the separate `HomelabInfra` repo:

```text
git@github.com:JoseSalermo/HomelabInfra.git
```

## Runtime Settings

The app expects these local environment values, usually from `.env`:

```env
VAULT_ADDR=http://vault:8200
VAULT_TOKEN=<financial-market-report app token>
VAULT_SECRET_PATH=secret/data/financial-market-report
```

The app container joins the external Docker network named `homelab`, so it can reach the shared Vault container by hostname `vault`.

## Verify

After Vault is running, unsealed, and loaded with the app secrets:

```bash
docker compose up -d financial-market-report
docker compose exec -T financial-market-report financial-market-report secrets-status --include-email
```

The app reads from Vault first. If Vault is unavailable or not configured, it falls back to environment variables and mounted files under `secrets/`.
