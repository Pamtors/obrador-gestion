"""Usuarios de la aplicación con rol de acceso; los de rol TIENDAS
van ligados a una tienda concreta."""
import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

class Rol(str, enum.Enum):
    REPARTIDORES = "REPARTIDORES"
    JEFES = "JEFES"
    VISUALIZADOR = "VISUALIZADOR"
    ADMINISTRACION = "ADMINISTRACION"
    PASTELERAS = "PASTELERAS"
    JEFE_PASTELEROS = "JEFE_PASTELEROS"
    TIENDAS = "TIENDAS"
    AREA_MANAGER = "AREA_MANAGER"
    COMERCIAL = "COMERCIAL"


# Nombres legibles para desplegables y listados
ROL_NOMBRES = {
    Rol.REPARTIDORES: "Repartidores",
    Rol.JEFES: "Jefes",
    Rol.VISUALIZADOR: "Visualizador",
    Rol.ADMINISTRACION: "Administración",
    Rol.PASTELERAS: "Pasteleras",
    Rol.JEFE_PASTELEROS: "Jefe pasteleros",
    Rol.TIENDAS: "Tiendas",
    Rol.AREA_MANAGER: "Area Manager",
    Rol.COMERCIAL: "Comercial",
}


class Usuario(Base):
    """Empleado con acceso a la aplicación."""
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    hash_contrasena: Mapped[str] = mapped_column(String(200), nullable=False)
    rol: Mapped[Rol] = mapped_column(Enum(Rol), nullable=False)
    # Solo relevante para rol TIENDAS: limita qué tienda puede ver
    tienda_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tiendas.id"), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    tienda: Mapped["Tienda | None"] = relationship("Tienda", back_populates="usuarios")
