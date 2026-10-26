"""add teacher_batch_assignments table (signup feature)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-11

Backs the new signup feature (POST /auth/teacher-signup, POST /auth/institute-signup)
and non-owner-teacher batch scoping: a teacher who belongs to an institute and isn't
the owner can only add students to a batch listed here for them. No column changes on
existing tables were needed - Teacher.institute_id was already nullable, which is what
makes independent (self-signed-up) teachers possible; Institute.hashed_password was
already nullable, which is what the old CLI-only bootstrap script relied on and what
institute self-signup now sets directly instead.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teacher_batch_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("batch", sa.String, nullable=False),
    )
    op.create_index(
        "ix_teacher_batch_assignments_teacher_id",
        "teacher_batch_assignments",
        ["teacher_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_teacher_batch_assignments_teacher_id", table_name="teacher_batch_assignments")
    op.drop_table("teacher_batch_assignments")
