from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Batch, Student, Test, ClassSession, TeacherBatchAssignment, Teacher
from ..schemas import BatchCreate, BatchRename, BatchOut
from ..auth import get_current_teacher
from ..scoping import owner_scope

router = APIRouter(prefix="/batches", tags=["batches"])


@router.get("", response_model=List[BatchOut])
def list_batches(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Every batch in this teacher's scope - the source of pickers on the Student,
    Test, and Schedule Class forms (they all reference batch_id now, not a free-text
    field). Institute-affiliated teachers see every batch their institute has created,
    even ones they aren't personally assigned to teach - TeacherBatchAssignment is a
    permission grant (can this teacher ADD STUDENTS to that batch), not a visibility
    filter on the batch list itself."""
    return db.query(Batch).filter(owner_scope(Batch, teacher)).order_by(Batch.name).all()


@router.post("", response_model=BatchOut)
def create_batch(payload: BatchCreate, db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    existing = db.query(Batch).filter(
        owner_scope(Batch, teacher), Batch.name.ilike(payload.name)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f'A batch named "{existing.name}" already exists')

    batch = Batch(institute_id=teacher.institute_id, teacher_id=teacher.id, name=payload.name)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.patch("/{batch_id}", response_model=BatchOut)
def rename_batch(batch_id: str, payload: BatchRename, db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Renaming here is exactly why batch became a real entity - this one edit now
    updates the name everywhere the batch is used (every student, test, and class
    session pointing at this batch_id) instead of needing a find-and-replace across
    four separate string columns."""
    batch = db.query(Batch).filter(Batch.id == batch_id, owner_scope(Batch, teacher)).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    clash = db.query(Batch).filter(
        owner_scope(Batch, teacher), Batch.name.ilike(payload.name), Batch.id != batch_id
    ).first()
    if clash:
        raise HTTPException(status_code=400, detail=f'A batch named "{clash.name}" already exists')

    batch.name = payload.name
    db.commit()
    db.refresh(batch)
    return batch


@router.delete("/{batch_id}")
def delete_batch(batch_id: str, db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Blocked if any class session (past or scheduled) still references this batch -
    class_sessions.batch_id is NOT NULL, so deleting the batch out from under real
    class history would either orphan those rows or force a silent cascade delete of
    scheduled/completed classes, neither of which a batch deletion should do without
    the teacher explicitly dealing with those classes first. Students and tests
    pointing at this batch are NOT blocking - their batch_id is nullable, so they're
    unassigned back to "no batch" instead, same as if that field had just been left
    empty. Any teacher-batch permission grants for this batch are removed too, since
    a grant to a batch that no longer exists is meaningless."""
    batch = db.query(Batch).filter(Batch.id == batch_id, owner_scope(Batch, teacher)).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    class_count = db.query(ClassSession).filter(ClassSession.batch_id == batch_id).count()
    if class_count:
        raise HTTPException(
            status_code=409,
            detail=f"Can't delete - {class_count} class session(s) still use this batch. Cancel or reassign them first.",
        )

    db.query(Student).filter(Student.batch_id == batch_id).update({"batch_id": None})
    db.query(Test).filter(Test.batch_id == batch_id).update({"batch_id": None})
    db.query(TeacherBatchAssignment).filter(TeacherBatchAssignment.batch_id == batch_id).delete()
    db.delete(batch)
    db.commit()
    return {"status": "deleted"}
