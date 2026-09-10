# Mimic42 production deployment (VPS, Docker, Caddy)

Single domain `https://mimic42.zomb.top`: Caddy proxies `/` to the `web`
container and `/api/v1/*` to the `api` container. Images are built by GitHub
Actions on every push to `main` and pulled from `ghcr.io` — nothing is
built on the server.

## First-time server setup (once)

```bash
DEPLOY=/root/sites/mimic42
mkdir -p "$DEPLOY"
cd "$DEPLOY"

# 1. Backend secrets in /etc/mimic42.env — mode 600, never committed,
#    never transferred over the network by the pipeline.
#    Values: same keys as the local .env, but PRODUCTION ones.
#    SECRET_KEY must match the key that encrypted the stored Telethon
#    sessions, otherwise no agent resumes after a restart.
#    DATABASE_CONNECTION_STRING uses the asyncpg driver:
#      postgresql+asyncpg://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres
cat > /etc/mimic42.env <<'EOF'
SUPABASE_URL=
DATABASE_CONNECTION_STRING=
MEM0_API_KEY=
OPENROUTER_API_KEY=
SECRET_KEY=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
CORS_ALLOW_ORIGINS=https://mimic42.zomb.top
EOF
chmod 600 /etc/mimic42.env

# 2. Compose-level variables (no secrets here).
cat > .env <<'EOF'
IMAGE_TAG=latest
API_PORT=8100
WEB_PORT=8101
EOF

# 3. Copy deploy/docker-compose.yml and deploy/deploy.sh from the repo
#    into this directory (later deploys refresh them via scp automatically).

# 4. Supabase schema (only when migrations changed):
#      supabase db push
#    Migrations are applied manually on purpose — the pipeline never migrates.

# 5. Register the domain in Caddy: append deploy/Caddyfile.snippet to
#    /etc/caddy/Caddyfile, then:
systemctl reload caddy
```
Prerequisite: the host Caddyfile must define the `(common)` snippet used
by `import common` (it does on the current VPS — verify before reload,
a bad Caddyfile takes down every site: `caddy validate --config
/etc/caddy/Caddyfile --adapter caddyfile`).

## How deploys work

Push to `main` → `deploy.yml` builds `mimic42-api` + `mimic42-web`,
pushes `ghcr.io/42-z/mimic42-{api,web}:<sha>` (+ `latest`), then SSHes to
the server, refreshes the compose files + `deploy.sh` via scp, and runs
`bash deploy.sh <sha>`. The script waits for both healthchecks (180 s) and
rolls back to the previous tag automatically on failure. Every attempted
tag is appended to `releases.log`.

Manual rollback: pick a tag from `releases.log` and either re-run
`bash deploy.sh <tag>` or trigger the `rollback.yml` workflow.

## Smoke test after deploy

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://mimic42.zomb.top/login
# → 200 (from Next, not from FastAPI)
curl -s -o /dev/null -w '%{http_code}\n' https://mimic42.zomb.top/api/v1/agents
# → 401/403 without a token (backend is reachable through Caddy)
```

Open the site, log in, check that the agent list loads.

## Troubleshooting

- `docker compose ps` — container + health status; `docker compose logs --tail=100 api web`.
- Agents stay STOPPED after restart with restore errors in `api` logs:
  `SECRET_KEY` in `/etc/mimic42.env` does not match the encryption key — fix the
  value and `docker compose up -d` again.
- `.session` files appearing inside the api container
  (`docker exec mimic42-api ls -la /app/data`): some path bypasses the
  database session storage and needs a volume — investigate before adding one.
- Ports 8100/8101 taken: override with `API_PORT`/`WEB_PORT` in `.env`
  and update `Caddyfile.snippet` accordingly.
