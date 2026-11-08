"""orden por producto en sabor_producto

Revision ID: 04e03a8d1ca9
Revises: 6b5e3ad1ace1
Create Date: 2026-07-28 14:10:38.378187

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '04e03a8d1ca9'
down_revision: Union[str, None] = '6b5e3ad1ace1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default temporal para poder añadir NOT NULL a una tabla con filas
    op.add_column('sabor_producto', sa.Column('orden', sa.Integer(), nullable=False, server_default='0'))

    # Backfill: dentro de cada producto, numera los sabores ya asignados según
    # el orden global que tenían hasta ahora (Sabor.orden), para que nada
    # cambie de sitio visualmente hasta que alguien reordene a propósito.
    # Subquery correlacionada en el SET: sintaxis válida tanto en SQLite como en
    # PostgreSQL (UPDATE...FROM sería solo de Postgres).
    op.execute("""
        UPDATE sabor_producto
        SET orden = (
            SELECT sub.rn
            FROM (
                SELECT sp2.id, ROW_NUMBER() OVER (
                    PARTITION BY sp2.producto_id ORDER BY s.orden, s.nombre
                ) AS rn
                FROM sabor_producto sp2
                JOIN sabores s ON s.id = sp2.sabor_id
            ) sub
            WHERE sub.id = sabor_producto.id
        )
    """)

    with op.batch_alter_table('sabor_producto') as batch_op:
        batch_op.alter_column('orden', server_default=None)


def downgrade() -> None:
    op.drop_column('sabor_producto', 'orden')
