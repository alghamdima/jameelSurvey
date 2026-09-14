"""create surveys and responses tables

Revision ID: 0002_surveys_and_responses
Revises: 0001_initial_schema
Create Date: 2026-09-13 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0002_surveys_and_responses'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. جدول المستخدمين المديرين (Admin Users)
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('username', sa.String(length=50), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    # 2. جدول الاستبيانات (Surveys)
    op.create_table(
        'surveys',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('public_id', sa.String(length=32), nullable=False, unique=True),
        sa.Column('title_ar', sa.String(length=255), nullable=False),
        sa.Column('title_en', sa.String(length=255), nullable=False),
        sa.Column('description_ar', sa.Text(), nullable=True),
        sa.Column('description_en', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    # 3. جدول أسئلة الاستبيانات (Survey Questions)
    op.create_table(
        'survey_questions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('survey_id', sa.Integer(), sa.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question_key', sa.String(length=50), nullable=False),
        sa.Column('text_ar', sa.Text(), nullable=False),
        sa.Column('text_en', sa.Text(), nullable=False),
        sa.Column('question_type', sa.String(length=20), nullable=False),
        sa.Column('is_required', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('order_index', sa.Integer(), server_default='0', nullable=False),
        sa.Column('options_json', sa.Text(), nullable=True)
    )

    # 4. جدول مشاركات الموظفين مع قيد UNIQUE الصارم (survey_id, employee_id)
    op.create_table(
        'survey_responses',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('survey_id', sa.Integer(), sa.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False),
        sa.Column('employee_id', sa.String(length=50), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('answers_json', sa.Text(), nullable=False),
        sa.UniqueConstraint('survey_id', 'employee_id', name='uq_survey_employee')
    )


def downgrade() -> None:
    op.drop_table('survey_responses')
    op.drop_table('survey_questions')
    op.drop_table('surveys')
    op.drop_table('admin_users')
