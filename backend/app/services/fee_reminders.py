"""
Daily automated fee reminder job. Wired into FastAPI's startup/shutdown via
APScheduler's BackgroundScheduler (see main.py). Notifies students (and their
parent, if set) once their fee's due_date is within FEE_REMINDER_DAYS_BEFORE days,
or the fee is already overdue - then keeps reminding once/day until paid or the
teacher deletes the record.

Only owners whose plan includes the `fee_reminders` feature (app/plans.py) get reminders;
Free-plan owners are skipped and counted in the summary as `skipped_plan`.

Deterministic, rule-based - no LLM involved, same as attendance/rank/fee logic
elsewhere in the app.
"""
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import and_

from ..database import SessionLocal, settings
from ..models import FeeRecord, Student
from . import subscriptions as subs
from .notify import notify

_scheduler: BackgroundScheduler | None = None


def _due_or_overdue_unpaid(db, institute_id: str | None = None, teacher_id: str | None = None):
    cutoff = datetime.utcnow() + timedelta(days=settings.fee_reminder_days_before)
    q = (
        db.query(FeeRecord)
        .join(FeeRecord.student)
        .filter(FeeRecord.is_paid == False)  # noqa: E712
        .filter(FeeRecord.due_date <= cutoff)
    )
    if teacher_id is not None:
        # An independent teacher's manual trigger - scope to THIS teacher's own
        # students only. Deliberately checked before institute_id: passing both
        # would be a caller bug (an independent teacher has no institute_id to pass),
        # and scoping this tightly is the safer failure mode if that ever happens.
        q = q.filter(and_(Student.institute_id.is_(None), Student.teacher_id == teacher_id))
    elif institute_id is not None:
        q = q.filter(Student.institute_id == institute_id)
    # else: neither given - the daily cron job's global sweep across every institute
    # AND every independent teacher. Only reachable from start_scheduler(), never from
    # a teacher-facing endpoint (see POST /payments/send-reminders-now, which always
    # passes one or the other).
    return q.all()


def reminder_template(student_name: str, fee: FeeRecord, when: str) -> tuple[str, list[str] | None]:
    """(template name, body variables) for the WhatsApp reminder. Variables are only sent
    once FEE_REMINDER_TEMPLATE_VARS=true (meaning the configured template really has them):
      {{1}} student  {{2}} amount still owed  {{3}} due date  {{4}} "was due" / "is due"
    The SMS fallback always carries the full text with the amount either way."""
    if not settings.fee_reminder_template_vars:
        return settings.fee_reminder_template, None
    return settings.fee_reminder_template, [
        student_name,
        f"{fee.amount_due - fee.amount_paid:,.2f}",
        fee.due_date.strftime("%d %b %Y"),
        when,
    ]


def _already_reminded_today(fee: FeeRecord) -> bool:
    return fee.last_reminder_sent_at is not None and fee.last_reminder_sent_at.date() == datetime.utcnow().date()


def send_due_fee_reminders(institute_id: str | None = None, teacher_id: str | None = None) -> dict:
    """Runs one pass: finds every unpaid fee due within the reminder window (or
    overdue) that hasn't already been reminded today, and notifies the student
    (+ parent, if a parent_phone is set). Pass institute_id to scope the sweep to one
    institute, or teacher_id to scope it to one independent teacher's own students
    (used by the manual POST /payments/send-reminders-now trigger - see payments.py
    for why it picks one or the other); leave both None for the daily cron job's
    global sweep across every institute AND independent teacher. Returns a small
    summary dict."""
    db = SessionLocal()
    sent = 0
    failed = 0
    skipped_plan = 0
    entitled: dict[subs.Owner | None, bool] = {}  # one plan lookup per owner per pass
    try:
        fees = _due_or_overdue_unpaid(db, institute_id, teacher_id)
        for fee in fees:
            if _already_reminded_today(fee):
                continue

            student = db.query(Student).filter(Student.id == fee.student_id).first()
            if not student:
                continue  # orphaned fee record - shouldn't happen, but never crash the job over it

            # Every reminder is a paid WhatsApp/SMS message, so only plans that include
            # the "fee_reminders" feature get them. Skipped fees are left untouched
            # (last_reminder_sent_at stays as-is), so they resume the day the owner
            # upgrades. A student with no owner at all is treated as not entitled.
            owner = subs.owner_for_student(student)
            if owner not in entitled:
                entitled[owner] = bool(owner) and subs.has_feature(db, owner, "fee_reminders")
            if not entitled[owner]:
                skipped_plan += 1
                continue

            overdue = fee.due_date < datetime.utcnow()
            when = "was due" if overdue else "is due"
            msg = (
                f"Fee reminder: Rs.{fee.amount_due - fee.amount_paid:.2f} {when} "
                f"on {fee.due_date.strftime('%d %b %Y')} for {student.name}. Please pay at your earliest convenience."
            )

            template, params = reminder_template(student.name, fee, when)
            channel = notify(student.phone, msg, template, params)
            if student.parent_phone:
                notify(student.parent_phone, msg, template, params)

            if channel != "failed":
                sent += 1
            else:
                failed += 1

            fee.last_reminder_sent_at = datetime.utcnow()
            db.commit()

        return {"checked": len(fees), "sent": sent, "failed": failed, "skipped_plan": skipped_plan}
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
