from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


@login_required
@ensure_csrf_cookie
def schedule_board(request):
    """Serve the Vue scheduling board. All data is loaded through the API.

    The agency time zone is passed to the page so shifts appear on the right
    local day, whatever time zone the scheduler's browser is in.
    """
    return render(request, "scheduling/board.html", {"time_zone": settings.TIME_ZONE})
