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
| **Settings** | Database address and password, mail server, time zone, limits | `/etc/scorecard/scorecard.env` |
| **Migration login** | The second database account, the one allowed to change tables. Root only; the service never reads it | `/etc/scorecard/migrate.env` |
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
4. Creates the `scorecard` MySQL database and two MySQL accounts, each
   with its own random 48-character password:
   - `scorecard`, which the app runs as. It can read and write rows and
     nothing else, so it cannot change or drop a table. Its password goes
     in `/etc/scorecard/scorecard.env`, which only root and the service can
     read.
   - `scorecard_migrate`, which can change tables. It is used only to
     install and update. Its password goes in `/etc/scorecard/migrate.env`,
     which only root can read.
5. Creates the tables (as `scorecard_migrate`), and adds the database
   trigger that stops activity log entries from being edited.
6. Creates the default super admin (step 2 below).
7. Installs and starts the `scorecard` service, and the nginx site.
8. Checks that both the backend and nginx answer.

It ends with:

```
Done. The Scorecard platform is running at http://scorecard.yourcompany.com/
```

## 2. The default super admin

The install makes one super admin, so someone can sign in straight away.
It is set at the top of `deploy/install.sh`:

| | |
|---|---|
| Email | `ali.asghar@appedology.com` (APD-2625) |
| Password | `ADMIN_PASSWORD` in `deploy/install.sh` |

The same email and password are:

- **in the app**, a system admin. It can sign in, approve other sign-ups,
  and make other admins from the **Users** screen.
- **in MySQL**, an account with full rights on the `scorecard` database,
  for looking at the data with MySQL Workbench or `mysql`. It accepts
  connections from the server itself only, so from another computer use an
  SSH tunnel (Workbench: **Standard TCP/IP over SSH**).

**Change the password after the first sign-in.** Anyone who has seen the
code knows the default. The two are separate once made, so change both:

- the app: **Change password** after signing in;
- MySQL: `sudo mysql -e "ALTER USER 'ali.asghar@appedology.com'@'localhost', 'ali.asghar@appedology.com'@'127.0.0.1' IDENTIFIED BY 'the-new-password'"`.

Running the install again (an update) never resets either password. Other
admins can still be made on the server, with a password typed in:

```bash
sudo scorecard-manage create-admin someone@appedology.com APD-1234
```

With `--external-db` only the app account is made; the DBA creates any
MySQL accounts.

### All the logins

| Login | Username | Password | Used by |
|---|---|---|---|
| App super admin | `ali.asghar@appedology.com` | `Scorecard@2026` (default, change it) | People, at the app's sign-in page |
| Database admin | `ali.asghar@appedology.com` | `Scorecard@2026` (default, change it) | People, with MySQL Workbench or `mysql` |
| App's database account | `scorecard` | Random, made by the install | The app itself |
| Migration account | `scorecard_migrate` | Random, made by the install | The install and updates only |
| MySQL root | `root` | None: `sudo mysql` | The server's administrator |

The two random passwords do not exist until the install runs, and every
server gets its own. To see them on the server:

```bash
sudo grep SCORECARD_DB= /etc/scorecard/scorecard.env      # scorecard
sudo cat /etc/scorecard/migrate.env                         # scorecard_migrate
```

Each prints an address of the form
`mysql://USERNAME:PASSWORD@127.0.0.1/scorecard`; the password is the part
between `:` and `@`. Nobody needs to type these, and changing one means
changing it in MySQL and in that file together.

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

## 4. Email

The app emails 6-digit codes. Each works once, for 5 minutes, and five wrong
tries use it up:

- **Confirm your email**, sent when someone signs up. Until they enter it,
  the account cannot be approved, so typing a colleague's address is not
  enough to get in.
- **Reset your password**, sent when someone presses **Forgot password?** on
  the sign-in screen. Nobody else is involved, and no admin sees a password.

It also sends two notices: **your password was changed** after any reset,
and **choose a new password** when an admin uses **Force password reset**
(for a lost laptop or a leaked password). A forced reset stops the old
password working at once; the person then uses Forgot password?.

Until mail is set up, sign-ups and password resets are refused with a
message saying so.

**Usually nothing to do here.** If the zip has a `mail.env` in it (the
developer's mail settings, which `make_package.py` adds), `install.sh` copies
them into `/etc/scorecard/scorecard.env` on every install. It also fills in
`SCORECARD_PUBLIC_URL` from the nginx site's `server_name` if it is empty.
The zip then holds the mail password, so keep it as you would the password.

To set them by hand instead, put these in `/etc/scorecard/scorecard.env`:

```
SCORECARD_PUBLIC_URL=https://scorecard.yourcompany.com
SCORECARD_SMTP_HOST=smtp.office365.com
SCORECARD_SMTP_PORT=587
SCORECARD_SMTP_USER=scorecard@appedology.com
SCORECARD_SMTP_PASSWORD=the-mailbox-password
```

For Microsoft 365 the mailbox needs SMTP AUTH turned on (Microsoft 365 admin
centre, the user, **Mail**, **Manage email apps**, **Authenticated SMTP**).
Then run `sudo systemctl restart scorecard`.

**If mail stops working** and someone is locked out,
`sudo scorecard-manage reset-password EMAIL` prints a reset code on the
screen instead of mailing it. First have them press **Forgot password?**,
enter their email and press **Send code**: that brings them to the code
boxes, even though no email arrives. Then run the command and give them the
code it prints, within 5 minutes. It replaces any code that was mailed.

---

## Updating to a new version

Same as the install, with the new zip:

```bash
unzip scorecard-20261015-def5678.zip
cd scorecard
sudo bash deploy/install.sh
```

Replaced: the code, the built app and the Python packages. The database
changes the new version needs (`backend/app/db/migrations/versions/`) are
applied by the script, as `scorecard_migrate`, and then the service is
restarted. The app itself cannot change tables. If it starts on a database
that has not been upgraded, it stops and its log says to run
`sudo scorecard-manage upgrade`.

**Updating from a version before the two database accounts:** the script
creates `scorecard_migrate` and `/etc/scorecard/migrate.env`, takes the
table-changing rights away from `scorecard`, and adds
`SCORECARD_AUTO_MIGRATE=0` to the settings file. Nothing else needs doing,
except setting up email (step 4 above). Accounts that were already approved
count as having confirmed their email. People still waiting for approval will
be asked to confirm theirs. Temporary passwords handed out before the update
stop working 24 hours after they were issued.

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
and `/etc/scorecard/migrate.env` somewhere safe once, since they hold the
two database passwords.

**Restore:** stop the service (`sudo systemctl stop scorecard`), then run
`gunzip < backup.sql.gz | sudo mysql scorecard` and unpack the tar into
`/var/lib`. Start the service again.

---

## Bringing data over from a laptop (optional)

This is only needed if the app was already used on a Windows laptop and that
history should come along. Do it right after the install, before anyone
signs in (the target database must be empty, so the commands below first
remove the default super admin).

1. On the laptop, stop the app. Copy `data\scorecard.db`, `data\objects\`
   and `data\results\` to the server, for example into `/tmp/laptop-data/`.
2. On the server:

```bash
sudo systemctl stop scorecard
sudo chown -R scorecard: /tmp/laptop-data
sudo mysql scorecard -e "DELETE FROM user_account"
sudo scorecard-manage copy-db sqlite:////tmp/laptop-data/scorecard.db
sudo rsync -a /tmp/laptop-data/objects /tmp/laptop-data/results /var/lib/scorecard/
sudo chown -R scorecard: /var/lib/scorecard
sudo systemctl start scorecard
sudo rm -rf /tmp/laptop-data
```

(`sqlite:////` has four slashes: three for the address, one for the path.)
The laptop's accounts come along, with their laptop passwords, in place of
the default super admin. If none of them is a system admin, make one with
`sudo scorecard-manage set-role EMAIL system_admin`.

---

## MySQL on another server

If the database lives on a separate MySQL 8 server:

1. On the database server, the DBA runs:

```sql
CREATE DATABASE scorecard CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- The app runs as this one. Rows only.
CREATE USER 'scorecard'@'APP_SERVER_IP' IDENTIFIED BY 'a-long-random-password';
GRANT SELECT, INSERT, UPDATE, DELETE ON scorecard.* TO 'scorecard'@'APP_SERVER_IP';

-- Install and update only. Changes tables.
CREATE USER 'scorecard_migrate'@'APP_SERVER_IP' IDENTIFIED BY 'another-long-random-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER
  ON scorecard.* TO 'scorecard_migrate'@'APP_SERVER_IP';
```

   The app's own account gets no `CREATE`, `ALTER`, `DROP` or `TRIGGER`.
   A bug in the app then cannot change a table or remove the trigger that
   protects the activity log.

2. On the app server:

```bash
sudo bash deploy/install.sh --external-db
```

   The first run stops after writing `/etc/scorecard/scorecard.env`. Set the
   address in it:

```
SCORECARD_DB=mysql://scorecard:a-long-random-password@db.yourcompany.com/scorecard
```

   Also set `SCORECARD_AUTO_MIGRATE=0`, and write the migration account's
   address into its own file, readable by root alone:

```bash
echo 'SCORECARD_MIGRATE_DB=mysql://scorecard_migrate:another-long-random-password@db.yourcompany.com/scorecard' \
  | sudo tee /etc/scorecard/migrate.env >/dev/null
sudo chmod 600 /etc/scorecard/migrate.env
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
| Get a locked-out admin back in | `sudo scorecard-manage reset-password EMAIL`: prints a 5-minute reset code, for when mail is not working |
| Apply database changes by hand | `sudo scorecard-manage upgrade` (the installer does this on every update) |
| Change someone's role | `sudo scorecard-manage set-role EMAIL admin` (`viewer`, `admin`, `system_admin`) |
| See disk use | `sudo du -sh /var/lib/scorecard/*` |

## Settings

These live in `/etc/scorecard/scorecard.env`. Restart the service after a
change.

| Setting | Set by install to | Meaning |
|---|---|---|
| `SCORECARD_DB` | local MySQL, random password | The database address the app runs as. That account can read and write rows only |
| `SCORECARD_AUTO_MIGRATE` | `0` | `0`: the app only checks that the tables are up to date. `1` (a laptop): it updates them itself |
| `SCORECARD_PUBLIC_URL` | `https://` + `SERVER_NAME` | The address of the "Open Scorecard" button in the emails |
| `SCORECARD_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD` | empty, `587` | The mail server (see "Email"). Empty: sign-ups and resets are refused |
| `SCORECARD_MAIL_FROM` | empty | The From address. Empty: the SMTP user |
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
| Service will not start; log says **the database is at migration ...** | The code was updated but the database was not | `sudo scorecard-manage upgrade`, then `sudo systemctl restart scorecard` |
| Sign-up says **This server cannot send email yet** | Mail is not set up | "Email", above |
| Sign-up or reset says **The email could not be sent just now** | The mail server refused or did not answer | `sudo journalctl -u scorecard -n 50` shows its reply. Usually the SMTP password, or SMTP AUTH turned off for the mailbox |
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
