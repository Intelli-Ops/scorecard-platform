# Deploying the Scorecard platform on Ubuntu

This guide installs the platform on one Ubuntu server, with MySQL as the
database. One script does the work, and running it again installs an update.

Time needed: about 15 minutes, mostly package downloads.

---

## What runs on the server

```
  Browser ──► nginx (port 80 / 443)
                 │
                 ├── /           the React app: plain files from /opt/scorecard/frontend/dist
                 │
                 └── /api/...  ──► backend (uvicorn, 127.0.0.1:8000, systemd service "scorecard")
                                      │
                                      ├── MySQL database "scorecard"  (accounts, uploads, runs, activity log)
                                      └── /var/lib/scorecard          (uploaded files, build results, cache)
```

| Piece | What it does | Where |
|---|---|---|
| **nginx** | The only thing the outside world talks to. Sends the app's pages, forwards `/api` to the backend, and holds the HTTPS certificate | `/etc/nginx/sites-available/scorecard` |
| **Backend** | Python (FastAPI) service. Checks sign-ins, stores uploads, builds the scorecards | `/opt/scorecard`, runs as the `scorecard` system user |
| **systemd** | Starts the backend at boot and restarts it if it stops | `/etc/systemd/system/scorecard.service` |
| **MySQL 8** | The database | the `scorecard` database |
| **Settings** | Database address and password, time zone, limits | `/etc/scorecard/scorecard.env` |
| **Data folder** | Every uploaded Excel file and every build's results | `/var/lib/scorecard` |

The backend listens on `127.0.0.1` only, so it cannot be reached except
through nginx. It runs as its own user, which can write to
`/var/lib/scorecard` and nowhere else.

---

## Requirements

| | |
|---|---|
| OS | Ubuntu **24.04** LTS (recommended) or 22.04 LTS, 64-bit |
| CPU / RAM | 2 CPUs and 8 GB RAM recommended. A build reads Excel files of up to about 240 MB into memory |
| Disk | 50 GB free to start. Every week's uploads are kept (on the development laptop, five weeks took about 1.3 GB including the cache), so watch `/var/lib/scorecard` |
| Access | `sudo`, and internet access for `apt` and `pip` during the install |
| Ports | 80 and 443 open to the people who will use it |

Nothing else needs to be installed first. Node.js is **not** needed: the app
arrives already built.

---

## 1. Install

Copy the zip to the server, then:

```bash
sudo apt-get install -y unzip
unzip scorecard-20260929-abc1234.zip
cd scorecard
sudo SERVER_NAME=scorecard.yourcompany.com bash deploy/install.sh
```

`SERVER_NAME` is the address people will type. Leave it out to answer on
any address, such as the server's IP.

What the script does, in order:

1. Installs `python3`, `nginx`, `mysql-server` and a few tools with `apt`.
2. Creates the `scorecard` system user (it cannot log in).
3. Copies the code to `/opt/scorecard` and installs the Python packages
   into `/opt/scorecard/.venv`.
4. Creates the `scorecard` MySQL database and a `scorecard` MySQL user
   with a random 48-character password, and writes that password into
   `/etc/scorecard/scorecard.env`. Only root and the service can read it.
5. Creates the tables, and adds the database trigger that stops activity
   log entries from being edited.
6. Installs and starts the `scorecard` service, and the nginx site.
7. Checks that both the backend and nginx answer.

It ends with:

```
Done. The Scorecard platform is running at http://scorecard.yourcompany.com/
```

## 2. Make the first admin

Nobody can sign in yet. People who sign up wait for an admin to approve
them, so the first admin has to be made on the server:

```bash
sudo scorecard-manage create-admin ali.asghar@appedology.com APD-1234
```

It asks for a password twice. That person can now sign in, approve other
sign-ups, and make other admins from the **Users** screen.

## 3. HTTPS

Passwords are sent at sign-in, so HTTPS is required before real use.

**If the server has a public domain name**, get a free certificate. It
renews itself:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d scorecard.yourcompany.com
```

**If the company has its own certificate** (internal servers), add it to
`/etc/nginx/sites-available/scorecard`:

```nginx
server {
    listen 443 ssl;
    server_name scorecard.yourcompany.com;
    ssl_certificate     /etc/ssl/certs/scorecard.crt;
    ssl_certificate_key /etc/ssl/private/scorecard.key;
    # ... then the same lines as the port 80 block
}
```

Then change the port 80 block to `return 301 https://$host$request_uri;`, and
run `sudo nginx -t && sudo systemctl reload nginx`.

Updates never overwrite this file, so HTTPS stays in place.

---

## Updating to a new version

Same as the install, with the new zip:

```bash
unzip scorecard-20261015-def5678.zip
cd scorecard
sudo bash deploy/install.sh
```

Replaced: the code, the built app and the Python packages. The service is
restarted, and the database migrations it has not yet had are applied
automatically (`backend/app/db/migrations/versions/`).

Kept: `/etc/scorecard/scorecard.env`, the MySQL database, `/var/lib/scorecard`
and the nginx site.

The service is down for a few seconds during the restart. A build that is
running at that moment is marked failed a couple of minutes later and can be
started again from the app; builds still waiting in the queue are kept and run
once the service is back. Take a backup first (below).

---

## Backups

Two things hold everything. Back up both, together:

```bash
# 1. The database
sudo mysqldump --single-transaction --routines --triggers scorecard \
  | gzip > /backup/scorecard-db-$(date +%F).sql.gz

# 2. The uploaded files and build results (skip cache/, it is rebuilt)
sudo tar czf /backup/scorecard-data-$(date +%F).tar.gz \
  --exclude=cache -C /var/lib scorecard
```

To run this every night, save it as `/etc/cron.daily/scorecard-backup` and
make it executable (`chmod +x`). Also copy `/etc/scorecard/scorecard.env`
somewhere safe once, since it holds the database password.

**Restore:** stop the service (`sudo systemctl stop scorecard`), then run
`gunzip < backup.sql.gz | sudo mysql scorecard` and unpack the tar into
`/var/lib`. Start the service again.

---

## Bringing data over from a laptop (optional)

This is only needed if the app was already used on a Windows laptop and that
history should come along. Do it right after the install, **before** step 2
(the target database must be empty).

1. On the laptop, stop the app. Copy `data\scorecard.db`, `data\objects\`
   and `data\results\` to the server, for example into `/tmp/laptop-data/`.
2. On the server:

```bash
sudo systemctl stop scorecard
sudo chown -R scorecard: /tmp/laptop-data
sudo scorecard-manage copy-db sqlite:////tmp/laptop-data/scorecard.db
sudo rsync -a /tmp/laptop-data/objects /tmp/laptop-data/results /var/lib/scorecard/
sudo chown -R scorecard: /var/lib/scorecard
sudo systemctl start scorecard
sudo rm -rf /tmp/laptop-data
```

(`sqlite:////` has four slashes: three for the address, one for the path.)
The laptop's accounts come along, so skip step 2 if an admin already
exists there.

---

## MySQL on another server

If the database lives on a separate MySQL 8 server:

1. On the database server, the DBA runs:

```sql
CREATE DATABASE scorecard CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'scorecard'@'APP_SERVER_IP' IDENTIFIED BY 'a-long-random-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, TRIGGER
  ON scorecard.* TO 'scorecard'@'APP_SERVER_IP';
```

   There is deliberately no `DROP`: `TRUNCATE` would get around the app's
   rules for the activity log.

2. On the app server:

```bash
sudo bash deploy/install.sh --external-db
```

   The first run stops after writing `/etc/scorecard/scorecard.env`. Set the
   address in it:

```
SCORECARD_DB=mysql://scorecard:a-long-random-password@db.yourcompany.com/scorecard
```

   Then run `sudo bash deploy/install.sh --external-db` again.

3. Add the activity log trigger once, with the DBA's admin account:

```bash
sudo scorecard-manage protect-log --as "mysql://admin:ADMINPASS@db.yourcompany.com/scorecard"
```

---

## Day to day

| To... | Run |
|---|---|
| See if it is running | `sudo systemctl status scorecard` |
| Read its log, live | `sudo journalctl -u scorecard -f` |
| Restart it (after editing settings) | `sudo systemctl restart scorecard` |
| Check it is healthy | `curl -f http://127.0.0.1/api/health` → `{"ok":true,"checks":{"database":true,"storage":true,"disk_space":true,"worker":true},"queued_builds":0}`. Any check `false` makes it a 503 and names what is wrong. Asked from another computer it says only `{"ok":true}` or `false` |
| Check it reaches the database | `sudo scorecard-manage check` |
| Unlock a locked-out admin | `sudo scorecard-manage reset-password EMAIL` |
| Change someone's role | `sudo scorecard-manage set-role EMAIL admin` (`viewer`, `admin`, `system_admin`) |
| See disk use | `sudo du -sh /var/lib/scorecard/*` |

## Settings

These live in `/etc/scorecard/scorecard.env`. Restart the service after a
change.

| Setting | Set by install to | Meaning |
|---|---|---|
| `SCORECARD_DB` | local MySQL, random password | The database address |
| `SCORECARD_DATA` | `/var/lib/scorecard` | Uploaded files, results, cache |
| `SCORECARD_TIMEZONE` | `Asia/Karachi` | Time zone for the out-of-hours sign-in alert |
| `SCORECARD_WORK_HOURS` | `7-21` | Sign-ins outside these hours are flagged |
| `SCORECARD_API_DOCS` | `0` | `1` shows the API listing at `/docs` (not reachable through nginx anyway) |
| `SCORECARD_CORS_ORIGINS` | empty | Not needed: page and API share one address |
| `SCORECARD_MAX_UPLOAD_MB` | `1024` | Largest single upload. Keep `client_max_body_size` in the nginx site's upload `location` above it |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser shows **502 Bad Gateway** | The backend is not running | `sudo journalctl -u scorecard -n 50` shows why |
| **413 Request Entity Too Large** on upload | The files are bigger than nginx allows | Raise `client_max_body_size` in the upload `location` of the nginx site (the 1m above it is for every other address, and stays) |
| The page loads, but sign-in says it cannot reach the server | Built without `frontend/.env.production` | Rebuild the zip with `deploy/make_package.py` |
| `ERROR: frontend/dist is missing` | The zip was not made with `make_package.py` | Make the zip with it; a plain copy of the code has no built app |
| `bash\r: not found` | A script has Windows line endings | Use the zip from `make_package.py`, which fixes them |
| Log says **activity_log triggers are not as they should be** | The trigger was never added (external MySQL) | Step 3 of "MySQL on another server" |
| `Access denied for user 'scorecard'` | The password in the settings file and MySQL differ | Set it again: `sudo mysql -e "ALTER USER 'scorecard'@'127.0.0.1' IDENTIFIED BY '...'"` and the same in `scorecard.env` |
| Activity log shows `127.0.0.1` for everyone | A second proxy or load balancer in front of nginx | Have that proxy pass the visitor's address, and trust it in `set_real_ip_from` |

---

## Making the zip (for the developer)

On the development machine, from the project folder:

```powershell
.venv\Scripts\python deploy\make_package.py
```

Commit first: it refuses to run while anything is changed or new and not in
git, so every zip is exactly one commit. It then runs the backend tests,
installs the frontend's packages from the lockfile (`npm ci`), builds the React
app and writes `release\scorecard-<date>-<commit>.zip`. The zip contains only
files in that commit, so it never includes `.venv`, `node_modules` or `data\`.
It also gives the server files Unix line endings.
