import logging

from django.conf import settings
from django.core.mail import send_mail

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


def send_ticket_confirmation(
    customer_email: str,
    customer_name: str,
    product_name: str,
    amount_cents: int,
    qr_code_base64: str,
) -> None:
    """Guest ticket delivery — the QR is embedded directly in the email, since a
    guest has no account wallet to view it in."""
    display_name = customer_name or "there"
    amount_display = f"${amount_cents / 100:.2f}"
    tickets_url = f"{FRONTEND_BASE}/tickets"

    html_body = f"""
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#fff;">
        Your Pass Is Confirmed
      </h1>
      <p style="margin:0 0 24px;font-size:15px;color:#aaa;">
        Hey {display_name}, your match pass is ready. Show the QR code below at the gate — no physical ticket needed.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:rgba(0,116,255,0.06);border:1px solid rgba(0,116,255,0.25);
                    border-radius:10px;margin-bottom:28px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0 0 4px;font-size:11px;color:#0074ff;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;">Pass</p>
            <p style="margin:0;font-size:18px;color:#fff;font-weight:700;">{product_name}</p>
            <p style="margin:8px 0 0;font-size:11px;color:#0074ff;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;">Amount Paid</p>
            <p style="margin:4px 0 0;font-size:18px;color:#fff;font-weight:700;">{amount_display}</p>
          </td>
        </tr>
      </table>

      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:28px;">
        <tr>
          <td align="center" style="background:#fff;border-radius:10px;padding:20px;">
            <img src="data:image/png;base64,{qr_code_base64}" alt="Ticket QR code"
                 width="220" height="220" style="display:block;width:220px;height:220px;" />
          </td>
        </tr>
      </table>

      <p style="margin:0 0 24px;font-size:14px;color:#aaa;line-height:1.7;">
        Security scans this code at the gate — no physical tickets issued. Passes are non-refundable.
        Questions? Reach out to us at
        <a href="mailto:{settings.DEFAULT_FROM_EMAIL}"
           style="color:#0074ff;text-decoration:none;">{settings.DEFAULT_FROM_EMAIL}</a>.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="center">
            <a href="{tickets_url}"
               style="display:inline-block;padding:14px 36px;background:#0074ff;
                      color:#fff;font-size:15px;font-weight:700;text-decoration:none;
                      border-radius:8px;letter-spacing:0.5px;">
              Browse More Passes &rarr;
            </a>
          </td>
        </tr>
      </table>
    """

    text_body = (
        f"Your Pass Is Confirmed — TekkyFutbol\n\n"
        f"Hey {display_name}, your match pass is ready.\n\n"
        f"Pass: {product_name}\n"
        f"Amount paid: {amount_display}\n\n"
        f"Your QR code is attached as an image in this email — show it at the gate for entry. "
        f"No physical tickets issued. Passes are non-refundable.\n"
        f"Questions? Email us at {settings.DEFAULT_FROM_EMAIL}\n\n"
        f"Browse more passes: {tickets_url}\n\n"
        f"— TekkyFutbol"
    )

    try:
        send_mail(
            subject=f"Your Pass Is Confirmed — {product_name}",
            message=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[customer_email],
            html_message=_wrap_html(html_body),
            fail_silently=False,
        )
        logger.info("Ticket confirmation sent to %s for '%s'", customer_email, product_name)
    except Exception:
        logger.exception("Failed to send ticket confirmation to %s", customer_email)
