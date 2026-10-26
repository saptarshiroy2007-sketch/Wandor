from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Teacher, Student, Institute
from ..schemas import UploadOut
from ..auth import get_current_teacher, get_current_student, get_current_institute_admin
from ..services.storage import save_file

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}
MAX_FILE_SIZE_MB = 25
MAX_PHOTO_SIZE_MB = 5  # a profile photo has no business being 25MB


_MAGIC = {"pdf": (b"%PDF",), "image": (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")}


def _check_magic(contents: bytes, allow_pdf: bool) -> None:
    """The Content-Type header is whatever the client says it is; check the file's own first
    bytes so an HTML/script file renamed .pdf is rejected."""
    kinds = _MAGIC["image"] + (_MAGIC["pdf"] if allow_pdf else ())
    if not contents.startswith(kinds):
        raise HTTPException(status_code=400, detail="That file's contents don't match its type")


async def _read_and_validate_photo(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}")
    contents = await file.read()
    if len(contents) > MAX_PHOTO_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Photo exceeds {MAX_PHOTO_SIZE_MB}MB limit")
    _check_magic(contents, allow_pdf=False)
    return contents


@router.post("/test-document", response_model=UploadOut)
async def upload_test_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Upload a PDF/image for a document_locked test. Returns a URL to pass as
    document_url in POST /tests/document."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_FILE_SIZE_MB}MB limit")
    _check_magic(contents, allow_pdf=True)

    url = save_file(contents, file.filename)
    return UploadOut(url=url, filename=file.filename)


# ---------- Profile photos - one small endpoint per role, mirroring the rest of the
# app's per-role router split (get_current_teacher/get_current_student/
# get_current_institute_admin each need their own bearer-token scheme). All three
# just save the file and stamp photo_url straight onto the account - no separate
# "confirm" step, since a profile photo isn't sensitive enough to need one. ----------
@router.post("/profile-photo/teacher", response_model=UploadOut)
async def upload_teacher_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    contents = await _read_and_validate_photo(file)
    url = save_file(contents, file.filename)
    teacher.photo_url = url
    db.commit()
    return UploadOut(url=url, filename=file.filename)


@router.post("/profile-photo/student", response_model=UploadOut)
async def upload_student_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student),
):
    contents = await _read_and_validate_photo(file)
    url = save_file(contents, file.filename)
    student.photo_url = url
    db.commit()
    return UploadOut(url=url, filename=file.filename)


@router.post("/profile-photo/institute", response_model=UploadOut)
async def upload_institute_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    contents = await _read_and_validate_photo(file)
    url = save_file(contents, file.filename)
    institute.photo_url = url
    db.commit()
    return UploadOut(url=url, filename=file.filename)
