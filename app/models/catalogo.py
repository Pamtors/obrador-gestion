"""Tabla de asociación del catálogo: disponibilidad de cada sabor dentro de cada producto."""
from sqlalchemy import Boolean, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SaborProducto(Base):
    """Disponibilidad de un sabor en un producto concreto. produccion y encargo
    son independientes (pueden estar ambos activos); out deshabilita el sabor
    en el producto por completo, ignorando los otros dos flags."""
    __tablename__ = "sabor_producto"
    __table_args__ = (UniqueConstraint("sabor_id", "producto_id", name="uq_sabor_producto"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    produccion: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)   # se hornea a diario para stock
    encargo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)     # disponible bajo pedido
    out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)         # deshabilitado (manda sobre el resto)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # posición del sabor dentro de ESTE producto

    sabor: Mapped["Sabor"] = relationship("Sabor", back_populates="sabor_productos")
    producto: Mapped["Producto"] = relationship("Producto", back_populates="sabor_productos")
