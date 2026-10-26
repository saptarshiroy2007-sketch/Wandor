"""Every teacher-facing query on Student/Test/ClassSession needs the SAME scoping
rule, and getting it wrong silently leaks data across tenants rather than erroring -
see the migration 0008 docstring for the bug this closes. One function, used
everywhere, so the rule can't drift between routers again.

Institute-affiliated teachers (Teacher.institute_id is not None) share their
institute's data by design - that's a feature, not a bug: teammates see the same
roster/tests/classes. Independent teachers (Teacher.institute_id is None) have no
institute to share within, so they're scoped to rows they personally created
(teacher_id match) instead. Without the teacher_id branch, every independent
teacher on the platform would match the same `institute_id IS NULL` condition and
see each other's data.
"""
from sqlalchemy import and_


def owner_scope(model, teacher):
    """Returns a SQLAlchemy boolean expression to `.filter()` by. `model` must have
    both an `institute_id` and a `teacher_id` column (Student, Test, ClassSession).
    For FeeRecord (which only has student_id), apply this to the joined Student
    class instead, after `.join(FeeRecord.student)`."""
    if teacher.institute_id is not None:
        return model.institute_id == teacher.institute_id
    return and_(model.institute_id.is_(None), model.teacher_id == teacher.id)


def student_test_scope(model, student):
    """Mirror of owner_scope() for the student-facing side (list_available_tests):
    which Test rows can this student see. Institute-affiliated students share their
    institute's tests (institute_id match). A student belonging to an independent
    teacher has no institute, so they're scoped to that teacher's tests specifically
    (student.teacher_id match on the test) - not every independent teacher's tests
    platform-wide."""
    if student.institute_id is not None:
        return model.institute_id == student.institute_id
    return and_(model.institute_id.is_(None), model.teacher_id == student.teacher_id)
