"""Data model for emergency-services shift scheduling.

Design notes:
- Business rules live in rules.py, not here. Models only enforce what the
  database itself must guarantee (valid time ranges, no duplicate assignment).
- A shift can need several people (`slots`), e.g. an engine needs a crew of 4.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class Qualification(models.Model):
    """A certification an employee holds, e.g. EMT-B, Paramedic, Driver."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Station(models.Model):
    """A physical location where shifts are worked (station, precinct...)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Employee(models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    rank = models.CharField(max_length=50, blank=True)
    qualifications = models.ManyToManyField(Qualification, blank=True, related_name="employees")
    # Contractual cap; the rules engine enforces it per local calendar week.
    max_weekly_hours = models.PositiveSmallIntegerField(default=48)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Shift(models.Model):
    station = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="shifts")
    start = models.DateTimeField()
    end = models.DateTimeField()
    required_qualification = models.ForeignKey(
        Qualification, null=True, blank=True, on_delete=models.PROTECT, related_name="shifts"
    )
    slots = models.PositiveSmallIntegerField(default=1, help_text="Number of people needed.")

    class Meta:
        ordering = ["start"]
        constraints = [
            # The database itself refuses a shift that ends before it starts.
            models.CheckConstraint(condition=Q(end__gt=F("start")), name="shift_end_after_start"),
            models.CheckConstraint(condition=Q(slots__gte=1), name="shift_slots_at_least_one"),
        ]

    def clean(self):
        if self.start and self.end and self.end <= self.start:
            raise ValidationError("A shift must end after it starts.")

    @property
    def duration_hours(self):
        return (self.end - self.start).total_seconds() / 3600

    def __str__(self):
        return f"{self.station} {self.start:%Y-%m-%d %H:%M}–{self.end:%H:%M}"


class Assignment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="assignments")
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="assignments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "shift"], name="unique_employee_per_shift"),
        ]

    def __str__(self):
        return f"{self.employee} → {self.shift}"
