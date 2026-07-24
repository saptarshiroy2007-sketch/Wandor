"""
Notification service. WhatsApp is primary (that's what these institutes' parents/students
actually check), Twilio SMS is the fallback for when WhatsApp delivery fails or a number
isn't on WhatsApp.
"""
import httpx
from twilio.rest import Client as TwilioClient

from ..database import settings


def send_whatsapp(to_phone: str, message: str, template_name: str | None = None) -> bool:
    """
    Uses WhatsApp Cloud API directly (Meta). For anything outside the 24hr customer
    service window, you MUST use a pre-approved template (template_name) - free-form
    text only works if the user messaged you first within 24h. Class cancellation
    alerts should almost always go through an approved template for reliability.
    """
    url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}

    if template_name:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {"name": template_name, "language": {"code": "en"}},
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": message},
        }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def send_sms(to_phone: str, message: str) -> bool:
    """Fallback channel via Twilio."""
    try:
        client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(body=message, from_=settings.twilio_from_number, to=to_phone)
        return True
    except Exception:
        return False


def notify(to_phone: str, message: str, template_name: str | None = None) -> str:
    """Try WhatsApp first, fall back to SMS. Returns the channel that succeeded."""
    if send_whatsapp(to_phone, message, template_name):
        return "whatsapp"
    if send_sms(to_phone, message):
        return "sms"
    return "failed"
