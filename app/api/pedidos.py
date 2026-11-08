"""Gestión de pedidos (tablas pedidos, lineas_pedido y lineas_pedido_otros).
Tipos de pedido: PARTICULAR (cliente final), B2B (restaurantes/franquicias) y TIENDA (reposición).
Control de acceso por matriz de permisos: clave "pedidos" (bandeja/detalle VER, crear/editar EDITAR)
y "pedidos.rutas"; puesto TIENDAS limitado a su tienda_id."""
import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import joinedload

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.catalogo import SaborProducto
from app.models.cliente_b2b import ClienteB2B
from app.models.pedido import LineaPedido, LineaPedidoOtros, Pedido
from app.models.plan_ruta import PlanRuta
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.tienda import Tienda
from app.models.usuario import Rol
from app.plantillas import templates

router = APIRouter(prefix="/pedidos")


def _catalogo_json(db) -> str:
    """Devuelve JSON {prod_id: {sabores:[...]}} para el form JS."""
    productos = db.query(Producto).filter(Producto.activo == True).order_by(Producto.nombre).all()
    # OUT deshabilita el sabor por completo: no se puede encargar
    sabor_rows = (db.query(SaborProducto).join(Sabor)
                  .filter(SaborProducto.out == False)
                  .order_by(SaborProducto.orden, Sabor.nombre).all())
    sabores_db = {s.id: {"id": s.id, "nombre": s.nombre, "abreviatura": s.abreviatura} for s in db.query(Sabor).all()}

    catalogo = {}
    for p in productos:
        catalogo[p.id] = {"nombre": p.nombre, "sabores": []}
    for sp in sabor_rows:
        if sp.producto_id in catalogo and sp.sabor_id in sabores_db:
            catalogo[sp.producto_id]["sabores"].append(sabores_db[sp.sabor_id])

    return json.dumps(catalogo)


def _pedido_a_dict(p: Pedido) -> dict:
    """Serializa un Pedido a dict plano para las plantillas (evita usar el ORM tras cerrar la sesión)."""
    return {
        "id": p.id,
        "referencia": p.referencia,
        "fecha_pedido": p.fecha_pedido,
        "fecha_recogida": p.fecha_recogida,
        "fecha_horneado": p.fecha_horneado,
        "tipo": p.tipo,
        "tienda_id": p.tienda_id,
        "ubicacion_entrega": p.ubicacion_entrega or "TIENDA",
        "cliente_b2b_id": p.cliente_b2b_id,
        "nombre_cliente": p.nombre_cliente,
        "telefono_cliente": p.telefono_cliente,
        "comentario": p.comentario,
        "creado_en": p.creado_en,
        "holded_doc_id": p.holded_doc_id,
    }


def _linea_a_dict(l: LineaPedido) -> dict:
    return {
        "id": l.id,
        "pedido_id": l.pedido_id,
        "producto_id": l.producto_id,
        "sabor_id": l.sabor_id,
        "cantidad": l.cantidad,
        "comentario": l.comentario,
    }


def _linea_otros_a_dict(l: LineaPedidoOtros) -> dict:
    return {
        "id": l.id,
        "pedido_id": l.pedido_id,
        "descripcion": l.descripcion,
        "cantidad": l.cantidad,
        "comentario": l.comentario,
    }


@router.get("/rutas", response_class=HTMLResponse)
@requiere_permiso("pedidos.rutas")
async def rutas_reparto(request: Request, fecha: str = ""):
    """Pedidos B2B de una fecha (por defecto mañana) agrupados por zona_ruta del cliente."""
    db = SessionLocal()
    try:
        if not fecha:
            fecha = (date.today() + timedelta(days=1)).isoformat()
        try:
            fecha_dt = date.fromisoformat(fecha)
        except ValueError:
            fecha_dt = date.today() + timedelta(days=1)

        pedidos_raw = (
            db.query(Pedido)
            .filter(Pedido.tipo == "B2B", Pedido.fecha_recogida == fecha_dt)
            .order_by(Pedido.id)
            .all()
        )

        clientes_b2b_all = {c.id: c for c in db.query(ClienteB2B).all()}
        tiendas_all = {t.id: t.nombre for t in db.query(Tienda).all()}

        # Entrada por pedido (reutilizada para agrupar por zona o por ruta)
        entries_by_id: dict[int, dict] = {}
        for p in pedidos_raw:
            cliente = clientes_b2b_all.get(p.cliente_b2b_id)
            entries_by_id[p.id] = {
                "id": p.id,
                "cliente": cliente.nombre_comercial if cliente else "—",
                "direccion": cliente.direccion_entrega or cliente.direccion_social or "—" if cliente else "—",
                "telefono": cliente.telefono or "—" if cliente else "—",
                "ventana": f"{cliente.ventana_entrega_desde or ''}–{cliente.ventana_entrega_hasta or ''}" if cliente and (cliente.ventana_entrega_desde or cliente.ventana_entrega_hasta) else "—",
                "tienda": tiendas_all.get(p.tienda_id, "—") if p.tienda_id else "—",
                "ubicacion_entrega": p.ubicacion_entrega or "TIENDA",
                "comentario": p.comentario or "",
                "zona": (cliente.zona_ruta or "").strip() if cliente else "",
            }

        # Si existe un plan de reparto guardado para esa fecha, mostrar por RUTA
        # y en el orden de paradas fijado en el planificador (Centro de impresión).
        plan_guardado = db.query(PlanRuta).filter(PlanRuta.fecha == fecha_dt).first()
        rutas = []
        usados: set[int] = set()
        if plan_guardado:
            try:
                plan = json.loads(plan_guardado.plan_json)
            except (ValueError, TypeError):
                plan = None
            for r in (plan or {}).get("rutas", []):
                paradas = []
                for parada in r.get("paradas", []):
                    pid = parada.get("pedido_id")
                    entry = entries_by_id.get(pid)
                    if entry and pid not in usados:
                        paradas.append(entry)
                        usados.add(pid)
                if paradas:
                    rutas.append({"nombre": r.get("nombre") or "Ruta", "paradas": paradas})

        # Pedidos aún no asignados a ninguna ruta → agrupados por zona (fallback)
        zonas: dict[str, list] = {}
        sin_zona: list = []
        for pid, entry in entries_by_id.items():
            if pid in usados:
                continue
            zona = entry["zona"]
            if zona:
                zonas.setdefault(zona, []).append(entry)
            else:
                sin_zona.append(entry)

        if sin_zona:
            zonas["Sin zona"] = sin_zona

        return templates.TemplateResponse("pedidos/rutas.html", {
            "request": request, "usuario": request.state.usuario,
            "fecha": fecha, "fecha_dt": fecha_dt,
            "rutas": rutas, "zonas": zonas,
            "manana": (date.today() + timedelta(days=1)).isoformat(),
        })
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
@requiere_permiso("pedidos")
async def bandeja(request: Request, fecha: str = "", tienda_id: str = ""):
    """Bandeja principal de pedidos con filtros por fecha de recogida y tienda (máx. 200)."""
    db = SessionLocal()
    try:
        query = db.query(Pedido).order_by(Pedido.fecha_recogida.desc(), Pedido.id.desc())
        if fecha:
            try:
                fecha_dt = date.fromisoformat(fecha)
                query = query.filter(Pedido.fecha_recogida == fecha_dt)
            except ValueError:
                pass
        usuario = request.state.usuario
        if usuario.rol == Rol.TIENDAS:
            query = query.filter(Pedido.tienda_id == (usuario.tienda_id or -1))
        elif tienda_id:
            try:
                query = query.filter(Pedido.tienda_id == int(tienda_id))
            except ValueError:
                pass

        pedidos_raw = query.limit(200).all()
        pedidos = [_pedido_a_dict(p) for p in pedidos_raw]

        tiendas = [{"id": t.id, "nombre": t.nombre} for t in
                   db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]
        clientes_b2b_all = db.query(ClienteB2B).all()
        b2b_map = {c.id: c.nombre_comercial for c in clientes_b2b_all}
        b2b_tipo_map = {c.id: c.tipo_cliente.value for c in clientes_b2b_all}
        tienda_map = {t["id"]: t["nombre"] for t in tiendas}

        # TIENDAS solo ve sus propios pedidos (el filtro por tienda se ignora arriba),
        # así que no se le ofrece el desplegable: elegir otra tienda no haría nada.
        tiendas_filtro = [] if usuario.rol == Rol.TIENDAS else tiendas

        return templates.TemplateResponse("pedidos/bandeja.html", {
            "request": request, "usuario": request.state.usuario,
            "pedidos": pedidos, "tiendas": tiendas_filtro,
            "b2b_map": b2b_map, "b2b_tipo_map": b2b_tipo_map, "tienda_map": tienda_map,
            "filtro_fecha": fecha, "filtro_tienda": tienda_id,
            "manana": (date.today() + timedelta(days=1)).isoformat(),
        })
    finally:
        db.close()


@router.get("/crear", response_class=HTMLResponse)
@requiere_permiso("pedidos", editar=True)
async def form_crear(request: Request):
    """Formulario de nuevo pedido con el catálogo embebido en JSON para el JS del cliente."""
    db = SessionLocal()
    try:
        tiendas = [{"id": t.id, "nombre": t.nombre, "es_franquicia": t.es_franquicia} for t in
                   db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]
        clientes_b2b = [{"id": c.id, "nombre_comercial": c.nombre_comercial, "codigo": c.codigo} for c in
                        db.query(ClienteB2B).filter(ClienteB2B.activo == True).order_by(ClienteB2B.nombre_comercial).all()]
        productos = [{"id": p.id, "nombre": p.nombre} for p in
                     db.query(Producto).filter(Producto.activo == True).order_by(Producto.nombre).all()]
        catalogo_json = _catalogo_json(db)
        return templates.TemplateResponse("pedidos/crear.html", {
            "request": request, "usuario": request.state.usuario,
            "tiendas": tiendas, "clientes_b2b": clientes_b2b,
            "productos": productos, "catalogo_json": catalogo_json,
            "hoy": date.today().isoformat(),
        })
    finally:
        db.close()


@router.post("/crear")
@requiere_permiso("pedidos", editar=True)
async def guardar_crear(request: Request):
    """Crea el pedido con sus líneas de producto y líneas libres ("otros")."""
    form = await request.form()
    try:
        fecha_recogida = date.fromisoformat(form.get("fecha_recogida") or "")
    except ValueError:
        return RedirectResponse(url="/pedidos/crear", status_code=302)
    db = SessionLocal()
    try:
        # Regla de negocio: siempre se hornea el día anterior a la recogida
        fecha_horneado = fecha_recogida - timedelta(days=1)

        tipo = form.get("tipo")
        ubicacion_entrega = form.get("ubicacion_entrega") or "TIENDA"
        tienda_id_raw = form.get("tienda_id")
        tienda_id = int(tienda_id_raw) if tienda_id_raw else None

        # ubicacion_entrega solo tiene sentido en B2B (TIENDA | CARRETERIA | RESTAURANTE)
        pedido = Pedido(
            referencia=form.get("referencia", "").strip() or None,
            fecha_pedido=date.today(),
            fecha_recogida=fecha_recogida,
            fecha_horneado=fecha_horneado,
            tipo=tipo,
            ubicacion_entrega=ubicacion_entrega if tipo == "B2B" else "TIENDA",
            tienda_id=tienda_id,
            cliente_b2b_id=int(form.get("cliente_b2b_id")) if form.get("cliente_b2b_id") else None,
            nombre_cliente=form.get("nombre_cliente", "").strip() or None,
            telefono_cliente=form.get("telefono_cliente", "").strip() or None,
            comentario=form.get("comentario", "").strip() or None,
        )
        db.add(pedido)
        db.flush()

        productos_ids = form.getlist("producto_id")
        sabores_ids = form.getlist("sabor_id")
        cantidades = form.getlist("cantidad")
        comentarios_linea = form.getlist("comentario_linea")

        for i in range(len(productos_ids)):
            # Fila incompleta (sin producto o sabor) → se ignora
            if not productos_ids[i] or i >= len(sabores_ids) or not sabores_ids[i]:
                continue
            try:
                cantidad = max(1, int(cantidades[i])) if i < len(cantidades) and cantidades[i] else 1
            except ValueError:
                cantidad = 1
            db.add(LineaPedido(
                pedido_id=pedido.id,
                producto_id=int(productos_ids[i]),
                sabor_id=int(sabores_ids[i]),
                cantidad=cantidad,
                comentario=comentarios_linea[i].strip() if i < len(comentarios_linea) and comentarios_linea[i] else None,
            ))

        descs = form.getlist("otro_descripcion")
        cants_otros = form.getlist("otro_cantidad")
        coms_otros = form.getlist("otro_comentario")
        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            try:
                cantidad_otro = max(1, int(cants_otros[i])) if i < len(cants_otros) and cants_otros[i] else 1
            except ValueError:
                cantidad_otro = 1
            db.add(LineaPedidoOtros(
                pedido_id=pedido.id,
                descripcion=desc.strip(),
                cantidad=cantidad_otro,
                comentario=coms_otros[i].strip() if i < len(coms_otros) and coms_otros[i] else None,
            ))

        db.commit()
        pedido_id = pedido.id
    finally:
        db.close()
    return RedirectResponse(url=f"/pedidos/{pedido_id}", status_code=302)


@router.get("/{id}", response_class=HTMLResponse)
@requiere_permiso("pedidos")
async def detalle(request: Request, id: int):
    """Detalle del pedido con líneas, tienda y cliente B2B asociados."""
    db = SessionLocal()
    try:
        p = db.query(Pedido).options(joinedload(Pedido.lineas), joinedload(Pedido.lineas_otros)).filter(Pedido.id == id).first()
        usuario = request.state.usuario
        # Para TIENDAS, pedido inexistente y pedido ajeno responden igual (404)
        # para no permitir enumerar qué ids existen.
        if usuario.rol == Rol.TIENDAS and (not p or p.tienda_id != usuario.tienda_id):
            raise HTTPException(status_code=404)
        if not p:
            return RedirectResponse(url="/pedidos/", status_code=302)

        pedido = _pedido_a_dict(p)
        lineas = [_linea_a_dict(l) for l in p.lineas]
        lineas_otros = [_linea_otros_a_dict(l) for l in p.lineas_otros]

        productos = {pr.id: pr.nombre for pr in db.query(Producto).all()}
        sabores = {s.id: {"nombre": s.nombre, "abreviatura": s.abreviatura} for s in db.query(Sabor).all()}
        tienda = db.query(Tienda).filter(Tienda.id == p.tienda_id).first()
        tienda_dict = {"id": tienda.id, "nombre": tienda.nombre, "es_franquicia": tienda.es_franquicia} if tienda else None
        b2b = db.query(ClienteB2B).filter(ClienteB2B.id == p.cliente_b2b_id).first() if p.cliente_b2b_id else None
        b2b_dict = {"id": b2b.id, "nombre_comercial": b2b.nombre_comercial, "codigo": b2b.codigo, "tipo_cliente": b2b.tipo_cliente.value} if b2b else None

        return templates.TemplateResponse("pedidos/detalle.html", {
            "request": request, "usuario": request.state.usuario,
            "pedido": pedido, "lineas": lineas, "lineas_otros": lineas_otros,
            "productos": productos, "sabores": sabores,
            "tienda": tienda_dict, "b2b": b2b_dict,
        })
    finally:
        db.close()


@router.get("/{id}/editar", response_class=HTMLResponse)
@requiere_permiso("pedidos", editar=True)
async def form_editar(request: Request, id: int):
    """Formulario de edición: reutiliza la plantilla de crear con los datos precargados."""
    db = SessionLocal()
    try:
        p = db.query(Pedido).options(joinedload(Pedido.lineas), joinedload(Pedido.lineas_otros)).filter(Pedido.id == id).first()
        if not p:
            return RedirectResponse(url="/pedidos/", status_code=302)

        usuario = request.state.usuario
        if usuario.rol == Rol.TIENDAS and p.tienda_id != usuario.tienda_id:
            raise HTTPException(status_code=404)

        pedido = _pedido_a_dict(p)
        lineas = [_linea_a_dict(l) for l in p.lineas]
        lineas_otros = [_linea_otros_a_dict(l) for l in p.lineas_otros]

        tiendas = [{"id": t.id, "nombre": t.nombre, "es_franquicia": t.es_franquicia} for t in
                   db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]
        clientes_b2b = [{"id": c.id, "nombre_comercial": c.nombre_comercial, "codigo": c.codigo} for c in
                        db.query(ClienteB2B).filter(ClienteB2B.activo == True).order_by(ClienteB2B.nombre_comercial).all()]
        productos = [{"id": pr.id, "nombre": pr.nombre} for pr in
                     db.query(Producto).filter(Producto.activo == True).order_by(Producto.nombre).all()]
        catalogo_json = _catalogo_json(db)

        return templates.TemplateResponse("pedidos/crear.html", {
            "request": request, "usuario": request.state.usuario,
            "pedido": pedido, "lineas": lineas, "lineas_otros": lineas_otros,
            "tiendas": tiendas, "clientes_b2b": clientes_b2b,
            "productos": productos, "catalogo_json": catalogo_json,
            "hoy": date.today().isoformat(),
            "editar": True,
        })
    finally:
        db.close()


@router.post("/{id}/editar")
@requiere_permiso("pedidos", editar=True)
async def guardar_editar(request: Request, id: int):
    """Actualiza la cabecera del pedido y reemplaza todas sus líneas (borra y reinserta)."""
    form = await request.form()
    try:
        fecha_recogida = date.fromisoformat(form.get("fecha_recogida") or "")
    except ValueError:
        return RedirectResponse(url=f"/pedidos/{id}/editar", status_code=302)
    db = SessionLocal()
    try:
        p = db.query(Pedido).filter(Pedido.id == id).first()
        if not p:
            return RedirectResponse(url="/pedidos/", status_code=302)

        usuario = request.state.usuario
        if usuario.rol == Rol.TIENDAS and p.tienda_id != usuario.tienda_id:
            raise HTTPException(status_code=404)

        fecha_horneado = fecha_recogida - timedelta(days=1)

        tipo_edit = form.get("tipo")
        ubicacion_edit = form.get("ubicacion_entrega") or "TIENDA"
        tienda_id_edit = form.get("tienda_id")

        p.referencia = form.get("referencia", "").strip() or None
        p.fecha_recogida = fecha_recogida
        p.fecha_horneado = fecha_horneado
        p.tipo = tipo_edit
        p.ubicacion_entrega = ubicacion_edit if tipo_edit == "B2B" else "TIENDA"
        p.tienda_id = int(tienda_id_edit) if tienda_id_edit else None
        p.cliente_b2b_id = int(form.get("cliente_b2b_id")) if form.get("cliente_b2b_id") else None
        p.nombre_cliente = form.get("nombre_cliente", "").strip() or None
        p.telefono_cliente = form.get("telefono_cliente", "").strip() or None
        p.comentario = form.get("comentario", "").strip() or None

        db.query(LineaPedido).filter(LineaPedido.pedido_id == id).delete()
        db.query(LineaPedidoOtros).filter(LineaPedidoOtros.pedido_id == id).delete()

        productos_ids = form.getlist("producto_id")
        sabores_ids = form.getlist("sabor_id")
        cantidades = form.getlist("cantidad")
        comentarios_linea = form.getlist("comentario_linea")

        for i in range(len(productos_ids)):
            # Fila incompleta (sin producto o sabor) → se ignora
            if not productos_ids[i] or i >= len(sabores_ids) or not sabores_ids[i]:
                continue
            try:
                cantidad = max(1, int(cantidades[i])) if i < len(cantidades) and cantidades[i] else 1
            except ValueError:
                cantidad = 1
            db.add(LineaPedido(
                pedido_id=id,
                producto_id=int(productos_ids[i]),
                sabor_id=int(sabores_ids[i]),
                cantidad=cantidad,
                comentario=comentarios_linea[i].strip() if i < len(comentarios_linea) and comentarios_linea[i] else None,
            ))

        descs = form.getlist("otro_descripcion")
        cants_otros = form.getlist("otro_cantidad")
        coms_otros = form.getlist("otro_comentario")
        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            try:
                cantidad_otro = max(1, int(cants_otros[i])) if i < len(cants_otros) and cants_otros[i] else 1
            except ValueError:
                cantidad_otro = 1
            db.add(LineaPedidoOtros(
                pedido_id=id,
                descripcion=desc.strip(),
                cantidad=cantidad_otro,
                comentario=coms_otros[i].strip() if i < len(coms_otros) and coms_otros[i] else None,
            ))

        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/pedidos/{id}", status_code=302)


@router.post("/{id}/eliminar")
@requiere_permiso("pedidos", editar=True)
async def eliminar(request: Request, id: int):
    """Borra el pedido; sus líneas caen en cascada (ondelete CASCADE)."""
    db = SessionLocal()
    try:
        p = db.query(Pedido).filter(Pedido.id == id).first()
        if p:
            usuario = request.state.usuario
            if usuario.rol == Rol.TIENDAS and p.tienda_id != usuario.tienda_id:
                raise HTTPException(status_code=404)
            db.delete(p)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/pedidos/", status_code=302)
