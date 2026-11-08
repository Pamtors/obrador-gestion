"""Centro de impresión: pegatinas (etiquetas) de pedidos, listados de pedidos para
obrador/tiendas y planificador de rutas de reparto. La configuración de pegatinas
se guarda como pares clave/valor en la tabla config (prefijo "pegatinas.")."""
from datetime import date, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import joinedload

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.fechas import fecha_es
from app.models.cliente_b2b import ClienteB2B
from app.models.config import Config
from app.models.pedido import Pedido
from app.models.plan_ruta import PlanRuta
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.tienda import Tienda
from app.plantillas import templates

router = APIRouter(prefix="/imprimir")

_CFG_DEFAULTS = {
    "pegatinas.por_pagina": "8",
    "pegatinas.mostrar_codigo": "1",
    "pegatinas.mostrar_fecha_entrega": "1",
    "pegatinas.mostrar_fecha_horneado": "1",
    "pegatinas.mostrar_fecha_caducidad": "1",
    "pegatinas.mostrar_formato": "1",
    "pegatinas.mostrar_registro_sanitario": "1",
    "pegatinas.label_codigo": "CÓDIGO",
    "pegatinas.label_fecha_entrega": "FECHA ENT.",
    "pegatinas.label_fecha_horneado": "FECHA HORN.",
    "pegatinas.label_fecha_caducidad": "FECHA CAD.",
    "pegatinas.label_formato": "FORMATO",
    "pegatinas.label_registro_sanitario": "REG. SANITARIO",
}


def _get_pegatinas_config(db) -> dict:
    """Lee la config de pegatinas de la tabla config, aplicando defaults si falta alguna clave."""
    rows = {r.key: r.value for r in db.query(Config).filter(Config.key.like("pegatinas.%")).all()}
    cfg = {k: rows.get(k, v) for k, v in _CFG_DEFAULTS.items()}
    # Normalizar a tipos útiles para el template
    return {
        "por_pagina": int(cfg["pegatinas.por_pagina"] or 8),
        "mostrar_codigo": cfg["pegatinas.mostrar_codigo"] == "1",
        "mostrar_fecha_entrega": cfg["pegatinas.mostrar_fecha_entrega"] == "1",
        "mostrar_fecha_horneado": cfg["pegatinas.mostrar_fecha_horneado"] == "1",
        "mostrar_fecha_caducidad": cfg["pegatinas.mostrar_fecha_caducidad"] == "1",
        "mostrar_formato": cfg["pegatinas.mostrar_formato"] == "1",
        "mostrar_registro_sanitario": cfg["pegatinas.mostrar_registro_sanitario"] == "1",
        "label_codigo": cfg["pegatinas.label_codigo"],
        "label_fecha_entrega": cfg["pegatinas.label_fecha_entrega"],
        "label_fecha_horneado": cfg["pegatinas.label_fecha_horneado"],
        "label_fecha_caducidad": cfg["pegatinas.label_fecha_caducidad"],
        "label_formato": cfg["pegatinas.label_formato"],
        "label_registro_sanitario": cfg["pegatinas.label_registro_sanitario"],
    }


def _label_codigo(tipo, referencia, b2b_codigo, abrev_sabor, fecha_recogida, fecha_horneado):
    """Compone el código de la pegatina: código de cliente (o referencia si no es B2B)
    + abreviatura del sabor + fecha de entrega."""
    cod_cliente = b2b_codigo if tipo == "B2B" else (referencia or "")
    abrev = abrev_sabor or ""
    # Si se entrega al día siguiente del horneado (caso normal) se imprime "MAÑANA"
    if fecha_horneado and fecha_recogida == fecha_horneado + timedelta(days=1):
        fecha_label = "MAÑANA"
    else:
        fecha_label = fecha_recogida.strftime("%d/%m")
    return f"{cod_cliente}{abrev}{fecha_label}"


def _pegatinas_de_pedidos(pedidos_raw, db):
    """Genera la lista de pegatinas de una lista de pedidos: una pegatina por unidad
    de cada línea (cantidad 3 → 3 pegatinas iguales). La caducidad se calcula como
    fecha_horneado + dias_caducidad del producto."""
    tienda_map = {t.id: t for t in db.query(Tienda).all()}
    b2b_map = {c.id: c for c in db.query(ClienteB2B).all()}
    sabores_map = {s.id: s for s in db.query(Sabor).all()}
    productos_map = {pr.id: pr for pr in db.query(Producto).all()}

    pegatinas = []
    for p in pedidos_raw:
        tienda = tienda_map.get(p.tienda_id)
        registro_sanitario = tienda.registro_sanitario if tienda else ""
        b2b = b2b_map.get(p.cliente_b2b_id) if p.cliente_b2b_id else None
        b2b_codigo = b2b.codigo if b2b else None
        nombre_cliente = b2b.nombre_comercial if b2b else (p.nombre_cliente or "")

        for linea in p.lineas:
            producto = productos_map.get(linea.producto_id)
            sabor = sabores_map.get(linea.sabor_id)
            dias_cad = producto.dias_caducidad if producto else 4
            fecha_caducidad = p.fecha_horneado + timedelta(days=dias_cad) if p.fecha_horneado else None
            codigo = _label_codigo(
                p.tipo, p.referencia, b2b_codigo,
                sabor.abreviatura if sabor else None,
                p.fecha_recogida, p.fecha_horneado
            )
            pegatina = {
                "codigo": codigo,
                "fecha_entrega": p.fecha_recogida,
                "fecha_horneado": p.fecha_horneado,
                "fecha_caducidad": fecha_caducidad,
                "formato": producto.nombre if producto else "",
                "nombre_cliente": nombre_cliente,
                "sabor": sabor.nombre if sabor else "",
                "registro_sanitario": registro_sanitario,
            }
            for _ in range(linea.cantidad):
                pegatinas.append(pegatina)
    return pegatinas


@router.get("/", response_class=HTMLResponse)
@requiere_permiso("impresion")
async def centro(request: Request):
    """Página índice del centro de impresión con accesos a cada listado."""
    manana = (date.today() + timedelta(days=1)).isoformat()
    return templates.TemplateResponse("imprimir/index.html", {
        "request": request, "usuario": request.state.usuario,
        "manana": manana,
    })


# IMPORTANTE: rutas específicas van ANTES de /pegatinas/{pedido_id}
@router.get("/pegatinas/config", response_class=HTMLResponse)
@requiere_permiso("impresion")
async def config_pegatinas_get(request: Request):
    """Formulario de configuración de pegatinas (campos visibles y sus etiquetas)."""
    db = SessionLocal()
    try:
        cfg = _get_pegatinas_config(db)
        return templates.TemplateResponse("imprimir/pegatinas_config.html", {
            "request": request, "usuario": request.state.usuario,
            "cfg": cfg,
        })
    finally:
        db.close()


@router.post("/pegatinas/config")
@requiere_permiso("impresion", editar=True)
async def config_pegatinas_post(request: Request):
    """Guarda la configuración de pegatinas en la tabla config (upsert clave a clave)."""
    form = await request.form()
    db = SessionLocal()
    try:
        nuevos = {
            "pegatinas.por_pagina": form.get("por_pagina", "8"),
            "pegatinas.mostrar_codigo": "1" if form.get("mostrar_codigo") else "0",
            "pegatinas.mostrar_fecha_entrega": "1" if form.get("mostrar_fecha_entrega") else "0",
            "pegatinas.mostrar_fecha_horneado": "1" if form.get("mostrar_fecha_horneado") else "0",
            "pegatinas.mostrar_fecha_caducidad": "1" if form.get("mostrar_fecha_caducidad") else "0",
            "pegatinas.mostrar_formato": "1" if form.get("mostrar_formato") else "0",
            "pegatinas.mostrar_registro_sanitario": "1" if form.get("mostrar_registro_sanitario") else "0",
            "pegatinas.label_codigo": form.get("label_codigo", "CÓDIGO").strip(),
            "pegatinas.label_fecha_entrega": form.get("label_fecha_entrega", "FECHA ENT.").strip(),
            "pegatinas.label_fecha_horneado": form.get("label_fecha_horneado", "FECHA HORN.").strip(),
            "pegatinas.label_fecha_caducidad": form.get("label_fecha_caducidad", "FECHA CAD.").strip(),
            "pegatinas.label_formato": form.get("label_formato", "FORMATO").strip(),
            "pegatinas.label_registro_sanitario": form.get("label_registro_sanitario", "REG. SANITARIO").strip(),
        }
        for key, value in nuevos.items():
            row = db.query(Config).filter(Config.key == key).first()
            if row:
                row.value = value
            else:
                db.add(Config(key=key, value=value))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/imprimir/pegatinas/config", status_code=302)


@router.get("/pegatinas/dia", response_class=HTMLResponse)
@requiere_permiso("impresion")
async def pegatinas_dia(request: Request, fecha: str = ""):
    """Pegatinas de todos los pedidos B2B con recogida en la fecha dada (por defecto mañana)."""
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today() + timedelta(days=1)
    except ValueError:
        fecha_dt = date.today() + timedelta(days=1)

    db = SessionLocal()
    try:
        pedidos_raw = (db.query(Pedido)
                       .options(joinedload(Pedido.lineas))
                       .filter(Pedido.fecha_recogida == fecha_dt, Pedido.tipo == "B2B")
                       .order_by(Pedido.id)
                       .all())

        pegatinas_list = _pegatinas_de_pedidos(pedidos_raw, db)
        cfg = _get_pegatinas_config(db)
        es_manana = fecha_dt == date.today() + timedelta(days=1)
        titulo = f"Pegatinas B2B — {'Mañana' if es_manana else fecha_dt.strftime('%d/%m/%Y')}"

        return templates.TemplateResponse("imprimir/pegatinas.html", {
            "request": request, "usuario": request.state.usuario,
            "pegatinas": pegatinas_list,
            "titulo": titulo,
            "volver_url": "/imprimir/",
            "pedido_id": None,
            "cfg": cfg,
        })
    finally:
        db.close()


@router.get("/pegatinas/{pedido_id}", response_class=HTMLResponse)
@requiere_permiso("impresion")
async def pegatinas_pedido(request: Request, pedido_id: int):
    """Pegatinas de un solo pedido (cualquier tipo)."""
    db = SessionLocal()
    try:
        p = db.query(Pedido).options(joinedload(Pedido.lineas)).filter(Pedido.id == pedido_id).first()
        if not p:
            return HTMLResponse("<p>Pedido no encontrado.</p>", status_code=404)

        pegatinas_list = _pegatinas_de_pedidos([p], db)
        cfg = _get_pegatinas_config(db)
        return templates.TemplateResponse("imprimir/pegatinas.html", {
            "request": request, "usuario": request.state.usuario,
            "pegatinas": pegatinas_list,
            "titulo": f"Pegatinas — Pedido #{pedido_id}",
            "volver_url": f"/pedidos/{pedido_id}",
            "pedido_id": pedido_id,
            "cfg": cfg,
        })
    finally:
        db.close()


@router.get("/rutas", response_class=HTMLResponse)
@requiere_permiso("impresion")
async def rutas_reparto(request: Request, fecha: str = ""):
    """Planificador imprimible de rutas: pedidos B2B del día agrupados por zona,
    con el plan de furgonetas guardado previamente (tabla planes_ruta) si existe."""
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today() + timedelta(days=1)
    except ValueError:
        fecha_dt = date.today() + timedelta(days=1)

    db = SessionLocal()
    try:
        pedidos_raw = (
            db.query(Pedido)
            .options(joinedload(Pedido.lineas))
            .filter(Pedido.tipo == "B2B", Pedido.fecha_recogida == fecha_dt)
            .order_by(Pedido.id)
            .all()
        )

        clientes_b2b = {c.id: c for c in db.query(ClienteB2B).all()}
        tiendas_all = {t.id: t.nombre for t in db.query(Tienda).all()}
        productos_map = {pr.id: pr.nombre for pr in db.query(Producto).all()}
        sabores_map = {s.id: s.nombre for s in db.query(Sabor).all()}

        import json as _json
        zonas: dict = {}
        for p in pedidos_raw:
            cliente = clientes_b2b.get(p.cliente_b2b_id)
            zona = (cliente.zona_ruta or "").strip() if cliente else ""
            if not zona:
                zona = "Sin zona"
            lineas_str = ", ".join(
                f"{productos_map.get(l.producto_id,'')} {sabores_map.get(l.sabor_id,'')} ×{l.cantidad}"
                for l in p.lineas
            )
            entry = {
                "pedido_id": p.id,
                "zona": zona,
                "cliente": cliente.nombre_comercial if cliente else "—",
                "direccion": (cliente.direccion_entrega or cliente.direccion_social or "") if cliente else "",
                "telefono": (cliente.telefono or "") if cliente else "",
                "ventana": f"{cliente.ventana_entrega_desde or ''}–{cliente.ventana_entrega_hasta or ''}" if cliente and (cliente.ventana_entrega_desde or cliente.ventana_entrega_hasta) else "",
                "comentario": p.comentario or "",
                "lineas": lineas_str,
                "tienda": tiendas_all.get(p.tienda_id, "") if p.tienda_id else "",
                "ubicacion": p.ubicacion_entrega or "TIENDA",
            }
            zonas.setdefault(zona, []).append(entry)

        plan_guardado = db.query(PlanRuta).filter(PlanRuta.fecha == fecha_dt).first()
        plan_json = plan_guardado.plan_json if plan_guardado else "null"
        guardado_en = plan_guardado.guardado_en.strftime("%H:%M") if plan_guardado else None

        return templates.TemplateResponse("imprimir/rutas_reparto.html", {
            "request": request, "usuario": request.state.usuario,
            "fecha": fecha_dt.isoformat(),
            "fecha_display": fecha_es(fecha_dt, "%A %d/%m/%Y").upper(),
            "zonas_json": _json.dumps(zonas, ensure_ascii=False, default=str),
            "plan_json": plan_json,
            "guardado_en": guardado_en,
            "manana": (date.today() + timedelta(days=1)).isoformat(),
        })
    finally:
        db.close()


@router.post("/rutas/guardar")
@requiere_permiso("impresion", editar=True)
async def guardar_rutas(request: Request):
    """Guarda (upsert por fecha) el plan de reparto que el JS envía como JSON (tabla planes_ruta)."""
    import json as _json
    body = await request.json()
    fecha_str = body.get("fecha")
    plan = body.get("plan")
    if not fecha_str or plan is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": False}, status_code=400)

    try:
        fecha_dt = date.fromisoformat(fecha_str)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": False}, status_code=400)

    db = SessionLocal()
    try:
        row = db.query(PlanRuta).filter(PlanRuta.fecha == fecha_dt).first()
        plan_str = _json.dumps(plan, ensure_ascii=False)
        if row:
            row.plan_json = plan_str
            from datetime import datetime as _dt
            row.guardado_en = _dt.now()
        else:
            db.add(PlanRuta(fecha=fecha_dt, plan_json=plan_str))
        db.commit()
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True})
    finally:
        db.close()


def _build_pedidos_raw(db, fecha_desde, fecha_hasta, tipo=None):
    """Consulta pedidos filtrados por rango de fecha_recogida y tipo opcional."""
    query = db.query(Pedido).options(joinedload(Pedido.lineas)).order_by(Pedido.fecha_recogida, Pedido.id)
    if fecha_desde:
        try:
            query = query.filter(Pedido.fecha_recogida >= date.fromisoformat(fecha_desde))
        except ValueError:
            pass
    if fecha_hasta:
        try:
            query = query.filter(Pedido.fecha_recogida <= date.fromisoformat(fecha_hasta))
        except ValueError:
            pass
    if tipo:
        query = query.filter(Pedido.tipo == tipo.upper())
    return query.all()


def _enriquecer_pedidos(pedidos_raw, db):
    """Convierte pedidos ORM en dicts con nombres resueltos (tienda, cliente, producto...)."""
    tienda_map = {t.id: t.nombre for t in db.query(Tienda).all()}
    b2b_map = {c.id: c.nombre_comercial for c in db.query(ClienteB2B).all()}
    productos_map = {pr.id: pr.nombre for pr in db.query(Producto).all()}
    sabores_map = {s.id: s.nombre for s in db.query(Sabor).all()}

    result = []
    for p in pedidos_raw:
        lineas = [
            {
                "producto": productos_map.get(l.producto_id, ""),
                "sabor": sabores_map.get(l.sabor_id, ""),
                "cantidad": l.cantidad,
                "comentario": l.comentario,
            }
            for l in p.lineas
        ]
        result.append({
            "id": p.id,
            "tipo": p.tipo,
            "referencia": p.referencia,
            "fecha_recogida": p.fecha_recogida,
            "fecha_horneado": p.fecha_horneado,
            "tienda": tienda_map.get(p.tienda_id, "Sin tienda"),
            "tienda_id": p.tienda_id,
            "nombre_cliente": b2b_map.get(p.cliente_b2b_id) if p.tipo == "B2B" else p.nombre_cliente,
            "telefono_cliente": p.telefono_cliente,
            "comentario": p.comentario,
            "lineas": lineas,
        })
    return result


@router.get("/pedidos", response_class=HTMLResponse)
@requiere_permiso("impresion")
async def lista_pedidos(request: Request, fecha_desde: str = "", fecha_hasta: str = "", manana: str = "", tipo: str = ""):
    """Listado imprimible de pedidos agrupados por día de recogida (?manana=1 filtra a mañana)."""
    if manana:
        fecha_desde = fecha_hasta = (date.today() + timedelta(days=1)).isoformat()

    db = SessionLocal()
    try:
        pedidos_raw = _build_pedidos_raw(db, fecha_desde, fecha_hasta, tipo or None)
        pedidos = _enriquecer_pedidos(pedidos_raw, db)

        dias: dict = {}
        for p in pedidos:
            fr = p["fecha_recogida"]
            dias.setdefault(fr, []).append(p)

        manana_iso = (date.today() + timedelta(days=1)).isoformat()
        return templates.TemplateResponse("imprimir/pedidos.html", {
            "request": request, "usuario": request.state.usuario,
            "dias": dias,
            "filtro_desde": fecha_desde,
            "filtro_hasta": fecha_hasta,
            "filtro_tipo": tipo,
            "manana_iso": manana_iso,
            "hoy": date.today(),
        })
    finally:
        db.close()


@router.get("/pedidos-tiendas", response_class=HTMLResponse)
@requiere_permiso("impresion")
async def lista_pedidos_tiendas(request: Request, fecha_desde: str = "", fecha_hasta: str = "", manana: str = ""):
    """Listado imprimible de pedidos agrupados por tienda (para preparar los envíos)."""
    if manana:
        fecha_desde = fecha_hasta = (date.today() + timedelta(days=1)).isoformat()

    db = SessionLocal()
    try:
        pedidos_raw = _build_pedidos_raw(db, fecha_desde, fecha_hasta)
        pedidos = _enriquecer_pedidos(pedidos_raw, db)

        tiendas: dict = {}
        for p in pedidos:
            nombre_tienda = p["tienda"]
            tiendas.setdefault(nombre_tienda, []).append(p)

        manana_iso = (date.today() + timedelta(days=1)).isoformat()
        return templates.TemplateResponse("imprimir/pedidos_tienda.html", {
            "request": request, "usuario": request.state.usuario,
            "tiendas": tiendas,
            "filtro_desde": fecha_desde,
            "filtro_hasta": fecha_hasta,
            "manana_iso": manana_iso,
            "hoy": date.today(),
        })
    finally:
        db.close()
