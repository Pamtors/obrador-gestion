"""Productos del catálogo (cada tamaño de venta es su propio producto, p.ej.
"TARTA GRANDE" y "TARTA MINI"). Los sabores disponibles por producto viven en
catalogo.py (SaborProducto)."""
from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Producto(Base):
    """Producto vendible (tipo de tarta + tamaño ya fusionados, p.ej. "TARTA GRANDE")."""
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    dias_caducidad: Mapped[int] = mapped_column(Integer, default=4, nullable=False)  # vida útil desde horneado
    dias_hasta_entrega: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # días entre horneado y entrega (para calcular fecha_horneado del pedido)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # posición en listados/UI
    permite_porciones: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # si se puede vender/contar por raciones sueltas
    precio_pvp: Mapped[float | None] = mapped_column(Float, nullable=True)
    precio_b2b: Mapped[float | None] = mapped_column(Float, nullable=True)        # restaurantes/bares
    precio_franquicia: Mapped[float | None] = mapped_column(Float, nullable=True)  # locales franquiciados

    sabor_productos: Mapped[list["SaborProducto"]] = relationship("SaborProducto", back_populates="producto", cascade="all, delete-orphan")
