"""Página de inicio (menú principal) para cualquier usuario autenticado."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.auth.permisos import requiere_sesion
from app.plantillas import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@requiere_sesion  # cualquier rol autenticado
async def inicio(request: Request):
    """Renderiza la portada; la plantilla decide qué secciones mostrar según el rol."""
    return templates.TemplateResponse("inicio.html", {"request": request, "usuario": request.state.usuario})
