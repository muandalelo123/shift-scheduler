"""Tests for the scheduling rules, including the edge cases that matter in
real agencies: exact rest boundaries, overnight shifts, week boundaries."""

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from scheduling.models import Assignment, Employee, Qualification, Shift, Station
from scheduling.services import AssignmentRejected, assign_employee, check_assignment

pytestmark = pytest.mark.django_db


def at(day, hour, minute=0):
    """Aware datetime in the agency's time zone. Day 1 = Monday 2026-11-02."""
    naive = datetime(2026, 11, 1, hour, minute) + timedelta(days=day)
    return timezone.make_aware(naive, timezone.get_current_timezone())


@pytest.fixture
def station():
    return Station.objects.create(name="Station 1")


@pytest.fixture
def paramedic():
    return Qualification.objects.create(code="PARAMEDIC", name="Paramedic")


@pytest.fixture
def employee():
    return Employee.objects.create(first_name="Ana", last_name="Diaz", max_weekly_hours=48)


def make_shift(station, start, end, **kwargs):
    return Shift.objects.create(station=station, start=start, end=end, **kwargs)


def codes(violations):
    return {v.code for v in violations}


# --- Happy path -------------------------------------------------------------

def test_valid_assignment_is_created(employee, station):
    shift = make_shift(station, at(1, 7), at(1, 19))
    assignment = assign_employee(employee.pk, shift.pk)
    assert Assignment.objects.filter(pk=assignment.pk).exists()


# --- Qualification ----------------------------------------------------------

def test_missing_qualification_is_rejected(employee, station, paramedic):
    shift = make_shift(station, at(1, 7), at(1, 19), required_qualification=paramedic)
    assert "missing_qualification" in codes(check_assignment(employee, shift))


def test_qualified_employee_is_accepted(employee, station, paramedic):
    employee.qualifications.add(paramedic)
    shift = make_shift(station, at(1, 7), at(1, 19), required_qualification=paramedic)
    assert check_assignment(employee, shift) == []


# --- Active status and capacity --------------------------------------------

def test_inactive_employee_is_rejected(employee, station):
    employee.is_active = False
    employee.save()
    shift = make_shift(station, at(1, 7), at(1, 19))
    assert "inactive_employee" in codes(check_assignment(employee, shift))


def test_full_shift_is_rejected(employee, station):
    shift = make_shift(station, at(1, 7), at(1, 19), slots=1)
    other = Employee.objects.create(first_name="Ben", last_name="Cole")
    assign_employee(other.pk, shift.pk)
    assert "shift_full" in codes(check_assignment(employee, shift))


def test_same_employee_cannot_be_assigned_twice(employee, station):
    shift = make_shift(station, at(1, 7), at(1, 19), slots=3)
    assign_employee(employee.pk, shift.pk)
    with pytest.raises(AssignmentRejected) as exc:
        assign_employee(employee.pk, shift.pk)
    assert codes(exc.value.violations) == {"already_assigned"}


# --- Overlap and rest -------------------------------------------------------

def test_overlapping_shifts_are_rejected(employee, station):
    assign_employee(employee.pk, make_shift(station, at(1, 7), at(1, 19)).pk)
    overlapping = make_shift(station, at(1, 18), at(2, 6))
    assert "overlap" in codes(check_assignment(employee, overlapping))


def test_rest_shorter_than_minimum_is_rejected(employee, station, settings):
    settings.SCHEDULING_MIN_REST_HOURS = 10
    assign_employee(employee.pk, make_shift(station, at(1, 7), at(1, 19)).pk)
    next_shift = make_shift(station, at(2, 4), at(2, 12))  # 9h rest
    assert "insufficient_rest" in codes(check_assignment(employee, next_shift))


def test_rest_exactly_at_minimum_is_allowed(employee, station, settings):
    settings.SCHEDULING_MIN_REST_HOURS = 10
    assign_employee(employee.pk, make_shift(station, at(1, 7), at(1, 19)).pk)
    next_shift = make_shift(station, at(2, 5), at(2, 13))  # exactly 10h rest
    assert check_assignment(employee, next_shift) == []


def test_rest_is_checked_before_an_existing_shift_too(employee, station, settings):
    settings.SCHEDULING_MIN_REST_HOURS = 10
    assign_employee(employee.pk, make_shift(station, at(2, 7), at(2, 19)).pk)
    earlier = make_shift(station, at(1, 19), at(2, 1))  # ends 6h before the next one
    assert "insufficient_rest" in codes(check_assignment(employee, earlier))


# --- Weekly hour cap --------------------------------------------------------

def test_weekly_cap_is_enforced(employee, station, settings):
    settings.SCHEDULING_MIN_REST_HOURS = 0
    for day in (1, 2, 3, 4):  # 4 x 12h = 48h, Monday to Thursday
        assign_employee(employee.pk, make_shift(station, at(day, 7), at(day, 19)).pk)
    fifth = make_shift(station, at(5, 7), at(5, 19))  # would make 60h
    assert "weekly_hours_exceeded" in codes(check_assignment(employee, fifth))


def test_weekly_cap_exactly_reached_is_allowed(employee, station, settings):
    settings.SCHEDULING_MIN_REST_HOURS = 0
    for day in (1, 2, 3):
        assign_employee(employee.pk, make_shift(station, at(day, 7), at(day, 19)).pk)
    fourth = make_shift(station, at(4, 7), at(4, 19))  # exactly 48h
    assert check_assignment(employee, fourth) == []


def test_overnight_shift_is_split_across_weeks(employee, station, settings):
    """A Sunday 19:00 → Monday 07:00 shift counts 5h in week 1 and 7h in week 2."""
    settings.SCHEDULING_MIN_REST_HOURS = 0
    employee.max_weekly_hours = 40
    employee.save()
    # Week 1 (Mon 2026-11-02 → Sun 2026-11-08): 36h already worked.
    for day in (1, 2, 3):
        assign_employee(employee.pk, make_shift(station, at(day, 7), at(day, 19)).pk)
    # Sunday night shift: 5h land in week 1 → 41h > 40h cap.
    sunday_night = make_shift(station, at(7, 19), at(8, 7))
    violations = check_assignment(employee, sunday_night)
    assert "weekly_hours_exceeded" in codes(violations)
    assert "week of 2026-11-02" in " ".join(v.message for v in violations)


def test_all_violations_are_reported_together(employee, station, paramedic):
    assign_employee(employee.pk, make_shift(station, at(1, 7), at(1, 19)).pk)
    bad = make_shift(station, at(1, 12), at(1, 20), required_qualification=paramedic)
    assert {"missing_qualification", "overlap"} <= codes(check_assignment(employee, bad))


# --- Database guarantees ----------------------------------------------------

def test_database_rejects_shift_ending_before_start(station):
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        make_shift(station, at(1, 19), at(1, 7))
