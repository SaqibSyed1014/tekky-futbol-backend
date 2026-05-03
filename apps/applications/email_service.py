"""
Application status email notifications.

Called from ApplicationService.update_application_status after a successful
status transition. Emails are dispatched via transaction.on_commit so the
message is only sent when the DB change is durable — never on a rolled-back
transaction.

Statuses that trigger an email: approved, rejected, waitlist, interview.
'pending' never triggers one (it is the initial state).
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

logger = logging.getLogger(__name__)

# ─── Subject lines ────────────────────────────────────────────────────────────

_SUBJECTS = {
    "approved": "🎉 Your TekkyFutbol Application Has Been Approved!",
    "rejected": "TekkyFutbol — Application Decision",
    "waitlist": "TekkyFutbol — You're on the Waitlist",
    "interview": "TekkyFutbol — You've Been Selected for an Interview",
}

# ─── Shared HTML wrapper ──────────────────────────────────────────────────────

def _wrap_html(body_html: str) -> str:
    """Wraps inner content in a branded email shell."""
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

          <!-- Header -->
          <tr>
            <td style="padding:28px 32px 20px;border-bottom:1px solid rgba(0,116,255,0.15);">
              <span style="font-family:'Arial Black',Arial,sans-serif;font-size:22px;
                           font-weight:900;letter-spacing:3px;color:#0074ff;
                           text-transform:uppercase;text-decoration:none;">
                TekkyFutbol
              </span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              {body_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 32px 28px;border-top:1px solid rgba(0,116,255,0.1);">
              <p style="margin:0;font-size:12px;color:#555;line-height:1.6;">
                This is an automated message from TekkyFutbol. Please do not reply to this email.<br/>
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


# ─── Status-specific body builders ───────────────────────────────────────────

def _body_approved(name: str, app_type: str, team_name: str | None, admin_notes: str | None) -> tuple[str, str]:
    type_label = "Full Team (Captain)" if app_type == "captain" else "Free Agent"
    team_line = f"<p style='margin:8px 0 0;font-size:15px;color:#ccc;'>Team: <strong style='color:#fff;'>{team_name}</strong></p>" if team_name else ""
    notes_block = (
        f"<table width='100%' cellpadding='0' cellspacing='0' border='0' style='margin-top:24px;background:rgba(0,200,100,0.06);border:1px solid rgba(0,200,100,0.2);border-radius:8px;'>"
        f"<tr><td style='padding:16px;'>"
        f"<p style='margin:0 0 4px;font-size:11px;color:#00c864;font-weight:700;text-transform:uppercase;letter-spacing:1px;'>Note from Admin</p>"
        f"<p style='margin:0;font-size:14px;color:#ccc;line-height:1.6;'>{admin_notes}</p>"
        f"</td></tr></table>"
    ) if admin_notes else ""

    html = f"""
      <p style="margin:0 0 8px;font-size:28px;">🎉</p>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;letter-spacing:1px;">Congratulations, {name}!</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">Your application has been <strong style="color:#00c864;">approved</strong>.</p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:rgba(0,200,100,0.06);border:1px solid rgba(0,200,100,0.25);border-radius:10px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0 0 4px;font-size:11px;color:#00c864;font-weight:700;text-transform:uppercase;letter-spacing:1px;">Application Type</p>
            <p style="margin:0;font-size:15px;color:#fff;font-weight:600;">{type_label}</p>
            {team_line}
          </td>
        </tr>
      </table>

      {notes_block}

      <p style="margin:28px 0 0;font-size:15px;color:#ccc;line-height:1.7;">
        We're thrilled to welcome you to the league. Our team will be in touch shortly with next steps,
        payment instructions, and onboarding details. Keep an eye on your inbox.
      </p>
    """

    text = (
        f"Congratulations {name}!\n\n"
        f"Your {type_label} application has been APPROVED.\n"
        + (f"Team: {team_name}\n" if team_name else "")
        + (f"\nAdmin note: {admin_notes}\n" if admin_notes else "")
        + "\nWe'll be in touch shortly with next steps and onboarding details.\n\n"
        f"— TekkyFutbol"
    )
    return _wrap_html(html), text


def _body_rejected(name: str, admin_notes: str | None) -> tuple[str, str]:
    notes_block = (
        f"<table width='100%' cellpadding='0' cellspacing='0' border='0' style='margin-top:24px;background:rgba(255,60,60,0.06);border:1px solid rgba(255,60,60,0.2);border-radius:8px;'>"
        f"<tr><td style='padding:16px;'>"
        f"<p style='margin:0 0 4px;font-size:11px;color:#ff6b6b;font-weight:700;text-transform:uppercase;letter-spacing:1px;'>Note from Admin</p>"
        f"<p style='margin:0;font-size:14px;color:#ccc;line-height:1.6;'>{admin_notes}</p>"
        f"</td></tr></table>"
    ) if admin_notes else ""

    html = f"""
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">Hi {name},</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Thank you for applying to TekkyFutbol. After careful review, we regret to inform you
        that your application was <strong style="color:#ff6b6b;">not approved</strong> at this time.
      </p>

      {notes_block}

      <p style="margin:28px 0 0;font-size:15px;color:#ccc;line-height:1.7;">
        We appreciate your interest in competing and encourage you to apply again in the next season.
        If you have any questions, feel free to reach out to our team.
      </p>
    """

    text = (
        f"Hi {name},\n\n"
        f"Thank you for your interest in TekkyFutbol. Unfortunately, your application was not approved at this time.\n"
        + (f"\nAdmin note: {admin_notes}\n" if admin_notes else "")
        + "\nWe encourage you to apply again next season.\n\n"
        f"— TekkyFutbol"
    )
    return _wrap_html(html), text


def _body_waitlist(name: str, admin_notes: str | None) -> tuple[str, str]:
    notes_block = (
        f"<table width='100%' cellpadding='0' cellspacing='0' border='0' style='margin-top:24px;background:rgba(160,100,255,0.06);border:1px solid rgba(160,100,255,0.2);border-radius:8px;'>"
        f"<tr><td style='padding:16px;'>"
        f"<p style='margin:0 0 4px;font-size:11px;color:#a064ff;font-weight:700;text-transform:uppercase;letter-spacing:1px;'>Note from Admin</p>"
        f"<p style='margin:0;font-size:14px;color:#ccc;line-height:1.6;'>{admin_notes}</p>"
        f"</td></tr></table>"
    ) if admin_notes else ""

    html = f"""
      <p style="margin:0 0 8px;font-size:28px;">⏳</p>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">Hi {name},</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Your application has been placed on the <strong style="color:#a064ff;">waitlist</strong>.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:rgba(160,100,255,0.06);border:1px solid rgba(160,100,255,0.25);border-radius:10px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0;font-size:15px;color:#ccc;line-height:1.7;">
              We currently don't have an open spot, but you're on our radar.
              If a position becomes available, you'll be among the first we contact.
            </p>
          </td>
        </tr>
      </table>

      {notes_block}

      <p style="margin:28px 0 0;font-size:15px;color:#ccc;line-height:1.7;">
        Thank you for your patience. Stay tuned — we'll reach out as soon as something opens up.
      </p>
    """

    text = (
        f"Hi {name},\n\n"
        f"Your TekkyFutbol application has been placed on the WAITLIST.\n"
        f"We'll reach out if a spot opens up.\n"
        + (f"\nAdmin note: {admin_notes}\n" if admin_notes else "")
        + "\n— TekkyFutbol"
    )
    return _wrap_html(html), text


def _body_interview(name: str, admin_notes: str | None) -> tuple[str, str]:
    notes_block = (
        f"<table width='100%' cellpadding='0' cellspacing='0' border='0' style='margin-top:24px;background:rgba(0,200,255,0.06);border:1px solid rgba(0,200,255,0.2);border-radius:8px;'>"
        f"<tr><td style='padding:16px;'>"
        f"<p style='margin:0 0 4px;font-size:11px;color:#00c8ff;font-weight:700;text-transform:uppercase;letter-spacing:1px;'>Note from Admin</p>"
        f"<p style='margin:0;font-size:14px;color:#ccc;line-height:1.6;'>{admin_notes}</p>"
        f"</td></tr></table>"
    ) if admin_notes else ""

    html = f"""
      <p style="margin:0 0 8px;font-size:28px;">💬</p>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">Hi {name},</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Great news — you've been selected for an <strong style="color:#00c8ff;">interview</strong>!
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:rgba(0,200,255,0.06);border:1px solid rgba(0,200,255,0.25);border-radius:10px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0;font-size:15px;color:#ccc;line-height:1.7;">
              Our team wants to learn more about you. You'll receive a separate email
              shortly with scheduling options and further details.
            </p>
          </td>
        </tr>
      </table>

      {notes_block}

      <p style="margin:28px 0 0;font-size:15px;color:#ccc;line-height:1.7;">
        Please keep an eye on your inbox. If you don't hear from us within 48 hours, check your spam folder.
      </p>
    """

    text = (
        f"Hi {name},\n\n"
        f"Congratulations! You've been selected for an interview for your TekkyFutbol application.\n"
        f"Check your email for scheduling details.\n"
        + (f"\nAdmin note: {admin_notes}\n" if admin_notes else "")
        + "\n— TekkyFutbol"
    )
    return _wrap_html(html), text


# ─── Public entry point ───────────────────────────────────────────────────────

def send_status_notification(application) -> None:
    """
    Schedule a status-update email to the applicant via transaction.on_commit.

    Safe to call inside an atomic block — the email is only sent after the
    surrounding transaction commits successfully.  If the transaction rolls
    back, no email is sent.

    No-ops silently for statuses that don't warrant a notification (e.g.
    transitioning back to 'pending' is impossible by design, so we only
    guard against unknown statuses).
    """
    status    = application.status
    subject   = _SUBJECTS.get(status)
    if not subject:
        return  # 'pending' — no outbound email needed

    applicant  = application.applicant
    name       = applicant.name or applicant.email.split("@")[0]
    to_email   = applicant.email
    app_type   = application.type          # 'captain' or 'free_agent'
    team_name  = (application.metadata or {}).get("team_name") or (
        application.team.name if application.team else None
    )
    admin_notes = application.admin_notes or None

    # Build content
    if status == "approved":
        html_body, text_body = _body_approved(name, app_type, team_name, admin_notes)
    elif status == "rejected":
        html_body, text_body = _body_rejected(name, admin_notes)
    elif status == "waitlist":
        html_body, text_body = _body_waitlist(name, admin_notes)
    elif status == "interview":
        html_body, text_body = _body_interview(name, admin_notes)
    else:
        return

    # Capture locals for the closure
    _subject, _html, _text, _to, _from = subject, html_body, text_body, to_email, settings.DEFAULT_FROM_EMAIL

    def _send():
        try:
            send_mail(
                subject=_subject,
                message=_text,
                from_email=_from,
                recipient_list=[_to],
                html_message=_html,
                fail_silently=False,
            )
            logger.info("Status email sent: status=%s to=%s", status, _to)
        except Exception:
            logger.exception("Failed to send status email to %s (status=%s)", _to, status)

    transaction.on_commit(_send)
