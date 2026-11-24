# GovFleet

**Government Vehicle Reservation and Fleet Management System**

GovFleet is a centralized, web-based vehicle reservation and dispatch system for a government agency. It replaces manual scheduling with a single source of truth for vehicle allocation, eliminating double-bookings, unauthorized usage, and dispatch delays under a role-based access model (**Admin**, **Scheduler**, **User**).

> CS 413 – Advanced Software Engineering · Group 7 · 1st Semester AY 2026–2027

## Feature status

| ID | Feature | Status |
|---|---|---|
| F-01 | Vehicle Reservation Request | ✅ Implemented & tested |
| — | Firebase Authentication + RBAC middleware | Planned |
| — | Scheduler approval & vehicle/driver assignment | Planned |
| — | Celery background status updates & reminders | Planned |
| — | jsPDF trip tickets & utilization reports | Planned |

See the [F-01 implementation report](docs/F-01-implementation-report.md) for design details, API contract, and test results.

## Tech stack

| Layer | Technology |
|---|---|
| Presentation | Django Templates, FullCalendar 6 (jsPDF planned) |
| Application / business logic | Python 3.14, Django 5.2, Django REST Framework 3.16 |
| Data | PostgreSQL 17 via Django ORM |
| Authentication | Django session login (temporary) → Firebase Authentication (planned) |
| Background jobs | Celery + Django-Celery-Beat + Redis (planned) |

## Project structure

```
govfleet/                 Django project (settings, root URLs)
reservations/
  models.py               Vehicle, Reservation + DB constraints
  services/               Business logic (VehicleReservationService)
  api/                    DRF serializers, views, URLs (JSON API)
  views.py, urls.py       HTML page views
  templates/, static/     FullCalendar page, login page, CSS/JS
  tests/                  pytest suite
scripts/                  Local database setup
docs/                     Reports and documentation
```

## Getting started (Windows)

### Prerequisites
- Python 3.12+ (developed on 3.14)
- PostgreSQL 13+ (developed on 17) and access to its `postgres` superuser

### 1. Install dependencies
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Configure environment
Copy `.env.example` to `.env` and set real values. Generate a Django secret key with:
```powershell
.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```
Use a long random value for `DB_PASSWORD`. **Never commit `.env`.**

### 3. Create the database
Creates a least-privilege `govfleet_app` role and the `govfleet` database from the values in `.env`. You will be prompted for the PostgreSQL superuser password (it is not stored).
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_db.ps1
```

### 4. Migrate and create an admin account
```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
```

### 5. Run
```powershell
.\.venv\Scripts\python.exe manage.py runserver
```
- Add vehicles at http://127.0.0.1:8000/admin/
- Make reservations at http://127.0.0.1:8000/

### Run the tests
```powershell
.\.venv\Scripts\python.exe -m pytest
```

## API overview

All endpoints require authentication and return JSON.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/vehicles/` | List active vehicles |
| GET | `/api/vehicles/<id>/availability/?start_time=&end_time=` | Check if a vehicle is free |
| POST | `/api/reservations/` | Submit a reservation request |
| GET | `/api/calendar/events/?start=&end=[&vehicle=]` | FullCalendar event feed |

Status codes: `400` invalid input · `401` not authenticated · `403` insufficient role (planned) · `409` time-slot conflict.
