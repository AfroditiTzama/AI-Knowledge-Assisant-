# Secure Authentication & Profile Pass

This is **Phase 1** of the production upgrade. It keeps the application local-first and self-hostable with SQLite.

## Included

- HttpOnly access and rotating refresh-token cookies
- CSRF protection for cookie-authenticated write requests
- same-origin `/api` proxy for Vercel/Railway cookie reliability
- cross-tab session refresh coordination
- persistent active sessions in SQLite
- revoke one session / sign out everywhere
- password change and password reset
- email verification with local outbox or SMTP
- brute-force lockout and auth endpoint rate limiting
- security event audit trail
- expanded My Profile:
  - name
  - email status
  - preferred language
  - Light / Dark / System theme
  - default Assistant response behavior
  - active sessions
  - security activity
  - account deletion
- Assistant prompt now respects saved language and response-style preferences

## Apply

From the repository root:

```bash
cd /Users/afrodititzama/Desktop/enterprise-ai-knowledge-assistant

git checkout -b feature/secure-profile-auth

unzip -o \
  "$HOME/Downloads/enterprise-ai-secure-profile-pass.zip"

git status --short
git diff --check
```

## Backend migration and tests

```bash
cd /Users/afrodititzama/Desktop/enterprise-ai-knowledge-assistant/apps/api

source .venv/bin/activate

set -a
source .env
set +a

alembic upgrade head
pytest -q
```

## Frontend build

```bash
cd /Users/afrodititzama/Desktop/enterprise-ai-knowledge-assistant/apps/web

npm run build
```

## Run locally

### Terminal 1 — Backend

```bash
cd /Users/afrodititzama/Desktop/enterprise-ai-knowledge-assistant/apps/api

source .venv/bin/activate

set -a
source .env
set +a

python -m uvicorn knowledge_assistant.main:app \
  --no-proxy-headers \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

### Terminal 2 — Frontend

```bash
cd /Users/afrodititzama/Desktop/enterprise-ai-knowledge-assistant/apps/web

npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`.

## Local test checklist

1. Existing user can sign in, including an older password shorter than 10 characters.
2. New registration requires at least 10 characters, one letter and one number.
3. Five failed sign-ins trigger a temporary lock and a `429` response.
4. Sign out works without a hard refresh.
5. Open the app in two tabs and confirm both remain usable after access-token refresh.
6. Change password and confirm all previous sessions are revoked.
7. Request password reset and open the generated `.eml` file under `storage/mail_outbox`.
8. Request email verification and verify the account.
9. Change name, language, theme and Assistant behavior in My Profile.
10. Revoke another session and inspect Security activity.
11. Test account deletion only with disposable test data.

## Railway environment

Use at least:

```env
APP_ENV=production
APP_DEBUG=false
FRONTEND_BASE_URL=https://enterprise-ai-knowledge.vercel.app
JWT_SECRET_KEY=<a-long-random-secret>
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=auto
CORS_ORIGINS=https://enterprise-ai-knowledge.vercel.app
MAIL_DELIVERY_MODE=outbox
```

Generate a secret locally with:

```bash
openssl rand -hex 32
```

For real password-reset and verification emails, switch `MAIL_DELIVERY_MODE=smtp` and configure the SMTP variables documented in `apps/api/.env.example`.

The frontend now uses `/api` in production and `apps/web/vercel.json` proxies requests to Railway. This avoids relying on third-party cookies between the Vercel and Railway domains.

## Validation performed while creating the patch

- Python compilation passed.
- 24 backend unit tests that do not require the missing uploaded runtime dependencies passed.
- All TypeScript/TSX files passed syntax transpilation.
- Alembic reports one migration head: `d4e8f1a2b3c4`.

A full `pytest -q`, live migration, and `npm run build` still need to run in the project's own Python 3.12 and Node environments before deployment.
