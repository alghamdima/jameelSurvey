"""Employee roster, revocable sessions, rate limits and unique question identifiers."""
from alembic import op
import sqlalchemy as sa

revision = "0004_security_and_employees"
down_revision = "0003_add_theme_and_images"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    duplicates = bind.execute(sa.text(
        "SELECT survey_id FROM survey_questions GROUP BY survey_id, question_key HAVING COUNT(*) > 1"
    )).scalars().all()
    if duplicates:
        raise RuntimeError("Duplicate question keys exist. Review affected surveys before migrating: "
                           + ", ".join(str(x) for x in sorted(set(duplicates))))
    with op.batch_alter_table("survey_questions") as batch:
        batch.create_unique_constraint("uq_survey_question_key", ["survey_id", "question_key"])
        batch.create_index("ix_survey_questions_survey_id", ["survey_id"])
    op.create_table("employees",
        sa.Column("employee_id", sa.String(50), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("employee_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    op.create_table("admin_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False))
    op.create_index("ix_admin_sessions_admin_id", "admin_sessions", ["admin_id"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.create_table("rate_limit_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False))
    op.create_index("ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"])

def downgrade():
    op.drop_table("rate_limit_buckets")
    op.drop_table("admin_sessions")
    op.drop_table("employee_imports")
    op.drop_table("employees")
    with op.batch_alter_table("survey_questions") as batch:
        batch.drop_constraint("uq_survey_question_key", type_="unique")
        batch.drop_index("ix_survey_questions_survey_id")