# F-01 Vehicle Reservation Request — Implementation Report

| | |
|---|---|
| **Project** | GovFleet — Government Vehicle Reservation and Fleet Management System |
| **Course** | CS 413 Advanced Software Engineering · Group 7 |
| **Feature** | F-01 — Vehicle Reservation Request |
| **Status** | Implemented; 59/59 automated tests passing |
| **Date** | November 24, 2026 (revised November 25, 2026) |
| **Branch** | `feature/f01-vehicle-reservation`, polished in `fix/f01-polish` |

> **Revision (Nov 25, 2026):** After Lab Activity 3 (test case TC-05, database outage, failed), F-01 was hardened: database outages now return a clean `503` in about 2 s instead of a 41 s hang and the debug page, there is a `/health/` endpoint, reservation creation is rate-limited, the calendar feed uses local time, the calendar's booking horizon comes from the server, FullCalendar is served locally, and CI runs on GitHub Actions. See [LA3-summary.md](LA3-summary.md) and §15.

---

## 1. Summary

F-01 lets an authenticated user request a vehicle for a specific date and time range. The system validates the request, checks the vehicle's availability, and responds with either a confirmation (reservation created with status **Pending**) or a clear explanation of why it was refused — including the conflicting time slots when the vehicle is already booked.

The implementation follows the layered client–server architecture defined in Lab Activity 2 (Worksheets A–D):

- **Presentation:** Django templates + FullCalendar page, communicating with the backend only through JSON endpoints.
- **Application:** thin Django REST Framework views delegating to a dedicated `VehicleReservationService`.
- **Data:** PostgreSQL via the Django ORM, with database-enforced rules that make double-booking impossible.

**Key outcome:** double-booking is prevented at two independent levels — a row-level lock in the service layer and a PostgreSQL exclusion constraint in the database — and this was verified by a test that fires eight simultaneous requests for the same slot and confirms exactly one succeeds.

### Expected result (Worksheet A) — met

| Requirement | How it is met |
|---|---|
| User requests an available vehicle for a date/time | Calendar drag-select or form → `POST /api/reservations/` |
| System checks availability | `VehicleReservationService.check_availability` / overlap query + DB constraint |
| Shows confirmation with request status | `201 Created` with reservation details and status `PENDING`, shown on the page |

---

## 2. Scope

### In scope (delivered)
- Vehicle and reservation data model with constraints and indexes
- Reservation business rules and conflict detection
- REST API: vehicle list, availability check, reservation creation, calendar feed
- Interactive FullCalendar reservation page
- Temporary session-based login
- Least-privilege PostgreSQL setup script
- Automated test suite (unit, API, database-constraint, concurrency)

### Out of scope (later phases)
- Firebase Authentication and Admin/Scheduler/User role enforcement
- Scheduler approval, rejection, and driver/vehicle assignment
- Celery + Django-Celery-Beat status transitions (`Approved → Ongoing → Completed`) and reminders
- jsPDF trip tickets and utilization reports
- Cancellation by the requester

---

## 3. Architecture

```
 Browser
 ┌───────────────────────────────────────────┐
 │ calendar.html + calendar.js (FullCalendar)│   Presentation layer
 └───────────────┬───────────────────────────┘
                 │ HTTP / JSON (session cookie + CSRF token)
 ┌───────────────▼───────────────────────────┐
 │ reservations/api/views.py  (DRF)          │   Application layer — HTTP
 │  parse & validate input → call service →  │   (no business rules)
 │  map domain errors to 400 / 409           │
 └───────────────┬───────────────────────────┘
                 │ Python calls
 ┌───────────────▼───────────────────────────┐
 │ services/reservation_service.py           │   Application layer — business
 │  VehicleReservationService                │   rules, availability, locking
 └───────────────┬───────────────────────────┘
                 │ Django ORM (transaction.atomic, select_for_update)
 ┌───────────────▼───────────────────────────┐
 │ PostgreSQL 17                             │   Data layer
 │  CHECK + EXCLUDE USING gist constraints   │
 └───────────────────────────────────────────┘
```

### Layer responsibilities

| Layer | Module(s) | Responsibility | Must NOT |
|---|---|---|---|
| Presentation | `templates/`, `static/reservations/calendar.js` | Render calendar, collect input, display results | Access the database or apply business rules |
| HTTP | `reservations/api/` | Authenticate, parse/validate input format, shape JSON responses, map errors to status codes | Contain booking rules or conflict logic |
| Service | `reservations/services/` | Business rules, availability, conflict detection, transactional creation | Know about HTTP or request objects |
| Data | `reservations/models.py`, migration | Schema, indexes, integrity constraints | — |

This separation matches the Worksheet B responsibility matrix (`VehicleReservationView` → `VehicleReservationService` → Database) and Worksheet D's mitigation *"Separate validation, service, and data access modules."*

---

## 4. Components

| Component | File | Type | Description |
|---|---|---|---|
| `Vehicle` model | `reservations/models.py` | Custom | Plate number (unique), name, type, capacity, active flag |
| `Reservation` model | `reservations/models.py` | Custom | Requester, vehicle, start/end time, purpose, status, timestamps |
| `VehicleReservationService` | `reservations/services/reservation_service.py` | Custom | All reservation business logic |
| Domain exceptions | `reservations/services/exceptions.py` | Custom | `ReservationValidationError`, `VehicleUnavailableError` |
| API views | `reservations/api/views.py` | Custom (on DRF) | Thin endpoints |
| Serializers | `reservations/api/serializers.py` | Custom (on DRF) | Input parsing, output shaping, privacy filtering |
| `SessionAuthentication401` | `reservations/api/authentication.py` | Adapted | Makes unauthenticated API calls return 401 instead of DRF's default 403 |
| Calendar page | `templates/reservations/calendar.html`, `static/reservations/calendar.js` | Custom | FullCalendar UI and request form |
| `api_exception_handler` | `reservations/api/exceptions.py` | Custom (on DRF) | Database outage → 503 JSON; other unexpected errors → generic 500 JSON; details logged only |
| `DatabaseUnavailableMiddleware` | `govfleet/middleware.py` | Custom | Database outage on HTML pages (calendar, login, admin) → friendly 503 page |
| Health probe | `govfleet/health.py` | Custom | `GET /health/` → 200 / 503 based on a `SELECT 1` |
| FullCalendar 6.1.15 | `static/reservations/vendor/fullcalendar-6.1.15/` | Reused | Calendar rendering and slot selection (vendored, integrity-verified npm bundle) |
| Django REST Framework 3.16.1 | pip | Reused | API framework |
| Django admin | built-in | Reused | Vehicle and reservation management (interim) |

---

## 5. Data model

### `Vehicle`
| Field | Type | Notes |
|---|---|---|
| `plate_number` | varchar(20) | Unique |
| `name` | varchar(100) | Make/model |
| `vehicle_type` | varchar(50) | Optional |
| `capacity` | smallint | Seats |
| `is_active` | boolean | Inactive vehicles cannot be reserved |
| `created_at`, `updated_at` | timestamptz | Audit |

### `Reservation`
| Field | Type | Notes |
|---|---|---|
| `requester` | FK → User | `PROTECT` on delete |
| `vehicle` | FK → Vehicle | `PROTECT` on delete |
| `start_time`, `end_time` | timestamptz | Half-open interval `[start, end)` |
| `purpose` | text (≤500) | Required |
| `status` | varchar | `PENDING`, `APPROVED`, `REJECTED`, `ONGOING`, `COMPLETED`, `CANCELLED` |
| `created_at`, `updated_at` | timestamptz | Audit |

### Constraints
| Name | Kind | Rule |
|---|---|---|
| `reservation_end_after_start` | CHECK | `end_time > start_time` |
| `reservation_no_overlap` | EXCLUDE USING gist | No two reservations for the same vehicle may have overlapping `tstzrange(start_time, end_time, '[)')` while their status is `PENDING`, `APPROVED`, or `ONGOING` |

The exclusion constraint requires the `btree_gist` extension, created by the first migration. It is a *trusted* extension in PostgreSQL 13+, so the application's non-superuser database role can install it.

### Indexes
Composite `(vehicle, start_time, end_time)`, plus `start_time`, `end_time`, and `status` individually (per Worksheet D: *"Add database indexes"*). Foreign keys are indexed automatically.

---

## 6. Business rules

| Rule | Value | Error |
|---|---|---|
| End must be after start | — | 400 `end_time` |
| Start cannot be in the past | — | 400 `start_time` |
| Maximum reservation length | 7 days | 400 `end_time` |
| Maximum booking horizon | 183 days (~6 months) ahead | 400 `start_time` |
| Purpose required | ≤500 chars, not blank | 400 `purpose` |
| Vehicle must exist and be active | — | 400 `vehicle` |
| No overlap with a slot-occupying reservation | `PENDING`, `APPROVED`, `ONGOING` block the slot | 409 |
| Back-to-back bookings allowed | 08:00–10:00 and 10:00–12:00 do not conflict | — |
| New reservations start as | `PENDING` | — |

**Design decision — Pending blocks the slot.** A pending request reserves the slot until a scheduler approves or rejects it. This prevents two users from both submitting requests for the same slot and leaving the scheduler to resolve the clash. Rejected, cancelled, and completed reservations free the slot.

The calendar UI mirrors the 6-month horizon by disabling times beyond it. The limit is passed from `VehicleReservationService.MAX_ADVANCE` to the page, so the UI and the rule cannot drift apart. The server remains the authority.

---

## 7. Concurrency and double-booking prevention

Worksheet A identifies the risk; Worksheet D and Guide Question 3 specify the mitigation: *database-level locking transactions and PostgreSQL range constraints rather than relying purely on client-side or application-level checks.* Both are implemented.

**Level 1 — serialized per-vehicle transactions (service layer)**
```
BEGIN
  SELECT ... FROM vehicle WHERE id = :id FOR UPDATE      -- lock this vehicle
  SELECT ... FROM reservation WHERE overlaps(...)        -- check conflicts
  INSERT INTO reservation ...                            -- create
COMMIT                                                   -- release lock
```
Locking the vehicle row forces concurrent requests for the *same* vehicle to run one after another, so each conflict check sees the previous request's committed reservation. Requests for *different* vehicles do not block each other. The transaction contains only these three statements, keeping lock time short (Worksheet D: *"Keep transactions short"*).

**Level 2 — exclusion constraint (database)**
Even if a future code path bypasses the service, PostgreSQL rejects any overlapping insert or update. The service catches this specific constraint violation and converts it to the same 409 response.

**Verification:** `test_concurrent_requests_for_same_slot_yield_one_booking` starts 8 threads behind a barrier, each with its own database connection, all requesting the same slot simultaneously. Result: exactly 1 success, 7 conflicts, 1 row in the database.

---

## 8. API contract

All `/api/` endpoints require authentication. Unauthenticated requests receive **401**. Timestamps in responses are local time (`+08:00`).

Every endpoint may also return:

| Status | Body | When |
|---|---|---|
| 503 Service Unavailable | `{"detail": "...", "code": "service_unavailable"}` + `Retry-After: 30` | Database unreachable |
| 500 Internal Server Error | `{"detail": "An unexpected error occurred.", "code": "server_error"}` | Unexpected bug (details only in server log) |

### `GET /api/vehicles/`
Active vehicles for selection.
```json
[{"id": 1, "plate_number": "SAB-1234", "name": "Toyota Hiace", "vehicle_type": "Van", "capacity": 12}]
```

### `GET /api/vehicles/<id>/availability/?start_time=<ISO>&end_time=<ISO>`
| Status | Meaning |
|---|---|
| 200 | `{"vehicle": 1, "available": true, "conflicts": []}` or `available: false` with conflicts |
| 400 | Invalid or missing time range |
| 404 | Unknown or inactive vehicle |

### `POST /api/reservations/`
Request:
```json
{
  "vehicle": 1,
  "start_time": "2026-11-26T08:00:00+08:00",
  "end_time": "2026-11-26T12:00:00+08:00",
  "purpose": "Site inspection, Brgy. Alangilan"
}
```
| Status | Body |
|---|---|
| 201 Created | Reservation object with `"status": "PENDING"` and nested vehicle |
| 400 Bad Request | Field errors, e.g. `{"end_time": ["End time must be after start time."]}` |
| 401 Unauthorized | Not logged in |
| 409 Conflict | `{"detail": "...", "code": "vehicle_unavailable", "conflicts": [{"start_time", "end_time", "status"}]}` |
| 429 Too Many Requests | Per-user limit exceeded (default 30/hour, `THROTTLE_RESERVATION_CREATE`); includes `Retry-After` |

### `GET /api/calendar/events/?start=<ISO>&end=<ISO>[&vehicle=<id>]`
Returns a FullCalendar event array of slot-occupying reservations, with `start`/`end` in local time (`+08:00`). The window is limited to 62 days.

### `GET /health/`
No authentication required. Returns `{"status": "ok", "database": "ok"}` (200) or `{"status": "unavailable", "database": "unavailable"}` (503). Never includes error details.

---

## 9. Security and privacy

| Concern | Measure |
|---|---|
| Secrets | Django secret key and DB credentials live in a git-ignored `.env`; only `.env.example` with placeholders is committed |
| Database privileges | App connects as `govfleet_app`: no superuser, no role creation, owns only its own database; `PUBLIC` cannot connect. `CREATEDB` is granted only so the test runner can create its throwaway database — remove in production |
| Superuser password | Setup script prompts interactively; never written to disk |
| Privacy of other users | Conflict responses and calendar events of other users show only time and status, never requester identity or trip purpose. Users see their own purpose |
| CSRF | Django CSRF protection on all state-changing requests; JS sends `X-CSRFToken` |
| XSS | Server data is inserted with `textContent`, never `innerHTML` |
| Error leakage | Custom DRF exception handler and middleware: all errors are structured JSON or a plain 503 page, never stack traces, even with `DEBUG=True`; details go to the server log |
| Availability | `connect_timeout=5` s, `CONN_HEALTH_CHECKS`, `DB_HOST=127.0.0.1`: a database outage fails fast instead of hanging requests |
| Abuse / flooding | Reservation creation rate-limited per user (429) |
| Transport (production) | With `DEBUG=False`: secure cookies, HTTPS redirect, HSTS (incl. subdomains, preload); `check --deploy` clean |
| Third-party scripts | FullCalendar served from the app's own static files (no CDN), integrity-verified against the npm registry |
| Input bounds | Purpose length, reservation duration, booking horizon, and calendar window are all capped |
| Dependencies | Exact versions pinned in `requirements.txt` (Worksheet D mitigation) |

---

## 10. Testing

**Framework:** pytest 8.4.2 + pytest-django 4.11.1, against a real PostgreSQL 17 test database (required, since the constraints are PostgreSQL-specific).

**Result:** **59 passed**, 0 failed (≈27 s). The suite also runs on GitHub Actions (PostgreSQL 17 service container) for every push and pull request to `main`.

| Suite | Tests | Covers |
|---|---|---|
| `test_reservation_service.py` | 21 | Creation as Pending; five overlap shapes (inside, overlapping start, overlapping end, covering, identical); back-to-back allowed; same slot on another vehicle allowed; rejected/cancelled/completed free the slot; end-before-start; past start; >7 days; >6 months ahead; ≤6 months allowed; inactive vehicle; blank purpose; DB exclusion constraint without service; DB check constraint; availability check |
| `test_api.py` | 26 | 401 on all endpoints; 201 create; 409 with no leaked details; 400 for each missing field, inverted range, unknown vehicle, malformed timestamp, inactive vehicle; availability endpoint and 404; inactive vehicles hidden from list; calendar hides others' purpose and shows own; calendar requires range; calendar feed in `+08:00`; per-user throttling (429) and read endpoints not throttled; page requires login and renders; page receives the server booking horizon; FullCalendar served locally |
| `test_resilience.py` | 11 | Database outage → 503 JSON on write and read endpoints, with `Retry-After` and no leaked internals; outage is logged; unexpected error → generic 500 JSON; outage on HTML page → friendly 503 page; non-database errors not swallowed; `/health/` ok without login, 503 when database unreachable, rejects POST; fail-fast connection settings |
| `test_concurrency.py` | 1 | 8 simultaneous requests → exactly 1 booking |

Run with:
```powershell
.\.venv\Scripts\python.exe -m pytest
```

---

## 11. Traceability to Lab Activity 2

| Worksheet item | Implementation |
|---|---|
| A — Layered client–server architecture | Template/JS → DRF views → service → ORM/PostgreSQL |
| A — Mitigation: error handling, transaction locks | Domain exceptions mapped to 400/409; `select_for_update` in `transaction.atomic` |
| B — FullCalendar does not access the DB; talks via HTTP/JSON | `calendar.js` uses only `/api/...` endpoints |
| B — `VehicleReservationView` validates and delegates | `ReservationCreateView` + serializers |
| B — `VehicleReservationService` handles rules and overlap | `VehicleReservationService` |
| C — Reservation request → pending confirmation | `POST /api/reservations/` → 201 `PENDING` |
| C — Availability / conflict checking via overlapping-timestamp query | `find_conflicts` (`start < req_end AND end > req_start`) |
| C — 400 missing/invalid fields, 409 already reserved | Implemented and tested |
| D — Pin library versions | `requirements.txt` |
| D — Database indexes | Four explicit indexes |
| D — Separate validation, service, data access | `api/serializers.py`, `services/`, `models.py` |
| D — Keep transactions short; add DB constraints | Three-statement transaction; CHECK + EXCLUDE constraints |
| Guide Q3 — PostgreSQL range constraints over app-level checks | `reservation_no_overlap` exclusion constraint |

---

## 12. Known limitations and assumptions

1. **Temporary authentication.** Django session login stands in for Firebase; no role (Admin/Scheduler/User) checks yet — any logged-in user can request. `403` is reserved for the RBAC phase.
2. **Six months = 183 days**, a fixed duration rather than calendar months, to avoid an extra dependency.
3. **No cancellation or editing** by the requester yet.
4. **Vehicle management** is via the Django admin until a dedicated Admin UI exists.
5. ~~FullCalendar loads from a CDN~~ — resolved: now served locally.
6. **Time zone** is `Asia/Manila`; timestamps are stored in UTC, returned in `+08:00`, and must include an offset in API calls.
7. **Throttle counters are per process** (Django's local-memory cache). With several server processes the effective limit is multiplied; move the cache to Redis when it is introduced in Phase 4.

---

## 13. Next phases

| Phase | Work | Prerequisite |
|---|---|---|
| 2 | Firebase Authentication: middleware verifying Firebase JWTs via `firebase-admin`, mapping UIDs to local user records with Admin/Scheduler/User roles; 403 enforcement | Firebase project + service-account key |
| 3 | Scheduler workflow: approve/reject, assign driver and vehicle | Phase 2 |
| 4 | Celery + Django-Celery-Beat + Redis: automatic `Approved → Ongoing → Completed`, reminders, retries and failure logging | Redis installed |
| 5 | jsPDF trip tickets and utilization reports with empty-dataset handling | Phases 3–4 |

---

## 14. Local setup

See [README.md](../README.md#getting-started-windows) for full instructions. In short:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# copy .env.example to .env and fill in values
powershell -ExecutionPolicy Bypass -File .\scripts\setup_db.ps1
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

---

## 15. Post-LA3 polish (`fix/f01-polish`)

| Item | Change | Verified by |
|---|---|---|
| A1 | DRF exception handler + middleware: DB outage → 503 (JSON for API, page for HTML), logged; UI shows "temporarily unavailable" | `test_resilience.py`; TC-05 re-run (see LA3 summary) |
| A2 | `connect_timeout=5`, `CONN_HEALTH_CHECKS=True`, default `DB_HOST=127.0.0.1` | TC-05 re-run: ≈2 s instead of 41 s |
| A3 | `GET /health/` database probe | `test_resilience.py`; manual probe during outage → 503 |
| B4 | Calendar feed returns `+08:00` like the reservation API | `test_calendar_events_use_local_time_like_reservation_api` |
| B5 | Calendar horizon taken from `MAX_ADVANCE` (was a hard-coded 184 days vs. the server's 183) | `test_calendar_page_uses_server_booking_horizon` |
| C6 | `SECURE_HSTS_PRELOAD=True` | `manage.py check --deploy` → no issues |
| C7 | FullCalendar 6.1.15 vendored (npm tarball, sha512 verified) | `test_calendar_page_serves_fullcalendar_locally` |
| C8 | Per-user throttle on `POST /api/reservations/` (429) | `test_reservation_create_is_throttled_per_user` |
| D9 | GitHub Actions CI: checks, missing-migration check, `check --deploy`, pytest on PostgreSQL 17 | Workflow run on the PR |
| E11 | README, this report, [LA3 summary](LA3-summary.md) | — |
