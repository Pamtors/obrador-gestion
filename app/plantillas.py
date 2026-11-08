"""Instancia compartida de Jinja2Templates, con los filtros propios registrados.

Los routers de app/api/ importan `templates` de aquí en vez de construir cada
uno el suyo, para que un filtro registrado una vez esté disponible en todas las
plantillas.
"""
from fastapi.templating import Jinja2Templates

from app.fechas import fecha_es

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["fecha_es"] = fecha_es
