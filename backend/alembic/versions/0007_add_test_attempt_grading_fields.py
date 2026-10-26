"""add max_score/graded_at to test_attempts, stop force-scoring document_locked attempts

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15

What changed and why:
- Adds test_attempts.max_score (Float, nullable) - the total possible marks for an
  attempt. mcq_auto attempts get this set automatically to len(questions) on submit.
  document_locked attempts have no Question rows to derive a total from, so a teacher
  sets it manually at grading time.
- Adds test_attempts.graded_at (DateTime, nullable) - when a teacher published a grade
  for a document_locked attempt. This is the "publish grade" flow that was previously
  entirely missing (see HANDOFF.md item 4): document_locked attempts had no notify
  trigger at all, and submit_attempt() was force-setting score=0 on submission for
  them (since the mcq scoring loop runs over an empty `correct` dict), which looked
  indistinguishable from "graded, scored zero." graded_at being null now means
  "genuinely not graded yet."
- Backfills existing document_locked attempts: any attempt with submitted_at set and
  score == 0 is a pre-fix false zero, not a real grade - reset to score=NULL so it
  shows up as ungraded rather than as a failing mark. mcq_auto attempts are untouched
  (their zero scores are real).

Run order: alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("test_attempts", sa.Column("max_score", sa.Float(), nullable=True))
    op.add_column("test_attempts", sa.Column("graded_at", sa.DateTime(), nullable=True))

    # Backfill: reset the old force-set score=0 on submitted document_locked attempts
    # back to NULL (ungraded), so they don't read as a real zero grade. Written as a
    # portable subquery (not UPDATE...FROM) since this needs to run against both
    # Supabase/Postgres and the local SQLite dev db.
    conn.execute(text("""
        UPDATE test_attempts
        SET score = NULL
        WHERE id IN (
            SELECT ta.id FROM test_attempts ta
            JOIN tests t ON t.id = ta.test_id
            WHERE t.test_type = 'document_locked'
              AND ta.submitted_at IS NOT NULL
              AND ta.score = 0
        )
    """))


def downgrade() -> None:
    op.drop_column("test_attempts", "graded_at")
    op.drop_column("test_attempts", "max_score")
