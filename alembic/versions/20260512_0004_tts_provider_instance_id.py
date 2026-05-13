from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260512_0004"
down_revision = "20260430_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tts_runtime_state",
        sa.Column("provider_instance_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tts_runtime_state", "provider_instance_id")
