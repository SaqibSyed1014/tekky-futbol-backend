from django.urls import path

app_name = "teams"

# ---------------------------------------------------------------------------
# WAIVER GATE — apply to every view that needs it:
#
#   from apps.waivers.permissions import HasSignedWaiver
#
#   class FreeAgentPoolView(generics.ListAPIView):
#       permission_classes = [IsAuthenticated, HasSignedWaiver]   # ← players must sign
#
#   class CreateInviteView(APIView):
#       permission_classes = [IsAuthenticated, IsCaptain, HasSignedWaiver]  # ← captains too
#
# HasSignedWaiver returns {"error": "waiver_required"} on 403 so the
# frontend can detect and redirect to /user/waiver automatically.
# ---------------------------------------------------------------------------

urlpatterns = [
    # Routes added in STEP 2 (free agent pool, invites, roster, etc.)
]
