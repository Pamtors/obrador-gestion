"""Gestión de usuarios del sistema (tabla usuarios). Solo accesible para JEFES."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.contrasena import hashear
from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.usuario import ROL_NOMBRES, Rol, Usuario
from app.models.tienda import Tienda
from app.plantillas import templates

router = APIRouter(prefix="/usuarios")


@router.get("/", response_class=HTMLResponse)
@requiere_permiso("admin")
async def listar_usuarios(request: Request):
    """Lista todos los usuarios con el formulario de alta (tiendas activas para el rol TIENDAS)."""
    db: Session = SessionLocal()
    try:
        usuarios = db.query(Usuario).order_by(Usuario.nombre).all()
        tiendas = db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()
        return templates.TemplateResponse(
            "usuarios/lista.html",
            {"request": request, "usuario": request.state.usuario, "usuarios": usuarios, "tiendas": tiendas, "roles": Rol,
             "nombres": ROL_NOMBRES, "error": request.query_params.get("error")},
        )
    finally:
        db.close()


@router.post("/crear")
@requiere_permiso("admin", editar=True)
async def crear_usuario(
    request: Request,
    nombre: str = Form(...),
    email: str = Form(...),
    contrasena: str = Form(...),
    rol: str = Form(...),
    tienda_id: str = Form(None),
):
    """Crea un usuario con la contraseña hasheada; tienda_id solo aplica al rol TIENDAS."""
    db: Session = SessionLocal()
    try:
        nuevo = Usuario(
            nombre=nombre.strip(),
            email=email.lower().strip(),
            hash_contrasena=hashear(contrasena),
            rol=Rol(rol),
            tienda_id=int(tienda_id) if tienda_id else None,
        )
        db.add(nuevo)
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/usuarios/?error=Ya+existe+un+usuario+con+ese+email.",
            status_code=302,
        )
    finally:
        db.close()
    return RedirectResponse(url="/usuarios/", status_code=302)


@router.post("/{usuario_id}/toggleactivo")
@requiere_permiso("admin", editar=True)
async def toggle_activo(request: Request, usuario_id: int):
    """Activa/desactiva un usuario (baja lógica: un usuario inactivo no puede iniciar sesión)."""
    db: Session = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if u and u.id != request.state.usuario.id:  # no desactivarse a uno mismo
            u.activo = not u.activo
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/usuarios/", status_code=302)
