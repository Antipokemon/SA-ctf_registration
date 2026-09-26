# SA-ctf_registration

Native Splunk Enterprise 10.4 registration app for the deprecated Splunk CTF scoreboard.

## Features

- Server-side registration window: DISABLED / UPCOMING / OPEN / CLOSED.
- Username comes from the authenticated Splunk session and cannot be supplied by the browser.
- Creates or updates records in `SA-ctf_scoreboard`'s `ctf_users` KV Store.
- Display name, team, first/last name, optional email.
- Search URL, event name, and scoring URL are assigned by the server.
- Admin page controls registration dates and shows the current event roster.
- Registration deadline is checked by the Python REST handler, not only in JavaScript.

## Install

Build:

```bash
make package
```

Install `dist/SA-ctf_registration-1.0.0.spl` through Splunk Web or extract it under `$SPLUNK_HOME/etc/apps`.

Restart Splunk after first install because the app adds `restmap.conf` and `web.conf` endpoints.

## Writer account

The REST endpoint authenticates a dedicated Splunk account to write the scoreboard KV Store. The default username is `svcaccount` and is configured in `default/ctf_registration.conf`.

Create the local secret after installation:

```bash
podman exec -u splunk splunk bash -lc '
mkdir -p /opt/splunk/etc/apps/SA-ctf_registration/local
cat > /opt/splunk/etc/apps/SA-ctf_registration/local/registration_secrets.conf <<EOF2
[writer]
password = REPLACE_WITH_SERVICE_ACCOUNT_PASSWORD
EOF2
chmod 600 /opt/splunk/etc/apps/SA-ctf_registration/local/registration_secrets.conf
'
```

Do **not** commit this file.

The writer account must have permission to read and write the `SA-ctf_scoreboard` `ctf_users` collection. If its current role cannot write that collection, grant the collection write ACL to the writer's role rather than granting write access to competitors.

## Roles

- `ctf_registration`: participant-facing role that imports `user`.
- `ctf_registration_admin`: registration administrator role. The admin REST endpoints also accept Splunk's `admin` role and the existing `ctf_admin` role.

Assign competitors `ctf_registration` in addition to the scoreboard role you use for the event.

## Default registration configuration

`default/ctf_registration.conf`:

```ini
[registration]
enabled = false
opens_at = 2026-10-01T12:00:00Z
closes_at = 2026-10-05T23:59:59Z
event = CTF-2026
search_url = http://127.0.0.1:8000
search_url_desc = Splunk Search
scoring_url =
allow_updates = true
scoreboard_app = SA-ctf_scoreboard
users_collection = ctf_users
writer_username = svcaccount
```

Times must be ISO-8601 timestamps with a timezone. `Z` means UTC.

The admin page writes changes to `local/ctf_registration.conf`.

## URLs

Participant page:

`/en-US/app/SA-ctf_registration/register`

Admin page:

`/en-US/app/SA-ctf_registration/admin`

REST endpoints:

- `GET  /servicesNS/nobody/SA-ctf_registration/ctf_registration/status`
- `POST /servicesNS/nobody/SA-ctf_registration/ctf_registration/register`
- `GET  /servicesNS/nobody/SA-ctf_registration/ctf_registration/admin/config`
- `POST /servicesNS/nobody/SA-ctf_registration/ctf_registration/admin/config`
- `GET  /servicesNS/nobody/SA-ctf_registration/ctf_registration/admin/roster`

## Logs

`$SPLUNK_HOME/var/log/splunk/ctf_registration.log`

## Test

Pure-Python tests do not require Splunk:

```bash
make test
```
