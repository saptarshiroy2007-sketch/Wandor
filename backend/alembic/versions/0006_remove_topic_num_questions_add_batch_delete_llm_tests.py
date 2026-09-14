"""remove topic/num_questions from tests, add tests.batch, delete LLM-generated MCQ tests

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14

What changed and why:
- MCQ test creation is now teacher-authored (questions supplied directly) rather than
  LLM-generated. The topic and num_questions columns were LLM-generation parameters and
  are now meaningless, so they are dropped.
- A new nullable batch column is added to tests. NULL = institute-wide visibility
  (any student in the institute sees this test). A set value = only students in that
  batch see this test. This fixes the bug where list_available_tests returned every
  test to every student regardless of batch (confirmed real bug in the audit session).
- Per the user's explicit decision (A1): existing mcq_auto tests that were created via
  LLM generation (identifiable by a non-null topic column, captured before the column
  is dropped) are DELETED at migration time, along with their Question rows. Tests with
  a null topic (manually created or document_locked) are preserved.

Run order: alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. Delete LLM-generated MCQ tests (topic IS NOT NULL) and their questions ---
    # Capture IDs of tests to delete before dropping the topic column.
    result = conn.execute(
        text("SELECT id FROM tests WHERE test_type = 'mcq_auto' AND topic IS NOT NULL")
    )
    ids_to_delete = [row[0] for row in result.fetchall()]

    if ids_to_delete:
        # Delete child Question rows first (FK constraint)
        placeholders = ", ".join(f"'{id_}'" for id_ in ids_to_delete)
        conn.execute(text(f"DELETE FROM questions WHERE test_id IN ({placeholders})"))
        conn.execute(text(f"DELETE FROM test_attempts WHERE test_id IN ({placeholders})"))
        conn.execute(text(f"DELETE FROM tests WHERE id IN ({placeholders})"))

    # --- 2. Drop the LLM-generation columns ---
    op.drop_column("tests", "topic")
    op.drop_column("tests", "num_questions")

    # --- 3. Add batch column (nullable - NULL = institute-wide visibility) ---
    op.add_column("tests", sa.Column("batch", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tests", "batch")
    op.add_column("tests", sa.Column("num_questions", sa.Integer(), nullable=True))
    op.add_column("tests", sa.Column("topic", sa.String(), nullable=True))
