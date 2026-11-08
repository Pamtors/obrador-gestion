"""añade rol visualizador

Revision ID: becfc4a4df3b
Revises: 543f350ab63d
Create Date: 2026-08-10 02:22:19.292423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'becfc4a4df3b'
down_revision: Union[str, None] = '543f350ab63d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE rol ADD VALUE IF NOT EXISTS 'VISUALIZADOR'")


def downgrade() -> None:
    pass
