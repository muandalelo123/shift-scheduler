"""API tests: authentication, the 422 contract for rejected assignments,
the dry-run check, the eligibility list, and week filtering."""

from datetime import datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from scheduling.models import Assignment, Employee, Qualification, Shift, Station

pytestmark = pytest.mark.django_db


def at(day, hour):
    """Aware datetime in the agency's time zone. Day 1 = Monday 2026-11-02."""
    naive = datetime(2026, 11, 1, hour) + timedelta(days=day)
    return timezone.make_aware(naive, timezone.get_current_timezone())


@pytest.fixture
def client():
    user = get_user_model().objects.create_user("scheduler", password="pw-for-tests-only")
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def station():
    return Station.objects.create(name="Station 1")


@pytest.fixture
def employee():
    return Employee.objects.create(first_name="Ana", last_name="Diaz")


def test_api_requires_login(station):
    assert APIClient().get("/api/shifts/").status_code == 403


def test_board_redirects_anonymous_users_to_login():
    response = APIClient().get("/")
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_valid_assignment_returns_201(client, station, employee):
    shift = Shift.objects.create(station=station, start=at(1, 7), end=at(1, 19))
    response = client.post("/api/assignments/", {"employee": employee.pk, "shift": shift.pk}, format="json")
    assert response.status_code == 201
    assert Assignment.objects.filter(employee=employee, shift=shift).exists()


def test_rejected_assignment_returns_422_with_every_violation(client, station, employee):
    paramedic = Qualification.objects.create(code="PARAMEDIC", name="Paramedic")
    first = Shift.objects.create(station=station, start=at(1, 7), end=at(1, 19))
    client.post("/api/assignments/", {"employee": employee.pk, "shift": first.pk}, format="json")
    overlapping = Shift.objects.create(station=station, start=at(1, 12), end=at(1, 20),
                                       required_qualification=paramedic)

    response = client.post("/api/assignments/", {"employee": employee.pk, "shift": overlapping.pk}, format="json")

    assert response.status_code == 422
    codes = {v["code"] for v in response.json()["violations"]}
    assert {"missing_qualification", "overlap"} <= codes
    assert not Assignment.objects.filter(shift=overlapping).exists()


def test_check_endpoint_saves_nothing(client, station, employee):
    shift = Shift.objects.create(station=station, start=at(1, 7), end=at(1, 19))
    response = client.post("/api/assignments/check/", {"employee": employee.pk, "shift": shift.pk}, format="json")
    assert response.json() == {"allowed": True, "violations": []}
    assert Assignment.objects.count() == 0


def test_eligible_lists_allowed_first_with_reasons_for_the_others(client, station):
    paramedic = Qualification.objects.create(code="PARAMEDIC", name="Paramedic")
    qualified = Employee.objects.create(first_name="Zoe", last_name="Ali")
    qualified.qualifications.add(paramedic)
    Employee.objects.create(first_name="Ben", last_name="Cole")
    shift = Shift.objects.create(station=station, start=at(1, 7), end=at(1, 19), required_qualification=paramedic)

    results = client.get(f"/api/shifts/{shift.pk}/eligible/").json()

    assert [r["employee_name"] for r in results] == ["Zoe Ali", "Ben Cole"]
    assert results[0]["allowed"] is True
    assert results[1]["violations"][0]["code"] == "missing_qualification"


def test_week_filter_includes_overnight_shift_from_previous_sunday(client, station):
    sunday_night = Shift.objects.create(station=station, start=at(7, 19), end=at(8, 7))   # Sun → Mon
    next_wednesday = Shift.objects.create(station=station, start=at(10, 7), end=at(10, 19))
    later = Shift.objects.create(station=station, start=at(15, 7), end=at(15, 19))

    ids = {s["id"] for s in client.get("/api/shifts/?week=2026-11-11").json()}

    assert ids == {sunday_night.pk, next_wednesday.pk}
    assert later.pk not in ids


def test_invalid_week_parameter_returns_400(client):
    assert client.get("/api/shifts/?week=next-tuesday").status_code == 400


def test_shift_ending_before_start_is_rejected_by_api(client, station):
    response = client.post("/api/shifts/", {
        "station": station.pk, "start": at(1, 19).isoformat(), "end": at(1, 7).isoformat(), "slots": 1,
    }, format="json")
    assert response.status_code == 400


def test_seed_demo_is_idempotent():
    call_command("seed_demo")
    shifts = Shift.objects.count()
    call_command("seed_demo")
    assert Shift.objects.count() == shifts == 56
    assert Employee.objects.count() == 8
