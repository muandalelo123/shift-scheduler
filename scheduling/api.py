"""REST API.

Assignments are never created with a plain ModelViewSet: every creation goes
through services.assign_employee, so the rules engine cannot be bypassed.
A rejected assignment returns HTTP 422 with the full list of violations.
"""

from datetime import date, datetime, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Assignment, Employee, Qualification, Shift, Station
from .serializers import (
    AssignmentRequestSerializer,
    AssignmentSerializer,
    EmployeeSerializer,
    QualificationSerializer,
    ShiftSerializer,
    StationSerializer,
    ViolationSerializer,
)
from .services import AssignmentRejected, assign_employee, check_assignment


class QualificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Qualification.objects.all()
    serializer_class = QualificationSerializer


class StationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Station.objects.all()
    serializer_class = StationSerializer


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.prefetch_related("qualifications")
    serializer_class = EmployeeSerializer


def _week_range(week_param):
    """Parse ?week=YYYY-MM-DD (any day of the week) into local Monday→Monday."""
    try:
        day = date.fromisoformat(week_param)
    except ValueError:
        raise ValidationError({"week": "Use the format YYYY-MM-DD."})
    monday = day - timedelta(days=day.weekday())
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(monday, datetime.min.time()), tz)
    end = timezone.make_aware(datetime.combine(monday + timedelta(days=7), datetime.min.time()), tz)
    return start, end


class ShiftViewSet(viewsets.ModelViewSet):
    serializer_class = ShiftSerializer

    def get_queryset(self):
        queryset = (
            Shift.objects.select_related("station", "required_qualification")
            .prefetch_related("assignments__employee")
            .order_by("start", "station__name")
        )
        week = self.request.query_params.get("week")
        if week:
            start, end = _week_range(week)
            # Any shift that overlaps the week, including overnight shifts.
            queryset = queryset.filter(start__lt=end, end__gt=start)
        station = self.request.query_params.get("station")
        if station:
            queryset = queryset.filter(station_id=station)
        return queryset

    @action(detail=True, methods=["get"])
    def eligible(self, request, pk=None):
        """Every active employee not yet on this shift, with the violations
        they would cause. Lets the UI show who can be assigned, and why the
        others can't, before the scheduler clicks anything."""
        shift = get_object_or_404(Shift, pk=pk)
        already_assigned = set(shift.assignments.values_list("employee_id", flat=True))
        results = []
        for employee in Employee.objects.filter(is_active=True).prefetch_related("qualifications"):
            if employee.pk in already_assigned:
                continue
            violations = check_assignment(employee, shift)
            results.append({
                "employee_id": employee.pk,
                "employee_name": str(employee),
                "allowed": not violations,
                "violations": ViolationSerializer(violations, many=True).data,
            })
        results.sort(key=lambda r: (not r["allowed"], r["employee_name"]))
        return Response(results)


class AssignmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                        mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = Assignment.objects.select_related("employee", "shift")
    serializer_class = AssignmentSerializer

    def create(self, request):
        data = AssignmentRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            assignment = assign_employee(data.validated_data["employee"].pk, data.validated_data["shift"].pk)
        except AssignmentRejected as exc:
            return Response(
                {"violations": ViolationSerializer(exc.violations, many=True).data},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response(AssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def check(self, request):
        """Dry run: which rules would this assignment break? Nothing is saved."""
        data = AssignmentRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        violations = check_assignment(data.validated_data["employee"], data.validated_data["shift"])
        return Response({
            "allowed": not violations,
            "violations": ViolationSerializer(violations, many=True).data,
        })
