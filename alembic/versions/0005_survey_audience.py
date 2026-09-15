"""Per-survey employee eligibility."""
from alembic import op
import sqlalchemy as sa
revision = "0005_survey_audience"
down_revision = "0004_security_and_employees"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("surveys", sa.Column("audience_mode", sa.String(20), nullable=False, server_default="all"))
    op.create_table("survey_audience",
        sa.Column("survey_id", sa.Integer(), sa.ForeignKey("surveys.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("employee_id", sa.String(50), sa.ForeignKey("employees.employee_id"), primary_key=True))

def downgrade():
    op.drop_table("survey_audience")
    with op.batch_alter_table("surveys") as batch:
        batch.drop_column("audience_mode")
