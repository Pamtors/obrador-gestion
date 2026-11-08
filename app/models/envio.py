"""Envío confirmado a una tienda: congela lo que sale del almacén, con la misma
garantía que produccion_dia para el horneado. Fuente de verdad para la ficha de
envío de la tienda y para el albarán de franquicia."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EnvioTienda(Base):
    """Envío confirmado a una tienda en una fecha."""
    __tablename__ = "envios_tienda"
    __table_args__ = (
        UniqueConstraint("tienda_id", "fecha", name="uq_envio_tienda_fecha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tienda_id: Mapped[int] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    confirmado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmado_por: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)

    lineas: Mapped[list["LineaEnvioTienda"]] = relationship(
        "LineaEnvioTienda", back_populates="envio", cascade="all, delete-orphan"
    )


class LineaEnvioTienda(Base):
    """Cantidad confirmada de una combinación producto/sabor dentro de un envío."""
    __tablename__ = "lineas_envio_tienda"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    envio_tienda_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("envios_tienda.id", ondelete="CASCADE"), nullable=False
    )
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    envio: Mapped["EnvioTienda"] = relationship("EnvioTienda", back_populates="lineas")
