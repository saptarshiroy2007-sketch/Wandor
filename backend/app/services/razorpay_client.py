"""One place that builds the Razorpay client (used by billing + fee payments).

The repo ships with NO Razorpay credentials (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET /
RAZORPAY_WEBHOOK_SECRET are empty in .env.example). With them empty the app runs normally
and every ONLINE-payment feature switches itself off cleanly: students/parents see
"pay your teacher directly", subscribing says online payments aren't set up, and nothing
ever calls Razorpay. Teachers can still record cash/UPI payments by hand. Add the keys to
the real .env to connect Razorpay - no code change needed.
"""
from fastapi import HTTPException

from ..database import settings

NOT_CONFIGURED = "Online payments aren't switched on yet."


def razorpay_configured() -> bool:
    """True only when both API keys are set."""
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def require_razorpay() -> None:
    """Call at the top of any endpoint that talks to Razorpay or checks a Razorpay
    signature. Without it, an empty secret would still produce a (forgeable) valid HMAC."""
    if not razorpay_configured():
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)


def get_razorpay_client():
    """Imported lazily so the whole backend doesn't fail to boot if the razorpay SDK
    has a packaging hiccup (it depends on pkg_resources/setuptools, which isn't always
    present in a fresh venv) or if Razorpay keys aren't configured yet."""
    import razorpay
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
