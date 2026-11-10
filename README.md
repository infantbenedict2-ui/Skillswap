# SkillSwap

## Local development and database configuration

From the project directory, activate the existing virtual environment and run the Flask entry point:

```powershell
.\.venv\Scripts\Activate.ps1
python .\app.py
```

The development server binds to `127.0.0.1:5000` by default. Open <http://127.0.0.1:5000/> (or <http://localhost:5000/>). Port `5057` is not used unless explicitly selected. Configure an intended port with `$env:SKILLSWAP_PORT` and host with `$env:SKILLSWAP_HOST`. Keep the default loopback host for local-only use. `$env:SKILLSWAP_DEBUG = "true"` enables Flask debugging; do not enable it on a public or production server. The server disables the reloader to prevent duplicate startup initialization.

The application accepts a SQLAlchemy URL in `SKILLSWAP_DATABASE_URL` (preferred) or `DATABASE_URL`. MySQL uses PyMySQL. Create the database and least-privilege application account first, then set the URL in the same PowerShell session:

```powershell
$secureUrl = Read-Host "Private MySQL SQLAlchemy URL" -AsSecureString
$urlPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureUrl)
try {
    $env:SKILLSWAP_DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($urlPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($urlPointer)
}
python .\app.py
```

URL-encode reserved characters in credentials. Never commit a real connection URL. If neither variable is set, the existing SQLite database at `instance\skillswap.db` is used. In development, startup creates missing tables and applies additive initialization unless `SKILLSWAP_SKIP_DATABASE_INIT=true`; it does not drop existing tables or records. Production requires that flag and uses explicit Flask-Migrate commands instead. A successful SQLite test does not verify a MySQL connection. If MySQL is unavailable or misconfigured, the application reports the SQLAlchemy startup error; fix the service, URL, database grants, or driver configuration rather than switching ports.

### Production MySQL configuration and safe connection check

The declared MySQL driver is PyMySQL. Production accepts `SKILLSWAP_DATABASE_URL`
(preferred) or `DATABASE_URL`; both are read from the process environment or
hosting-provider secret manager. A generic `mysql://` URL is normalized to
`mysql+pymysql://`; other MySQL drivers are rejected. The password must be
URL-encoded when it contains reserved URL characters. Use a unique,
least-privilege application account and restrict database network access to
the application host.

Create the production database with `utf8mb4` and a matching collation before
applying migrations, for example `utf8mb4_unicode_ci` or a MySQL-supported
`utf8mb4_*` collation. The application opens PyMySQL connections with
`charset=utf8mb4` and initializes each connection's session time zone to UTC.
`db-check` verifies connectivity with a read-only `SELECT 1`, then reports
server version, connection/database character sets, database collation,
session time zone, and foreign-key enforcement. It exits with an error if
these settings do not meet the application requirements.

Set the connection string in a private environment variable; do not put a real
credential in `.env.example`, README files, shell history, screenshots, or
source control. Example shape only (replace every placeholder privately):

```text
mysql+pymysql://<user>:<url-encoded-password>@<approved-host>:3306/<database>?charset=utf8mb4
```

In PowerShell, read a URL without echoing it and run the non-mutating check:

```powershell
$env:SKILLSWAP_ENV = "production"
$secureUrl = Read-Host "Private MySQL SQLAlchemy URL" -AsSecureString
$urlPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureUrl)
try {
    $env:SKILLSWAP_DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($urlPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($urlPointer)
}
$env:SKILLSWAP_SKIP_DATABASE_INIT = "true"
python -m flask --app app db-check
```

Configure the other required production secrets/settings through the same
secret manager before loading the production app. The command does not create
tables or alter records; however, set `SKILLSWAP_SKIP_DATABASE_INIT=true`
before invoking it so the legacy development startup initializer is skipped.
It connects only to the exact database URL explicitly provided to the process.
Do not run it against an unapproved or unknown database. A successful check
does not validate credentials for a separate account, schema completeness,
backup recovery, migration execution, or hosting network policy. Use
`flask db check` after migrations to compare model metadata with the schema.

SQLAlchemy uses `pool_pre_ping` to detect stale pooled connections and recycles
connections every 1800 seconds. Flask-Migrate/Alembic operate through the same
SQLAlchemy PyMySQL engine; reviewed migration commands are run explicitly, not
by application workers. Validate migrations against a disposable MySQL
database with the same MySQL/MariaDB version and collation before scheduling
production changes. The test suite uses SQLite and does not establish that a
live production MySQL server is reachable or compatible.

To check whether port 5000 already has a listener before starting another copy:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue
```

If the existing SkillSwap process is already listening on 5000, use that server and browser URL rather than starting a duplicate. Flask reports a bind error if another process owns the configured port.

## Production preparation (not deployed)

Production requires MySQL, a `FLASK_SECRET_KEY` with at least 32 bytes, a
canonical HTTPS `SKILLSWAP_PUBLIC_URL`, a matching `SKILLSWAP_TRUSTED_HOSTS`
allowlist, `SKILLSWAP_COOKIE_SECURE=true`, and `SKILLSWAP_ADMIN_EMAIL`. The app
fails at startup if these are missing or invalid; SQLite is for development
and tests only. Use a least-privilege MySQL account and set
`SKILLSWAP_DATABASE_URL` to a `mysql+pymysql://...` SQLAlchemy URL, URL-encoding
reserved characters. Never put private credentials in source control.

`.env.example` lists supported variables but is documentation only; the app
does not load it. Store values in the hosting provider's secret manager.
`.gitignore` excludes environment files, the virtual environment, and
`instance/`, which contains the local database, persisted development secret,
and private uploads. This workspace has no Git repository; inspect files and
run secret scanning before initializing or publishing one.

### Database migrations and administrator setup

The project uses Flask-Migrate/Alembic for versioned schema changes. The
initial revision creates the baseline schema and inserts the built-in skill
catalog on a **new, empty database**; a follow-up revision aligns existing
report/review foreign-key actions with the SQLAlchemy models. The migration
chain does not modify an existing database unless an operator explicitly runs
a migration command. Production requires `SKILLSWAP_SKIP_DATABASE_INIT=true`;
schema changes must never run implicitly when WSGI workers start.

For a new, empty database, first configure `SKILLSWAP_DATABASE_URL` and the
other required environment variables, including
`SKILLSWAP_SKIP_DATABASE_INIT=true`, then run this once from the project
directory:

```sh
python -m flask --app app db upgrade
```

For PowerShell, set the variables in that same shell session before running
the command. To create a future migration after changing SQLAlchemy models:

```sh
python -m flask --app app db migrate -m "Describe the schema change"
```

Review every generated revision before applying it: autogeneration cannot
reliably infer renames, data transformations, or every database-specific
operation. Apply reviewed revisions explicitly with `flask db upgrade`.
`flask db check` checks for model/schema drift once the database is at the
current revision.

#### Adopting an existing database

Never run the initial `upgrade` against a database that already contains the
SkillSwap tables; it would fail because those tables already exist. Back up
the database, restore a copy into an isolated verification database, and set
`SKILLSWAP_DATABASE_URL` to that copy with
`SKILLSWAP_SKIP_DATABASE_INIT=true`. Stamp the copy at the baseline, apply the
forward migration, then verify the resulting schema:

```sh
python -m flask --app app db stamp 07abe9ce39eb
python -m flask --app app db upgrade
python -m flask --app app db check
```

`stamp 07abe9ce39eb` records the baseline revision only; it does not create,
alter, or seed tables. `db upgrade` applies only the later forward changes.
`db check` verifies the final copied schema against current models. If upgrade
fails or `db check` reports drift, stop and prepare/review a reconciliation
migration for that exact schema. Only after the copied database passes and a
restorable backup has been confirmed, point `SKILLSWAP_DATABASE_URL` to the
original database, run `db stamp 07abe9ce39eb` once, then `db upgrade`. This
preserves existing rows while applying the reviewed forward change. Do not run
the initial `upgrade` against an unstamped pre-existing schema. The initial
revision intentionally refuses downgrade because dropping its tables would
delete user data. Do not use database reset, downgrade, or `drop_all` commands
on a database with user data.

Local development retains the pre-existing additive startup initialization
behavior unless `SKILLSWAP_SKIP_DATABASE_INIT=true` is set. For repeatable
migration testing or explicit migration operations, set that variable to
`true` so application import cannot initialize or alter the database first.
No migration command is run automatically by a web worker.

Register the intended administrator through the normal registration flow,
then set `SKILLSWAP_ADMIN_EMAIL` to that account's exact email and run:

```sh
python -m flask --app app promote-admin
```

Production never auto-promotes the first public registrant.

### WSGI startup, TLS, and uploads

Install `requirements.txt` on a supported Linux host. Gunicorn is included
only for non-Windows platforms; Windows remains supported for local
development, but is not the documented production runtime. Start the app with:

```sh
gunicorn --workers 2 --bind 0.0.0.0:8000 wsgi:app
```

Run behind a hosting platform or reverse proxy that terminates TLS and forwards
only trusted traffic. Configure its HTTPS/host handling to match
`SKILLSWAP_PUBLIC_URL` and `SKILLSWAP_TRUSTED_HOSTS`; do not expose Flask's
development server. `/health` performs a database readiness query and returns
503 if the database is unavailable. It does not verify schema completeness or
SMTP delivery.

Uploads live in `instance/uploads/`, outside Flask's static directory. Provide
persistent private storage and write permission for the service account, and
include uploads in secured backups. Malware scanning is not implemented;
uploaded files are not guaranteed malware-free. Use a private object store and
scanning pipeline if required by the deployment threat model.

### Email and hosting checklist

Password reset email requires `SKILLSWAP_EMAIL_ENABLED=true`,
`SKILLSWAP_SMTP_HOST`, `SKILLSWAP_SMTP_PORT`, and `SKILLSWAP_EMAIL_FROM`.
Provide both `SKILLSWAP_SMTP_USERNAME` and `SKILLSWAP_SMTP_PASSWORD` if the
SMTP provider requires authentication. SMTP uses STARTTLS. Successful SMTP
submission means the server accepted the message, not that it arrived in the
recipient's inbox. Email sending is disabled in automated tests.

Before hosting, configure TLS, managed MySQL, persistent upload storage,
secret rotation and backup, database/upload backups, monitoring and log
retention, outbound SMTP, DNS, and a tested restore procedure. Restrict
database/network access to the application. Review hosting-specific worker,
timeout, health-check, and secret-management requirements. No deployment,
production host, live MySQL connection, or live SMTP account was configured or
verified during this task.

## Session scheduling API

All session endpoints require an authenticated user. JSON requests use
`Content-Type: application/json`. Session dates use `YYYY-MM-DD`; times use
24-hour `HH:MM` or `HH:MM:SS` format, interpreted as UTC. The API derives the
skill from the accepted request. In the existing request flow, the request
sender is the learner and the receiver is the teacher.

### Create a session

`POST /api/sessions` — either participant on the accepted request may create it.

```json
{
  "skill_request_id": 12,
  "teacher_id": 4,
  "learner_id": 9,
  "title": "Python functions",
  "date": "2027-03-18",
  "start_time": "14:00",
  "end_time": "15:00",
  "notes": "Bring a laptop"
}
```

Returns `201` with the session. A participant cannot have overlapping
`SCHEDULED` or `IN_PROGRESS` sessions on the same date.

### List and filter sessions

`GET /api/sessions?filter=upcoming&page=1&per_page=20`

Filters are `upcoming` (future scheduled sessions), `in_progress`, `completed`,
and `cancelled`. Pagination defaults to page 1 and 20 items per page; `per_page`
is limited to 100. The response includes a `sessions` array and `pagination`
metadata (`page`, `per_page`, `total`, and `pages`).

### View or update a session

- `GET /api/sessions/<id>` — returns session details to either participant.
- `PUT /api/sessions/<id>` — participants may update `date`, `start_time`,
  `end_time`, and/or `notes` while the session is `SCHEDULED`.

### Change session status

- `POST /api/sessions/<id>/start` — changes `SCHEDULED` to `IN_PROGRESS`.
- `POST /api/sessions/<id>/confirm-completion` — records the caller's
  completion confirmation. The session becomes `COMPLETED` only after both
  participants confirm.
- `POST /api/sessions/<id>/cancel` — changes a scheduled or in-progress session
  to `CANCELLED`. Cancelled sessions cannot be completed.

Statuses are `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`.
Session creation, updates, cancellation, start, completion confirmations, and
completion each create participant notifications.

## Session ratings

The existing `Review` model stores session ratings along with the app's
request-based reviews. A session rating is allowed only after the session is
`COMPLETED`; either participant may independently rate the other once. Ratings
are integers from 1 through 5. Reviewer and reviewed-user identities are
derived from the authenticated user and the other session participant. A
notification is sent to the rated participant.

All rating endpoints require authentication. Session rating details are visible
only to that session's participants; authenticated users can view active users'
public rating summaries.

### Submit a rating

`POST /api/ratings`

```json
{
  "session_id": 27,
  "rating": 5,
  "comment": "Clear and helpful session"
}
```

`comment` is optional (maximum 1,000 characters). The response is `201` with
the recorded rating. Requests fail if the session is not completed, the caller
is not a participant, the rating is outside 1–5, or the caller already rated
that session.

### Read ratings

- `GET /api/ratings/user/<user_id>` — public average, count, 1–5 distribution,
  and rating entries for the user.
- `GET /api/ratings/session/<session_id>` — rating summary and entries, limited
  to session participants.
- `GET /api/ratings/me` — the authenticated user's received summary and ratings
  plus ratings they have given.

Summaries include `average_rating`, `rating_count`, and `rating_distribution`
(keys `"1"` through `"5"`, including zero counts). The public profile displays
the average, total review count, and star distribution.

## Notifications

Notifications are stored per user with a title, message, type, optional related
entity ID, read state, and creation timestamp. Existing notification records
are retained and receive a title during startup schema migration. The app
creates notifications for new/accepted/rejected/cancelled skill requests, new
chat messages, session scheduling/updates/cancellation/completion and
completion confirmations, and ratings received. The notification page supports
all/unread views, read actions, deletion, timestamps, and links to related app
areas.

All notification APIs require authentication and operate only on the current
user's notifications.

### Notification API endpoints

- `GET /api/notifications` — returns the current user's notifications, newest
  first, with pagination. Optional query parameters: `unread=true|false`,
  `page` (default 1), and `per_page` (default 20, maximum 100).
- `GET /api/notifications/unread-count` — returns `{"unread_count": 3}`.
- `POST /api/notifications/<id>/read` — marks one owned notification as read.
- `POST /api/notifications/read-all` — marks all of the current user's
  notifications as read.
- `DELETE /api/notifications/<id>` — deletes one owned notification (204 on
  success).

Example:

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:5000/api/notifications?unread=true&page=1&per_page=20" `
  -Headers @{ Cookie = "session=YOUR_AUTHENTICATED_SESSION_COOKIE" }
```

The JSON notification shape includes `id`, `user_id`, `title`, `message`,
`type`, `related_entity_id`, `is_read`, `created_at`, and `href`. Unsupported
filter values or invalid pagination return 400; unauthenticated API requests
return 401; attempts to read, modify, or delete another user's notification
return 404.

### Email notification service configuration

Email delivery is opt-in and is not automatically sent by web requests. The
service in `services/email_notifications.py` can be called from a background
worker after notification persistence. Set `SKILLSWAP_EMAIL_ENABLED=true`,
`SKILLSWAP_SMTP_HOST`, and `SKILLSWAP_EMAIL_FROM` to enable it. Optional
`SKILLSWAP_SMTP_PORT` defaults to 587; SMTP authentication uses
`SKILLSWAP_SMTP_USERNAME` and `SKILLSWAP_SMTP_PASSWORD` when configured. Keep
credentials in environment variables or a secret manager, never in source
control. Delivery is disabled while Flask is in testing mode.

## Privacy, blocking, and reporting

Privacy settings are stored on the user's existing account record. Profile
visibility can be `public` or `private`; location and online-status visibility
are booleans. Notification preferences can independently disable in-app
notifications for requests, messages, sessions, and ratings. Private profiles
are omitted from matching and cannot be viewed by other members; location is
hidden when its visibility is disabled.

Blocking works in either direction for access enforcement: if either member
has blocked the other, they are removed from matches and existing conversation
lists, and cannot exchange new swap requests or messages. The block owner can
view and remove their own block list.

### Privacy API

- `GET /api/privacy` — read the authenticated user's settings.
- `PUT /api/privacy` — update any of `profile_visibility`,
  `location_visibility`, `online_status_visibility`, and
  `notification_preferences`.

Example:

```json
{
  "profile_visibility": "private",
  "location_visibility": false,
  "online_status_visibility": false,
  "notification_preferences": {
    "messages": false,
    "ratings": true
  }
}
```

Preference keys are `requests`, `messages`, `sessions`, and `ratings`; supplied
values must be booleans. Settings updates may be partial.

### Block API

- `POST /api/users/<id>/block` — block an account (201 when newly blocked;
  repeated requests return 200).
- `DELETE /api/users/<id>/block` — unblock an account (204 on success).
- `GET /api/users/me/blocked` — list accounts blocked by the current user.

Blocking oneself is rejected. Block operations and lists require
authentication.

### Reporting API

- `POST /api/reports` — submit a report with `reported_user_id`, `reason`, and
  `description`.
- `GET /api/reports` — administrator-only paginated report list; optional
  `status`, `page`, and `per_page` filters.
- `GET /api/reports/<id>` — administrator-only report details.
- `PUT /api/reports/<id>/status` — administrator-only status update.

Allowed reasons are `inappropriate_behaviour`, `spam`, `fake_profile`,
`harassment`, and `other`. Descriptions are required and limited to 2,000
characters. A reporter cannot report themselves or create a second open report
for the same user. Report statuses are `submitted`, `under_review`, `resolved`,
and `rejected`; administrators can set `under_review`, `resolved`, or
`rejected`. Non-admin access to moderation endpoints returns 403.

## Administration

The admin page is available at `/admin`. It shows live database totals and
status counts, searchable/filterable users, skill category and usage information,
swap requests, sessions, report review controls with moderation notes, recent
admin audit events, and charts/tables for registrations, requests, sessions,
popular skills, and rating distribution. Skill records can be deactivated
without deleting their history.

### Admin account setup and security

Set `SKILLSWAP_ADMIN_EMAIL` to the email address of the intended administrator.
In development, startup can assign the designated existing account the admin
role and retains the existing first-user bootstrap behavior if no admin exists.
In production, the first public registrant is never promoted automatically;
create the account through registration and explicitly run
`python -m flask --app app promote-admin` with `SKILLSWAP_ADMIN_EMAIL` set.
Use a strong password. Admin pages redirect unauthenticated users to login and
deny regular users; admin APIs return 401 when unauthenticated and 403 for
non-admin users.
Admin user responses do not include password hashes or authentication tokens.
Status changes, skill changes, and report moderation are recorded in the
`activity_log` table in the same database transaction as each change.

### Admin API

All endpoints below require an authenticated administrator. List endpoints
accept `page` (default 1) and `per_page` (default 20, maximum 100) where
applicable.

- `GET /api/admin/dashboard` — live counts for users, skills, requests,
  sessions, ratings, average rating, and unresolved reports.
- `GET /api/admin/users?search=<name-or-email>&status=all|active|inactive` —
  paginated user list.
- `GET /api/admin/users/<id>` — safe user profile and usage details.
- `PUT /api/admin/users/<id>/status` — suspend/reactivate with
  `{"is_active": false}` or `{"is_active": true}`.
- `GET /api/admin/skills?category=<category>&active=all|true|false` — skill
  catalog with user and request usage counts.
- `GET /api/admin/requests?status=<status>` — request inspection; supported
  statuses are pending, accepted, rejected, cancelled, and completed.
- `GET /api/admin/sessions?status=<status>` — session inspection; supported
  statuses are SCHEDULED, IN_PROGRESS, COMPLETED, and CANCELLED.
- `GET /api/admin/reports?status=<status>` — paginated report review queue.
- `PUT /api/admin/reports/<id>/status` — set `under_review`, `resolved`, or
  `rejected`; optional `moderation_notes` is limited to 2,000 characters.
- `GET /api/admin/analytics` — monthly user/request series, session status
  counts, popular skills, and 1–5 star distribution.

## Frontend integration

The existing Flask/Jinja frontend now uses the current database and routes for
the public home catalog, skill search/detail pages, profiles, requests,
messaging, sessions, ratings, notifications, privacy, blocking, reporting, and
administration. The `/find-skills` page supports real skill/category/location
filters, minimum member rating, teaching experience, and availability. Search
excludes inactive, private, or blocked members. Teaching listings can record
beginner/intermediate/advanced experience and weekday/weekend/evening/flexible
availability; existing listings remain valid with these optional fields empty.
The dashboard shows actual upcoming sessions, and session actions, privacy
preferences, block-list changes, session ratings, and reports use the existing
authenticated JSON APIs. Form submission states and API failures are announced
accessibly, and duplicate submissions are disabled.

The layout reuses the site's responsive stylesheet and navigation patterns.
Session scheduling requires an accepted request; completion remains a
two-participant confirmation. Profile photo URLs remain supported; members can
also upload PNG, JPEG, or WebP profile images. Chat supports PNG/JPEG/WebP, PDF,
and UTF-8 text attachments. Images are validated and re-encoded with Pillow;
attachments are stored outside the static web root, assigned random filenames,
and served only to the two connected conversation participants.

### Password reset and upload configuration

`GET/POST /forgot-password` accepts reset requests. When email is enabled, a
generic response is shown for known and unknown addresses to prevent account
enumeration. The email service logs whether the SMTP server accepted or rejected
delivery; SMTP acceptance is not confirmation of delivery to the recipient's
mailbox. The service sends a single-use link that expires after one hour; only
a SHA-256 token hash is stored. `GET/POST /reset-password/<token>` validates the
token and updates the password. Configure SMTP with
`SKILLSWAP_EMAIL_ENABLED=true`, `SKILLSWAP_SMTP_HOST`,
`SKILLSWAP_EMAIL_FROM`, and
`SKILLSWAP_PUBLIC_URL=https://your-canonical-host`. `SKILLSWAP_SMTP_PORT`
defaults to 587 with STARTTLS. Optional authentication uses both
`SKILLSWAP_SMTP_USERNAME` and `SKILLSWAP_SMTP_PASSWORD`; never put credentials
in source control or logs. Reset links use the explicitly configured HTTPS
origin rather than the incoming request Host header. Do not enable email until
the SMTP host/sender, canonical URL, and (if required) credentials are
configured. Automated tests mock email and never deliver real messages.

Startup creates and verifies write access to `instance/uploads`,
`instance/uploads/profile`, and `instance/uploads/messages`; startup fails with
the required path if those directories cannot be written. Uploads are limited
to 10 MiB per request. Profile images are decoded and re-encoded as PNG, JPEG,
or WebP. Chat attachments accept those image formats, PDF, and UTF-8 text only
when the extension, declared MIME type, and checked file content agree.
Files are stored outside static serving, use random server-side names, and
downloads are authorized to conversation participants. Ensure the service
account has write access and include uploads in backup/retention planning. Do
not expose the instance directory as a static web directory. Configure a
matching request-body limit at any reverse proxy. Private profile images
require an owner/admin session; public profile images follow profile visibility.
Malware scanning is not configured; do not treat accepted file types as
malware-free.

Startup performs additive, non-destructive schema updates for the optional
skill listing and message attachment columns and creates the password-reset
token table. Existing rows are retained. Back up the database before upgrading
and apply schema changes in a maintenance window when using MySQL, whose DDL
operations may commit independently.

Configure `SKILLSWAP_COOKIE_SECURE=true` when serving the site exclusively over
HTTPS; the session cookie is HTTP-only and uses `SameSite=Lax`.

## Tests

Run the test suite with:

```powershell
python -m unittest discover -s tests -v
```

The test suite uses isolated SQLite databases. A successful local suite does
not verify connectivity, permissions, migrations, or persistence on a
configured MySQL server; validate those against the deployment database before
release.

## GitHub setup and publishing

This folder can be initialized as a Git repository after you review the
contents. The `.gitignore` rules exclude the private `instance/` directory
(including the local SQLite database, persisted development secret, and
uploads), real `.env` files, SQLite/database exports and sidecars, logs,
virtual environments, Python caches, editor conflict copies, and backup
artifacts. `.env.example` is intentionally allowed; it contains blank
configuration placeholders only. `requirements.txt` contains the Python
runtime dependencies.

Before staging, inspect the files you intend to publish and run the test suite.
After staging, review the exact staged file list and changes, and confirm the
database, `instance/`, `.env`, secrets, and backup files are absent. Do not
force-add ignored files. Never publish credentials in source files, command
history, commit messages, screenshots, test output, or repository issues.

Example next steps (replace the remote URL with your own GitHub repository;
these commands are instructions only and have not been run here):

```powershell
git init
git branch -M main
git status --short --ignored
git check-ignore -v instance\skillswap.db instance\secret_key .env .env.local
git add .gitignore .env.example README.md app.py models.py requirements.txt wsgi.py migrations services static templates tests
git status --short
git diff --cached --check
git diff --cached --name-only
git diff --cached
```

Review the staged diff carefully before making the first commit. Only after the
staged files are confirmed safe, create the GitHub repository and connect/push
it explicitly:

```powershell
git remote add origin https://github.com/<your-account>/<your-repository>.git
git remote -v
git commit -m "Prepare SkillSwap project for GitHub"
git push -u origin main
```

Do not run `git add -f` for ignored private files. If a secret was ever
committed, removing it in a later commit is not enough: rotate/revoke it and
follow GitHub's history-removal guidance before publishing.
