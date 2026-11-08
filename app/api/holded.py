"""Integración con Holded (ERP/facturación): configuración de la API key,
sincronización de contactos con clientes B2B locales y creación de albaranes
o facturas a partir de pedidos B2B. Flujo: pedido B2B → preview con precios
→ crear documento en Holded → guardar holded_doc_id en el pedido."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import joinedload

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.cliente_b2b import ClienteB2B, TipoCliente, TipoDocumento
from app.models.config import Config
from app.models.pedido import Pedido
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.tienda import Tienda
from app.services.holded import construir_items, crear_documento, normalizar_contacto, obtener_contactos_holded
from app.plantillas import templates

router = APIRouter(prefix="/holded")


def _es_pedido_de_franquicia(pedido: Pedido, tiendas_map: dict[int, Tienda]) -> bool:
    """True si el pedido se recoge en una tienda franquicia: se factura a través
    de su albarán (app/api/franquicias.py), no del flujo Holded B2B normal."""
    if pedido.tienda_id is None:
        return False
    tienda = tiendas_map.get(pedido.tienda_id)
    return tienda is not None and tienda.es_franquicia


# ── Index / lista de documentos ───────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@requiere_permiso("holded")
async def index(request: Request, pendientes: str = ""):
    """Lista de pedidos B2B con su estado de facturación (con o sin holded_doc_id).
    Con pendientes=1 filtra solo los que aún no tienen documento en Holded."""
    db = SessionLocal()
    try:
        b2b_map = {c.id: c for c in db.query(ClienteB2B).all()}
        tiendas_map = {t.id: t for t in db.query(Tienda).all()}
        query = (
            db.query(Pedido)
            .filter(Pedido.tipo == "B2B")
            .order_by(Pedido.fecha_recogida.desc(), Pedido.id.desc())
        )
        if pendientes == "1":
            query = query.filter(Pedido.holded_doc_id == None)  # noqa: E711
        pedidos_raw = [
            p for p in query.all()
            if not _es_pedido_de_franquicia(p, tiendas_map)
        ][:300]

        pedidos = []
        for p in pedidos_raw:
            b2b = b2b_map.get(p.cliente_b2b_id)
            doc_label = "Factura" if b2b and b2b.tipo_documento == TipoDocumento.FACTURA else "Albarán"
            pedidos.append({
                "id": p.id,
                "fecha_recogida": p.fecha_recogida,
                "fecha_horneado": p.fecha_horneado,
                "b2b_nombre": b2b.nombre_comercial if b2b else "—",
                "b2b_id": b2b.id if b2b else None,
                "tipo_cliente": b2b.tipo_cliente.value if b2b else "B2B",
                "doc_label": doc_label,
                "holded_doc_id": p.holded_doc_id,
            })

        return templates.TemplateResponse("holded/index.html", {
            "request": request,
            "usuario": request.state.usuario,
            "pedidos": pedidos,
            "solo_pendientes": pendientes == "1",
            "resultado_lote": None,
        })
    finally:
        db.close()


# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/config", response_class=HTMLResponse)
@requiere_permiso("holded")
async def config_page(request: Request, ok: str = ""):
    """Muestra la API key de Holded enmascarada (tabla config, clave holded_api_key)."""
    db = SessionLocal()
    try:
        cfg = db.query(Config).filter(Config.key == "holded_api_key").first()
        api_key = cfg.value if cfg else ""
        if api_key and len(api_key) > 8:
            masked = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
        else:
            masked = "No configurada"
        return templates.TemplateResponse("holded/config.html", {
            "request": request,
            "usuario": request.state.usuario,
            "api_key_configurada": bool(api_key),
            "api_key_masked": masked,
            "guardado_ok": ok == "1",
        })
    finally:
        db.close()


@router.post("/config")
@requiere_permiso("holded", editar=True)
async def config_guardar(request: Request):
    """Guarda/actualiza la API key de Holded en la tabla config."""
    form = await request.form()
    api_key = (form.get("api_key") or "").strip()
    db = SessionLocal()
    try:
        cfg = db.query(Config).filter(Config.key == "holded_api_key").first()
        if cfg:
            cfg.value = api_key
        else:
            db.add(Config(key="holded_api_key", value=api_key))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/holded/config?ok=1", status_code=303)


# ── Sync contactos ────────────────────────────────────────────────────────────

def _get_api_key(db) -> str:
    cfg = db.query(Config).filter(Config.key == "holded_api_key").first()
    return cfg.value if cfg else ""


def _calcular_plan_sync(db, contactos: list[dict]) -> dict:
    """
    Clasifica los contactos de Holded en tres grupos sin tocar la BD.
    Devuelve {ya_vinculados, vincular_por_nombre, crear_nuevos}.
    Matching: primero por id_holded ya guardado, luego por nombre comercial
    (case-insensitive) entre los clientes locales aún sin vincular.
    """
    clientes = db.query(ClienteB2B).all()
    by_holded_id = {c.id_holded: c for c in clientes if c.id_holded}
    by_nombre = {
        c.nombre_comercial.lower().strip(): c
        for c in clientes
        if not c.id_holded
    }

    ya_vinculados = []
    vincular_por_nombre = []
    crear_nuevos = []

    for raw in contactos:
        c = normalizar_contacto(raw)
        if not c["nombre"]:
            continue
        if c["id_holded"] in by_holded_id:
            ya_vinculados.append({**c, "cliente_id": by_holded_id[c["id_holded"]].id})
        elif c["nombre"].lower().strip() in by_nombre:
            cliente = by_nombre[c["nombre"].lower().strip()]
            vincular_por_nombre.append({**c, "cliente_id": cliente.id})
        else:
            crear_nuevos.append(c)

    return {
        "ya_vinculados": ya_vinculados,
        "vincular_por_nombre": vincular_por_nombre,
        "crear_nuevos": crear_nuevos,
    }


@router.get("/sync", response_class=HTMLResponse)
@requiere_permiso("holded")
async def sync_preview(request: Request):
    """Preview de sincronización de contactos: descarga contactos de Holded y muestra
    el plan (vinculados / a vincular / a crear) sin modificar clientes_b2b."""
    db = SessionLocal()
    try:
        api_key = _get_api_key(db)
        if not api_key:
            return templates.TemplateResponse("holded/sync.html", {
                "request": request, "usuario": request.state.usuario,
                "error": "API key de Holded no configurada.",
                "plan": None,
            })
        try:
            # run_in_threadpool: requests es bloqueante y congelaría el event loop
            contactos = await run_in_threadpool(obtener_contactos_holded, api_key)
        except Exception as e:
            return templates.TemplateResponse("holded/sync.html", {
                "request": request, "usuario": request.state.usuario,
                "error": str(e), "plan": None,
            })
        plan = _calcular_plan_sync(db, contactos)
        return templates.TemplateResponse("holded/sync.html", {
            "request": request, "usuario": request.state.usuario,
            "error": None, "plan": plan, "resultado": None,
        })
    finally:
        db.close()


@router.post("/sync", response_class=HTMLResponse)
@requiere_permiso("holded", editar=True)
async def sync_ejecutar(request: Request):
    """Ejecuta la sincronización: vincula por nombre (rellena id_holded) y crea
    los clientes B2B nuevos en clientes_b2b. Los ya vinculados se dejan igual."""
    db = SessionLocal()
    try:
        api_key = _get_api_key(db)
        if not api_key:
            return templates.TemplateResponse("holded/sync.html", {
                "request": request, "usuario": request.state.usuario,
                "error": "API key no configurada.", "plan": None, "resultado": None,
            })
        try:
            # run_in_threadpool: requests es bloqueante y congelaría el event loop
            contactos = await run_in_threadpool(obtener_contactos_holded, api_key)
        except Exception as e:
            return templates.TemplateResponse("holded/sync.html", {
                "request": request, "usuario": request.state.usuario,
                "error": str(e), "plan": None, "resultado": None,
            })

        plan = _calcular_plan_sync(db, contactos)

        # Solo se procesan los contactos marcados en el preview (por id de Holded).
        form = await request.form()
        vincular_sel = set(form.getlist("vincular_ids"))
        crear_sel = set(form.getlist("crear_ids"))

        # Ejecutar cambios
        creados = 0
        vinculados = 0

        for c in plan["vincular_por_nombre"]:
            if c["id_holded"] not in vincular_sel:
                continue
            cliente = db.query(ClienteB2B).filter(ClienteB2B.id == c["cliente_id"]).first()
            if cliente:
                cliente.id_holded = c["id_holded"]
                vinculados += 1

        for c in plan["crear_nuevos"]:
            if c["id_holded"] not in crear_sel:
                continue
            db.add(ClienteB2B(
                nombre_comercial=c["nombre"],
                id_holded=c["id_holded"],
                cif=c["cif"] or None,
                email=c["email"] or None,
                telefono=c["telefono"] or None,
            ))
            creados += 1

        db.commit()

        return templates.TemplateResponse("holded/sync.html", {
            "request": request, "usuario": request.state.usuario,
            "error": None, "plan": plan,
            "resultado": {
                "ya_vinculados": len(plan["ya_vinculados"]),
                "vinculados": vinculados,
                "creados": creados,
            },
        })
    finally:
        db.close()


# ── Crear todos los pendientes ────────────────────────────────────────────────

@router.post("/crear-todos", response_class=HTMLResponse)
@requiere_permiso("holded", editar=True)
async def crear_todos(request: Request):
    """Crea en lote los documentos Holded de todos los pedidos B2B pendientes.
    Cada pedido se procesa de forma independiente: los errores no bloquean al resto,
    y el holded_doc_id se guarda en pedidos justo tras crear cada documento."""
    db = SessionLocal()
    try:
        api_key = _get_api_key(db)
        if not api_key:
            pendientes_ids = []
            total_pendientes = 0
            error_global = "API key de Holded no configurada."
        else:
            error_global = None
            tiendas_map = {t.id: t for t in db.query(Tienda).all()}
            # Máximo 20 por click: evita que el navegador corte la conexión
            # con lotes grandes y Holded lento. Se repite el click si quedan más.
            pendientes_query = (
                db.query(Pedido)
                .filter(Pedido.tipo == "B2B", Pedido.holded_doc_id == None)  # noqa: E711
                .order_by(Pedido.fecha_recogida.asc(), Pedido.id.asc())
            )
            pendientes_todos = [
                p for p in pendientes_query.all()
                if not _es_pedido_de_franquicia(p, tiendas_map)
            ]
            total_pendientes = len(pendientes_todos)
            pendientes_ids = [p.id for p in pendientes_todos[:20]]
    finally:
        db.close()

    creados: list[dict] = []
    errores: list[dict] = []

    if not error_global:
        for pedido_id in pendientes_ids:
            pedido_dict, lineas, errs = _preview_data(pedido_id)
            b2b_nombre = (pedido_dict or {}).get("b2b_nombre", f"Pedido #{pedido_id}")

            if errs:
                err_msg = errs[0]
                # Error codificado por _preview_data: cliente sin vincular a Holded
                if err_msg.startswith("FALTA_HOLDED_ID:"):
                    parts = err_msg.split(":", 2)
                    err_msg = f"Cliente '{parts[2] if len(parts) > 2 else '?'}' sin ID de Holded"
                errores.append({"id": pedido_id, "nombre": b2b_nombre, "error": err_msg})
                continue

            if not lineas:
                errores.append({"id": pedido_id, "nombre": b2b_nombre, "error": "Sin líneas con precio configurado"})
                continue

            try:
                items = construir_items(lineas)
                # Factura o albarán según el tipo_documento configurado en el cliente B2B
                doc_tipo = pedido_dict["doc_tipo_holded"]
                prefijo = "FAC" if doc_tipo == "invoice" else "ALB"
                holded_doc_id = await run_in_threadpool(
                    crear_documento,
                    api_key=api_key,
                    contact_id=pedido_dict["b2b_id_holded"],
                    fecha=pedido_dict["fecha_recogida"],
                    numero=f"{prefijo}-{pedido_id:05d}",
                    items=items,
                    doc_tipo=doc_tipo,
                )
                db2 = SessionLocal()
                try:
                    p = db2.query(Pedido).filter(Pedido.id == pedido_id).first()
                    p.holded_doc_id = holded_doc_id
                    db2.commit()
                finally:
                    db2.close()

                creados.append({
                    "id": pedido_id,
                    "nombre": b2b_nombre,
                    "doc_label": pedido_dict["doc_label"],
                    "holded_doc_id": holded_doc_id,
                })
            except Exception as e:
                errores.append({"id": pedido_id, "nombre": b2b_nombre, "error": str(e)[:200]})

    # Recarga el índice con resultado
    db3 = SessionLocal()
    try:
        b2b_map = {c.id: c for c in db3.query(ClienteB2B).all()}
        tiendas_map3 = {t.id: t for t in db3.query(Tienda).all()}
        pedidos_raw = [
            p for p in (
                db3.query(Pedido)
                .filter(Pedido.tipo == "B2B")
                .order_by(Pedido.fecha_recogida.desc(), Pedido.id.desc())
                .all()
            )
            if not _es_pedido_de_franquicia(p, tiendas_map3)
        ][:300]
        pedidos = []
        for p in pedidos_raw:
            b2b = b2b_map.get(p.cliente_b2b_id)
            doc_label = "Factura" if b2b and b2b.tipo_documento == TipoDocumento.FACTURA else "Albarán"
            pedidos.append({
                "id": p.id,
                "fecha_recogida": p.fecha_recogida,
                "fecha_horneado": p.fecha_horneado,
                "b2b_nombre": b2b.nombre_comercial if b2b else "—",
                "b2b_id": b2b.id if b2b else None,
                "tipo_cliente": b2b.tipo_cliente.value if b2b else "B2B",
                "doc_label": doc_label,
                "holded_doc_id": p.holded_doc_id,
            })
    finally:
        db3.close()

    return templates.TemplateResponse("holded/index.html", {
        "request": request,
        "usuario": request.state.usuario,
        "pedidos": pedidos,
        "solo_pendientes": False,
        "resultado_lote": {
            "creados": creados,
            "errores": errores,
            "error_global": error_global,
            "restantes": max(0, total_pendientes - len(creados)),
        },
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _preview_data(pedido_id: int):
    """
    Carga pedido + líneas con precios para previsualizar el albarán.
    Devuelve (pedido_dict | None, lineas_items, errores).
    Lee pedidos, lineas_pedido, clientes_b2b y productos.
    El precio depende del tipo de cliente: FRANQUICIA → precio_franquicia,
    resto → precio_b2b. Las líneas sin precio se reportan como error.
    """
    db = SessionLocal()
    try:
        pedido = (
            db.query(Pedido)
            .options(joinedload(Pedido.lineas))
            .filter(Pedido.id == pedido_id)
            .first()
        )
        if not pedido:
            return None, [], ["Pedido no encontrado."]
        if pedido.tipo != "B2B":
            return None, [], ["Solo se pueden crear albaranes para pedidos B2B."]

        if pedido.tienda_id is not None:
            tiendas_map = {t.id: t for t in db.query(Tienda).filter(Tienda.id == pedido.tienda_id).all()}
            if _es_pedido_de_franquicia(pedido, tiendas_map):
                return None, [], ["Este pedido se recoge en una franquicia; se factura a través de su albarán, no aquí."]

        b2b = db.query(ClienteB2B).filter(ClienteB2B.id == pedido.cliente_b2b_id).first()
        if not b2b:
            return None, [], ["Este pedido no tiene cliente B2B asociado."]
        if not b2b.id_holded:
            # Error con formato parseable (FALTA_HOLDED_ID:id:nombre) para crear_todos
            pedido_dict_err = {
                "id": pedido.id,
                "tipo": pedido.tipo,
                "fecha_recogida": pedido.fecha_recogida,
                "holded_doc_id": pedido.holded_doc_id,
                "b2b_nombre": b2b.nombre_comercial,
                "b2b_id": b2b.id,
                "b2b_id_holded": None,
                "doc_tipo_holded": "waybill",
                "doc_label": "Albarán",
            }
            return pedido_dict_err, [], [f"FALTA_HOLDED_ID:{b2b.id}:{b2b.nombre_comercial}"]

        sabores_map = {s.id: s.nombre for s in db.query(Sabor).all()}
        productos_map = {p.id: p for p in db.query(Producto).all()}

        es_franquicia = b2b.tipo_cliente == TipoCliente.FRANQUICIA

        lineas = []
        errores = []
        for l in pedido.lineas:
            producto = productos_map.get(l.producto_id)
            sabor_n = sabores_map.get(l.sabor_id, f"sabor#{l.sabor_id}")
            prod_n = producto.nombre if producto else f"producto#{l.producto_id}"
            if es_franquicia:
                precio = producto.precio_franquicia if producto else None
                precio_campo = "franquicia"
            else:
                precio = producto.precio_b2b if producto else None
                precio_campo = "B2B"
            if precio is None:
                errores.append(f"Sin precio {precio_campo} para: {sabor_n} {prod_n}")
                continue
            lineas.append({
                "sabor_nombre": sabor_n,
                "tamano_nombre": prod_n,
                "cantidad": l.cantidad,
                "precio_franquicia": precio,  # clave mantenida para compatibilidad con construir_items
            })

        if not lineas and not errores:
            errores.append("El pedido no tiene líneas de producto.")

        doc_tipo_holded = "invoice" if b2b.tipo_documento and b2b.tipo_documento.value == "FACTURA" else "waybill"
        pedido_dict = {
            "id": pedido.id,
            "tipo": pedido.tipo,
            "fecha_recogida": pedido.fecha_recogida,
            "holded_doc_id": pedido.holded_doc_id,
            "b2b_nombre": b2b.nombre_comercial,
            "b2b_id_holded": b2b.id_holded,
            "doc_tipo_holded": doc_tipo_holded,
            "doc_label": "Factura" if doc_tipo_holded == "invoice" else "Albarán",
        }
        return pedido_dict, lineas, errores
    finally:
        db.close()


# ── Albarán ───────────────────────────────────────────────────────────────────

@router.get("/albaran/{pedido_id}", response_class=HTMLResponse)
@requiere_permiso("holded")
async def albaran_preview(request: Request, pedido_id: int):
    """Previsualiza el albarán/factura de un pedido: líneas, precios y errores detectados."""
    pedido_dict, lineas, errores = _preview_data(pedido_id)
    return templates.TemplateResponse("holded/albaran.html", {
        "request": request,
        "usuario": request.state.usuario,
        "pedido": pedido_dict,
        "lineas": lineas,
        "errores": errores,
        "resultado": None,
    })


@router.post("/albaran/{pedido_id}", response_class=HTMLResponse)
@requiere_permiso("holded", editar=True)
async def albaran_crear(request: Request, pedido_id: int):
    """Crea el documento del pedido en Holded y guarda holded_doc_id en pedidos.
    Si el pedido ya tiene documento, exige el flag 'recrear' para generar otro."""
    form = await request.form()
    recrear = form.get("recrear") == "1"

    pedido_dict, lineas, errores = _preview_data(pedido_id)

    if errores:
        return templates.TemplateResponse("holded/albaran.html", {
            "request": request, "usuario": request.state.usuario,
            "pedido": pedido_dict, "lineas": lineas,
            "errores": errores, "resultado": None,
        })

    if pedido_dict.get("holded_doc_id") and not recrear:
        errores = ["Este pedido ya tiene albarán en Holded. Usa 'Recrear' para generar uno nuevo."]
        return templates.TemplateResponse("holded/albaran.html", {
            "request": request, "usuario": request.state.usuario,
            "pedido": pedido_dict, "lineas": lineas,
            "errores": errores, "resultado": None,
        })

    db = SessionLocal()
    try:
        cfg = db.query(Config).filter(Config.key == "holded_api_key").first()
        api_key = cfg.value if cfg else ""
    finally:
        db.close()

    if not api_key:
        return templates.TemplateResponse("holded/albaran.html", {
            "request": request, "usuario": request.state.usuario,
            "pedido": pedido_dict, "lineas": lineas,
            "errores": ["API key de Holded no configurada. Ve a Holded → Configuración."],
            "resultado": None,
        })

    if not lineas:
        return templates.TemplateResponse("holded/albaran.html", {
            "request": request, "usuario": request.state.usuario,
            "pedido": pedido_dict, "lineas": lineas,
            "errores": ["El pedido no tiene líneas de producto con precio de franquicia configurado."],
            "resultado": None,
        })

    try:
        items = construir_items(lineas)
        doc_tipo = pedido_dict["doc_tipo_holded"]
        prefijo = "FAC" if doc_tipo == "invoice" else "ALB"
        numero = f"{prefijo}-{pedido_id:05d}"
        holded_doc_id = await run_in_threadpool(
            crear_documento,
            api_key=api_key,
            contact_id=pedido_dict["b2b_id_holded"],
            fecha=pedido_dict["fecha_recogida"],
            numero=numero,
            items=items,
            doc_tipo=doc_tipo,
        )
    except Exception as e:
        return templates.TemplateResponse("holded/albaran.html", {
            "request": request, "usuario": request.state.usuario,
            "pedido": pedido_dict, "lineas": lineas,
            "errores": [str(e)], "resultado": None,
        })

    db = SessionLocal()
    try:
        p = db.query(Pedido).filter(Pedido.id == pedido_id).first()
        p.holded_doc_id = holded_doc_id
        db.commit()
    finally:
        db.close()

    pedido_dict["holded_doc_id"] = holded_doc_id
    return templates.TemplateResponse("holded/albaran.html", {
        "request": request, "usuario": request.state.usuario,
        "pedido": pedido_dict, "lineas": lineas,
        "errores": [], "resultado": holded_doc_id,
    })
