"""add teacher_id to students and tests, to fix independent-teacher data isolation

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15

What changed and why (this is a real cross-tenant data leak fix, not a cosmetic one):

Every teacher-facing query in the app scopes by institute_id alone. For a teacher
who belongs to an institute, that's correct and intentional - teammates share the
same roster/tests/classes. But an INDEPENDENT teacher (Teacher.institute_id IS NULL)
has no institute to share within, and there was no other column to scope by -
`Student.institute_id == teacher.institute_id` compiles to `institute_id IS NULL`,
which matches every independent teacher's students on the entire platform, not just
the calling teacher's own. Same bug existed for Test. ClassSession already had a
teacher_id column (just never used to scope queries) - this migration brings
Student and Test up to the same shape so app/scoping.py can apply one consistent
rule everywhere: institute-affiliated teachers scope by institute_id (shared),
independent teachers scope by teacher_id (private to them).

Nullable on purpose: teacher_id only matters when institute_id is NULL. Rows
created by an institute admin directly (POST /institute/students) have no teacher
at all and keep teacher_id NULL - they're scoped by institute_id like everything
else at that institute.

No backfill needed: this app never had an independent-teacher user base large
enough for the leak to plausibly have been exploited (all sessions to date were
you and Aahir developing/testing), and there's no way to reconstruct after the
fact which pre-existing NULL-institute_id row belonged to which teacher anyway,
since teacher_id genuinely didn't exist as a signal before now. New rows are
correctly scoped from this migration forward.

Run order: alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain nullable columns, no inline FK constraint - matches how batch was added in
    # migration 0006 rather than teacher_batch_assignments' create_table in 0005 (that
    # one could declare the FK at table-creation time; ALTER TABLE ADD COLUMN with an
    # inline FK is the kind of DDL SQLite's ALTER TABLE support is fussy about, and the
    # local dev SQLite db needs to run this same migration).
    op.add_column("students", sa.Column("teacher_id", sa.String(), nullable=True))
    op.add_column("tests", sa.Column("teacher_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tests", "teacher_id")
    op.drop_column("students", "teacher_id")
