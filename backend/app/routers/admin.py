from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Institute, Teacher, Student, FeeRecord
from ..schemas import AdminSummary, InstituteAdminOut
from ..auth import get_current_superadmin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/summary", response_model=AdminSummary)
def admin_summary(db: Session = Depends(get_db), _: object = Depends(get_current_superadmin)):
    total_institutes = db.query(func.count(Institute.id)).scalar() or 0
    total_teachers = db.query(func.count(Teacher.id)).scalar() or 0
    total_students = db.query(func.count(Student.id)).scalar() or 0
    total_fees = db.query(func.count(FeeRecord.id)).scalar() or 0
    total_paid = db.query(func.coalesce(func.sum(FeeRecord.amount_paid), 0.0)).scalar() or 0.0
    total_due = db.query(func.coalesce(func.sum(FeeRecord.amount_due - FeeRecord.amount_paid), 0.0)).scalar() or 0.0
    overdue_count = db.query(func.count(FeeRecord.id)).filter(FeeRecord.is_paid == False, FeeRecord.due_date < func.now()).scalar() or 0
    overdue_amount = db.query(func.coalesce(func.sum(FeeRecord.amount_due - FeeRecord.amount_paid), 0.0)).filter(FeeRecord.is_paid == False, FeeRecord.due_date < func.now()).scalar() or 0.0

    return AdminSummary(
        total_institutes=total_institutes,
        total_teachers=total_teachers,
        total_students=total_students,
        total_fees=total_fees,
        total_paid=total_paid,
        total_due=total_due,
        overdue_count=overdue_count,
        overdue_amount=overdue_amount,
    )


@router.get("/institutes", response_model=list[InstituteAdminOut])
def list_institutes(db: Session = Depends(get_db), _: object = Depends(get_current_superadmin)):
    institutes = (
    db.query(
        Institute.id,
        Institute.name,
        Institute.owner_phone,
        Institute.plan,
        Institute.created_at,
        func.count(Teacher.id).label("total_teachers"),
        func.count(Student.id).label("total_students"),
        func.coalesce(func.sum(FeeRecord.amount_paid), 0.0).label("total_paid"),
        func.coalesce(func.sum(FeeRecord.amount_due - FeeRecord.amount_paid), 0.0).label("total_due"),
        func.count(
            func.nullif(FeeRecord.is_paid, True)
        ).filter(FeeRecord.due_date < func.now()).label("overdue_count"),
    )
    .join(Teacher, Teacher.institute_id == Institute.id, isouter=True)
    .join(Student, Student.institute_id == Institute.id, isouter=True)
    .join(FeeRecord, FeeRecord.student_id == Student.id, isouter=True)
    .group_by(Institute.id)
    .all()
)

    response = []
    for row in institutes:
        response.append(InstituteAdminOut(
            id=row.id,
            name=row.name,
            owner_phone=row.owner_phone,
            plan=row.plan,
            created_at=row.created_at,
            total_teachers=row.total_teachers,
            total_students=row.total_students,
            total_fees=db.query(func.count(FeeRecord.id)).join(Student).filter(Student.institute_id == row.id).scalar() or 0,
            total_paid=row.total_paid,
            total_due=row.total_due,
            overdue_count=row.overdue_count or 0,
        ))

    return response