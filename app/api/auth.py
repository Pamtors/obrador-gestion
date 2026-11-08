"""Rutas de autenticación: login (formulario) y logout. Trabaja sobre la tabla usuarios."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.contrasena import verificar
from app.auth.permisos import COOKIE_SESION, obtener_usuario_actual
from app.auth.sesion import crear_token_sesion
from app.database import SessionLocal
from app.models.usuario import Usuario
from app.plantillas import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def pantalla_login(request: Request):
    """Muestra el formulario de login; si ya hay sesión activa redirige a inicio."""
    if obtener_usuario_actual(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def procesar_login(request: Request, email: str = Form(...), contrasena: str = Form(...)):
    """Valida credenciales contra usuarios activos y, si son correctas,
    crea el token de sesión y lo deja en una cookie httponly de 8 horas."""
    db: Session = SessionLocal()
    try:
        usuario = db.query(Usuario).filter(
            Usuario.email == email.lower().strip(),
            Usuario.activo == True,
        ).first()
        if not usuario or not verificar(contrasena, usuario.hash_contrasena):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Email o contraseña incorrectos."},
                status_code=401,
            )
        token = crear_token_sesion(usuario.id)
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key=COOKIE_SESION,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 8,
        )
        return response
    finally:
        db.close()


@router.get("/logout")
async def logout():
    """Cierra sesión borrando la cookie y redirige al login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_SESION)
    return response
