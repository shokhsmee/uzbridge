# uzbridge

A company SaaS that connects Uzbek payment systems to CRMs. Phase 1: a
manager creates a payment link inside an amoCRM lead, the customer pays with
Payme, Click or Uzum Bank, and the lead moves to the "Paid" stage by itself.

Each company gets its own subdomain (`acme.uzbridge.uz`). In the dashboard it
connects amoCRM (OAuth, full access), enters its own merchant keys for each
provider and picks the paid stage per pipeline. Money always goes straight to
the company's own merchant account; uzbridge only relays API calls.

## Layout

- `backend/` Django 5 + Django Ninja, Celery, PostgreSQL
  - `accounts` companies, users, memberships, subdomain handoff login
  - `payments` invoices, provider accounts (encrypted keys), the pay page, and
    `providers/{payme,click,uzum}.py` with each provider's callback state machine
  - `amocrm` OAuth, token refresh, API client with the 7 req/s limit, lead sync, widget API
- `frontend/` React + Vite + Tailwind dashboard (Uzbek / Russian)
- `widget/` amoCRM lead-card widget; `build.py` produces the archive to upload

Provider callbacks are `https://api.<domain>/cb/{payme,click,uzum}/<account-uuid>/`;
the dashboard shows each company its own URLs to paste into the provider cabinet.

## Run locally

Needs Python 3.12 with uv, Node 20+, PostgreSQL and Redis (Postgres.app and
Homebrew Redis work, or `docker compose up -d` for both).

```
cd backend
cp .env.example .env        # fill SECRET_KEY and FIELD_ENCRYPTION_KEYS
createdb uzbridge
uv run python manage.py migrate
uv run python manage.py runserver 127.0.0.1:8010
```

```
cd frontend
npm install
npm run dev                 # http://app.localhost:5174
```

Sign up on `app.localhost:5174`; you land on `<slug>.localhost:5174`. With
`CELERY_TASK_ALWAYS_EAGER=true` in `.env` tasks run inline and Redis isn't
needed; otherwise run `uv run celery -A config worker -B -l info`.

Without a public URL the providers can't reach you, so replay their side:

```
uv run python scripts/simulate.py payme <slug> <invoice-number>
uv run python scripts/simulate.py click <slug> <invoice-number>
```

The widget can be tried outside amoCRM through
`widget/dev/harness.html` (instructions at the top of that file).

## Tests

```
cd backend && uv run pytest
```

The Payme tests replay both sandbox scenarios; Click covers the signature,
prepare/complete and cancel paths; Uzum mocks Checkout with respx. amoCRM
tests cover OAuth state and host checks, single-use refresh tokens, the widget
JWT, the uninstall signature and the paid → lead sync.

## Before going live

- Create the external integration in amoCRM (all scopes), set its redirect
  URI to `https://app.<domain>/oauth/amocrm/callback` and the uninstall hook to
  `https://app.<domain>/oauth/amocrm/uninstall`, upload `widget/dist/uzbridge-widget.zip`
  (`python widget/build.py https://api.<domain>`), and put client id/secret in `.env`.
- Wildcard DNS and TLS for `*.<domain>`.
- Confirm the Uzum Checkout production base URL with Uzum (`UZUM_CHECKOUT_URL`).
- Set `PAYME_ALLOWED_IPS` to Payme's range (185.234.113.1–15).
# uzbridge
