#!/usr/bin/env bash
set -euo pipefail
: "${DEPLOY_HOST:?Set DEPLOY_HOST to the SSH target}"
ssh "$DEPLOY_HOST" bash -s <<'REMOTE'
set -euo pipefail
base=/srv/insight-studio
test -f "$base/previous-release"
previous="$(cat "$base/previous-release")"
case "$previous" in "$base"/releases/*) ;; *) exit 1 ;; esac
test -x "$previous/.venv/bin/uvicorn"
if [[ ! -f "$previous/backend/BUDGET_GUARD_VERSION" ]]; then
  printf 'Refusing rollback: the target predates durable model billing.\n' >&2
  exit 1
fi
if [[ ! -f "$previous/backend/ACCOUNT_SCHEMA_VERSION" ]]; then
  printf 'Refusing rollback: the target lacks account ownership and per-user quotas. A legacy recovery requires a consistent pre-migration data restore, not a code-only rollback.\n' >&2
  exit 1
fi
current="$(readlink -f "$base/current")"
ln -sfn "$previous" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
printf '%s\n' "$current" > "$base/previous-release"
systemctl restart insight-studio
sleep 3
curl -fsS http://127.0.0.1:8108/api/health
printf '\nRolled back to %s\n' "$previous"
REMOTE
