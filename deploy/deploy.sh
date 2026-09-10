#!/usr/bin/env bash
# Idempotent Mimic42 rollout on the VPS: deploy.sh <image-tag>.
#
# - Atomically writes IMAGE_TAG into .env (compose-level variables only;
#   secrets live in api.env and are never touched here).
# - Pulls images, recreates containers, waits for both healthchecks (180s).
# - On failure dumps logs and rolls back to the previous tag automatically.
# - Appends every attempted tag to releases.log (source for manual rollback).
# - Prunes project images older than a week.
#
# Delivered to the server by scp on every deploy run (infrastructure as
# code); safe to re-run with the same tag.
set -euo pipefail

TAG="${1:?usage: deploy.sh <image-tag>}"
COMPOSE="docker compose -f docker-compose.yml"
HEALTH_TIMEOUT=180

log() {
  echo "[deploy $(date -u +%FT%TZ)] $*"
}

previous_tag() {
  grep -E '^IMAGE_TAG=' .env 2>/dev/null | cut -d= -f2- || true
}

write_tag() {
  local tag="$1" tmp
  tmp="$(mktemp .env.XXXXXX)"
  grep -v -E '^IMAGE_TAG=' .env 2>/dev/null > "$tmp" || true
  printf 'IMAGE_TAG=%s\n' "$tag" >> "$tmp"
  mv "$tmp" .env
}

wait_healthy() {
  local elapsed=0
  while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
    if $COMPOSE ps --format json | python3 -c "
import json, sys
raw = sys.stdin.read().strip()
try:
    docs = json.loads(raw)
except ValueError:
    docs = None
if docs is None:
    # compose v5 prints one JSON object per line
    docs = [json.loads(line) for line in raw.splitlines() if line.strip()]
elif isinstance(docs, dict):
    docs = [docs]
services = docs if isinstance(docs, list) else []
names = {svc.get('Name', '') for svc in services}
healthy = {svc.get('Name', '') for svc in services if svc.get('Health') == 'healthy'}
if not {'mimic42-api', 'mimic42-web'} <= healthy:
    sys.exit(1)
"; then
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  return 1
}

rollback() {
  local tag="$1"
  log "ROLLBACK to ${tag}"
  write_tag "$tag"
  $COMPOSE pull api web
  $COMPOSE up -d --remove-orphans
}

main() {
  cd "$(dirname "$0")"
  local prev
  prev="$(previous_tag)"

  log "deploying tag ${TAG} (previous: ${prev:-none})"
  echo "$(date -u +%FT%TZ) ${TAG}" >> releases.log

  write_tag "$TAG"
  $COMPOSE pull api web
  $COMPOSE up -d --remove-orphans

  if wait_healthy; then
    log "healthy: api + web"
  else
    log "healthcheck FAILED after ${HEALTH_TIMEOUT}s, dumping logs"
    $COMPOSE logs --tail=100 api web || true
    if [ -n "$prev" ] && [ "$prev" != "$TAG" ]; then
      rollback "$prev"
      if wait_healthy; then
        log "rollback to ${prev} healthy"
      else
        log "rollback to ${prev} NOT healthy, needs manual intervention"
      fi
    fi
    exit 1
  fi

  log "pruning our images older than 7 days (neighbors untouched)"
  docker image prune -a --force --filter "until=168h" --filter "reference=ghcr.io/42-z/mimic42-*" || true
  log "done"
}

main "$@"
