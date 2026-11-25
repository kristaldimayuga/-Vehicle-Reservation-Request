# Lab Activity 3 — Summary and Follow-up

| | |
|---|---|
| **Project** | GovFleet — Government Vehicle Reservation and Fleet Management System |
| **Course** | CS 413 Advanced Software Engineering · Group 7 |
| **Feature under test** | F-01 — Vehicle Reservation Request |
| **Date** | November 25, 2026 |
| **Follow-up branch** | `fix/f01-polish` |

This document records the one failed Lab Activity 3 test case, TC-05, along with its root cause, the fix, and the re-test result. The full test-case table is in the LA3 worksheet.

---

## 1. Failed test case: TC-05 — Database outage

| | |
|---|---|
| **Scenario** | PostgreSQL becomes unavailable while the application is running; a user loads the reservation page / submits a request |
| **Expected** | The system fails gracefully: a clear "service unavailable" message, no stack trace, no long hang |
| **Actual (LA3)** | The request hung for about **41 seconds**, then returned **HTTP 500** with Django's debug page, which exposed a stack trace and configuration details |
| **Result** | **FAIL** |

### Root cause

1. **No connection timeout.** Django's PostgreSQL connection had no `connect_timeout`, so every failed connection attempt waited for the operating system's TCP timeout.
2. **`DB_HOST=localhost`.** On Windows, `localhost` resolves to IPv6 `::1` first and then to IPv4 `127.0.0.1`, so each failed connection was attempted twice.
3. **No error handling for database errors.** `OperationalError` was not handled by the API or the pages, so it fell through to Django's default 500 handling. With `DEBUG=True` that is the debug page.
4. **No UI handling.** The front end had no message for a "service unavailable" response.

---

## 2. Fix

| # | Change | Where |
|---|---|---|
| A1 | DRF exception handler: database connectivity errors → **503 JSON** (`code: service_unavailable`, `Retry-After: 30`), other unexpected errors → generic 500 JSON; details logged server-side only | `reservations/api/exceptions.py` |
| A1 | Middleware: the same treatment for HTML pages (calendar, login, admin) → friendly **503 page** that does not touch the database | `govfleet/middleware.py`, `templates/503.html` |
| A1 | Front end shows "GovFleet is temporarily unavailable. Please try again in a moment." on any 503 | `static/reservations/calendar.js` |
| A2 | `connect_timeout=5` s, `CONN_HEALTH_CHECKS=True`, `DB_HOST=127.0.0.1` | `govfleet/settings.py`, `.env.example` |
| A3 | `GET /health/`: reports database reachability (200 / 503) for monitoring | `govfleet/health.py` |

Errors are logged by the `govfleet` / `govfleet.api` loggers.

---

## 3. Re-test (TC-05)

**Method:** The app was run with the database port pointed at a closed port (`DB_PORT=5499`). This reproduces "PostgreSQL is not running", because connection attempts are refused. Requests were made with `curl`.

| Request | Before (LA3) | After |
|---|---|---|
| `GET /reservations/calendar/` (logged-in session) | ≈41 s → 500 debug page | **≈2.0 s → 503** "Service temporarily unavailable" page, `Retry-After: 30`, no stack trace |
| `GET /api/vehicles/` (logged-in session) | — | **≈2.1 s → 503** `{"detail": "The service is temporarily unavailable. Please try again shortly.", "code": "service_unavailable"}` |
| `POST /accounts/login/` | — | **≈2.0 s → 503** page |
| `GET /health/` | (did not exist) | **≈2.1 s → 503** `{"status": "unavailable", "database": "unavailable"}` |

**Result:** **PASS.** Outages are reported in about 2 s with a clear message and no internal details.

Automated regression tests were also added in `reservations/tests/test_resilience.py` (11 tests). They simulate the outage by raising the same `OperationalError` psycopg2 raises.

> To repeat the manual test exactly as in LA3, stop the PostgreSQL Windows service (e.g. `Stop-Service postgresql-x64-17` in an elevated PowerShell) while `runserver` is running, then reload the reservation page. Start the service again afterwards.

---

## 4. Other improvements made in the same branch

| # | Change |
|---|---|
| B4 | Calendar feed timestamps now in local time (`+08:00`), consistent with the reservation API |
| B5 | Calendar booking horizon now comes from the server rule (`MAX_ADVANCE`, 183 days); previously hard-coded to 184 days |
| C6 | `SECURE_HSTS_PRELOAD` enabled; `manage.py check --deploy` reports no issues |
| C7 | FullCalendar 6.1.15 served locally instead of from a CDN (integrity-verified) |
| C8 | Reservation creation rate-limited per user (429 Too Many Requests) |
| D9 | GitHub Actions CI: system checks, missing-migration check, deployment check, and the full pytest suite on PostgreSQL 17 |

Test suite: **59 passed** (43 before LA3 follow-up + 16 new).
