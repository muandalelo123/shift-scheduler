"""Scheduling rules engine.

Each rule is a small function that receives the employee, the candidate
shift, and the employee's other assigned shifts, and returns a list of
violations (empty when the rule passes). Rules never touch the database
directly, which keeps them fast and easy to unit-test.

Adding a rule = writing one function and appending it to RULES.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _overlap_hours(start_a, end_a, start_b, end_b):
    """Hours shared by two time ranges (0 if they don't overlap)."""
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)
    seconds = (earliest_end - latest_start).total_seconds()
    return max(seconds, 0) / 3600


def _local_week_bounds(moment):
    """Monday 00:00 → next Monday 00:00, in the agency's local time zone."""
    local = timezone.localtime(moment)
    monday = (local - timedelta(days=local.weekday())).date()
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(monday, datetime.min.time()), tz)
    end = timezone.make_aware(datetime.combine(monday + timedelta(days=7), datetime.min.time()), tz)
    return start, end


def _weeks_touched(shift):
    """All local weeks a shift falls into (a Sunday night shift touches two)."""
    weeks = []
    cursor = shift.start
    while cursor < shift.end:
        bounds = _local_week_bounds(cursor)
        weeks.append(bounds)
        cursor = bounds[1]
    return weeks


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def employee_is_active(employee, shift, other_shifts):
    if not employee.is_active:
        return [Violation("inactive_employee", f"{employee} is not active.")]
    return []


def has_required_qualification(employee, shift, other_shifts):
    required = shift.required_qualification
    if required is None:
        return []
    if not employee.qualifications.filter(pk=required.pk).exists():
        return [Violation(
            "missing_qualification",
            f"{employee} lacks the required qualification {required.code}.",
        )]
    return []


def shift_has_open_slot(employee, shift, other_shifts):
    filled = shift.assignments.exclude(employee=employee).count()
    if filled >= shift.slots:
        return [Violation("shift_full", f"All {shift.slots} slot(s) on this shift are filled.")]
    return []


def no_overlap(employee, shift, other_shifts):
    violations = []
    for other in other_shifts:
        if _overlap_hours(shift.start, shift.end, other.start, other.end) > 0:
            violations.append(Violation("overlap", f"Overlaps with existing shift {other}."))
    return violations


def minimum_rest(employee, shift, other_shifts):
    """Require N hours of rest between consecutive shifts (boundary allowed:
    exactly N hours is fine)."""
    required = timedelta(hours=settings.SCHEDULING_MIN_REST_HOURS)
    violations = []
    for other in other_shifts:
        if _overlap_hours(shift.start, shift.end, other.start, other.end) > 0:
            continue  # already reported by no_overlap
        gap = shift.start - other.end if other.end <= shift.start else other.start - shift.end
        if gap < required:
            hours = gap.total_seconds() / 3600
            violations.append(Violation(
                "insufficient_rest",
                f"Only {hours:g}h of rest next to shift {other} "
                f"(minimum {settings.SCHEDULING_MIN_REST_HOURS}h).",
            ))
    return violations


def weekly_hour_cap(employee, shift, other_shifts):
    """Hours are counted in the week they are actually worked, so an overnight
    shift from Sunday to Monday is split between the two weeks."""
    violations = []
    for week_start, week_end in _weeks_touched(shift):
        total = _overlap_hours(shift.start, shift.end, week_start, week_end)
        for other in other_shifts:
            total += _overlap_hours(other.start, other.end, week_start, week_end)
        if total > employee.max_weekly_hours:
            violations.append(Violation(
                "weekly_hours_exceeded",
                f"{total:g}h in the week of {week_start:%Y-%m-%d} "
                f"exceeds the {employee.max_weekly_hours}h cap.",
            ))
    return violations


RULES = [
    employee_is_active,
    has_required_qualification,
    shift_has_open_slot,
    no_overlap,
    minimum_rest,
    weekly_hour_cap,
]


def evaluate(employee, shift, other_shifts):
    """Run every rule and return all violations, so the scheduler sees every
    problem at once instead of fixing them one by one."""
    violations = []
    for rule in RULES:
        violations.extend(rule(employee, shift, other_shifts))
    return violations
