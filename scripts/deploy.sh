#!/usr/bin/env bash
# Native Linux deployment to an explicitly selected, dedicated application host.
set -euo pipefail
umask 077
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
: "${DEPLOY_HOST:?Set DEPLOY_HOST to an SSH target with root privileges}"
: "${SITE_URL:?Set SITE_URL to https://your.domain.example}"
if [[ "$DEPLOY_HOST" == -* || "$DEPLOY_HOST" =~ [[:space:]] ]]; then
  echo "DEPLOY_HOST must be a single SSH host or user@host." >&2
  exit 1
fi
cd "$PROJECT_DIR"
SITE_URL="$(python3 deploy/render-caddy.py --site-url "$SITE_URL" --print-url)"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ "${1:-}" != "--skip-build" ]]; then
  (cd frontend && npm ci && npm run build)
fi
test -f frontend/dist/index.html
test -f backend/app/main.py
mkdir -p .local
chmod 700 .local
ARCHIVE_PATH="$PROJECT_DIR/.local/release-$RELEASE_ID.tar.gz"
# Release a fixed set of runtime inputs, never the entire checkout. Recursive
# exclusions also protect against a developer putting local data inside them.
COPYFILE_DISABLE=1 tar --no-xattrs --exclude='.git' --exclude='.local' \
  --exclude='.env' --exclude='.env.*' --exclude='node_modules' --exclude='.venv' \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='data' \
  --exclude='*.sqlite3*' --exclude='*.pem' --exclude='*.key' --exclude='*.tar.gz' \
  -czf "$ARCHIVE_PATH" backend frontend/dist deploy LICENSE NOTICE LICENSING.md THIRD_PARTY_NOTICES.md
scp "$ARCHIVE_PATH" "$DEPLOY_HOST:/tmp/insight-studio-$RELEASE_ID.tar.gz"
ssh "$DEPLOY_HOST" bash -s -- "$RELEASE_ID" "$SITE_URL" <<'REMOTE'
set -euo pipefail
umask 077
if [[ "$(id -u)" != 0 ]]; then
  echo "Use an SSH account with root privileges for systemd/Caddy installation." >&2
  exit 1
fi
for command in python3.12 caddy systemctl tar curl; do command -v "$command" >/dev/null; done
release_id="$1"
site_url="$2"
base=/srv/insight-studio
release="$base/releases/$release_id"
id insight-studio >/dev/null 2>&1 || useradd --system --home-dir "$base" --shell /usr/sbin/nologin insight-studio
install -d -m 755 "$base/releases" "$release"
install -d -m 700 -o insight-studio -g insight-studio "$base/shared" "$base/shared/data"
tar -xzf "/tmp/insight-studio-$release_id.tar.gz" -C "$release"
python3.12 -m venv "$release/.venv"
(cd "$release" && sha256sum -c deploy/wheels/SHA256SUMS)
"$release/.venv/bin/pip" install --disable-pip-version-check -q --find-links "$release/deploy/wheels" -r "$release/backend/requirements.txt"
python3.12 - <<'PY'
import pathlib, secrets
env = pathlib.Path('/srv/insight-studio/shared/.env')
if not env.exists():
    env.write_text('\n'.join([
        'ADMIN_USERNAME=admin',
        'ADMIN_PASSWORD=' + secrets.token_urlsafe(32),
        'SESSION_SECRET=' + secrets.token_hex(48),
        'COOKIE_SECURE=true',
        'DATA_DIR=/srv/insight-studio/shared/data',
        'STATIC_DIR=/srv/insight-studio/current/frontend/dist',
        'LLM_BASE_URL=https://openrouter.ai/api/v1',
        'LLM_API_KEY=',
        'LLM_MODEL=deepseek/deepseek-v4-pro-0813',
        'LLM_PROVIDER_ONLY=sail-research/fp4',
        'LLM_INPUT_PER_MILLION_USD=0.45',
        'LLM_OUTPUT_PER_MILLION_USD=0.8',
    ]) + '\n')
# Upgrade an account-capable installation without resetting keys, reports or
# historical billing. Existing administrators are never overwritten by seeding.
values = dict(line.split('=', 1) for line in env.read_text().splitlines()
              if '=' in line and not line.startswith('#'))
missing = []
if not values.get('ADMIN_USERNAME'):
    missing.append('ADMIN_USERNAME=admin')
if not values.get('ADMIN_PASSWORD'):
    missing.append('ADMIN_PASSWORD=' + secrets.token_urlsafe(32))
if missing:
    with env.open('a') as output:
        output.write('\n' + '\n'.join(missing) + '\n')
env.chmod(0o600)
PY
chown -R insight-studio:insight-studio "$base/shared"
python3.12 "$release/deploy/render-caddy.py" --site-url "$site_url" --output "$release/deploy/Caddyfile.rendered"
caddy validate --config "$release/deploy/Caddyfile.rendered" --adapter caddyfile
if [[ -L "$base/current" ]]; then
  readlink -f "$base/current" > "$base/previous-release"
fi
ln -sfn "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
install -m 644 "$release/deploy/insight-studio.service" /etc/systemd/system/insight-studio.service
systemctl daemon-reload
systemctl enable insight-studio.service >/dev/null
systemctl restart insight-studio.service
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8108/api/health >/dev/null; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8108/api/health >/dev/null
# This script manages the dedicated host's Caddyfile; preserve its first backup.
if [[ -f /etc/caddy/Caddyfile && ! -f /etc/caddy/Caddyfile.before-insight ]]; then
  cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-insight
fi
install -m 644 "$release/deploy/Caddyfile.rendered" /etc/caddy/Caddyfile
systemctl enable caddy.service >/dev/null
systemctl reload-or-restart caddy.service
rm "/tmp/insight-studio-$release_id.tar.gz"
printf 'Release: %s\n' "$release_id"
REMOTE
# Credentials go only to an ignored owner-readable file, never the terminal.
ssh "$DEPLOY_HOST" python3.12 - "$SITE_URL" <<'PY' > "$PROJECT_DIR/.local/access.json"
import json, pathlib, sys
env = dict(line.split('=', 1) for line in pathlib.Path('/srv/insight-studio/shared/.env').read_text().splitlines()
           if '=' in line and not line.startswith('#'))
print(json.dumps({'url': sys.argv[1], 'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}))
PY
chmod 600 "$PROJECT_DIR/.local/access.json"
printf '\nDeployed to %s\nInitial admin credentials saved privately in .local/access.json (not printed).\n' "$SITE_URL"
