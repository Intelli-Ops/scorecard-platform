#!/usr/bin/env bash
# Install - or update - the Scorecard platform on Ubuntu 22.04 or 24.04.
#
# From the unzipped package:
#
#   sudo bash deploy/install.sh                  MySQL on this same machine
#   sudo bash deploy/install.sh --external-db    MySQL on another server
#
#   sudo SERVER_NAME=scorecard.example.com bash deploy/install.sh
#                                                with the address people will
#                                                type (first install only)
#
# Running it again from a newer package IS the update: the code and Python
# packages are replaced and the service restarted. The settings file, the
# database, the uploaded files and the nginx site are kept as they are.
#
# Where things go:
#   /opt/scorecard            the code, its Python environment, the built app
#   /var/lib/scorecard        uploaded files, build results, cache
#   /etc/scorecard/scorecard.env   settings, including the database password
set -euo pipefail

APP_DIR=/opt/scorecard
DATA_DIR=/var/lib/scorecard
CONF_DIR=/etc/scorecard
ENV_FILE=$CONF_DIR/scorecard.env
NGINX_SITE=/etc/nginx/sites-available/scorecard
APP_USER=scorecard
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

# ------------------------------------------------------------------ checks
[[ $EUID -eq 0 ]] || die "run it as root: sudo bash deploy/install.sh"
. /etc/os-release
[[ ${ID:-} == ubuntu ]] || die "this script is for Ubuntu (this is ${PRETTY_NAME:-unknown})"
[[ -f $SRC/backend/requirements.txt ]] || die "run it from the unzipped package"
[[ -f $SRC/frontend/dist/index.html ]] \
  || die "frontend/dist is missing - make the package with deploy/make_package.py"
[[ $SRC != "$APP_DIR" ]] || die "unzip the package somewhere other than $APP_DIR"

# ------------------------------------------------------------------ packages
step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
PKGS=(python3 python3-venv nginx rsync curl openssl)
[[ $EXTERNAL_DB -eq 1 ]] || PKGS+=(mysql-server)
apt-get install -y -q "${PKGS[@]}"

# Python 3.11 or newer. 24.04 has 3.12; 22.04 has 3.10, so there 3.11 comes
# from the deadsnakes archive.
PY=python3
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  apt-get install -y -q software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -q
  apt-get install -y -q python3.11 python3.11-venv
  PY=python3.11
fi
echo "Python: $($PY --version)"

# ------------------------------------------------------------------ account
step "Service account '$APP_USER'"
if id -u "$APP_USER" >/dev/null 2>&1; then
  echo "exists"
else
  useradd --system --home-dir "$APP_DIR" --no-create-home \
          --shell /usr/sbin/nologin "$APP_USER"
  echo "created"
fi

# ------------------------------------------------------------------ code
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

# ------------------------------------------------------------------ data
step "Data folder -> $DATA_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR"

# ------------------------------------------------------------------ settings + database
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
  # Two accounts, one password: MySQL tells a socket connection (localhost)
  # from a TCP one (127.0.0.1), and the app connects over TCP.
  # No DROP: TRUNCATE would get around the app's rules for the activity log.
  # TRIGGER lets the app SEE the activity log's trigger - MySQL hides
  # triggers from anyone without it - so it does not warn on every start.
  mysql <<SQL
CREATE DATABASE IF NOT EXISTS $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER '$APP_USER'@'localhost' IDENTIFIED BY '$PASS';
CREATE USER '$APP_USER'@'127.0.0.1' IDENTIFIED BY '$PASS';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, TRIGGER
  ON $DB_NAME.* TO '$APP_USER'@'localhost', '$APP_USER'@'127.0.0.1';
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

step "Database"
scorecard-manage check
# On a first install the app cannot add the activity log's trigger itself and
# says so; root adds it just below, so that one warning is left out here.
out=$(scorecard-manage upgrade 2>&1) || { echo "$out"; die "could not create the tables"; }
grep -v "activity_log triggers are not as they should be" <<<"$out" || true

if [[ $EXTERNAL_DB -eq 0 ]]; then
  step "Activity log protection"
  # As MySQL's root, over the local socket. Creating a trigger needs more than
  # the app's own account has. Rows of activity_log can be deleted (by a
  # system admin, and the deletion is logged) but never edited.
  mysql "$DB_NAME" <<'SQL'
DROP TRIGGER IF EXISTS activity_log_no_delete;
DROP TRIGGER IF EXISTS activity_log_no_update;
CREATE TRIGGER activity_log_no_update BEFORE UPDATE ON activity_log FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'activity_log rows cannot be changed';
SQL
  echo "activity_log rows cannot be edited"
fi

# ------------------------------------------------------------------ service
step "Service"
install -m 644 "$SRC/deploy/scorecard.service" /etc/systemd/system/scorecard.service
systemctl daemon-reload
systemctl enable scorecard >/dev/null
systemctl restart scorecard

# ------------------------------------------------------------------ nginx
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

# ------------------------------------------------------------------ check
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
