"""Gestión de stock en tiendas: partes diarios de recuento, previsiones objetivo,
días de reparto y mermas. Todo cuelga de tiendas y del catálogo (producto/sabor)."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ParteStock(Base):
    """Recuento diario de stock hecho por el personal de una tienda."""
    __tablename__ = "partes_stock"
    __table_args__ = (
        # Un solo parte por tienda y día (índice único: evita duplicados por doble click)
        Index("uq_parte_tienda_fecha", "tienda_id", "fecha", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    tienda_id: Mapped[int] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=False)
    cerrado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # una vez cerrado no se edita
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    lineas: Mapped[list["LineaParteStock"]] = relationship(
        "LineaParteStock", back_populates="parte", cascade="all, delete-orphan"
    )
    otros: Mapped[list["LineaParteStockOtros"]] = relationship(
        "LineaParteStockOtros", back_populates="parte", cascade="all, delete-orphan"
    )
    sobrantes: Mapped[list["SobranteParte"]] = relationship(
        "SobranteParte", back_populates="parte", cascade="all, delete-orphan"
    )


class ParteCongelador(Base):
    """Parte del congelador de una tienda de congelados: recuento de la reserva
    congelada por producto/sabor en una fecha. Es un parte APARTE del de vitrina
    (el de vitrina es el ParteStock normal). Se rellena ~2 veces por semana, la
    noche del conteo (2 días antes del reparto), tras sacar la descongelación.
    Alimenta la reposición: Σ objetivo de vitrina del ciclo − congelador contado."""
    __tablename__ = "partes_congelador"
    __table_args__ = (
        Index("uq_parte_congelador_tienda_fecha", "tienda_id", "fecha", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    tienda_id: Mapped[int] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=False)
    cerrado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    lineas: Mapped[list["LineaParteCongelador"]] = relationship(
        "LineaParteCongelador", back_populates="parte", cascade="all, delete-orphan"
    )


class LineaParteCongelador(Base):
    """Recuento del congelador para una combinación producto/sabor dentro de un parte de congelador."""
    __tablename__ = "lineas_parte_congelador"
    __table_args__ = (
        UniqueConstraint("parte_congelador_id", "producto_id", "sabor_id", name="uq_linea_parte_congelador"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    parte_congelador_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("partes_congelador.id", ondelete="CASCADE"), nullable=False
    )
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parte: Mapped["ParteCongelador"] = relationship("ParteCongelador", back_populates="lineas")


class SobranteParte(Base):
    """Unidades sobrantes (sin sabor) por producto al cierre del día.
    Sustituye a las antiguas columnas fijas sobrante_* de partes_stock:
    cualquier producto nuevo tiene su casilla de sobrante sin tocar código."""
    __tablename__ = "sobrantes_parte"
    __table_args__ = (
        UniqueConstraint("parte_stock_id", "producto_id", name="uq_sobrante_parte"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    parte_stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("partes_stock.id", ondelete="CASCADE"), nullable=False
    )
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parte: Mapped["ParteStock"] = relationship("ParteStock", back_populates="sobrantes")


class LineaParteStock(Base):
    """Recuento de una combinación producto/sabor dentro de un parte."""
    __tablename__ = "lineas_parte_stock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    parte_stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("partes_stock.id", ondelete="CASCADE"), nullable=False
    )
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)   # tartas enteras
    raciones: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # porciones sueltas (solo si el producto permite_porciones)

    parte: Mapped["ParteStock"] = relationship("ParteStock", back_populates="lineas")


class LineaParteStockOtros(Base):
    """Items fuera del catálogo: rellenos, pedidos no recogidos, sobrantes."""
    __tablename__ = "lineas_parte_stock_otros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    parte_stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("partes_stock.id", ondelete="CASCADE"), nullable=False
    )
    descripcion: Mapped[str] = mapped_column(String(200), nullable=False)
    tartas_enteras: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raciones: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parte: Mapped["ParteStock"] = relationship("ParteStock", back_populates="otros")


class PrevisionStock(Base):
    """Objetivo de stock de tartas enteras por tienda, día de semana y combinación."""
    __tablename__ = "prevision_stock"
    __table_args__ = (
        UniqueConstraint("tienda_id", "dia_semana", "producto_id", "sabor_id",
                         name="uq_prevision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tienda_id: Mapped[int] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=False)
    dia_semana: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Lun … 6=Dom
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StockCongeladoObrador(Base):
    """Inventario de tartas congeladas que hay en el obrador, por producto/sabor.
    Una fila = existencias actuales de esa combinación. El roster de combinaciones
    se limita a lo que las tiendas de congelados tienen en previsión (solo aparece
    lo que de verdad se congela). Sirve para saber cuánto queda y cuánto preparar."""
    __tablename__ = "stock_congelado_obrador"
    __table_args__ = (
        UniqueConstraint("producto_id", "sabor_id", name="uq_stock_congelado_obrador"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class DiasReparto(Base):
    """Días de la semana en que cada tienda recibe mercancía."""
    __tablename__ = "dias_reparto"
    __table_args__ = (
        UniqueConstraint("tienda_id", "dia_semana", name="uq_dia_reparto"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tienda_id: Mapped[int] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=False)
    dia_semana: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Lun … 6=Dom


class Merma(Base):
    """Registro de producto desechado/perdido en una tienda."""
    __tablename__ = "mermas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    tienda_id: Mapped[int] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=False)
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    motivo: Mapped[str] = mapped_column(String(20), nullable=False)  # causa de la merma (caducidad, rotura, etc.)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
