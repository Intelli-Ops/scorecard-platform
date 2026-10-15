#!/usr/bin/env bash
# Install - or update - the Scorecard platform on Ubuntu 22.04 or 24.04.
set -euo pipefail

APP_DIR=/opt/scorecard
DATA_DIR=/var/lib/scorecard
CONF_DIR=/etc/scorecard
ENV_FILE=$CONF_DIR/scorecard.env
MIGRATE_ENV=$CONF_DIR/migrate.env
NGINX_SITE=/etc/nginx/sites-available/scorecard
APP_USER=scorecard
MIGRATE_USER=scorecard_migrate
DB_NAME=scorecard
SERVER_NAME=${SERVER_NAME:-_}
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

EXTERNAL_DB=0
for arg in "$@"; do
  case $arg in
    --external-db) EXTERNAL_DB=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# key=value in the settings file: the line replaced if it is there, added if not.
set_setting() {
  local tmp
  tmp=$(mktemp)
  if grep -q "^$1=" "$ENV_FILE"; then
    K=$1 V=$2 awk -F= '$1 == ENVIRON["K"] { print ENVIRON["K"] "=" ENVIRON["V"]; next } { print }' \
      "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    printf '%s=%s\n' "$1" "$2" >> "$tmp"
  fi
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

# Checks
[[ $EUID -eq 0 ]] || die "run it as root: sudo bash deploy/install.sh"
. /etc/os-release
[[ ${ID:-} == ubuntu ]] || die "this script is for Ubuntu (this is ${PRETTY_NAME:-unknown})"
[[ -f $SRC/backend/requirements.txt ]] || die "run it from the unzipped package"
[[ -f $SRC/frontend/dist/index.html ]] \
  || die "frontend/dist is missing - make the package with deploy/make_package.py"
[[ $SRC != "$APP_DIR" ]] || die "unzip the package somewhere other than $APP_DIR"

# Packages
step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
PKGS=(python3 python3-venv nginx rsync curl openssl)
[[ $EXTERNAL_DB -eq 1 ]] || PKGS+=(mysql-server)
apt-get install -y -q "${PKGS[@]}"

# Python 3.11 or newer.
PY=python3
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  apt-get install -y -q software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -q
  apt-get install -y -q python3.11 python3.11-venv
  PY=python3.11
fi
echo "Python: $($PY --version)"

# Account
step "Service account '$APP_USER'"
if id -u "$APP_USER" >/dev/null 2>&1; then
  echo "exists"
else
  useradd --system --home-dir "$APP_DIR" --no-create-home \
          --shell /usr/sbin/nologin "$APP_USER"
  echo "created"
fi

# Code
step "Code -> $APP_DIR"
mkdir -p "$APP_DIR/frontend"
# The code is root's; the service only reads it.
rsync -a --delete --exclude '__pycache__/' --exclude '/tests/' \
      "$SRC/backend/" "$APP_DIR/backend/"
rsync -a --delete "$SRC/frontend/dist/" "$APP_DIR/frontend/dist/"
rsync -a --delete "$SRC/deploy/" "$APP_DIR/deploy/"
chown -R root:root "$APP_DIR/backend" "$APP_DIR/frontend" "$APP_DIR/deploy"
chmod -R u=rwX,go=rX "$APP_DIR/backend" "$APP_DIR/frontend" "$APP_DIR/deploy"

step "Python packages"
# A Python environment made by another Python version is started again.
if [[ -x $APP_DIR/.venv/bin/python ]] \
   && ! "$APP_DIR/.venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  rm -rf "$APP_DIR/.venv"
fi
[[ -x $APP_DIR/.venv/bin/python ]] || "$PY" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"
"$APP_DIR/.venv/bin/python" -m compileall -q "$APP_DIR/backend/app"
# The app's server commands, as the service account: see deploy/scorecard-manage.
install -m 755 "$SRC/deploy/scorecard-manage" /usr/local/bin/scorecard-manage

# Data
step "Data folder -> $DATA_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR"

# Settings + database
step "Settings -> $ENV_FILE"
install -d -m 755 "$CONF_DIR"
if [[ -f $ENV_FILE ]]; then
  echo "kept as it is"
elif [[ $EXTERNAL_DB -eq 1 ]]; then
  install -m 640 -o root -g "$APP_USER" "$SRC/deploy/scorecard.env.example" "$ENV_FILE"
  die "wrote $ENV_FILE. Set SCORECARD_DB in it to the MySQL server's address
(see DEPLOY.md, 'MySQL on another server'), then run this script again."
else
  systemctl enable --now mysql >/dev/null
  if [[ -n $(mysql -N -e "SELECT 1 FROM mysql.user WHERE user = '$APP_USER' LIMIT 1") ]]; then
    die "MySQL already has a '$APP_USER' user but $ENV_FILE is missing.
Either restore that file, or remove the user (DROP USER '$APP_USER'@'localhost',
'$APP_USER'@'127.0.0.1') and run this script again."
  fi
  PASS=$(openssl rand -hex 24)
  # Two accounts, one password.
  mysql <<SQL
CREATE DATABASE IF NOT EXISTS $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER '$APP_USER'@'localhost' IDENTIFIED BY '$PASS';
CREATE USER '$APP_USER'@'127.0.0.1' IDENTIFIED BY '$PASS';
SQL
  (
    umask 077
    sed "s|^SCORECARD_DB=.*|SCORECARD_DB=mysql://$APP_USER:$PASS@127.0.0.1/$DB_NAME|" \
        "$SRC/deploy/scorecard.env.example" > "$ENV_FILE"
  )
  chown root:"$APP_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  echo "written, with a new database password"
fi

# Settings added since the file was first written.
if ! grep -q '^SCORECARD_AUTO_MIGRATE=' "$ENV_FILE"; then
  printf '\n# The installer applies migrations; the app only checks (DEPLOY.md).\nSCORECARD_AUTO_MIGRATE=0\n' >> "$ENV_FILE"
  echo "added SCORECARD_AUTO_MIGRATE=0"
fi

# The mail account, from mail.env in the package (deploy/make_package.py adds it.
if [[ -f $SRC/mail.env ]]; then
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%$'\r'}
    [[ $line =~ ^(SCORECARD_(SMTP_[A-Z]+|MAIL_FROM|PUBLIC_URL))=(.*)$ ]] || continue
    set_setting "${BASH_REMATCH[1]}" "${BASH_REMATCH[3]}"
    echo "mail: set ${BASH_REMATCH[1]}"
  done < "$SRC/mail.env"
fi

# The address in the links the app mails.
if ! grep -q '^SCORECARD_PUBLIC_URL=.\+' "$ENV_FILE"; then
  name=$SERVER_NAME
  if [[ $name == _ && -f $NGINX_SITE ]]; then
    name=$(awk '$1 == "server_name" { sub(/;$/, "", $2); print $2; exit }' "$NGINX_SITE")
  fi
  [[ -n $name && $name != _ ]] || name=$(hostname -I | awk '{print $1}')
  scheme=http
  grep -q '^SCORECARD_REQUIRE_HTTPS=1' "$ENV_FILE" && scheme=https
  set_setting SCORECARD_PUBLIC_URL "$scheme://$name"
  echo "set SCORECARD_PUBLIC_URL=$scheme://$name (change it there if people use another address)"
fi

# Database accounts two mysql accounts, so the running app cannot change the schema: scorecard           the app's own - rows only: select, insert, update, delete. a bug in the app cannot then drop a table or the trigger that stops the activity log being edited. scorecard_migrate   changes the schema - used only by `scorecard-manage upgrade`, here and on each update. its address is in $migrate_env, readable by root alone; the service never sees it.
if [[ $EXTERNAL_DB -eq 0 ]]; then
  step "Database accounts"
  if [[ ! -f $MIGRATE_ENV ]]; then
    if [[ -n $(mysql -N -e "SELECT 1 FROM mysql.user WHERE user = '$MIGRATE_USER' LIMIT 1") ]]; then
      die "MySQL already has a '$MIGRATE_USER' user but $MIGRATE_ENV is missing.
Either restore that file, or remove the user (DROP USER '$MIGRATE_USER'@'localhost',
'$MIGRATE_USER'@'127.0.0.1') and run this script again."
    fi
    MPASS=$(openssl rand -hex 24)
    mysql <<SQL
CREATE USER '$MIGRATE_USER'@'localhost' IDENTIFIED BY '$MPASS';
CREATE USER '$MIGRATE_USER'@'127.0.0.1' IDENTIFIED BY '$MPASS';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER
  ON $DB_NAME.* TO '$MIGRATE_USER'@'localhost', '$MIGRATE_USER'@'127.0.0.1';
SQL
    (
      umask 077
      echo "SCORECARD_MIGRATE_DB=mysql://$MIGRATE_USER:$MPASS@127.0.0.1/$DB_NAME" > "$MIGRATE_ENV"
    )
    chown root:root "$MIGRATE_ENV"
    chmod 600 "$MIGRATE_ENV"
    echo "created '$MIGRATE_USER', address in $MIGRATE_ENV (root only)"
  fi
  # Rows only, on a new install and on an update alike.
  mysql <<SQL
REVOKE ALL PRIVILEGES ON $DB_NAME.* FROM '$APP_USER'@'localhost', '$APP_USER'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE
  ON $DB_NAME.* TO '$APP_USER'@'localhost', '$APP_USER'@'127.0.0.1';
SQL
  echo "'$APP_USER' may read and write rows, and nothing more"
elif [[ ! -f $MIGRATE_ENV ]]; then
  echo "WARNING: no $MIGRATE_ENV - migrations will run as the app's own account."
  echo "         See DEPLOY.md, 'MySQL on another server', to separate them."
fi

step "Database"
scorecard-manage check
# On a first install the app cannot add the activity log's trigger itself and says so.
out=$(scorecard-manage upgrade 2>&1) || { echo "$out"; die "could not create the tables"; }
grep -v "activity_log triggers are not as they should be" <<<"$out" || true

if [[ $EXTERNAL_DB -eq 0 ]]; then
  step "Activity log protection"
  # As MySQL's root, over the local socket.
  mysql "$DB_NAME" <<'SQL'
DROP TRIGGER IF EXISTS activity_log_no_delete;
DROP TRIGGER IF EXISTS activity_log_no_update;
CREATE TRIGGER activity_log_no_update BEFORE UPDATE ON activity_log FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'activity_log rows cannot be changed';
SQL
  echo "activity_log rows cannot be edited"
fi

# Service
step "Service"
install -m 644 "$SRC/deploy/scorecard.service" /etc/systemd/system/scorecard.service
systemctl daemon-reload
systemctl enable scorecard >/dev/null
systemctl restart scorecard

# Nginx
step "Web server"
if [[ -f $NGINX_SITE ]]; then
  echo "kept $NGINX_SITE as it is"
else
  sed "s|server_name _;|server_name $SERVER_NAME;|" \
      "$SRC/deploy/nginx-scorecard.conf" > "$NGINX_SITE"
  echo "wrote $NGINX_SITE (server_name $SERVER_NAME)"
fi
ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/scorecard
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx >/dev/null
systemctl reload-or-restart nginx

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 'Nginx Full' >/dev/null
  echo "firewall: opened ports 80 and 443"
fi

# Check
step "Checking"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[[ $ok -eq 1 ]] || die "the backend did not answer. See: sudo journalctl -u scorecard -n 50"
curl -fsS http://127.0.0.1/api/health >/dev/null \
  || die "the backend answers but nginx does not pass it on. See: sudo nginx -t"
echo "backend and nginx both answer"

if [[ $SERVER_NAME == _ ]]; then
  ADDRESS=$(hostname -I | awk '{print $1}')
else
  ADDRESS=$SERVER_NAME
fi
cat <<EOF

Done. The Scorecard platform is running at http://$ADDRESS/

On a first install, make the first system admin (it asks for a password):

  sudo scorecard-manage create-admin you@appedology.com APD-1234

Then add HTTPS - see DEPLOY.md, "HTTPS".
EOF
if ! grep -q '^SCORECARD_SMTP_HOST=.\+' "$ENV_FILE"; then
  cat <<EOF

NOTE: email is not set up, so nobody can sign up and no password can be reset
from the app. Set SCORECARD_SMTP_* in $ENV_FILE - see DEPLOY.md, "Email".
EOF
fi
