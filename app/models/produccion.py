"""Producción diaria del obrador. Referencia producto/sabor del catálogo."""
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProduccionDia(Base):
    """Cantidad confirmada a hornear por día y combinación producto/sabor.
    Editada por las pasteleras; fuente de verdad para los Envíos."""
    __tablename__ = "produccion_dia"
    __table_args__ = (
        UniqueConstraint("fecha", "producto_id", "sabor_id", name="uq_produccion_dia"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
