# Shift Scheduler

A rules-driven shift scheduling backend for emergency services (Fire, EMS, Police), built with Django and PostgreSQL.

Emergency-services scheduling is hard because every assignment must respect qualifications, rest periods, and contractual hour caps. This project models those constraints explicitly and explains every rejected assignment.

> Status: work in progress. Done: data model, rules engine, tests. Next: REST API, Vue scheduling view, CI.

## What it enforces

| Rule | Example rejection |
|---|---|
| Required qualification | `Ana Diaz lacks the required qualification PARAMEDIC.` |
| No overlapping shifts | `Overlaps with existing shift Station 1 2026-11-02 07:00–19:00.` |
| Minimum rest between shifts (configurable, default 10h) | `Only 9h of rest next to shift ... (minimum 10h).` |
| Weekly hour cap per employee | `52h in the week of 2026-11-02 exceeds the 48h cap.` |
| Shift capacity (crew size) | `All 4 slot(s) on this shift are filled.` |
| Active employees only | `Ana Diaz is not active.` |

All violations are reported at once, so a scheduler can fix everything in one pass.

## Design decisions

- **Rules are plain functions** (`scheduling/rules.py`). Each receives the employee, the candidate shift, and the employee's other shifts, and returns violations. Adding a rule means writing one function and registering it.
- **One entry point for assignments** (`scheduling/services.py`). The admin and the upcoming API both go through `assign_employee`, so the rules cannot be bypassed.
- **Concurrency safety.** Assignment creation runs in a transaction with row locks (`select_for_update`), so two schedulers cannot double-book a person or over-fill a shift at the same moment.
- **Hours are counted where they are worked.** An overnight shift from Sunday 19:00 to Monday 07:00 counts 5h in one week and 7h in the next, using the agency's local time zone.
- **The database guards what it can.** Check constraints reject shifts that end before they start; a unique constraint prevents duplicate assignments.

## Run locally (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

createdb shift_scheduler           # PostgreSQL must be running
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver         # admin at http://127.0.0.1:8000/admin/
```

Database settings come from environment variables (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`). Set `DB_ENGINE=sqlite` to run without PostgreSQL.

## Tests

```bash
pytest
```

The suite covers each rule and its edge cases: rest exactly at the minimum, weekly cap exactly reached, overnight shifts split across weeks, and multiple violations reported together.

## Tech stack

Python 3.12+, Django 5.1, Django REST Framework, PostgreSQL, pytest.
