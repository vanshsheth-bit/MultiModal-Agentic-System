from alembic import op
import sqlalchemy as sa


revision = "004_add_querylog_rag_telemetry"
down_revision = "003_add_document_ocr_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("query_logs", sa.Column("retrieval_confidence", sa.Float(), nullable=True))
    op.add_column("query_logs", sa.Column("retrieval_supports", sa.Integer(), nullable=True))
    op.add_column("query_logs", sa.Column("retrieval_hit", sa.Boolean(), nullable=True))
    op.add_column("query_logs", sa.Column("avg_vector_distance", sa.Float(), nullable=True))
    op.add_column("query_logs", sa.Column("grounded", sa.Boolean(), nullable=True))
    op.add_column("query_logs", sa.Column("hallucination_flag", sa.Boolean(), nullable=True))
    op.add_column("query_logs", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("query_logs", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("query_logs", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column("query_logs", sa.Column("estimated_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("query_logs", "estimated_cost_usd")
    op.drop_column("query_logs", "total_tokens")
    op.drop_column("query_logs", "completion_tokens")
    op.drop_column("query_logs", "prompt_tokens")
    op.drop_column("query_logs", "hallucination_flag")
    op.drop_column("query_logs", "grounded")
    op.drop_column("query_logs", "avg_vector_distance")
    op.drop_column("query_logs", "retrieval_hit")
    op.drop_column("query_logs", "retrieval_supports")
    op.drop_column("query_logs", "retrieval_confidence")
