"""
Daily automated fee reminder job. Wired into FastAPI's startup/shutdown via
APScheduler's BackgroundScheduler (see main.py). Notifies students (and their
parent, if set) once their fee's due_date is within FEE_REMINDER_DAYS_BEFORE days,
or the fee is already overdue - then keeps reminding once/day until paid or the
teacher deletes the record.

Deterministic, rule-based - no LLM involved, same as attendance/rank/fee logic
elsewhere in the app.
"""
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from ..database import SessionLocal, settings
from ..models import FeeRecord, Student
from .notify import notify

_scheduler: BackgroundScheduler | None = None


def _due_or_overdue_unpaid(db, institute_id: str | None = None):
    cutoff = datetime.utcnow() + timedelta(days=settings.fee_reminder_days_before)
    q = (
        db.query(FeeRecord)
        .join(FeeRecord.student)
        .filter(FeeRecord.is_paid == False)  # noqa: E712
        .filter(FeeRecord.due_date <= cutoff)
    )
    if institute_id is not None:
        q = q.filter(Student.institute_id == institute_id)
    return q.all()


def _already_reminded_today(fee: FeeRecord) -> bool:
    return fee.last_reminder_sent_at is not None and fee.last_reminder_sent_at.date() == datetime.utcnow().date()


def send_due_fee_reminders(institute_id: str | None = None) -> dict:
    """Runs one pass: finds every unpaid fee due within the reminder window (or
    overdue) that hasn't already been reminded today, and notifies the student
    (+ parent, if a parent_phone is set). Pass institute_id to scope the sweep to one
    institute (used by the manual POST /payments/send-reminders-now trigger); leave
    it None for the daily cron job's global sweep across every institute. Returns a
    small summary dict."""
    db = SessionLocal()
    sent = 0
    failed = 0
    try:
        fees = _due_or_overdue_unpaid(db, institute_id)
        for fee in fees:
            if _already_reminded_today(fee):
                continue

            student = db.query(Student).filter(Student.id == fee.student_id).first()
            if not student:
                continue  # orphaned fee record - shouldn't happen, but never crash the job over it

            overdue = fee.due_date < datetime.utcnow()
            when = "was due" if overdue else "is due"
            msg = (
                f"Fee reminder: Rs.{fee.amount_due - fee.amount_paid:.2f} {when} "
                f"on {fee.due_date.strftime('%d %b %Y')} for {student.name}. Please pay at your earliest convenience."
            )

            channel = notify(student.phone, msg, "fee_reminder")
            if student.parent_phone:
                notify(student.parent_phone, msg, "fee_reminder")

            if channel != "failed":
                sent += 1
            else:
                failed += 1

            fee.last_reminder_sent_at = datetime.utcnow()
            db.commit()

        return {"checked": len(fees), "sent": sent, "failed": failed}
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    """Called once from main.py's startup event. No-op if fee_reminder_enabled=False
    in settings, so this can be killed instantly in an environment where you don't
    want it running (e.g. some test/staging setups) without touching code."""
    global _scheduler
    if not settings.fee_reminder_enabled:
        return None

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        send_due_fee_reminders,
        trigger="cron",
        hour=settings.fee_reminder_hour,
        minute=0,
        id="daily_fee_reminders",
        replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
