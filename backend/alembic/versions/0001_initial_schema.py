"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-27

Hand-written to match app/models.py as of this fix batch (adds hashed_password on
students + attendance_records table on top of the pre-existing skeleton schema).
Written by hand rather than via `alembic revision --autogenerate` since no live
Postgres instance is reachable from this environment - double check against a real
DB with `alembic check` before applying to production.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institutes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("owner_phone", sa.String, nullable=False, unique=True),
        sa.Column("plan", sa.String, server_default="free"),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "teachers",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("institute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("institutes.id")),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("phone", sa.String, nullable=False, unique=True),
        sa.Column("hashed_password", sa.String, nullable=False),
        sa.Column("is_owner", sa.Boolean, server_default=sa.false()),
    )

    op.create_table(
        "students",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("institute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("institutes.id")),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("phone", sa.String, nullable=False),
        sa.Column("parent_phone", sa.String, nullable=True),
        sa.Column("batch", sa.String, nullable=True),
        sa.Column("hashed_password", sa.String, nullable=True),
    )

    class_status = postgresql.ENUM("scheduled", "cancelled", "completed", name="classstatus")
    class_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "class_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("institute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("institutes.id")),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teachers.id")),
        sa.Column("batch", sa.String, nullable=False),
        sa.Column("subject", sa.String, nullable=False),
        sa.Column("start_time", sa.DateTime, nullable=False),
        sa.Column("end_time", sa.DateTime, nullable=False),
        sa.Column("status", class_status, server_default="scheduled"),
        sa.Column("cancel_reason", sa.String, nullable=True),
    )

    op.create_table(
        "fee_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("students.id")),
        sa.Column("amount_due", sa.Float, nullable=False),
        sa.Column("amount_paid", sa.Float, server_default="0.0"),
        sa.Column("due_date", sa.DateTime, nullable=False),
        sa.Column("razorpay_order_id", sa.String, nullable=True),
        sa.Column("razorpay_payment_id", sa.String, nullable=True),
        sa.Column("paid_at", sa.DateTime, nullable=True),
        sa.Column("is_paid", sa.Boolean, server_default=sa.false()),
    )

    test_type = postgresql.ENUM("mcq_auto", "document_locked", name="testtype")
    test_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tests",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("institute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("institutes.id")),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("test_type", test_type, nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("document_url", sa.String, nullable=True),
        sa.Column("topic", sa.String, nullable=True),
        sa.Column("num_questions", sa.Integer, server_default="10"),
    )

    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("test_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tests.id")),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("option_a", sa.String),
        sa.Column("option_b", sa.String),
        sa.Column("option_c", sa.String),
        sa.Column("option_d", sa.String),
        sa.Column("correct_option", sa.String),
    )

    op.create_table(
        "test_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("test_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tests.id")),
        sa.Column("student_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("students.id")),
        sa.Column("started_at", sa.DateTime),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("is_flagged", sa.Boolean, server_default=sa.false()),
        sa.Column("flag_count", sa.Integer, server_default="0"),
        sa.Column("answers", sa.Text, nullable=True),
    )

    op.create_table(
        "attendance_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("institute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("institutes.id")),
        sa.Column("class_session_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("class_sessions.id")),
        sa.Column("student_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("students.id")),
        sa.Column("present", sa.Boolean, server_default=sa.false()),
        sa.Column("marked_at", sa.DateTime),
        sa.Column("marked_by_teacher_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teachers.id"), nullable=True),
    )

    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("institute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("institutes.id")),
        sa.Column("recipient_phone", sa.String, nullable=False),
        sa.Column("channel", sa.String),
        sa.Column("message", sa.Text),
        sa.Column("status", sa.String),
        sa.Column("sent_at", sa.DateTime),
    )


def downgrade() -> None:
    op.drop_table("notification_logs")
    op.drop_table("attendance_records")
    op.drop_table("test_attempts")
    op.drop_table("questions")
    op.drop_table("tests")
    postgresql.ENUM(name="testtype").drop(op.get_bind(), checkfirst=True)
    op.drop_table("fee_records")
    op.drop_table("class_sessions")
    postgresql.ENUM(name="classstatus").drop(op.get_bind(), checkfirst=True)
    op.drop_table("students")
    op.drop_table("teachers")
    op.drop_table("institutes")
