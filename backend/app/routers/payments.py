import hmac
import hashlib
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import razorpay

from ..database import get_db, settings
from ..models import FeeRecord, Student, Teacher
from ..schemas import CreateOrderRequest, CreateFeeRequest, FeeRecordOut, VerifyPaymentRequest
from ..auth import get_current_teacher, get_current_user, get_current_student

router = APIRouter(prefix="/payments", tags=["payments"])

client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


@router.get("/due", response_model=list[FeeRecordOut])
def list_due_fees(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Fee tracker dashboard - who's paid, who hasn't, across the institute."""
    return (
        db.query(FeeRecord)
        .join(FeeRecord.student)
        .filter(FeeRecord.student.has(institute_id=teacher.institute_id))
        .order_by(FeeRecord.is_paid.asc(), FeeRecord.due_date.asc())
        .all()
    )


@router.get("/my-dues", response_model=list[FeeRecordOut])
def list_my_due_fees(db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    """Student-facing pending dues for the logged-in student."""
    return (
        db.query(FeeRecord)
        .filter(FeeRecord.student_id == student.id, FeeRecord.is_paid == False)
        .order_by(FeeRecord.due_date.asc())
        .all()
    )


@router.get("/my-fees", response_model=list[FeeRecordOut])
def list_my_fees(db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    """Student-facing fee history for the logged-in student."""
    return (
        db.query(FeeRecord)
        .filter(FeeRecord.student_id == student.id)
        .order_by(FeeRecord.due_date.asc())
        .all()
    )


@router.post("/create")
def create_fee(
    payload: CreateFeeRequest,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    student = db.query(Student).filter(Student.id == payload.student_id, Student.institute_id == teacher.institute_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    fee = FeeRecord(
        student_id=student.id,
        amount_due=payload.amount_due,
        due_date=payload.due_date,
    )
    db.add(fee)
    db.commit()
    db.refresh(fee)
    return fee


@router.post("/create-order")
def create_order(
    payload: CreateOrderRequest,
    db: Session = Depends(get_db),
    current: tuple[Any, str] = Depends(get_current_user),
):
    """Creates a Razorpay order for a specific fee record, scoped to the teacher's institute."""
    fee = db.query(FeeRecord).join(FeeRecord.student).filter(FeeRecord.id == payload.fee_record_id).first()
    if not fee:
        raise HTTPException(status_code=404, detail="Fee record not found")
    if fee.is_paid:
        raise HTTPException(status_code=400, detail="Already paid")

    role = current[1]
    if role == "teacher":
        teacher = current[0]
        if fee.student.institute_id != teacher.institute_id:
            raise HTTPException(status_code=403, detail="Not authorized to create order for this fee record")
    else:
        student = current[0]
        if fee.student_id != student.id:
            raise HTTPException(status_code=403, detail="Students can only pay their own fees")

    order = client.order.create({
        "amount": int(fee.amount_due * 100),  # paise
        "currency": "INR",
        "receipt": fee.id,
    })
    fee.razorpay_order_id = order["id"]
    db.commit()

    return {"order_id": order["id"], "amount": fee.amount_due, "key_id": settings.razorpay_key_id}


@router.post("/verify")
def verify_payment(
    payload: VerifyPaymentRequest,
    db: Session = Depends(get_db),
    current: tuple[Any, str] = Depends(get_current_user),
):
    fee = (
        db.query(FeeRecord)
        .join(FeeRecord.student)
        .filter(FeeRecord.id == payload.fee_record_id)
        .first()
    )
    if not fee:
        raise HTTPException(status_code=404, detail="Fee record not found")

    role = current[1]
    if role == "teacher":
        teacher = current[0]
        if fee.student.institute_id != teacher.institute_id:
            raise HTTPException(status_code=403, detail="Not authorized")
    else:
        student = current[0]
        if fee.student_id != student.id:
            raise HTTPException(status_code=403, detail="Students can only verify their own payment")

    if fee.is_paid:
        return {"status": "already_paid"}

    if fee.razorpay_order_id != payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Order ID mismatch")

    if not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay key secret is not configured")

    expected_signature = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid Razorpay signature")

    fee.is_paid = True
    fee.amount_paid = fee.amount_due
    fee.razorpay_payment_id = payload.razorpay_payment_id
    fee.paid_at = datetime.utcnow()
    db.commit()

    return {"status": "ok"}


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """Razorpay hits this on payment success. Verify the signature - never trust
    client-reported 'I paid' without this, that's a free-tests-forever exploit waiting to happen."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not settings.razorpay_webhook_secret:
        raise HTTPException(status_code=500, detail="Razorpay webhook secret is not configured")

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
