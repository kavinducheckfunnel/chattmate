# ChatterMate — Operations Runbook

Production: **https://chat.growmiq.io** · VPS `187.77.156.57` (`srv1541176`, Ubuntu 24.04)

> This VPS also runs **Checkfunnel** (Django/daphne/celery, natively — not in Docker).
> ChatterMate must never take it down. Everything below is scoped to the
> `chattermate` compose project and touches nothing of Checkfunnel's.

---

## Access

```bash
ssh -i ~/.ssh/checkfunnel_ci_deploy root@187.77.156.57
```

Password authentication is **disabled** (`/etc/ssh/sshd_config.d/01-hardening.conf`).
Key auth only. If the key is ever lost, recover through the Hostinger VNC console —
there is no password fallback by design.

---

## Layout

| | |
|---|---|
| App directory | `/opt/chattermate` |
| Compose project | `chattermate` |
| Compose file | `docker-compose.growmiq.yml` |
| Secrets | `backend/.env`, `.env.growmiq` (mode 600) |
| Backups | `/var/backups/chattermate` |
| nginx vhost | `/etc/nginx/sites-available/chattermate` |
| TLS | `/etc/letsencrypt/live/chat.growmiq.io/` |

Everything is published on **loopback only** — the host nginx is the sole public entry.

| Service | Address |
|---|---|
| backend | `127.0.0.1:8080` (8000 belongs to Checkfunnel's daphne) |
| frontend | `127.0.0.1:3080` |
| postgres, redis | not published at all — private network only |

The standard compose shortcut, used throughout:

```bash
cd /opt/chattermate
alias dc='docker compose -p chattermate -f docker-compose.growmiq.yml --env-file .env.growmiq'
```

---

## Everyday commands

```bash
dc ps                          # what's running
dc logs -f backend             # follow backend
dc logs --tail=100 knowledge_processor
dc restart backend
/opt/chattermate/scripts/deploy.sh              # sync-built code, rebuild, restart, verify
/opt/chattermate/scripts/deploy.sh --no-build   # restart only
/usr/local/bin/chattermate-health.sh            # run the health check now
```

---

## Automation already in place

| What | When | Where |
|---|---|---|
| Backup (db + uploads + env) | 02:15 daily | `/etc/cron.d/chattermate-backup` → `/var/log/chattermate-backup.log` |
| Restore rehearsal | 03:40 Sundays | same cron → `/var/log/chattermate-restore-check.log` |
| Health check | every 10 min | `/etc/cron.d/chattermate-health` → `/var/log/chattermate-health.log` |
| TLS renewal | certbot timer | `systemctl list-timers | grep certbot` |

02:15 is deliberate — Checkfunnel's own backup runs at midnight, and two `pg_dump`s
on 2 vCPU would contend.

---

## Backup and restore

```bash
/usr/local/bin/chattermate-backup.sh            # run one now
/usr/local/bin/chattermate-restore.sh --list    # what's available
```

Each night produces three files sharing a timestamp. **All three are needed for a
real recovery:**

- `db-<stamp>.dump` — the database
- `uploads-<stamp>.tar.gz` — attachments and knowledge files (on disk, not in the DB)
- `env-<stamp>.tar.gz` — **contains `ENCRYPTION_KEY`**

That last one is the trap. Message bodies, agent memory and stored provider
credentials are encrypted with `ENCRYPTION_KEY`. Restore a database without it and
you get unreadable ciphertext. Keep a copy somewhere other than the VPS.

**Rehearse a restore (safe — throwaway container, production untouched):**

```bash
/usr/local/bin/chattermate-restore.sh --verify /var/backups/chattermate/db-<stamp>.dump
```

**Restore into production (destructive — asks for confirmation):**

```bash
/usr/local/bin/chattermate-restore.sh --into-live /var/backups/chattermate/db-<stamp>.dump
# then, if uploads were lost too:
docker run --rm -i -v chattermate_uploads:/data -w /data alpine:3 tar xzf - < uploads-<stamp>.tar.gz
```

> ⚠️ **Backups currently live only on this VPS.** A disk failure loses both the
> database and its backups. Set `OFFSITE_RCLONE_REMOTE` in
> `/etc/chattermate-backup.env` to fix this — see *Open items* below.

---

## Signup control

Signup is currently **OPEN** (`ALLOW_PUBLIC_SIGNUP=true` in `backend/.env`) — reopened
on 12 Aug for testing. Anyone with the URL can create a workspace.

Outstanding risks while it stays open: verification is **soft** — mail is
delivered, but an unverified user can still sign in, so addresses are prompted
for rather than proven (flip `REQUIRE_EMAIL_VERIFICATION` to change that); no
usage metering (one tenant can spend the whole AI budget); and backups still
only on this VPS.

```bash
# close it
sed -i 's/^ALLOW_PUBLIC_SIGNUP=.*/ALLOW_PUBLIC_SIGNUP=false/' /opt/chattermate/backend/.env && dc up -d backend
# open it
sed -i 's/^ALLOW_PUBLIC_SIGNUP=.*/ALLOW_PUBLIC_SIGNUP=true/'  /opt/chattermate/backend/.env && dc up -d backend
```

Closed, `POST /api/v1/organizations` returns `403 Signups are currently closed.`
Existing users can always still log in either way — the flag gates registration only.

Related knob in the same file: `SIGNUP_RATE_LIMIT_PER_HOUR` (default 20, per IP).

Password policy has exactly one home — `MIN_PASSWORD_LENGTH` and
`MIN_PASSWORD_CHARACTER_CLASSES` in `backend/app/core/security.py` (8 characters,
3 of 4 character classes). Signup, invitations, admin resets and the public
password reset all run through the same validator. There is deliberately **no**
signup-specific length setting: when one existed, it drifted out of step with the
checklist the UI shows and signups failed against rules the user had just met.

---

## Platform email (verification and password reset)

**Configured and delivering** as of 13 Aug 2026, via Gmail SMTP.

| Setting | Value |
|---|---|
| Host / port | `smtp.gmail.com:587` (STARTTLS) |
| Account | `ai.checkfunnel@gmail.com` (Google App Password, app name "chattermate") |
| From | `ChatterMate <ai.checkfunnel@gmail.com>` |

Two things about this account that are easy to get wrong:

- **`FROM_EMAIL` must equal `SMTP_USERNAME`.** Gmail will not send as an
  arbitrary address; a mismatch either bounces or is silently rewritten to the
  authenticated mailbox. To send as `noreply@growmiq.io`, first add it under
  Gmail → Settings → Accounts → *Send mail as* and verify it, then change
  `FROM_EMAIL`.
- **The App Password is stored with its spaces removed.** Google displays it as
  four groups of four for readability; the spaces are not part of the secret and
  `smtplib` would transmit them verbatim.

Gmail caps sending at roughly **500 messages/day**. That is comfortable for early
customers but is a hard ceiling — move to a transactional provider (Resend,
SendGrid, Mailgun) before signup volume approaches it, which also gets mail off a
`gmail.com` sender address and onto the growmiq.io domain with its own SPF/DKIM.

STARTTLS is **required** on non-465 ports: a server that refuses it makes the
send fail rather than fall back to plaintext, because these messages carry live
credentials.

If credentials are ever removed, `is_configured()` returns false and the system
degrades deliberately rather than silently — signup still succeeds but reports
`email_verification_sent: false`, and password reset answers `503` rather than
accepting a request it cannot fulfil.

### Rotating the credential

```bash
# in /opt/chattermate/backend/.env  (mode 600)
SMTP_PASSWORD=<new app password, spaces stripped>
```
Then `dc up -d backend`. Verify before relying on it:
```bash
docker exec -i chattermate-backend-1 python - <<'EOF'
import smtplib
from app.core.config import settings
s = smtplib.SMTP(settings.SMTP_SERVER, int(settings.SMTP_PORT), timeout=20)
s.starttls(); s.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
print("SMTP AUTH: OK"); s.quit()
EOF
```

This is separate from the customer-support **email channel**
(`app/channels/email.py`), which uses each organization's own inbox credentials.
Platform mail always goes out as the platform, and never through a tenant's
mail server.

### Requiring verification

`REQUIRE_EMAIL_VERIFICATION` (default `false`) decides whether an unverified user
is blocked from signing in.

- **`false` (current)** — the account works immediately; a dismissible banner
  prompts for verification. Chosen as the default because verification depends on
  SMTP, and a mail outage under `true` locks out every new customer with no way to
  trigger the mail that would let them back in.
- **`true`** — signup issues no session at all (no cookies, no tokens) and shows
  "check your inbox"; login returns `403` until the link is clicked.

Flip it only once mail delivery is proven in production. Verified behaviour of
both modes, tested 12 Aug: under `true`, a wrong password still returns `401` and
not `403`, so the gate never reveals that an account exists to someone who does
not already know the password.

### Endpoints

All unauthenticated, all rate limited by IP, all non-disclosing by design —
a password-reset request answers identically whether the address exists or not.

| Route | Purpose |
|---|---|
| `POST /api/v1/auth/forgot-password/request` | Email a 6-digit code (15 min TTL, 5 attempts) |
| `POST /api/v1/auth/forgot-password/verify` | Exchange code for a new password; revokes all sessions |
| `POST /api/v1/auth/verify-email` | Consume the link token (48 h TTL, single use) |
| `POST /api/v1/auth/resend-verification` | Issue a fresh link, invalidating earlier ones |

Tokens are stored as SHA-256 digests in `auth_tokens`; the plaintext exists only
in the email. A leaked backup therefore yields no usable credential.

---

## Verifying tenant isolation

```bash
/opt/chattermate/scripts/tenant_isolation_smoke.sh https://chat.growmiq.io
```

11 checks: two tenants can sign up independently, and neither can read or modify the
other's organization, agents or users. **Run this after every deploy that touches
auth, repositories or API routes.**

It needs signup open, and makes 4 signups against a budget of 5/hour, so:

```bash
# open signup temporarily, clear the limiter, run, close again
docker exec chattermate-redis-1 redis-cli --scan --pattern 'public_rl:signup:*' \
  | xargs -r docker exec chattermate-redis-1 redis-cli DEL
```

Delete the tenants it leaves behind:

```bash
docker exec chattermate-backend-1 python -c "
from app.database import SessionLocal
from app.models.organization import Organization
db = SessionLocal()
for o in db.query(Organization).filter(Organization.domain.like('smoke-%')).all():
    db.delete(o)
db.commit()"
```

Use the ORM for this, **not** SQL. `roles.organization_id` has no `ON DELETE CASCADE`
at the database level, so `DELETE FROM organizations` fails on a foreign key — the
cascade exists only in SQLAlchemy.

---

## Troubleshooting

### 502 from the site

```bash
dc ps                         # is the backend actually up?
tail -30 /var/log/nginx/chattermate.error.log
```

**`upstream sent too big header`** — this has bitten us before. Login and signup set
a `user_info` cookie carrying the full role object with all 26 permissions, which
overflows nginx's default proxy buffers. The backend logs a clean `200` while nginx
returns 502. Fixed by `proxy_buffer_size 32k` in the `/api/` block; if it recurs
after a config change, that setting has been lost.

**`connect() failed (111: Connection refused)`** — backend is down or still booting.
Cold start takes ~30s.

### Backend won't start

```bash
dc logs --tail=50 backend
```

**`Multiple head revisions are present`** — the repo ships two unmerged alembic
branches. The compose command uses `alembic upgrade heads` (plural). If someone
changes it to `head`, migrations abort and, chained with `&&`, the server never
starts.

**Firebase `Could not deserialize key data`** — expected and harmless. Firebase
credentials are placeholders; only browser push notifications are affected.

### Everything is slow / OOM

```bash
free -h; docker stats --no-stream
```

7.8 GB total, 8 GB swap, shared with Checkfunnel. The heaviest process is
`knowledge_processor` (torch + FastEmbed). To buy headroom immediately:

```bash
dc stop knowledge_processor    # pauses knowledge ingestion only; chat keeps working
```

### Build fails on `pip install` with a hash mismatch

Four services share one Dockerfile, and building them together downloads the ~200 MB
torch wheel several times in parallel, which corrupts it. `deploy.sh` already builds
the backend alone first. Don't run a bare `dc build`.

### Certificate

```bash
certbot certificates
certbot renew --dry-run
```

Renewal is automatic. Expires 2026-11-09.

---

## Open items

These are **not** done yet and matter before real customers:

1. **Off-site backups.** Install `rclone`, configure a remote, then:
   ```bash
   echo 'OFFSITE_RCLONE_REMOTE=your-remote:chattermate-backups' > /etc/chattermate-backup.env
   chmod 600 /etc/chattermate-backup.env
   ```
   The backup script picks it up automatically and logs `offsite: copied`.
2. **Error tracking.** No Sentry DSN configured — failures are only visible in logs.
3. **Alert delivery.** Health alerts go to local `root` mail, which nobody reads.
   Set `ALERT_WEBHOOK` in `/etc/chattermate-backup.env` to a Slack/Discord webhook.
4. **No staging environment.** Deploys go straight to production.
5. **Email runs on a Gmail account.** Working and delivering, but capped at
   ~500/day and sending from a `gmail.com` address rather than growmiq.io.
   Fine now; move to a transactional provider before signup volume grows.
6. **Tenant isolation has no database backstop.** Correct scoping still depends
   on every one of 266 endpoints applying its own `organization_id` filter.
   The 25-probe IDOR sweep is the compensating control, not a substitute for
   PostgreSQL row-level security.

---

## Domain history

The site moved from `chattermate.growmiq.io` to **`chat.growmiq.io`** on 12 Aug 2026.

The old name is still served and **301-redirects** to the new one, over HTTPS as
well as HTTP — it keeps its own certificate because a browser only follows a
redirect after the TLS handshake succeeds, so serving the retired name on port 80
alone would give anyone with a bookmarked `https://` link a certificate error
instead of a redirect.

`CORS_ORIGINS` deliberately still lists both names: a widget embedded on a
customer's site while the old host was live calls it directly, and dropping it
from the allowlist would break those pages before the redirect could run. Remove
the old entry once no widget references it.

Both certificates renew via the existing certbot timer. The retired vhost can be
deleted entirely once traffic to it reaches zero (`grep chattermate.growmiq.io
/var/log/nginx/chattermate.access.log`).
