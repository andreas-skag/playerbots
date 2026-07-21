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

# Sentinel: world DB exists and creature_template is populated
count=$(mysql_root "SELECT COUNT(*) FROM information_schema.tables \
    WHERE table_schema='classicmangos' AND table_name='creature_template'" || echo 0)
if [ "$count" = "1" ]; then
    rows=$(mysql_root "SELECT COUNT(*) FROM classicmangos.creature_template" || echo 0)
    if [ "$rows" -gt 0 ]; then
        echo "db-init: world DB already populated ($rows creature templates) - nothing to do"
        exit 0
    fi
fi

echo "db-init: installing full classic-db (this takes a few minutes)..."
cd /classic-db

cat > InstallFullDB.config <<EOF
DB_HOST="$MYSQL_HOST"
MYSQL_HOST="$MYSQL_HOST"
MYSQL_PORT="3306"
MYSQL_USERNAME="mangos"
MYSQL_PASSWORD="$MANGOS_PW"
MYSQL_USERIP="%"
WORLD_DB_NAME="classicmangos"
REALM_DB_NAME="classicrealmd"
CHAR_DB_NAME="classiccharacters"
LOGS_DB_NAME="classiclogs"
MYSQL_PATH=""
MYSQL_DUMP_PATH=""
CORE_PATH="/core-tree"
LOCALES="YES"
DEV_UPDATES="NO"
AHBOT="NO"
PLAYERBOTS_DB="YES"
FORCE_WAIT="NO"
EOF

./InstallFullDB.sh -InstallAll root "$ROOT_PW"
echo "db-init: done"
