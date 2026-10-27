#!/usr/bin/env bash
set -euo pipefail
: "${DEPLOY_HOST:?Set DEPLOY_HOST to the SSH target}"
ssh "$DEPLOY_HOST" bash -s <<'REMOTE'
set -euo pipefail
backup_dir=/srv/insight-studio/backups
install -d -m 700 "$backup_dir"
backup_file="$backup_dir/insight-studio-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
backup_temp="$backup_file.partial"
systemctl stop insight-studio
trap 'rm -f "$backup_temp"; systemctl start insight-studio' EXIT
umask 077
tar -czf "$backup_temp" -C /srv/insight-studio/shared .
mv "$backup_temp" "$backup_file"
printf 'Backup: %s\n' "$backup_file"
REMOTE
