"""Plan catalog - the single place limits, features and prices live. Edit here to
re-price or re-shape a tier; nothing else hardcodes a limit.

Prices are in rupees and are the BASE price, EXCLUDING GST: GST (GST_RATE_BPS, 18% by
default) is added on top. The Razorpay Plan you create in the dashboard must be priced at
base + GST - the charge amount comes from the Razorpay Plan, not from this file, so
GET /billing/plans reports the exact `total` paise to use for each plan/cycle (see
services/invoices.py::price_breakdown). PLACEHOLDER PRICES - set your real ones.

A limit of None means unlimited.
"""
from typing import Optional

from .database import settings

PLAN_ORDER = ["free", "basic", "pro"]
PAID_PLAN_KEYS = ("basic", "pro")
CYCLE_KEYS = ("monthly", "yearly")

PLANS: dict[str, dict] = {
    "free": {
        "label": "Free",
        "price_monthly": 0,
        "price_yearly": 0,
        "max_students": 25,
        "max_teachers": 1,
        "online_fee_collection": False,
        "fee_reminders": False,  # each reminder is a paid WhatsApp/SMS message
    },
    "basic": {
        "label": "Basic",
        "price_monthly": 499,
        "price_yearly": 4990,   # ~2 months free
        "max_students": 150,
        "max_teachers": 3,
        "online_fee_collection": True,
        "fee_reminders": True,
    },
    "pro": {
        "label": "Pro",
        "price_monthly": 1499,
        "price_yearly": 14990,
        "max_students": None,
        "max_teachers": 15,
        "online_fee_collection": True,
        "fee_reminders": True,
    },
}

# Razorpay requires a total_count of billing cycles when creating a subscription.
# Large on purpose - the customer can cancel any time; this is only the upper bound.
TOTAL_COUNT = {"monthly": 120, "yearly": 10}

TRIAL_PLAN = "pro"


def razorpay_plan_id(plan: str, cycle: str) -> str:
    """Env-configured Razorpay plan_xxx id for (plan, cycle); '' if not configured."""
    return getattr(settings, f"razorpay_plan_{plan}_{cycle}", "") or ""


def plan_from_razorpay_plan_id(rz_plan_id: str) -> Optional[tuple[str, str]]:
    """Reverse lookup: which (plan, cycle) is this Razorpay plan id? None if unknown."""
    if not rz_plan_id:
        return None
    for plan in ("basic", "pro"):
        for cycle in ("monthly", "yearly"):
            if razorpay_plan_id(plan, cycle) == rz_plan_id:
                return plan, cycle
    return None


def limits(plan: str) -> dict:
    return PLANS.get(plan, PLANS["free"])
