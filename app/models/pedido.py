"""Pedidos (encargos) con sus líneas. Un pedido puede ser de particular,
de cliente B2B (FK a clientes_b2b) o de una tienda propia (FK a tiendas);
las líneas referencian producto+sabor del catálogo."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Pedido(Base):
    """Encargo de tartas con fecha de recogida/entrega."""
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    referencia: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fecha_pedido: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_recogida: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_horneado: Mapped[date | None] = mapped_column(Date, nullable=True)  # día en que el obrador debe hornearlo
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # PARTICULAR | B2B | TIENDA
    ubicacion_entrega: Mapped[str | None] = mapped_column(String(20), nullable=True, default="TIENDA")  # TIENDA | CARRETERIA | RESTAURANTE
    tienda_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=True)  # solo si tipo=TIENDA (o recogida en tienda)
    cliente_b2b_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("clientes_b2b.id"), nullable=True)  # solo si tipo=B2B
    nombre_cliente: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telefono_cliente: Mapped[str | None] = mapped_column(String(30), nullable=True)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    holded_doc_id: Mapped[str | None] = mapped_column(String(24), nullable=True)  # id del documento (factura/albarán) creado en Holded

    lineas: Mapped[list["LineaPedido"]] = relationship("LineaPedido", back_populates="pedido", cascade="all, delete-orphan")
    lineas_otros: Mapped[list["LineaPedidoOtros"]] = relationship("LineaPedidoOtros", back_populates="pedido", cascade="all, delete-orphan")


class LineaPedido(Base):
    """Línea de pedido de catálogo: combinación producto/sabor."""
    __tablename__ = "lineas_pedido"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pedido_id: Mapped[int] = mapped_column(Integer, ForeignKey("pedidos.id", ondelete="CASCADE"), nullable=False)
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos.id"), nullable=False)
    sabor_id: Mapped[int] = mapped_column(Integer, ForeignKey("sabores.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)

    pedido: Mapped["Pedido"] = relationship("Pedido", back_populates="lineas")


class LineaPedidoOtros(Base):
    """Línea de pedido fuera del catálogo (texto libre, p.ej. personalizaciones)."""
    __tablename__ = "lineas_pedido_otros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pedido_id: Mapped[int] = mapped_column(Integer, ForeignKey("pedidos.id", ondelete="CASCADE"), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(300), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)

    pedido: Mapped["Pedido"] = relationship("Pedido", back_populates="lineas_otros")
