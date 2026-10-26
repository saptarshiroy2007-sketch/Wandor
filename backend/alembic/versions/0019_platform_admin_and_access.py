"""Platform admin accounts, admin audit log, subscription access columns, created_at on teachers/students

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-21

- platform_admins / admin_audit_log: operator logins and an append-only log of what they did.
- subscriptions: grace_until + admin_banned/admin_ban_reason/admin_banned_at (the access lifecycle).
- teachers.created_at / students.created_at: nullable, NOT backfilled - existing rows stay NULL so they
  count toward totals but never toward "gained this week".
- Backfill: every institute and every independent teacher (institute_id IS NULL) without a Subscription
  gets a plan='free', status='active' row, so the admin panel can see/extend/ban every account the
  lifecycle can lock. Idempotent (only inserts where none exists); the downgrade keeps those rows.
"""
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("phone", sa.String(), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "admin_audit_log",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("admin_id", _uuid(), sa.ForeignKey("platform_admins.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("subscription_id", _uuid(), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("old_value", sa.String(), nullable=True),
        sa.Column("new_value", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_admin_audit_log_admin_id", "admin_audit_log", ["admin_id"])
    op.create_index("ix_admin_audit_log_subscription_id", "admin_audit_log", ["subscription_id"])

    op.add_column("subscriptions", sa.Column("grace_until", sa.DateTime(), nullable=True))
    op.add_column("subscriptions", sa.Column("admin_banned", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("subscriptions", sa.Column("admin_ban_reason", sa.String(), nullable=True))
    op.add_column("subscriptions", sa.Column("admin_banned_at", sa.DateTime(), nullable=True))
    op.add_column("teachers", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("students", sa.Column("created_at", sa.DateTime(), nullable=True))
    _backfill_free_subscriptions()


def _backfill_free_subscriptions() -> None:
    bind = op.get_bind()
    subs = sa.table(
        "subscriptions",
        sa.column("id", _uuid()), sa.column("institute_id", _uuid()), sa.column("teacher_id", _uuid()),
        sa.column("plan", sa.String()), sa.column("status", sa.String()),
        sa.column("cancel_at_period_end", sa.Boolean()), sa.column("admin_banned", sa.Boolean()),
        sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()),
    )
    now = datetime.utcnow()
    owners = [
        ("institute_id", "SELECT i.id FROM institutes i WHERE NOT EXISTS "
                         "(SELECT 1 FROM subscriptions s WHERE s.institute_id = i.id)"),
        ("teacher_id", "SELECT t.id FROM teachers t WHERE t.institute_id IS NULL AND NOT EXISTS "
                       "(SELECT 1 FROM subscriptions s WHERE s.teacher_id = t.id)"),
    ]
    for col, query in owners:
        ids = [str(r[0]) for r in bind.execute(sa.text(query)).fetchall()]
        if ids:
            op.bulk_insert(subs, [
                {"id": str(uuid.uuid4()), "institute_id": None, "teacher_id": None, col: oid,
                 "plan": "free", "status": "active", "cancel_at_period_end": False,
                 "admin_banned": False, "created_at": now, "updated_at": now}
                for oid in ids])


def downgrade() -> None:
    op.drop_column("students", "created_at")
    op.drop_column("teachers", "created_at")
    op.drop_column("subscriptions", "admin_banned_at")
    op.drop_column("subscriptions", "admin_ban_reason")
    op.drop_column("subscriptions", "admin_banned")
    op.drop_column("subscriptions", "grace_until")
    op.drop_index("ix_admin_audit_log_subscription_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_admin_id", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
    op.drop_table("platform_admins")
