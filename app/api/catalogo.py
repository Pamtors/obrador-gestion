"""Catálogo de productos: sabores, productos (cada tamaño de venta es su propio
producto, con su precio propio) y sus asignaciones. Tablas: productos, sabores,
sabor_producto. Todo el módulo es solo para JEFES."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.catalogo import SaborProducto
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.plantillas import templates

router = APIRouter(prefix="/catalogo")


# ── SABORES ───────────────────────────────────────────────────────────────────

@router.get("/sabores", response_class=HTMLResponse)
@requiere_permiso("catalogo")
async def sabores(request: Request):
    """Lista de sabores con la matriz de asignación sabor→producto (tabla sabor_producto)."""
    db = SessionLocal()
    try:
        raw = (db.query(Sabor)
               .options(joinedload(Sabor.sabor_productos))
               .order_by(Sabor.orden, Sabor.nombre).all())
        productos = db.query(Producto).filter(Producto.activo == True).order_by(Producto.nombre).all()

        items = [
            {
                "id": s.id, "nombre": s.nombre, "orden": s.orden,
                "abreviatura": s.abreviatura or "",
                # Asignado = existe fila SaborProducto para ese producto
                "asignados": {sp.producto_id for sp in s.sabor_productos},
            }
            for s in raw
        ]
        prods = [{"id": p.id, "nombre": p.nombre} for p in productos]

        return templates.TemplateResponse("catalogo/sabores.html", {
            "request": request, "usuario": request.state.usuario,
            "items": items, "productos": prods,
            "error": request.query_params.get("error"),
        })
    finally:
        db.close()


@router.post("/sabores/crear")
@requiere_permiso("catalogo", editar=True)
async def crear_sabor(request: Request, nombre: str = Form(...)):
    """Crea un sabor (nombre único en mayúsculas) al final del orden actual."""
    nombre = nombre.strip().upper()
    db = SessionLocal()
    try:
        orden = db.query(Sabor).count() + 1
        sabor = Sabor(nombre=nombre, orden=orden)
        db.add(sabor)
        db.commit()
        return RedirectResponse(url="/catalogo/sabores", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/catalogo/sabores?error=Ya+existe+un+sabor+con+el+nombre+%27{nombre}%27",
            status_code=302,
        )
    finally:
        db.close()


@router.post("/sabores/importar")
@requiere_permiso("catalogo", editar=True)
async def importar_sabores(request: Request, nombres: str = Form(...)):
    """Alta masiva de sabores desde un textarea (uno por línea, ignora duplicados)."""
    db = SessionLocal()
    try:
        orden = db.query(Sabor).count()
        for linea in nombres.splitlines():
            nombre = linea.strip().upper()
            if not nombre:
                continue
            if db.query(Sabor).filter(Sabor.nombre == nombre).first():
                continue
            orden += 1
            db.add(Sabor(nombre=nombre, orden=orden))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/catalogo/sabores", status_code=302)


@router.post("/sabores/{id}/editar")
@requiere_permiso("catalogo", editar=True)
async def editar_sabor(request: Request, id: int, nombre: str = Form(...), orden: int = Form(0), abreviatura: str = Form("")):
    """Edita nombre, orden y abreviatura del sabor (la abreviatura se usa en el código de las pegatinas)."""
    db = SessionLocal()
    try:
        s = db.query(Sabor).filter(Sabor.id == id).first()
        if s:
            s.nombre = nombre.strip().upper()
            s.orden = orden
            s.abreviatura = abreviatura.strip().upper() or None
            db.commit()
    except IntegrityError:
        db.rollback()
    finally:
        db.close()
    return RedirectResponse(url="/catalogo/sabores", status_code=302)


@router.post("/sabores/{id}/subir")
@requiere_permiso("catalogo", editar=True)
async def subir_sabor(request: Request, id: int):
    """Sube el sabor una posición intercambiando su orden con el anterior."""
    db = SessionLocal()
    try:
        actual = db.query(Sabor).filter(Sabor.id == id).first()
        if actual:
            anterior = (db.query(Sabor)
                        .filter(Sabor.orden < actual.orden)
                        .order_by(Sabor.orden.desc()).first())
            if anterior:
                actual.orden, anterior.orden = anterior.orden, actual.orden
                db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/catalogo/sabores", status_code=302)


@router.post("/sabores/{id}/bajar")
@requiere_permiso("catalogo", editar=True)
async def bajar_sabor(request: Request, id: int):
    """Baja el sabor una posición intercambiando su orden con el siguiente."""
    db = SessionLocal()
    try:
        actual = db.query(Sabor).filter(Sabor.id == id).first()
        if actual:
            siguiente = (db.query(Sabor)
                         .filter(Sabor.orden > actual.orden)
                         .order_by(Sabor.orden.asc()).first())
            if siguiente:
                actual.orden, siguiente.orden = siguiente.orden, actual.orden
                db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/catalogo/sabores", status_code=302)


@router.post("/sabores/{sabor_id}/producto/{prod_id}/asignacion")
@requiere_permiso("catalogo", editar=True)
async def asignar_sabor_producto(request: Request, sabor_id: int, prod_id: int):
    """Asigna/quita un sabor a un producto. Asignar = crear fila (en producción);
    quitar = borrar la fila (deja de aparecer en ese producto)."""
    db = SessionLocal()
    try:
        sp = (db.query(SaborProducto)
              .filter(SaborProducto.sabor_id == sabor_id, SaborProducto.producto_id == prod_id)
              .first())
        if sp:
            db.delete(sp)
        else:
            # Al final de la lista de ESE producto, no al principio (orden=0)
            orden_max = (db.query(SaborProducto)
                         .filter(SaborProducto.producto_id == prod_id)
                         .count())
            db.add(SaborProducto(sabor_id=sabor_id, producto_id=prod_id, produccion=True, orden=orden_max + 1))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/catalogo/sabores", status_code=302)


# ── PRODUCTOS ─────────────────────────────────────────────────────────────────

@router.get("/productos", response_class=HTMLResponse)
@requiere_permiso("catalogo")
async def productos(request: Request):
    """Vista central del catálogo: producto seleccionado (cada tamaño de venta es
    su propio producto, con su propio precio) y sus sabores con estado (sabor_producto)."""
    db = SessionLocal()
    try:
        # Productos: activos primero, luego por orden/nombre (eje central de la vista)
        prods = db.query(Producto).order_by(Producto.activo.desc(), Producto.orden, Producto.nombre).all()
        sabs = db.query(Sabor).order_by(Sabor.orden, Sabor.nombre).all()

        productos = [{
            "id": p.id, "nombre": p.nombre, "activo": p.activo,
            "dias_caducidad": p.dias_caducidad, "dias_hasta_entrega": p.dias_hasta_entrega,
            "permite_porciones": p.permite_porciones,
            "precio_pvp": p.precio_pvp, "precio_b2b": p.precio_b2b, "precio_franquicia": p.precio_franquicia,
        } for p in prods]
        sabores = [{"id": s.id, "nombre": s.nombre} for s in sabs]

        # Producto seleccionado: el de ?sel= si es válido, si no el primero
        ids = [p["id"] for p in productos]
        try:
            sel = int(request.query_params.get("sel", ""))
        except ValueError:
            sel = None
        if sel not in ids:
            sel = ids[0] if ids else None

        # Sabores del producto seleccionado = solo los asignados (con sus flags),
        # en el orden propio de ESTE producto (sabor_producto.orden)
        nombre_por_sabor = {s["id"]: s["nombre"] for s in sabores}
        sp_sel = (db.query(SaborProducto)
                  .filter(SaborProducto.producto_id == sel)
                  .order_by(SaborProducto.orden, SaborProducto.id)
                  .all()) if sel else []
        sabores_sel = [
            {
                "id": sp.sabor_id, "nombre": nombre_por_sabor.get(sp.sabor_id, "?"),
                "produccion": sp.produccion, "encargo": sp.encargo, "out": sp.out,
                "primero": i == 0, "ultimo": i == len(sp_sel) - 1,
            }
            for i, sp in enumerate(sp_sel)
        ]

        return templates.TemplateResponse("catalogo/productos.html", {
            "request": request, "usuario": request.state.usuario,
            "productos": productos, "sabores": sabores,
            "sabores_sel": sabores_sel,
            "sel": sel,
            "error": request.query_params.get("error"),
            "guardado": "guardado" in request.query_params,
        })
    finally:
        db.close()


@router.post("/productos/crear")
@requiere_permiso("catalogo", editar=True)
async def crear_producto(
    request: Request,
    nombre: str = Form(...),
    dias_caducidad: int = Form(4),
    dias_hasta_entrega: int = Form(1),
    permite_porciones: bool = Form(False),
):
    """Crea un producto (un tamaño de venta concreto, ej. "TARTA GRANDE");
    dias_caducidad y dias_hasta_entrega alimentan fechas de pegatinas y pedidos."""
    db = SessionLocal()
    try:
        p = Producto(
            nombre=nombre.strip().upper(),
            dias_caducidad=dias_caducidad,
            dias_hasta_entrega=dias_hasta_entrega,
            permite_porciones=permite_porciones,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return RedirectResponse(url=f"/catalogo/productos?sel={p.id}", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/catalogo/productos?error=Ya+existe+un+producto+%27{nombre.strip().upper()}%27",
            status_code=302,
        )
    finally:
        db.close()


def _mover_producto(id: int, delta: int):
    """Mueve un producto una posición en el orden del catálogo. Normaliza antes
    el orden (hay productos con valores duplicados) según el orden visible actual."""
    db = SessionLocal()
    try:
        prods = db.query(Producto).order_by(
            Producto.activo.desc(), Producto.orden, Producto.nombre).all()
        for i, p in enumerate(prods, start=1):
            p.orden = i
        idx = next((i for i, p in enumerate(prods) if p.id == id), None)
        if idx is not None and 0 <= idx + delta < len(prods):
            prods[idx].orden, prods[idx + delta].orden = prods[idx + delta].orden, prods[idx].orden
        db.commit()
    finally:
        db.close()


@router.post("/productos/{id}/subir")
@requiere_permiso("catalogo", editar=True)
async def subir_producto(request: Request, id: int):
    """Sube el producto una posición en el orden de listas y fichas."""
    _mover_producto(id, -1)
    return RedirectResponse(url=f"/catalogo/productos?sel={id}", status_code=302)


@router.post("/productos/{id}/bajar")
@requiere_permiso("catalogo", editar=True)
async def bajar_producto(request: Request, id: int):
    """Baja el producto una posición en el orden de listas y fichas."""
    _mover_producto(id, 1)
    return RedirectResponse(url=f"/catalogo/productos?sel={id}", status_code=302)


def _mover_sabor_en_producto(prod_id: int, sabor_id: int, delta: int):
    """Mueve un sabor una posición dentro del orden de ESE producto (no afecta
    a su orden en ningún otro producto). Normaliza antes el orden según el
    orden visible actual, igual que _mover_producto."""
    db = SessionLocal()
    try:
        filas = (db.query(SaborProducto)
                 .filter(SaborProducto.producto_id == prod_id)
                 .order_by(SaborProducto.orden, SaborProducto.id).all())
        for i, sp in enumerate(filas, start=1):
            sp.orden = i
        idx = next((i for i, sp in enumerate(filas) if sp.sabor_id == sabor_id), None)
        if idx is not None and 0 <= idx + delta < len(filas):
            filas[idx].orden, filas[idx + delta].orden = filas[idx + delta].orden, filas[idx].orden
        db.commit()
    finally:
        db.close()


@router.post("/productos/{prod_id}/sabor/{sabor_id}/subir")
@requiere_permiso("catalogo", editar=True)
async def subir_sabor_en_producto(request: Request, prod_id: int, sabor_id: int):
    """Sube el sabor una posición en el orden de este producto."""
    _mover_sabor_en_producto(prod_id, sabor_id, -1)
    return RedirectResponse(url=f"/catalogo/productos?sel={prod_id}", status_code=302)


@router.post("/productos/{prod_id}/sabor/{sabor_id}/bajar")
@requiere_permiso("catalogo", editar=True)
async def bajar_sabor_en_producto(request: Request, prod_id: int, sabor_id: int):
    """Baja el sabor una posición en el orden de este producto."""
    _mover_sabor_en_producto(prod_id, sabor_id, 1)
    return RedirectResponse(url=f"/catalogo/productos?sel={prod_id}", status_code=302)


@router.post("/productos/{id}/toggle")
@requiere_permiso("catalogo", editar=True)
async def toggle_producto(request: Request, id: int):
    """Activa/desactiva el producto (los inactivos no aparecen al crear pedidos)."""
    db = SessionLocal()
    try:
        p = db.query(Producto).filter(Producto.id == id).first()
        if p:
            p.activo = not p.activo
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/catalogo/productos?sel={id}", status_code=302)


@router.post("/productos/{id}/editar")
@requiere_permiso("catalogo", editar=True)
async def editar_producto(
    request: Request,
    id: int,
    nombre: str = Form(...),
    dias_caducidad: int = Form(4),
    dias_hasta_entrega: int = Form(1),
    permite_porciones: bool = Form(False),
):
    """Edita nombre, plazos (caducidad / entrega) y porciones del producto."""
    db = SessionLocal()
    try:
        p = db.query(Producto).filter(Producto.id == id).first()
        if p:
            p.nombre = nombre.strip().upper()
            p.dias_caducidad = dias_caducidad
            p.dias_hasta_entrega = dias_hasta_entrega
            p.permite_porciones = permite_porciones
            db.commit()
    except IntegrityError:
        db.rollback()
    finally:
        db.close()
    return RedirectResponse(url=f"/catalogo/productos?sel={id}", status_code=302)


@router.post("/productos/{id}/precios")
@requiere_permiso("catalogo", editar=True)
async def guardar_precios_producto(request: Request, id: int):
    """Guarda los precios (PVP/B2B/Fra) de un único producto."""
    form = await request.form()
    db = SessionLocal()
    try:
        p = db.query(Producto).filter(Producto.id == id).first()
        if p:
            pvp_str = form.get("pvp", "").strip().replace(",", ".")
            b2b_str = form.get("b2b", "").strip().replace(",", ".")
            fra_str = form.get("fra", "").strip().replace(",", ".")
            p.precio_pvp = float(pvp_str) if pvp_str else None
            p.precio_b2b = float(b2b_str) if b2b_str else None
            p.precio_franquicia = float(fra_str) if fra_str else None
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/catalogo/productos?sel={id}&guardado=1", status_code=302)


@router.post("/productos/{prod_id}/sabor/{sabor_id}/toggle")
@requiere_permiso("catalogo", editar=True)
async def toggle_flag_sabor_en_producto(request: Request, prod_id: int, sabor_id: int, flag: str = Form(...)):
    """Conmuta un flag (produccion | encargo | out) de un sabor en un producto.
    produccion y encargo son multiselección; out deshabilita el sabor por completo."""
    if flag not in ("produccion", "encargo", "out"):
        return RedirectResponse(url=f"/catalogo/productos?sel={prod_id}", status_code=302)
    db = SessionLocal()
    try:
        sp = (db.query(SaborProducto)
              .filter(SaborProducto.sabor_id == sabor_id, SaborProducto.producto_id == prod_id)
              .first())
        if not sp:
            sp = SaborProducto(sabor_id=sabor_id, producto_id=prod_id, produccion=False)
            db.add(sp)
        setattr(sp, flag, not getattr(sp, flag))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/catalogo/productos?sel={prod_id}", status_code=302)
