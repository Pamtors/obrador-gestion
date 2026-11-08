"""Albaranes de envío a franquicias: foto congelada del envío (líneas con
nombre/precio ya congelados) para que el impreso y la copia en Holded no
cambien si la previsión/stock se recalcula después. Ver §5.2 del plan."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AlbaranFranquicia(Base):
    """Albarán de un envío a una franquicia en una fecha concreta (uno por
    tienda y día: evita duplicados en Holded si se regenera)."""
    __tablename__ = "albaranes_franquicia"
    __table_args__ = (
        UniqueConstraint("tienda_id", "fecha", name="uq_albaran_franquicia_tienda_fecha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tienda_id: Mapped[int] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=False)
    cliente_b2b_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes_b2b.id"), nullable=False)  # receptor, copiado al generar
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    numero: Mapped[str | None] = mapped_column(String(30), nullable=True)  # AF{codigo_albaran}-YYYY-DDMM
    holded_doc_id: Mapped[str | None] = mapped_column(String(24), nullable=True)  # id del documento en Holded, hasta que se cree
    total_sin_iva: Mapped[float] = mapped_column(Float, nullable=False)
    total_iva: Mapped[float] = mapped_column(Float, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    creado_por: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=False)
    actualizado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # solo si se editó tras generar
    actualizado_por: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)

    lineas: Mapped[list["LineaAlbaranFranquicia"]] = relationship(
        "LineaAlbaranFranquicia", back_populates="albaran", cascade="all, delete-orphan"
    )


class LineaAlbaranFranquicia(Base):
    """Línea de envío congelada: nombre y precio_franquicia copiados en el
    momento de generar (no se recalculan del catálogo después)."""
    __tablename__ = "lineas_albaran_franquicia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    albaran_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("albaranes_franquicia.id", ondelete="CASCADE"), nullable=False
    )
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    producto_nombre: Mapped[str] = mapped_column(String(100), nullable=False)  # congelado
    sabor_nombre: Mapped[str] = mapped_column(String(100), nullable=False)  # congelado
    descripcion: Mapped[str] = mapped_column(String(200), nullable=False)  # "SABOR PRODUCTO", para el impreso
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    precio_unit: Mapped[float] = mapped_column(Float, nullable=False)  # precio_franquicia congelado, para Holded

    albaran: Mapped["AlbaranFranquicia"] = relationship("AlbaranFranquicia", back_populates="lineas")
