"""Gestión de tiendas propias y franquicias (tabla tiendas). Solo JEFES."""
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.cliente_b2b import ClienteB2B, TipoCliente
from app.models.tienda import Tienda
from app.plantillas import templates

router = APIRouter(prefix="/tiendas")

_ERROR_CODIGO_EN_USO = "El código de albarán '{codigo}' ya está en uso por otra franquicia."


def _redirect_codigo_en_uso(codigo: str) -> RedirectResponse:
    mensaje = _ERROR_CODIGO_EN_USO.format(codigo=codigo)
    return RedirectResponse(url=f"/tiendas/?error={quote(mensaje)}", status_code=302)


def _codigo_disponible(db, codigo: str, excluir_id: int | None = None) -> bool:
    """True si ninguna OTRA tienda franquicia usa ya ese codigo_albaran (case-insensitive)."""
    q = db.query(Tienda).filter(Tienda.es_franquicia == True, Tienda.codigo_albaran == codigo)
    if excluir_id is not None:
        q = q.filter(Tienda.id != excluir_id)
    return q.first() is None


def _generar_codigo_default(db, nombre: str, excluir_id: int | None = None) -> str:
    """1ª letra del nombre en mayúsculas; si colisiona, prueba con un sufijo numérico."""
    base = (nombre.strip()[:1] or "X").upper()
    codigo = base
    i = 2
    while not _codigo_disponible(db, codigo, excluir_id):
        codigo = f"{base}{i}"
        i += 1
    return codigo


class _CodigoEnUso(Exception):
    """Señala que el codigo_albaran pedido ya está en uso por otra franquicia."""
    def __init__(self, codigo: str):
        self.codigo = codigo


def _resolver_codigo_albaran(db, es_franquicia: bool, codigo_raw: str, nombre: str, excluir_id: int | None = None) -> str | None:
    """Calcula el codigo_albaran final a partir del formulario: valida el código
    dado por el usuario (o genera uno por defecto), o lo limpia si no es franquicia.
    Lanza _CodigoEnUso si el código pedido ya está en uso."""
    if not es_franquicia:
        return None
    codigo = codigo_raw.strip().upper() or None
    if codigo:
        if not _codigo_disponible(db, codigo, excluir_id):
            raise _CodigoEnUso(codigo)
        return codigo
    return _generar_codigo_default(db, nombre, excluir_id)


@router.get("/", response_class=HTMLResponse)
@requiere_permiso("admin")
async def listar_tiendas(request: Request):
    """Lista todas las tiendas con sus acciones (editar, activar, franquicia, eliminar)."""
    db = SessionLocal()
    try:
        tiendas = db.query(Tienda).order_by(Tienda.nombre).all()
        clientes_franquicia = db.query(ClienteB2B).filter(
            ClienteB2B.tipo_cliente == TipoCliente.FRANQUICIA
        ).order_by(ClienteB2B.nombre_comercial).all()
        return templates.TemplateResponse("tiendas/lista.html", {
            "request": request, "usuario": request.state.usuario, "tiendas": tiendas,
            "clientes_franquicia": clientes_franquicia,
            "error": request.query_params.get("error"),
        })
    finally:
        db.close()


@router.post("/crear")
@requiere_permiso("admin", editar=True)
async def crear_tienda(request: Request):
    """Crea una tienda; el flag es_franquicia determina qué tarifa se le aplica en pedidos."""
    form = await request.form()
    db = SessionLocal()
    try:
        nombre = form.get("nombre", "").strip().upper()
        es_franquicia = "es_franquicia" in form
        try:
            codigo_albaran = _resolver_codigo_albaran(db, es_franquicia, form.get("codigo_albaran", ""), nombre)
        except _CodigoEnUso as e:
            return _redirect_codigo_en_uso(e.codigo)
        cliente_b2b_id = form.get("cliente_b2b_id") or None
        db.add(Tienda(
            nombre=nombre,
            direccion=form.get("direccion", "").strip() or None,
            es_franquicia=es_franquicia,
            es_congelados="es_congelados" in form,
            otros=form.get("otros", "").strip() or None,
            cliente_b2b_id=int(cliente_b2b_id) if (es_franquicia and cliente_b2b_id) else None,
            codigo_albaran=codigo_albaran,
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_codigo_en_uso(codigo_albaran)
    finally:
        db.close()
    return RedirectResponse(url="/tiendas/", status_code=302)


@router.post("/{id}/toggle")
@requiere_permiso("admin", editar=True)
async def toggle_tienda(request: Request, id: int):
    """Activa/desactiva la tienda (baja lógica; deja de aparecer en formularios de pedido)."""
    db = SessionLocal()
    try:
        t = db.query(Tienda).filter(Tienda.id == id).first()
        if t:
            t.activa = not t.activa
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/tiendas/", status_code=302)


@router.post("/{id}/toggle-franquicia")
@requiere_permiso("admin", editar=True)
async def toggle_franquicia(request: Request, id: int):
    """Alterna el flag es_franquicia de la tienda; al activarla, asegura un codigo_albaran único."""
    db = SessionLocal()
    try:
        t = db.query(Tienda).filter(Tienda.id == id).first()
        codigo_albaran = t.codigo_albaran if t else None
        if t:
            t.es_franquicia = not t.es_franquicia
            if t.es_franquicia and not t.codigo_albaran:
                t.codigo_albaran = _generar_codigo_default(db, t.nombre, excluir_id=t.id)
            codigo_albaran = t.codigo_albaran
            db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_codigo_en_uso(codigo_albaran)
    finally:
        db.close()
    return RedirectResponse(url="/tiendas/", status_code=302)


@router.post("/{id}/eliminar")
@requiere_permiso("admin", editar=True)
async def eliminar_tienda(request: Request, id: int):
    """Borra la tienda de forma definitiva (borrado físico, no baja lógica)."""
    db = SessionLocal()
    try:
        t = db.query(Tienda).filter(Tienda.id == id).first()
        if t:
            db.delete(t)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/tiendas/", status_code=302)


@router.post("/{id}/editar")
@requiere_permiso("admin", editar=True)
async def editar_tienda(request: Request, id: int):
    """Actualiza nombre, dirección, flag de franquicia, receptor de facturación,
    código de albarán y notas de la tienda."""
    form = await request.form()
    db = SessionLocal()
    try:
        t = db.query(Tienda).filter(Tienda.id == id).first()
        if not t:
            return RedirectResponse(url="/tiendas/", status_code=302)
        es_franquicia = "es_franquicia" in form
        nombre = form.get("nombre", "").strip().upper()
        try:
            codigo_albaran = _resolver_codigo_albaran(db, es_franquicia, form.get("codigo_albaran", ""), nombre or t.nombre, excluir_id=t.id)
        except _CodigoEnUso as e:
            return _redirect_codigo_en_uso(e.codigo)
        cliente_b2b_id = form.get("cliente_b2b_id") or None
        t.nombre = nombre
        t.direccion = form.get("direccion", "").strip() or None
        t.es_franquicia = es_franquicia
        t.es_congelados = "es_congelados" in form
        t.otros = form.get("otros", "").strip() or None
        t.cliente_b2b_id = int(cliente_b2b_id) if (es_franquicia and cliente_b2b_id) else None
        t.codigo_albaran = codigo_albaran
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_codigo_en_uso(codigo_albaran)
    finally:
        db.close()
    return RedirectResponse(url="/tiendas/", status_code=302)
