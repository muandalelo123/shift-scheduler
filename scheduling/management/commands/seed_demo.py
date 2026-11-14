"""Create demo data: python manage.py seed_demo [--reset]

Two stations, eight employees with different qualifications and hour caps,
and day (07:00–19:00) and night (19:00–07:00) shifts for this week and next.
"""

from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from scheduling.models import Assignment, Employee, Qualification, Shift, Station

EMPLOYEES = [
    # Paramedics also hold the EMT certification, as in real agencies.
    ("Ana", "Diaz", "Captain", ["EMT", "PARAMEDIC", "DRIVER"], 48),
    ("Ben", "Cole", "Lieutenant", ["EMT", "DRIVER"], 48),
    ("Chloe", "Nguyen", "Firefighter", ["EMT", "PARAMEDIC"], 48),
    ("David", "Okafor", "Firefighter", ["EMT"], 36),
    ("Emma", "Rossi", "Firefighter", ["EMT", "DRIVER"], 48),
    ("Farid", "Haddad", "Probationary", ["EMT"], 40),
    ("Grace", "Kim", "Paramedic", ["EMT", "PARAMEDIC"], 24),
    ("Hugo", "Moreau", "Firefighter", [], 48),
]


class Command(BaseCommand):
    help = "Load demo stations, employees, and shifts."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing scheduling data first.")

    @transaction.atomic
    def handle(self, *args, reset=False, **options):
        if reset:
            Assignment.objects.all().delete()
            Shift.objects.all().delete()
            Employee.objects.all().delete()
            Station.objects.all().delete()
            Qualification.objects.all().delete()

        quals = {}
        for code, name in [("EMT", "Emergency Medical Technician"), ("PARAMEDIC", "Paramedic"),
                           ("DRIVER", "Apparatus Driver")]:
            quals[code], _ = Qualification.objects.get_or_create(code=code, defaults={"name": name})

        for first, last, rank, codes, cap in EMPLOYEES:
            employee, created = Employee.objects.get_or_create(
                first_name=first, last_name=last, defaults={"rank": rank, "max_weekly_hours": cap}
            )
            if created:
                employee.qualifications.set(quals[c] for c in codes)

        stations = [Station.objects.get_or_create(name=n)[0] for n in ("Station 1", "Station 2")]

        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        created_shifts = 0
        for offset in range(14):
            day = monday + timedelta(days=offset)
            for station in stations:
                day_start = timezone.make_aware(datetime.combine(day, time(7)), tz)
                night_start = timezone.make_aware(datetime.combine(day, time(19)), tz)
                for start, slots, qual in [(day_start, 3, quals["PARAMEDIC"]), (night_start, 2, quals["EMT"])]:
                    _, created = Shift.objects.get_or_create(
                        station=station, start=start,
                        defaults={"end": start + timedelta(hours=12), "slots": slots, "required_qualification": qual},
                    )
                    created_shifts += created

        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready: {Employee.objects.count()} employees, {created_shifts} new shifts."
        ))
