"""align id/FK columns created as VARCHAR by migrations 0005-0011 with models.py (UUID + FKs)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-20

Why: models.py declares every id/FK as UUID with real foreign keys, but several migrations
created them as VARCHAR with no FK (batches.*, otp_codes.*, students.batch_id/teacher_id,
tests.batch_id/teacher_id, class_sessions.batch_id, teacher_batch_assignments.batch_id).
A database built by `alembic upgrade head` therefore differed from one built by create_all()
(what production was bootstrapped with): no referential integrity, and ids compared as text.

Idempotent on purpose: columns that are already UUID (a create_all-built database) and
foreign keys that already exist are left alone, so this is safe on both kinds of database.
Postgres only (SQLite has no column types to fix). New FKs are added NOT VALID so a database
that already holds an orphaned row can still migrate; the constraint is enforced for all new
writes, and `ALTER TABLE ... VALIDATE CONSTRAINT` can be run once the orphans are cleaned up.
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

UUID_COLUMNS = [
    ("batches", "id"), ("batches", "institute_id"), ("batches", "teacher_id"),
    ("class_sessions", "batch_id"),
    ("otp_codes", "id"), ("otp_codes", "institute_id"),
    ("students", "teacher_id"), ("students", "batch_id"),
    ("teacher_batch_assignments", "batch_id"),
    ("tests", "teacher_id"), ("tests", "batch_id"),
]
FKS = [  # (table, column, referred table)
    ("batches", "institute_id", "institutes"), ("batches", "teacher_id", "teachers"),
    ("class_sessions", "batch_id", "batches"),
    ("students", "batch_id", "batches"), ("students", "teacher_id", "teachers"),
    ("teacher_batch_assignments", "batch_id", "batches"),
    ("tests", "teacher_id", "teachers"), ("tests", "batch_id", "batches"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    insp = sa.inspect(bind)
    for table, col in UUID_COLUMNS:
        if not insp.has_table(table):
            continue
        current = next((c for c in insp.get_columns(table) if c["name"] == col), None)
        if current is None or isinstance(current["type"], sa.dialects.postgresql.UUID):
            continue
        op.execute(sa.text(f'ALTER TABLE "{table}" ALTER COLUMN "{col}" TYPE uuid USING "{col}"::uuid'))
    insp = sa.inspect(bind)  # re-read after the type changes
    for table, col, ref in FKS:
        if not insp.has_table(table):
            continue
        have = any(fk["constrained_columns"] == [col] and fk["referred_table"] == ref
                   for fk in insp.get_foreign_keys(table))
        if not have:
            op.execute(sa.text(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{table}_{col}_fkey" '
                f'FOREIGN KEY ("{col}") REFERENCES "{ref}" (id) NOT VALID'
            ))


    # models.py now declares index=True on teacher_batch_assignments.teacher_id (0005 created it,
    # a create_all-built database never had it).
    op.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS ix_teacher_batch_assignments_teacher_id '
        'ON teacher_batch_assignments (teacher_id)'
    ))


def downgrade() -> None:
    # Deliberately a no-op: UUID columns + FKs are what models.py has always declared, and a
    # create_all-built database never had the VARCHAR form to go back to.
    pass
