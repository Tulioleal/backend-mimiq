from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260424_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("gcs_path", sa.String(length=1024), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "generations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("voice_id", sa.String(length=36), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("style_prompt", sa.Text(), nullable=False),
        sa.Column("slider_config", sa.JSON(), nullable=False),
        sa.Column("output_gcs_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["voice_id"], ["voices.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_generations_voice_id", "generations", ["voice_id"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("generation_id", sa.String(length=36), nullable=False),
        sa.Column("gpu_time_ms", sa.Integer(), nullable=True),
        sa.Column("rtf", sa.Float(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["generation_id"], ["generations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("generation_id"),
    )
    op.create_index("ix_metrics_generation_id", "metrics", ["generation_id"])


def downgrade() -> None:
    op.drop_index("ix_metrics_generation_id", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_generations_voice_id", table_name="generations")
    op.drop_table("generations")
    op.drop_table("voices")
