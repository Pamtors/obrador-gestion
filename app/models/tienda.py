"""Tiendas físicas (propias o franquiciadas). Referenciadas por usuarios,
pedidos, partes de stock, previsiones, días de reparto y mermas."""
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tienda(Base):
    """Punto de venta físico de la empresa."""
    __tablename__ = "tiendas"
    __table_args__ = (
        # codigo_albaran único entre franquicias (las no-franquicia tienen NULL y quedan fuera)
        Index(
            "uq_tiendas_codigo_albaran_franquicia", "codigo_albaran", unique=True,
            sqlite_where=text("es_franquicia = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    direccion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    es_franquicia: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # franquicia: se le factura el stock que recibe (ver ClienteB2B tipo FRANQUICIA)
    es_congelados: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # tienda de tartas congeladas: recibe reposición del congelador (no reparto diario) y descongela a vitrina
    registro_sanitario: Mapped[str | None] = mapped_column(String(50), nullable=True)
    otros: Mapped[str | None] = mapped_column(Text, nullable=True)
    cliente_b2b_id: Mapped[int | None] = mapped_column(ForeignKey("clientes_b2b.id"), nullable=True)  # receptor de facturación si es_franquicia
    codigo_albaran: Mapped[str | None] = mapped_column(String(10), nullable=True)  # prefijo para AF{codigo}-YYYY-DDMM; único entre franquicias

    usuarios: Mapped[list["Usuario"]] = relationship("Usuario", back_populates="tienda")
