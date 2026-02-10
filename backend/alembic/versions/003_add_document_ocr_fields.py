from alembic import op
import sqlalchemy as sa


revision = "003_add_document_ocr_fields"
down_revision = "002_fix_query_logs_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "ocr_status",
            sa.String(32),
            nullable=False,
            server_default="not_needed",
        ),
    )
    op.add_column("documents", sa.Column("ocr_pages_total", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("ocr_pages_done", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("ocr_error", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("ocr_updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "ocr_updated_at")
    op.drop_column("documents", "ocr_error")
    op.drop_column("documents", "ocr_pages_done")
    op.drop_column("documents", "ocr_pages_total")
    op.drop_column("documents", "ocr_status")
