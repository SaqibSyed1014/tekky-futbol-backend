"""
Kit selection email notifications.

Sends an email to all admin users when a captain locks their kit selection.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

logger = logging.getLogger(__name__)

FRONTEND_BASE = getattr(settings, "FRONTEND_BASE_URL", "https://tekkyfutbol.net")


def _wrap_html(body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0a0a0a;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;background:#000;border-radius:12px;
                      border:1px solid rgba(0,116,255,0.3);
                      box-shadow:0 0 40px rgba(0,116,255,0.1);">
          <tr>
            <td style="padding:28px 32px 20px;border-bottom:1px solid rgba(0,116,255,0.15);">
              <span style="font-family:'Arial Black',Arial,sans-serif;font-size:22px;
                           font-weight:900;letter-spacing:3px;color:#0074ff;
                           text-transform:uppercase;">TekkyFutbol</span>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">{body_html}</td>
          </tr>
          <tr>
            <td style="padding:20px 32px 28px;border-top:1px solid rgba(0,116,255,0.1);">
              <p style="margin:0;font-size:12px;color:#555;line-height:1.6;">
                This is an automated message from TekkyFutbol. Please do not reply.<br/>
                &copy; 2025 TekkyFutbol. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_kit_locked_email(kit_selection) -> None:
    """Notify all admins that a captain has locked their kit selection."""
    from apps.users.models import User

    team         = kit_selection.team
    captain      = team.captain
    captain_name = captain.name or captain.email.split("@")[0]
    kit_slug     = kit_selection.kit_slug
    admin_url    = f"{FRONTEND_BASE}/admin/kits"

    html_body = f"""
      <p style="margin:0 0 8px;font-size:28px;">👕</p>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">
        Kit selection locked — {team.name}
      </h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Captain <strong style="color:#0074ff;">{captain_name}</strong> has finalised the kit
        selection for team <strong style="color:#fff;">{team.name}</strong>.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:rgba(0,116,255,0.06);border:1px solid rgba(0,116,255,0.25);
                    border-radius:10px;margin-bottom:28px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0 0 4px;font-size:11px;color:#0074ff;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;">Selected Kit</p>
            <p style="margin:0;font-size:18px;color:#fff;font-weight:700;">{kit_slug}</p>
            <p style="margin:4px 0 0;font-size:13px;color:#aaa;">Team: {team.name} &nbsp;|&nbsp; Captain: {captain_name} ({captain.email})</p>
          </td>
        </tr>
      </table>

      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="center">
            <a href="{admin_url}"
               style="display:inline-block;padding:14px 36px;background:#0074ff;
                      color:#fff;font-size:15px;font-weight:700;text-decoration:none;
                      border-radius:8px;letter-spacing:0.5px;">
              View Kit Orders &rarr;
            </a>
          </td>
        </tr>
      </table>
    """

    text_body = (
        f"Kit selection locked — {team.name}\n\n"
        f"Captain {captain_name} ({captain.email}) has finalised the kit selection.\n"
        f"Selected kit: {kit_slug}\n\n"
        f"View all kit orders: {admin_url}\n\n"
        f"— TekkyFutbol"
    )

    html = _wrap_html(html_body)
    admin_emails = list(
        User.objects.filter(role="admin", is_active=True).values_list("email", flat=True)
    )

    if not admin_emails:
        logger.warning("No admin users found — kit lock email not sent for team %s", team.id)
        return

    def _send():
        try:
            send_mail(
                subject=f"👕 Kit locked — {team.name} selected {kit_slug}",
                message=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=admin_emails,
                html_message=html,
                fail_silently=False,
            )
            logger.info("Kit lock email sent to admins for team %s (kit=%s)", team.id, kit_slug)
        except Exception:
            logger.exception("Failed to send kit lock email for team %s", team.id)

    transaction.on_commit(_send)
