from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_0003"
down_revision = "20260424_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("gcs_path", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("health_report", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confirmed_voice_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["confirmed_voice_id"], ["voices.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_voice_candidates_confirmed_voice_id",
        "voice_candidates",
        ["confirmed_voice_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_voice_candidates_confirmed_voice_id", table_name="voice_candidates")
    op.drop_table("voice_candidates")
