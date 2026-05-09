"""
Team invite email notifications.

Sends branded HTML emails for:
  - Direct invite to a registered player (invite email with accept link)
  - Captain notification when a player accepts their invite
  - Captain notification when a player rejects their invite
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

logger = logging.getLogger(__name__)

FRONTEND_BASE = getattr(settings, "FRONTEND_BASE_URL", "https://tekkyfutbol.net")


# ---------------------------------------------------------------------------
# Shared HTML wrapper (matches existing application email style)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Email builders
# ---------------------------------------------------------------------------

def _build_direct_invite_email(player_name: str, team_name: str, captain_name: str, join_url: str) -> tuple[str, str]:
    html = f"""
      <p style="margin:0 0 8px;font-size:28px;">⚽</p>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">
        You've been invited, {player_name}!
      </h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        <strong style="color:#0074ff;">{captain_name}</strong> has invited you to join their team
        <strong style="color:#fff;">{team_name}</strong> on TekkyFutbol.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:rgba(0,116,255,0.06);border:1px solid rgba(0,116,255,0.25);border-radius:10px;margin-bottom:28px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0 0 4px;font-size:11px;color:#0074ff;font-weight:700;text-transform:uppercase;letter-spacing:1px;">Team</p>
            <p style="margin:0;font-size:18px;color:#fff;font-weight:700;">{team_name}</p>
            <p style="margin:4px 0 0;font-size:13px;color:#aaa;">Captain: {captain_name}</p>
          </td>
        </tr>
      </table>

      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="center">
            <a href="{join_url}"
               style="display:inline-block;padding:14px 36px;background:#0074ff;
                      color:#fff;font-size:15px;font-weight:700;text-decoration:none;
                      border-radius:8px;letter-spacing:0.5px;">
              View Invitation &rarr;
            </a>
          </td>
        </tr>
      </table>

      <p style="margin:24px 0 0;font-size:13px;color:#555;text-align:center;">
        This invite expires in 7 days. If you did not expect this email, you can safely ignore it.
      </p>
    """
    text = (
        f"Hi {player_name},\n\n"
        f"{captain_name} has invited you to join team '{team_name}' on TekkyFutbol.\n\n"
        f"View your invitation: {join_url}\n\n"
        f"This invite expires in 7 days.\n\n"
        f"— TekkyFutbol"
    )
    return _wrap_html(html), text


def _build_invite_accepted_email(captain_name: str, player_name: str, team_name: str) -> tuple[str, str]:
    html = f"""
      <p style="margin:0 0 8px;font-size:28px;">🎉</p>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">
        {player_name} accepted your invite!
      </h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Hi {captain_name}, <strong style="color:#00c864;">{player_name}</strong> has accepted your
        invitation to join <strong style="color:#fff;">{team_name}</strong>.
      </p>
      <p style="margin:0 0 0;font-size:15px;color:#ccc;line-height:1.7;">
        Their membership is now <strong style="color:#f0a500;">pending admin approval</strong>.
        Once approved, they will appear on your official roster.
      </p>
    """
    text = (
        f"Hi {captain_name},\n\n"
        f"{player_name} has accepted your invitation to join {team_name}!\n\n"
        f"Their membership is now pending admin approval.\n"
        f"Once approved, they will appear on your official roster.\n\n"
        f"— TekkyFutbol"
    )
    return _wrap_html(html), text


def _build_invite_rejected_email(captain_name: str, player_name: str, team_name: str) -> tuple[str, str]:
    html = f"""
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">
        Invite declined
      </h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Hi {captain_name}, <strong style="color:#ff6b6b;">{player_name}</strong> has declined your
        invitation to join <strong style="color:#fff;">{team_name}</strong>.
      </p>
      <p style="margin:0;font-size:15px;color:#ccc;line-height:1.7;">
        You can invite another player from the free-agent pool in your captain dashboard.
      </p>
    """
    text = (
        f"Hi {captain_name},\n\n"
        f"{player_name} has declined your invitation to join {team_name}.\n\n"
        f"You can invite another player from the free-agent pool in your dashboard.\n\n"
        f"— TekkyFutbol"
    )
    return _wrap_html(html), text


# ---------------------------------------------------------------------------
# Public entry points (all fire via transaction.on_commit)
# ---------------------------------------------------------------------------

def send_direct_invite_email(invite) -> None:
    """Send the invite email to a registered player after a direct invite is created."""
    player       = invite.invited_user
    captain      = invite.invited_by
    team         = invite.team
    player_name  = player.name or player.email.split("@")[0]
    captain_name = captain.name or captain.email.split("@")[0]
    join_url     = f"{FRONTEND_BASE}/join/{invite.token}"

    subject  = f"⚽ {captain_name} invited you to join {team.name} on TekkyFutbol"
    html, text = _build_direct_invite_email(player_name, team.name, captain_name, join_url)
    _from    = settings.DEFAULT_FROM_EMAIL
    _to      = player.email

    def _send():
        try:
            send_mail(
                subject=subject,
                message=text,
                from_email=_from,
                recipient_list=[_to],
                html_message=html,
                fail_silently=False,
            )
            logger.info("Direct invite email sent to %s (invite=%s)", _to, invite.id)
        except Exception:
            logger.exception("Failed to send invite email to %s", _to)

    transaction.on_commit(_send)


def send_invite_accepted_email(invite) -> None:
    """Notify captain that a player accepted their direct invite."""
    captain      = invite.invited_by
    player       = invite.invited_user
    team         = invite.team
    captain_name = captain.name or captain.email.split("@")[0]
    player_name  = player.name or player.email.split("@")[0]

    subject      = f"🎉 {player_name} joined {team.name}!"
    html, text   = _build_invite_accepted_email(captain_name, player_name, team.name)
    _from        = settings.DEFAULT_FROM_EMAIL
    _to          = captain.email

    def _send():
        try:
            send_mail(
                subject=subject,
                message=text,
                from_email=_from,
                recipient_list=[_to],
                html_message=html,
                fail_silently=False,
            )
            logger.info("Accept notification sent to captain %s", _to)
        except Exception:
            logger.exception("Failed to send accept notification to %s", _to)

    transaction.on_commit(_send)


def _build_membership_approved_email(player_name: str, team_name: str, captain_name: str) -> tuple[str, str]:
    html = f"""
      <p style="margin:0 0 8px;font-size:28px;">✅</p>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">
        You're officially on the team!
      </h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Hi {player_name}, the admin has approved your membership on
        <strong style="color:#fff;">{team_name}</strong>. You are now an official roster member.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:rgba(0,200,100,0.06);border:1px solid rgba(0,200,100,0.25);border-radius:10px;margin-bottom:28px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0 0 4px;font-size:11px;color:#00c864;font-weight:700;text-transform:uppercase;letter-spacing:1px;">Team</p>
            <p style="margin:0;font-size:18px;color:#fff;font-weight:700;">{team_name}</p>
            <p style="margin:4px 0 0;font-size:13px;color:#aaa;">Captain: {captain_name}</p>
          </td>
        </tr>
      </table>

      <p style="margin:0;font-size:13px;color:#555;text-align:center;">
        Log in to your player dashboard to view your team details.
      </p>
    """
    text = (
        f"Hi {player_name},\n\n"
        f"Great news! Admin has approved your membership on team '{team_name}'.\n"
        f"You are now an official roster member.\n\n"
        f"Captain: {captain_name}\n\n"
        f"— TekkyFutbol"
    )
    return _wrap_html(html), text


def _build_membership_rejected_email(player_name: str, team_name: str) -> tuple[str, str]:
    html = f"""
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">
        Membership not approved
      </h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Hi {player_name}, unfortunately your membership on
        <strong style="color:#fff;">{team_name}</strong> was not approved by the admin at this time.
      </p>
      <p style="margin:0;font-size:15px;color:#ccc;line-height:1.7;">
        If you have questions, please contact the TekkyFutbol admin.
      </p>
    """
    text = (
        f"Hi {player_name},\n\n"
        f"Unfortunately your membership on team '{team_name}' was not approved by the admin.\n\n"
        f"If you have questions, please contact the TekkyFutbol admin.\n\n"
        f"— TekkyFutbol"
    )
    return _wrap_html(html), text


def send_membership_approved_email(membership) -> None:
    """Notify player that admin approved their team membership."""
    player       = membership.user
    team         = membership.team
    captain      = team.captain
    player_name  = player.name or player.email.split("@")[0]
    captain_name = captain.name or captain.email.split("@")[0]

    subject    = f"✅ You're officially on {team.name}!"
    html, text = _build_membership_approved_email(player_name, team.name, captain_name)
    _from      = settings.DEFAULT_FROM_EMAIL
    _to        = player.email

    def _send():
        try:
            send_mail(
                subject=subject,
                message=text,
                from_email=_from,
                recipient_list=[_to],
                html_message=html,
                fail_silently=False,
            )
            logger.info("Membership approval email sent to %s (membership=%s)", _to, membership.id)
        except Exception:
            logger.exception("Failed to send membership approval email to %s", _to)

    transaction.on_commit(_send)


def send_membership_rejected_email(membership) -> None:
    """Notify player that admin rejected their team membership."""
    player      = membership.user
    team        = membership.team
    player_name = player.name or player.email.split("@")[0]

    subject    = f"Membership update — {team.name}"
    html, text = _build_membership_rejected_email(player_name, team.name)
    _from      = settings.DEFAULT_FROM_EMAIL
    _to        = player.email

    def _send():
        try:
            send_mail(
                subject=subject,
                message=text,
                from_email=_from,
                recipient_list=[_to],
                html_message=html,
                fail_silently=False,
            )
            logger.info("Membership rejection email sent to %s", _to)
        except Exception:
            logger.exception("Failed to send membership rejection email to %s", _to)

    transaction.on_commit(_send)


def send_invite_rejected_email(invite) -> None:
    """Notify captain that a player rejected their direct invite."""
    captain      = invite.invited_by
    player       = invite.invited_user
    team         = invite.team
    captain_name = captain.name or captain.email.split("@")[0]
    player_name  = player.name or player.email.split("@")[0]

    subject      = f"Invite declined — {player_name} won't be joining {team.name}"
    html, text   = _build_invite_rejected_email(captain_name, player_name, team.name)
    _from        = settings.DEFAULT_FROM_EMAIL
    _to          = captain.email

    def _send():
        try:
            send_mail(
                subject=subject,
                message=text,
                from_email=_from,
                recipient_list=[_to],
                html_message=html,
                fail_silently=False,
            )
            logger.info("Reject notification sent to captain %s", _to)
        except Exception:
            logger.exception("Failed to send reject notification to %s", _to)

    transaction.on_commit(_send)
