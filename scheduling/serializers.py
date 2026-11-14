"""Serializers translate models to and from JSON for the REST API."""

from rest_framework import serializers

from .models import Assignment, Employee, Qualification, Shift, Station


class QualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Qualification
        fields = ["id", "code", "name"]


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ["id", "name"]


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    qualifications = serializers.SlugRelatedField(
        many=True, slug_field="code", queryset=Qualification.objects.all(), required=False
    )

    class Meta:
        model = Employee
        fields = ["id", "first_name", "last_name", "full_name", "rank",
                  "qualifications", "max_weekly_hours", "is_active"]

    def get_full_name(self, obj):
        return str(obj)


class AssignedEmployeeSerializer(serializers.ModelSerializer):
    """Compact view of an assignment, nested inside a shift."""

    employee_id = serializers.IntegerField(source="employee.id")
    employee_name = serializers.CharField(source="employee.__str__")

    class Meta:
        model = Assignment
        fields = ["id", "employee_id", "employee_name"]


class ShiftSerializer(serializers.ModelSerializer):
    station_name = serializers.CharField(source="station.name", read_only=True)
    required_qualification_code = serializers.CharField(
        source="required_qualification.code", read_only=True, default=None
    )
    assignments = AssignedEmployeeSerializer(many=True, read_only=True)
    duration_hours = serializers.FloatField(read_only=True)

    class Meta:
        model = Shift
        fields = ["id", "station", "station_name", "start", "end", "duration_hours",
                  "required_qualification", "required_qualification_code", "slots", "assignments"]

    def validate(self, attrs):
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end": "A shift must end after it starts."})
        return attrs


class AssignmentRequestSerializer(serializers.Serializer):
    """Input for creating or checking an assignment."""

    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    shift = serializers.PrimaryKeyRelatedField(queryset=Shift.objects.all())


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = ["id", "employee", "shift", "created_at"]


class ViolationSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
