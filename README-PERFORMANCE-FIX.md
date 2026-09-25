# NomanBot performance fix

## What was fixed

- The database pool now uses the configured production values instead of a
  hard-coded pool of two connections.
- The global ban check no longer freezes the async bot loop while it waits for
  TiDB; it runs in a worker and has a short cache.
- `/start` no longer performs a second remote database query, and required
  channel/group membership checks run concurrently and are cached briefly.
- Admin dashboard and statistics database queries run outside the bot event
  loop.
- Product-list, product-detail, account-editor, provider-selection, and admin
  back-navigation queries also run outside the bot event loop.
- Deposit verification releases its database connection before waiting on
  RPC, Binance Pay, or IMAP/network services. This prevents pending deposits
  from making normal commands wait for a database connection.

## Deploy exactly one mode

Use **one** of these modes for a given bot token, never both:

1. **Render/Railway/VPS polling:** run `main.py`. Do not configure a Telegram
   webhook for this token.
2. **Vercel webhook:** deploy `api/index.py` and run `set_webhook.py` once
   after deployment. Do not run `main.py` at the same time.

Both modes call Telegram webhook APIs. Starting both causes one deployment to
disable the other, so commands may appear to stop working.

## Recommended environment values

```env
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT=10
MEMBERSHIP_CACHE_TTL=300
BANNED_USER_CACHE_TTL=30
```

Keep your existing `.env` file private and copy it into the deployed project.
The delivery archive intentionally excludes it so bot, database, payment, and
email credentials are not copied accidentally.
