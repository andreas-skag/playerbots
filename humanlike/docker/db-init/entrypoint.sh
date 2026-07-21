#!/bin/bash
# One-shot DB initializer. Idempotent: exits 0 immediately if the world DB
# is already populated. Full reset: docker compose down -v && docker compose up
set -euo pipefail

MYSQL_HOST="${MYSQL_HOST:-db}"
ROOT_PW="${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD not set}"
MANGOS_PW="${MANGOS_DB_PASSWORD:?MANGOS_DB_PASSWORD not set}"

mysql_root() {
    mariadb -h "$MYSQL_HOST" -u root -p"$ROOT_PW" -N -B -e "$1"
}

# Sentinel: only a fully completed install writes this marker table.
# A partial install (crash mid-run) leaves no marker, so init re-runs;
# the DeleteAll invocation below makes reruns safe.
marker=$(mysql_root "SELECT COUNT(*) FROM information_schema.tables \
    WHERE table_schema='classicmangos' AND table_name='_dbinit_complete'" || echo 0)
if [ "$marker" = "1" ]; then
    echo "db-init: install marker present - nothing to do"
    exit 0
fi

echo "db-init: installing full classic-db (this takes a few minutes)..."
cd /classic-db

cat > InstallFullDB.config <<EOF
MYSQL_HOST="$MYSQL_HOST"
MYSQL_PORT="3306"
MYSQL_USERNAME="mangos"
MYSQL_PASSWORD="$MANGOS_PW"
MYSQL_USERIP="%"
WORLD_DB_NAME="classicmangos"
REALM_DB_NAME="classicrealmd"
CHAR_DB_NAME="classiccharacters"
LOGS_DB_NAME="classiclogs"
MYSQL_PATH="mariadb"
MYSQL_DUMP_PATH="mariadb-dump"
CORE_PATH="/core-tree"
LOCALES="YES"
DEV_UPDATES="NO"
AHBOT="NO"
PLAYERBOTS_DB="YES"
FORCE_WAIT="NO"
EOF

./InstallFullDB.sh -InstallAll root "$ROOT_PW" DeleteAll
mysql_root "CREATE TABLE IF NOT EXISTS classicmangos._dbinit_complete (completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
mysql_root "INSERT INTO classicmangos._dbinit_complete () VALUES ()"
echo "db-init: done"
