"""Application services: the only place where assignments are created.

Views, the API, and the admin all go through `assign_employee`, so the rules
can never be bypassed.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction

from . import rules
from .models import Assignment, Employee, Shift


class AssignmentRejected(Exception):
    def __init__(self, violations):
        self.violations = violations
        super().__init__("; ".join(v.message for v in violations))


def _relevant_shifts(employee, shift):
    """Other shifts of this employee that could affect the rules: anything
    within a week either side covers overlap, rest, and weekly caps."""
    margin = timedelta(days=7, hours=settings.SCHEDULING_MIN_REST_HOURS)
    return list(
        Shift.objects.filter(
            assignments__employee=employee,
            end__gt=shift.start - margin,
            start__lt=shift.end + margin,
        ).exclude(pk=shift.pk)
    )


def check_assignment(employee, shift):
    """Dry run: return the violations without saving anything."""
    return rules.evaluate(employee, shift, _relevant_shifts(employee, shift))


@transaction.atomic
def assign_employee(employee_id, shift_id):
    """Validate and create an assignment.

    Row locks prevent two schedulers from double-booking the same person or
    over-filling the same shift at the same moment.
    """
    employee = Employee.objects.select_for_update().get(pk=employee_id)
    shift = Shift.objects.select_for_update().get(pk=shift_id)

    if Assignment.objects.filter(employee=employee, shift=shift).exists():
        raise AssignmentRejected([rules.Violation("already_assigned", f"{employee} is already on this shift.")])

    violations = check_assignment(employee, shift)
    if violations:
        raise AssignmentRejected(violations)
    return Assignment.objects.create(employee=employee, shift=shift)
