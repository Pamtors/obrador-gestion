"""Sabores de cheesecake. Su disponibilidad por producto se define en
catalogo.SaborProducto (flags produccion/encargo/out); base_id permite
agrupar sabores que comparten base."""
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Sabor(Base):
    """Sabor de cheesecake (p.ej. Lotus, pistacho)."""
    __tablename__ = "sabores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # posición en listados/UI
    abreviatura: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Si base_id es None este sabor ES su propia base; si apunta a otro sabor comparte esa base en horneado
    base_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=True)

    base: Mapped["Sabor | None"] = relationship("Sabor", remote_side="Sabor.id", foreign_keys=[base_id])
    sabor_productos: Mapped[list["SaborProducto"]] = relationship("SaborProducto", back_populates="sabor", cascade="all, delete-orphan")
