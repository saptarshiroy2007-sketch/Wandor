"""My Profile fields - bio/photo/email on teachers, students, institutes; education on teachers

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-21

All nullable, all purely for profile display - email here is NOT a login credential
(login stays phone-first everywhere, unchanged); it's just a contact field a person
can optionally fill in on their profile. Backs the new "My Profile" screen and its
completion-percentage indicator (computed on read in the API, not stored - see
schemas.py's _profile_completion_pct()).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("institutes", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("institutes", sa.Column("photo_url", sa.String(), nullable=True))
    op.add_column("institutes", sa.Column("email", sa.String(), nullable=True))

    op.add_column("teachers", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("teachers", sa.Column("photo_url", sa.String(), nullable=True))
    op.add_column("teachers", sa.Column("education", sa.String(), nullable=True))
    op.add_column("teachers", sa.Column("email", sa.String(), nullable=True))

    op.add_column("students", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("students", sa.Column("photo_url", sa.String(), nullable=True))
    op.add_column("students", sa.Column("email", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("students", "email")
    op.drop_column("students", "photo_url")
    op.drop_column("students", "bio")

    op.drop_column("teachers", "email")
    op.drop_column("teachers", "education")
    op.drop_column("teachers", "photo_url")
    op.drop_column("teachers", "bio")

    op.drop_column("institutes", "email")
    op.drop_column("institutes", "photo_url")
    op.drop_column("institutes", "bio")
