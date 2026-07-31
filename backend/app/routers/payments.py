import hmac
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db, settings
from ..models import FeeRecord, Teacher, Student
from ..schemas import CreateOrderRequest, FeeRecordOut
from ..auth import get_current_teacher, get_current_student
from ..services.fee_reminders import send_due_fee_reminders

router = APIRouter(prefix="/payments", tags=["payments"])


def get_razorpay_client():
    """Imported lazily so the whole backend doesn't fail to boot if the razorpay SDK
    has a packaging hiccup (it depends on pkg_resources/setuptools, which isn't always
    present in a fresh venv) or if Razorpay keys aren't configured yet."""
    import razorpay
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


@router.get("/due", response_model=list[FeeRecordOut])
def list_due_fees(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Fee tracker dashboard - who's paid, who hasn't, WITHIN this teacher's institute only."""
    return (
        db.query(FeeRecord)
        .join(FeeRecord.student)
        .filter(Student.institute_id == teacher.institute_id)
        .filter(FeeRecord.is_paid == False)  # noqa: E712
        .all()
    )


@router.post("/create-order")
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db),
                  student: Student = Depends(get_current_student)):
    """Student-facing - creates a Razorpay order for a specific fee record.
    Requires a student token and verifies the fee record actually belongs to that student,
    so one student can never generate/pay an order against someone else's fee record."""
    fee = db.query(FeeRecord).filter(
        FeeRecord.id == payload.fee_record_id, FeeRecord.student_id == student.id
    ).first()
    if not fee:
        raise HTTPException(status_code=404, detail="Fee record not found")
    if fee.is_paid:
        raise HTTPException(status_code=400, detail="Already paid")

    client = get_razorpay_client()
    order = client.order.create({
        "amount": int(fee.amount_due * 100),  # paise
        "currency": "INR",
        "receipt": fee.id,
    })
    fee.razorpay_order_id = order["id"]
    db.commit()

    return {"order_id": order["id"], "amount": fee.amount_due, "key_id": settings.razorpay_key_id}


@router.post("/send-reminders-now")
def trigger_fee_reminders(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Manual override for the daily cron job (services/fee_reminders.py) - scoped to
    the calling teacher's own institute only, so triggering this never sends reminders
    for another institute's students. Runs synchronously; fine for typical
    coaching-centre fee-record volumes, but revisit as a background task if this ever
    needs to sweep thousands of records on demand."""
    return send_due_fee_reminders(institute_id=teacher.institute_id)


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """Razorpay hits this on payment success. Verify the signature - never trust
    client-reported 'I paid' without this, that's a free-tests-forever exploit waiting to happen."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()
    payment_entity = payload["payload"]["payment"]["entity"]
    order_id = payment_entity["order_id"]

    fee = db.query(FeeRecord).filter(FeeRecord.razorpay_order_id == order_id).first()
    if fee:
        fee.is_paid = True
        fee.amount_paid = fee.amount_due
        fee.razorpay_payment_id = payment_entity["id"]
        from datetime import datetime
        fee.paid_at = datetime.utcnow()
        db.commit()

    return {"status": "ok"}
