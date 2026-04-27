from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260424_0002"
down_revision = "20260424_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tts_runtime_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(length=255), nullable=True),
        sa.Column("endpoint", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("tts_runtime_state")
