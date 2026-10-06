# ShopFlow — sample backend for demos

A small, intentionally buggy e-commerce backend. **It is never run.** It exists only
so Debug Pipeline has real source code to index: its files and functions match the
tracebacks in `sample_logs/shopflow.log` and the errors produced by
`log_generator/fake_log_generator.py`, so Step 1 can point at the actual culprit
functions and Step 2 can explain the real bug inside them.

Index it from the dashboard: **Codebase → Folder on the API server →** the absolute
path of this `sample_backend` folder.

| Folder | What's in it |
|---|---|
| `auth/` | JWT tokens, login, brute-force lockout, OAuth2, roles, refresh tokens |
| `database/` | Connection pool, query executor, transactions, user table |
| `payments/` | Stripe calls, card validation |
| `cache/` | Redis client, cached-object serialiser |
| `api/` | Auth middleware, rate limiter, JSON responses, routes |
| `workers/` | Celery email and order tasks, SMTP client |
