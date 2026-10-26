"""batch as a real entity - replaces free-text batch strings with Batch FK rows

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-20

The bigger version of the earlier typo-tolerance fix (batch_utils.py's
normalize_batch()/batch_matches(), migration-less at the time). That fix made
"Class 10A" and "class 10a" COMPARE as equal; it never stopped four different
tables (students, tests, class_sessions, teacher_batch_assignments) from each
holding their own independently-typed copy of the batch name. This migration
replaces all four string columns with a batch_id FK into a new `batches` table -
one canonical row per batch, everything else just points at it, and comparisons
become plain id equality (batch_utils.py's helpers are no longer needed anywhere
and have been removed from the codebase in this same change).

Backfill strategy (all done in Python here, not raw SQL, since a coaching-centre's
actual data volume is small and this keeps the logic portable across SQLite and
Postgres without relying on dialect-specific GROUP BY/window-function SQL):

1. Add batches table + nullable batch_id columns to all four tables.
2. Walk every row of students/tests/class_sessions/teacher_batch_assignments once,
   grouping by (owner scope, case-insensitive trimmed name) - the exact same
   grouping batch_matches() used to do at query time, done once here instead of on
   every request from now on. First-seen casing becomes the Batch's canonical name.
   teacher_batch_assignments has no institute_id/teacher_id columns of its own (it
   only has teacher_id as the ASSIGNEE) - resolves via that teacher's own
   institute_id, since this table's own docstring says it only ever applies to a
   non-owner, institute-affiliated teacher.
3. Any teacher_batch_assignment row that collapses onto a (teacher_id, batch_id)
   pair already seen (two old rows that were typo'd differently but are the SAME
   batch) is deleted rather than creating a duplicate - a fresh unique constraint
   goes on afterward to keep it that way going forward.
4. Drop the old string columns, tighten NOT NULL where the original column was
   NOT NULL (class_sessions.batch_id, teacher_batch_assignments.batch_id).

Downgrade reconstructs the string columns from each row's linked Batch.name, then
drops the batches table - a best-effort reversal, not a byte-for-byte undo (original
per-row typos/casing are gone forever once step 2 above has deduped them, same as
any other data-normalizing migration).
"""
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "batches",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("institute_id", sa.String, nullable=True),
        sa.Column("teacher_id", sa.String, nullable=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.add_column("students", sa.Column("batch_id", sa.String, nullable=True))
    op.add_column("tests", sa.Column("batch_id", sa.String, nullable=True))
    op.add_column("class_sessions", sa.Column("batch_id", sa.String, nullable=True))
    op.add_column("teacher_batch_assignments", sa.Column("batch_id", sa.String, nullable=True))

    metadata = sa.MetaData()
    # Explicit lightweight table definitions, NOT autoload_with=conn - reflection
    # tries to guess a SQLAlchemy type from SQLite's raw declared column type, and
    # gets it wrong for the app's custom postgresql.UUID-as-string columns (id,
    # institute_id, teacher_id, batch_id all store plain UUID strings everywhere in
    # this codebase, never actual Postgres UUID objects - see models.py's UUID(as_uuid=False)).
    # Reflection misreads that as numeric on SQLite and every row blows up reading a
    # UUID string back as a decimal. Declaring the columns as sa.String here sidesteps
    # that entirely and is also just safer practice - migrations shouldn't depend on
    # models.py's current shape anyway, only on the schema as of this exact revision.
    students_t = sa.Table("students", metadata,
        sa.Column("id", sa.String), sa.Column("institute_id", sa.String),
        sa.Column("teacher_id", sa.String), sa.Column("batch", sa.String),
        sa.Column("batch_id", sa.String))
    tests_t = sa.Table("tests", metadata,
        sa.Column("id", sa.String), sa.Column("institute_id", sa.String),
        sa.Column("teacher_id", sa.String), sa.Column("batch", sa.String),
        sa.Column("batch_id", sa.String))
    sessions_t = sa.Table("class_sessions", metadata,
        sa.Column("id", sa.String), sa.Column("institute_id", sa.String),
        sa.Column("teacher_id", sa.String), sa.Column("batch", sa.String),
        sa.Column("batch_id", sa.String))
    tba_t = sa.Table("teacher_batch_assignments", metadata,
        sa.Column("id", sa.String), sa.Column("teacher_id", sa.String),
        sa.Column("batch", sa.String), sa.Column("batch_id", sa.String))
    teachers_t = sa.Table("teachers", metadata,
        sa.Column("id", sa.String), sa.Column("institute_id", sa.String))
    batches_t = sa.Table("batches", metadata,
        sa.Column("id", sa.String), sa.Column("institute_id", sa.String),
        sa.Column("teacher_id", sa.String), sa.Column("name", sa.String),
        sa.Column("created_at", sa.DateTime))

    batch_registry = {}  # (scope_key, lower(name)) -> batch_id, so every table shares the same grouping

    def get_or_create_batch(institute_id, teacher_id, raw_name):
        if raw_name is None:
            return None
        name = " ".join(str(raw_name).split()).strip()
        if not name:
            return None
        scope = ("inst", institute_id) if institute_id is not None else ("teacher", teacher_id)
        key = (scope, name.lower())
        if key in batch_registry:
            return batch_registry[key]
        new_id = str(uuid.uuid4())
        conn.execute(batches_t.insert().values(
            id=new_id, institute_id=institute_id, teacher_id=teacher_id,
            name=name, created_at=datetime.utcnow(),
        ))
        batch_registry[key] = new_id
        return new_id

    for row in conn.execute(sa.select(students_t.c.id, students_t.c.institute_id, students_t.c.teacher_id, students_t.c.batch)):
        bid = get_or_create_batch(row.institute_id, row.teacher_id, row.batch)
        conn.execute(students_t.update().where(students_t.c.id == row.id).values(batch_id=bid))

    for row in conn.execute(sa.select(tests_t.c.id, tests_t.c.institute_id, tests_t.c.teacher_id, tests_t.c.batch)):
        bid = get_or_create_batch(row.institute_id, row.teacher_id, row.batch)
        conn.execute(tests_t.update().where(tests_t.c.id == row.id).values(batch_id=bid))

    for row in conn.execute(sa.select(sessions_t.c.id, sessions_t.c.institute_id, sessions_t.c.teacher_id, sessions_t.c.batch)):
        bid = get_or_create_batch(row.institute_id, row.teacher_id, row.batch)
        conn.execute(sessions_t.update().where(sessions_t.c.id == row.id).values(batch_id=bid))

    teacher_institute = {
        t.id: t.institute_id for t in conn.execute(sa.select(teachers_t.c.id, teachers_t.c.institute_id))
    }
    seen_assignment_keys = set()
    for row in conn.execute(sa.select(tba_t.c.id, tba_t.c.teacher_id, tba_t.c.batch)):
        inst_id = teacher_institute.get(row.teacher_id)
        if inst_id:
            bid = get_or_create_batch(inst_id, None, row.batch)
        else:
            bid = get_or_create_batch(None, row.teacher_id, row.batch)
        dedupe_key = (row.teacher_id, bid)
        if bid is None or dedupe_key in seen_assignment_keys:
            conn.execute(tba_t.delete().where(tba_t.c.id == row.id))
            continue
        seen_assignment_keys.add(dedupe_key)
        conn.execute(tba_t.update().where(tba_t.c.id == row.id).values(batch_id=bid))

    op.drop_column("students", "batch")
    op.drop_column("tests", "batch")
    op.drop_column("class_sessions", "batch")
    op.drop_column("teacher_batch_assignments", "batch")

    with op.batch_alter_table("class_sessions") as batch_op:
        batch_op.alter_column("batch_id", nullable=False)
    with op.batch_alter_table("teacher_batch_assignments") as batch_op:
        batch_op.alter_column("batch_id", nullable=False)

    with op.batch_alter_table("teacher_batch_assignments") as batch_op:
        batch_op.create_unique_constraint(
            "uq_teacher_batch_assignment", ["teacher_id", "batch_id"]
        )


def downgrade() -> None:
    conn = op.get_bind()

    op.add_column("students", sa.Column("batch", sa.String, nullable=True))
    op.add_column("tests", sa.Column("batch", sa.String, nullable=True))
    op.add_column("class_sessions", sa.Column("batch", sa.String, nullable=True))
    op.add_column("teacher_batch_assignments", sa.Column("batch", sa.String, nullable=True))

    metadata = sa.MetaData()
    students_t = sa.Table("students", metadata, sa.Column("id", sa.String), sa.Column("batch_id", sa.String), sa.Column("batch", sa.String))
    tests_t = sa.Table("tests", metadata, sa.Column("id", sa.String), sa.Column("batch_id", sa.String), sa.Column("batch", sa.String))
    sessions_t = sa.Table("class_sessions", metadata, sa.Column("id", sa.String), sa.Column("batch_id", sa.String), sa.Column("batch", sa.String))
    tba_t = sa.Table("teacher_batch_assignments", metadata, sa.Column("id", sa.String), sa.Column("batch_id", sa.String), sa.Column("batch", sa.String))
    batches_t = sa.Table("batches", metadata, sa.Column("id", sa.String), sa.Column("name", sa.String))

    names = {b.id: b.name for b in conn.execute(sa.select(batches_t.c.id, batches_t.c.name))}

    for t in (students_t, tests_t, sessions_t, tba_t):
        for row in conn.execute(sa.select(t.c.id, t.c.batch_id)):
            conn.execute(t.update().where(t.c.id == row.id).values(batch=names.get(row.batch_id)))

    with op.batch_alter_table("teacher_batch_assignments") as batch_op:
        batch_op.drop_constraint("uq_teacher_batch_assignment", type_="unique")
        batch_op.drop_column("batch_id")
    op.drop_column("class_sessions", "batch_id")
    op.drop_column("tests", "batch_id")
    op.drop_column("students", "batch_id")
    op.drop_table("batches")
