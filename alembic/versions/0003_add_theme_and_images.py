"""add theme_style and background fields to surveys

Revision ID: 0003_add_theme_and_images
Revises: 0002_surveys_and_responses
Create Date: 2026-09-13 18:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0003_add_theme_and_images'
down_revision: Union[str, None] = '0002_surveys_and_responses'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('surveys') as batch_op:
        batch_op.add_column(sa.Column('theme_style', sa.String(length=30), server_default='creative', nullable=False))
        batch_op.add_column(sa.Column('header_image_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('background_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('surveys') as batch_op:
        batch_op.drop_column('background_url')
        batch_op.drop_column('header_image_url')
        batch_op.drop_column('theme_style')
