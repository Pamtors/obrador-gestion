"""Clientes B2B (restaurantes, bares, hoteles) y franquicias como clientes de
facturación. Referenciados desde pedidos.cliente_b2b_id; sin relación con tiendas."""
import enum

from sqlalchemy import Boolean, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TipoCliente(str, enum.Enum):
    B2B = "B2B"              # restaurantes, bares, hoteles
    FRANQUICIA = "FRANQUICIA"  # locales franquiciados (pagan por el stock que reciben)


class TipoDocumento(str, enum.Enum):
    FACTURA = "FACTURA"
    ALBARAN = "ALBARAN"


class MetodoEnvioFactura(str, enum.Enum):
    """Canal por el que el cliente quiere recibir la factura."""
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    NA = "N.A."


class ClienteB2B(Base):
    """Cliente profesional al que se le sirve y factura (B2B o franquicia)."""
    __tablename__ = "clientes_b2b"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    id_holded: Mapped[str | None] = mapped_column(String(24), nullable=True)  # id del contacto en Holded (integración facturación)
    nombre_comercial: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    razon_social: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cif: Mapped[str | None] = mapped_column(String(20), nullable=True)
    direccion_social: Mapped[str | None] = mapped_column(String(300), nullable=True)
    direccion_entrega: Mapped[str | None] = mapped_column(String(300), nullable=True)
    zona_ruta: Mapped[str | None] = mapped_column(String(100), nullable=True)  # zona para agrupar entregas en la ruta de reparto
    ventana_entrega_desde: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "08:00"
    ventana_entrega_hasta: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "10:00"
    telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tipo_cliente: Mapped[TipoCliente] = mapped_column(Enum(TipoCliente), default=TipoCliente.B2B, nullable=False)
    tipo_documento: Mapped[TipoDocumento] = mapped_column(Enum(TipoDocumento), default=TipoDocumento.ALBARAN, nullable=False)  # documento que se le emite por defecto
    metodo_envio_factura: Mapped[MetodoEnvioFactura] = mapped_column(Enum(MetodoEnvioFactura), default=MetodoEnvioFactura.NA, nullable=False)
    via_pago: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cuenta_bancaria: Mapped[str | None] = mapped_column(String(30), nullable=True)
    comentarios: Mapped[str | None] = mapped_column(Text, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
