# OpsCore

One platform for many oil & gas and maritime clients. Something happens at a
site, the right person finds out straight away, and a clean record is kept.

```
 drone / camera / sensor / WhatsApp / phone / person
                     │  events and messages
                     ▼
 ┌───────────────────────────────────────────────────────────┐
 │ CORE   clients · sites · assets · contacts · event types  │
 │        rules ("if this happens, do that") · alerts        │
 │        work orders · notifications · tamper-evident audit │
 └───────────────────────────────────────────────────────────┘
          │                                   │
   alerts by SMS, WhatsApp, email      OPS ASSISTANT module
   work orders, evidence trail         answers drivers and truckers in
                                       EN/ES/PT from approved answers,
                                       hands everything else to a person
```

It came out of the pain-point research (*Oil & Gas and Maritime, US vs LATAM*).
All six pains share one shape: **event → right person told → record kept**. So
this is one engine that each client configures, not six apps.

| Research pain | Covered by |
|---|---|
| O&G 1: safety and compliance at remote sites | Event types, rules, alerts, notifications, audit trail |
| O&G 2: visibility over remote assets | Sites and assets, CSV import, measurement events |
| O&G 3: workforce gap, after-hours coordination | Ops Assistant (WhatsApp/SMS, EN/ES/PT) |
| Maritime 1: congestion, status questions on disruption days | Ops Assistant plus gate and queue events; repeated events merge into one alert |
| Maritime 2: yard safety | Near-miss events, rules, work orders |
| Maritime 3: compliance, cyber, evidence | Hash-chained audit log with a verify endpoint |

## Status

**Built and tested:** the backend API, database, background worker and Ops
Assistant module. All automated tests pass (the PostgreSQL-only ones are skipped
on SQLite); lint is clean.

**Loops the worker closes** (run `python -m app.worker` next to the API):
- An alert nobody acknowledges is sent again to the same people: critical every
  10 min, high 30 min, medium 1 h, low 2 h, or the rule's own interval.
- A work order past its due time is reported once to its assignee, or to the
  people its rule notifies.
- A conversation handed to a person that nobody answers for 8 hours goes back to
  the assistant with an apology to the sender, and its alert is resolved.
- A message that still fails after its retries (about three hours) is written to
  the audit trail as `notification.failed`.

**Demo screens (`frontend/`):** a Next.js app with one live scenario per
research pain, run against this API, plus an operations console per demo
client (alerts, work orders, conversations, audit trail, setup). See
[frontend/README.md](frontend/README.md).

**Not built yet:**
- Admin screens for editing setup (sites, rules, contacts, answers). The demo
  console shows setup read-only; editing is done through the API docs at `/docs`.
- Adapters for real WhatsApp/Twilio inbound webhooks. Inbound uses a generic
  JSON shape, and outbound sending through Twilio is built.
- Real detectors. AeroTwin's drone detections become events here once connected.

**Checked against PostgreSQL 17:** the whole suite passes, including the
row-level security tests, with the API connecting as a role that does not own
the tables and, separately, as a single non-superuser owner role (the way Neon
works on Vercel). See [Testing](#testing).

## What a client can configure without code

| Setting | Example |
|---|---|
| Sites and assets (form or CSV upload) | `PAD-07`, `GATE-A`, tank batteries, cranes |
| Event types and the fields they carry | `gas_detection` with `gas` (choice) and `ppm` (number, min 0) |
| Rules | if `attributes.ppm >= 10` and `asset.criticality >= 4`, then critical, SMS + email the `safety_lead`, open an urgent work order due in 2 h |
| Contacts and roles | who is `safety_lead`, `on_call_coordinator`, `yard_supervisor` |
| Language and units | EN/ES/PT per person; imperial or metric per client |
| Modules | Ops Assistant on or off |
| Assistant answers | approved text per language, optionally per site |

New clients start from an industry **starter pack** (event types and rules for
oil & gas or maritime) that they can edit or switch off. Packs never create
assistant answers: an invented gate time sent to a real driver is worse than
"a person will reply".

## Run it locally

Needs Python 3.12+.

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m app.cli migrate
.venv/Scripts/python -m app.cli seed-demo          # four invented demo clients
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs. `seed-demo` prints the demo logins and API keys:

- **Permian Ridge Operating (demo)**: US oil & gas, English, imperial units.
- **Andes Energy (demo)**: LATAM oil & gas, Spanish, metric.
- **Bayou Container Terminal (demo)**: US maritime.
- **Terminal Atlântico (demo)**: LATAM maritime, Portuguese.

All four have the assistant on and use the password `demo-password-1234`.

Try it:

```bash
# A gas sensor reports 18 ppm H2S on a tank battery
curl -X POST localhost:8000/api/v1/events -H "X-API-Key: <Andes key>" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"gas_detection","asset_code":"TB-07-1","attributes":{"gas":"h2s","ppm":18}}'

# A driver asks on WhatsApp, in Spanish
curl -X POST localhost:8000/api/v1/assistant/inbound -H "X-API-Key: <Andes key>" \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender":"+5492994441111","body":"Hola, cual es el horario de ingreso al pad 7?"}'
```

The worker delivers retries and closes idle conversations:
`python -m app.worker` (or `--once` from a scheduler).

### With Docker (PostgreSQL)

```bash
docker compose up --build
docker compose run --rm api python -m app.cli create-platform-admin --email you@company.com --name "You"
```

Change every password in `docker-compose.yml` and `deploy/init-roles.sql` first.

## How it works

### Multi-client isolation, enforced twice

1. **In the application.** Every query on client data filters on `org_id`
   (`app/services/scoping.py`). An id that belongs to another client returns
   *404 not found*, never *403*, so ids cannot be used to probe.
2. **In PostgreSQL.** Migration `0002` turns on row-level security for every
   client table. Each transaction pins `app.current_org` (`app/db.py`), so even
   a query that forgets its filter only sees the current client's rows.

   This only works if the API connects as an ordinary role, because superusers
   and table owners bypass it. That's why there are two URLs:
   `OPSCORE_DATABASE_URL` (app role) and `OPSCORE_MIGRATION_DATABASE_URL`
   (owner).

### Event → alert → notification

`app/services/events.py`

1. **Validate.** The event type must exist and be active, and the site and
   asset must belong to this client. Attributes are checked against the event
   type's schema. Timestamps must carry a time zone and fall between 30 days
   ago and 5 minutes ahead.
2. **Store** the event. It's immutable evidence. Sending the same
   `Idempotency-Key` again returns the original event, so device retries never
   duplicate.
3. **Evaluate active rules.** Evaluation never throws: missing or mistyped data
   makes a condition false.
4. **Raise the alert.** A match opens an alert, or **merges** into the live
   alert for the same rule and location, so 300 identical events during a
   strike become one alert with a count, not 300 texts. A merge re-notifies
   only when severity rises, or on the rule's reminder interval.
5. **Notify.** Notifications go to an outbox and are delivered after the
   response. Failures retry with exponential backoff (30 s up to 1 h, then
   give up). Permanent failures, such as a bad number, stop at once.
   Delivery is at-least-once.

### Ops Assistant

`app/assistant/`

| Message | What happens |
|---|---|
| Emergency words (fire, herido, vazamento...) | Critical escalation and a safety reply. This still fires even if a person already owns the chat. |
| "talk to a person" / "hablar con alguien" | Hand-off reply; conversation escalated |
| Person already handling it | Bot stays quiet |
| Covered by an approved answer | Reply in the sender's language |
| Anything else | "A person will reply"; escalated |

Escalations are ordinary `assistant.escalation` events, so they use the same
rules, alerts and notifications as everything else.

There are two answerers:
- **Keyword matching**: offline and free. Always on, and the fallback.
- **Claude** (`OPSCORE_ASSISTANT_LLM_ENABLED=true`, model `claude-opus-5-5`):
  understands paraphrases. It may only answer from the approved entries and
  must cite them; uncited answers are discarded. Sender messages are treated
  as untrusted input. Any outage, refusal or rate limit falls back to keyword
  matching. Needs `OPSCORE_ANTHROPIC_API_KEY` (or `ANTHROPIC_API_KEY`); the app
  refuses to start with Claude switched on and no key.

Thanks, greetings and "ok" get a short courtesy reply and are never escalated.
Escalated conversations go back to the assistant after
`OPSCORE_ASSISTANT_ESCALATION_HANDBACK_HOURS` (default 8) with no reply from the team.

A site-specific answer is only sent when the sender names that site, matched
the way people type ("pad 7" = `PAD-07`; "pad 17" does not match).

### Audit trail

Every configuration change and every human action is recorded with who, what,
when and the request id. Entries are hash-chained per client.
`GET /api/v1/audit/verify` recomputes the chain and reports the first entry
that was edited or removed.

### Roles

| Role | Can |
|---|---|
| viewer | read sites, assets, events, alerts, work orders, notifications, conversations |
| member | + report events, update work order status |
| supervisor | + acknowledge/resolve alerts, manage work orders, reply in assistant chats |
| admin | + configure sites, rules, contacts, API keys, members below admin, read audit |
| owner | + manage admins and owners (there is always at least one owner) |

API keys get narrow scopes instead of roles: `events:write`, `events:read`,
`messages:write`.

## Edge cases handled

- **Clients:** cross-client ids and codes; the same site code used by two
  clients; adding a person who already has an account (their password is never
  changed); the last owner can't be removed; admins can't create admins.
- **Sign-in:** wrong password and unknown email look identical (timing too);
  rate limits on sign-in and per WhatsApp sender; password change and
  "sign out everywhere" kill old tokens; revoked and expired keys stop working;
  passwords over 72 bytes are fully checked.
- **Events:** missing time zone, future or stale timestamps, asset not at the
  named site, deactivated site or asset, wrong attribute types, undeclared
  attributes (kept, with a warning), retries, concurrent duplicates.
- **Rules:** invalid rules rejected with every problem listed; schema changes
  that would break a live rule are refused; templates can't reach Python
  internals; contacts without an address are recorded as *skipped*; rules that
  notify nobody are audited.
- **CSV import:** Excel BOM, Windows-1252, `;` delimiter and decimal commas
  (`-38,5476`), blank trailing rows, duplicate codes, unknown sites. All or
  nothing, with every error reported by row number.
- **Assistant:** duplicate webhook delivery returns the same reply; media-only
  messages; language switching mid-chat; two messages from one sender at once;
  closed chats start fresh; idle chats auto-close (escalated ones never do).

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest        # 373 tests (5 PostgreSQL-only are skipped), in-memory SQLite
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

Against PostgreSQL, including the row-level security tests (needs a
non-superuser app role, see `deploy/init-roles.sql`):

```bash
OPSCORE_TEST_DATABASE_URL=postgresql+psycopg://opscore_app:PW@localhost:5432/opscore_test \
OPSCORE_TEST_MIGRATION_DATABASE_URL=postgresql+psycopg://opscore:PW@localhost:5432/opscore_test \
.venv/Scripts/python -m pytest
```

## Deploy to Vercel (one project)

`vercel.json` at the repository root deploys everything as a single Vercel project:

| Part | Folder | On Vercel |
|---|---|---|
| Demo screens (Next.js) | `frontend/` | Service `web`, public at `/` |
| OpsCore API (FastAPI) | `backend/` | Service `api`, private: only the web service reaches it, through a binding that sets `OPSCORE_API_URL` |
| Worker (reminders, overdue work orders, hand-back) | `backend/` | Daemon `worker`, built from `backend/Dockerfile`, production deployments only |

The local SQLite file cannot be used on Vercel (its disk is temporary), so the
deployment uses PostgreSQL.

1. Push this repository to GitHub.
2. In Vercel: **Add New → Project**, import the repository and keep the root
   directory as the repository root. Vercel reads `vercel.json`.
3. **Storage → Create Database → Neon (Postgres)** and connect it to the project.
   This sets `DATABASE_URL` and `DATABASE_URL_UNPOOLED`, which OpsCore reads.
4. **Settings → Environment Variables**:
   - `OPSCORE_ENVIRONMENT` = `production`
   - `OPSCORE_JWT_SECRET` = a long random value, from
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`
5. Create the tables and the four demo clients once, from your machine, using the
   database's direct connection string (Neon: `DATABASE_URL_UNPOOLED`). In PowerShell:

   ```powershell
   cd backend
   $env:OPSCORE_DATABASE_URL = "<DATABASE_URL_UNPOOLED from Vercel>"
   $env:OPSCORE_JWT_SECRET = "<the same secret as on Vercel>"
   .venv/Scripts/python -m app.cli migrate
   .venv/Scripts/python -m app.cli seed-demo
   ```

   Remove the two variables afterwards (or close the terminal) so local runs use SQLite again.
6. Deploy (or redeploy) to production. Open the project URL: the home page should
   show "Connected" at the top right.

Anyone who opens the URL acts as the demo owner. Keep the link private, or turn on
Vercel Deployment Protection for production.

## Production checklist

- `OPSCORE_ENVIRONMENT=production`. The app refuses to start with SQLite,
  the development JWT secret, or bcrypt cost below 12, and hides `/docs`.
  The development JWT secret is also refused with any non-SQLite database, and
  `docker compose` will not start until `OPSCORE_JWT_SECRET` is set.
- Two database roles, as above. Run `python -m app.cli migrate` on every deploy.
- Run at least one `python -m app.worker`.
- Put a TLS proxy in front. The rate limiters are per process, so move them to
  Redis before running several API replicas.
- Configure SMTP/Twilio, or notifications only go to the log.

## Layout

```
backend/
  app/
    main.py              FastAPI app, middleware, health checks
    config.py            settings (OPSCORE_*), production guard
    db.py                engine, sessions, UTC timestamps, tenant hook for RLS
    models/              tables
    schemas/             request/response bodies (unknown fields rejected)
    services/            business logic; flush, never commit
      events.py          intake -> rules -> alerts -> work orders -> notifications
      rules.py           rule validation and evaluation (pure functions)
      audit.py           hash-chained audit log
      imports.py         CSV import
    assistant/           Ops Assistant: language, answerers, conversations
    notify/              providers (log, SMTP, Twilio) and the retrying dispatcher
    packs/               starter packs per industry
    api/                 routes and auth dependencies
    cli.py  worker.py
  alembic/versions/      0001 schema, 0002 row-level security
  tests/                 368 tests (+5 PostgreSQL-only)
deploy/init-roles.sql
docker-compose.yml
```
