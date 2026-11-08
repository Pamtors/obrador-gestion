"""Configuración de aplicación persistida en BD como pares clave/valor."""
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Config(Base):
    """Par clave/valor genérico para ajustes editables en runtime."""
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
