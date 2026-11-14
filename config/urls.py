from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from scheduling import api, views

router = DefaultRouter()
router.register("qualifications", api.QualificationViewSet)
router.register("stations", api.StationViewSet)
router.register("employees", api.EmployeeViewSet)
router.register("shifts", api.ShiftViewSet, basename="shift")
router.register("assignments", api.AssignmentViewSet)

urlpatterns = [
    path("", views.schedule_board, name="schedule-board"),
    path("api/", include(router.urls)),
    path("admin/", admin.site.urls),
]
