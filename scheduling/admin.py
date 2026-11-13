from django import forms
from django.contrib import admin

from .models import Assignment, Employee, Qualification, Shift, Station
from .services import check_assignment


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "rank", "max_weekly_hours", "is_active")
    list_filter = ("is_active", "qualifications")
    filter_horizontal = ("qualifications",)


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("station", "start", "end", "required_qualification", "slots")
    list_filter = ("station",)


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ("employee", "shift")

    def clean(self):
        # The admin goes through the same rules engine as the API.
        cleaned = super().clean()
        employee, shift = cleaned.get("employee"), cleaned.get("shift")
        if employee and shift and not self.instance.pk:
            violations = check_assignment(employee, shift)
            if violations:
                raise forms.ValidationError([v.message for v in violations])
        return cleaned


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    form = AssignmentForm
    list_display = ("employee", "shift", "created_at")
