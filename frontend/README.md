# OpsCore demo screens

A Next.js app for showing OpsCore to prospects. Each scenario is one pain point
from the research (*Oil & Gas and Maritime, US vs LATAM*), run live against the
real OpsCore API: the events, messages, alerts, notifications, work orders and
audit entries on screen are all real API records.

## Run it

The backend must be running first, with the demo clients seeded:

```bash
cd ../backend
.venv/Scripts/python -m app.cli migrate
.venv/Scripts/python -m app.cli seed-demo
.venv/Scripts/python -m uvicorn app.main:app --port 8000
# in a second terminal: reminders, overdue work orders, auto hand-back
.venv/Scripts/python -m app.worker
```

Then, in this folder:

```bash
npm install
npm run dev          # http://localhost:3010
```

Settings (optional, see `.env.example`):

| Variable | Default |
|---|---|
| `OPSCORE_API_URL` | `http://127.0.0.1:8000` |
| `OPSCORE_DEMO_PASSWORD` | `demo-password-1234` |

## What is in it

| Page | What it shows |
|---|---|
| `/` | The four demo markets, the scenarios to lead with for each, and the six research pains mapped to their demo |
| `/demo/<id>` | One scenario: the opening figure, what to say, steps to run one by one, and the live result |
| `/console/<client>` | The operations console: alerts (acknowledge, resolve, reopen), work orders (start, done, cancel), conversations (read, reply as a person, hand back, close), audit trail with chain check, and setup (read-only) |
| `/record/<client>/<alert>` | The incident record for one alert: what was reported, who was told and when, work orders, the timeline and the chain check. Printable, for an insurer or an auditor |

| Scenario | Client | Pain |
|---|---|---|
| `us-og-safety` | Permian Ridge Operating | O&G 1 |
| `us-og-after-hours` | Permian Ridge Operating | O&G 3 |
| `latam-og-assets` | Andes Energy | O&G 2 |
| `latam-og-contractors` | Andes Energy | O&G 1 (hypothesis) |
| `latam-port-disruption` | Terminal Atlântico | Maritime 1 |
| `latam-port-yard` | Terminal Atlântico | Maritime 2 (hypothesis) |
| `us-port-yard-safety` | Bayou Container Terminal | Maritime 2 |
| `us-port-congestion` | Bayou Container Terminal | Maritime 1 |
| `us-port-records` | Bayou Container Terminal | Maritime 3 (short context demo) |

The home page follows the research's "Priority by market" table: for each market, the
demo to lead with, the one to show next, and what to skip. Every scenario page carries the
opening figure, what to say, the steps, the closing question, and the research's discovery
questions for that pain.

Scenario content lives in `src/lib/scenarios.ts`; the code that runs each step
is in `src/lib/runner.ts`.

## How it talks to OpsCore

The browser never holds credentials. Every call goes through
`/api/ops/<client>/...`, a server route that only allows the API paths the
screens use:

- People's actions use the demo client's owner login.
- Device traffic (sensor events, inbound WhatsApp/SMS) uses a device API key.
  The proxy creates one per client the first time it is needed and keeps it in
  memory.

## Demo behaviour to know

- Opening or restarting a scenario resolves the client's alerts that are still
  open, with the note "Closed before a new demo run". OpsCore merges repeat
  events into an open alert without messaging anyone again, so without this a
  second run would show nobody being told.
- Each run uses new sender phone numbers, so conversations left with a person
  from an earlier run do not swallow the new messages.
- Messages are sent through OpsCore's log provider unless Twilio is configured
  in the backend, so nobody's phone is actually messaged.
- Times on screen are the client's own time zone (Texas time for Permian, São Paulo
  time for Terminal Atlântico), not the presenter's laptop.
- The proxy only lets the screens read setup and act on alerts, work orders and
  conversations; it cannot change rules, contacts or settings. Don't host it publicly
  without putting a login in front of it: anyone who can open it acts as the demo owner.
