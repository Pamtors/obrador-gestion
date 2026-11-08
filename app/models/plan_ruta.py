"""Plan de ruta de reparto guardado por día (una fila por fecha)."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlanRuta(Base):
    """Snapshot del plan de reparto de un día; el detalle va serializado en JSON."""
    __tablename__ = "planes_ruta"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)  # paradas/orden de la ruta serializado como JSON
    guardado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
