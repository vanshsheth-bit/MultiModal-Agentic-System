from alembic import op
import sqlalchemy as sa


revision = "002_fix_query_logs_schema"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("query_logs", "user_id", existing_type=sa.Integer(), nullable=True)

    op.alter_column(
        "query_logs",
        "query",
        new_column_name="query_text",
        existing_type=sa.Text(),
    )

    op.add_column("query_logs", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("query_logs", sa.Column("sources_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("query_logs", "sources_count")
    op.drop_column("query_logs", "latency_ms")

    op.alter_column(
        "query_logs",
        "query_text",
        new_column_name="query",
        existing_type=sa.Text(),
    )

    op.alter_column("query_logs", "user_id", existing_type=sa.Integer(), nullable=False)
