"""Custom survey lists are independent of the optional central roster."""
from alembic import op
import sqlalchemy as sa
revision = "0006_optional_employee_roster"
down_revision = "0005_survey_audience"
branch_labels = None
depends_on = None

def upgrade():
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("survey_audience", naming_convention=convention) as batch:
        batch.drop_constraint("fk_survey_audience_employee_id_employees", type_="foreignkey")

def downgrade():
    missing = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM survey_audience a LEFT JOIN employees e ON a.employee_id=e.employee_id "
        "WHERE e.employee_id IS NULL")).scalar_one()
    if missing:
        raise RuntimeError("Register custom audience numbers before downgrading; no entries have been removed.")
    with op.batch_alter_table("survey_audience") as batch:
        batch.create_foreign_key("fk_survey_audience_employee_id_employees", "employees",
                                 ["employee_id"], ["employee_id"])
