"""Gestión de albaranes para tiendas franquicia. La configuración de datos del
emisor (Obrador Demo) se guarda como pares clave/valor en la tabla config
(prefijo "empresa."). Los albaranes de envío son una foto congelada del
envío del día (líneas con nombre/precio ya copiados) para que el impreso y
la copia en Holded no cambien si la previsión/stock se recalcula después."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from starlette.concurrency import run_in_threadpool

from app.api.holded import _get_api_key
from app.api.stock import envio_confirmado_map
from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.albaran_franquicia import AlbaranFranquicia, LineaAlbaranFranquicia
from app.models.cliente_b2b import ClienteB2B
from app.models.config import Config
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.stock import DiasReparto
from app.models.tienda import Tienda
from app.models.usuario import Rol
from app.services.holded import crear_documento
from app.plantillas import templates

router = APIRouter(prefix="/franquicias")

_CFG_DEFAULTS = {
    "empresa.razon_social": "OBRADOR DEMO SL",
    "empresa.cif": "B00000000",
    "empresa.direccion": "Calle Ejemplo, 1",
    "empresa.cp": "00000",
    "empresa.poblacion": "Ciudad Demo",
    "empresa.provincia": "Provincia Demo",
    "empresa.telefono": "600000000",
    "empresa.email": "contacto@obrador-demo.example",
    "empresa.registro_sanitario": "",
}


def _get_empresa_config(db) -> dict:
    """Lee la config del emisor de la tabla config, aplicando defaults si falta alguna clave."""
    rows = {r.key: r.value for r in db.query(Config).filter(Config.key.like("empresa.%")).all()}
    # Un valor guardado en blanco no debe pisar el default (así el impreso nunca sale vacío).
    cfg = {k: (rows.get(k) or v) for k, v in _CFG_DEFAULTS.items()}
    return {
        "razon_social": cfg["empresa.razon_social"],
        "cif": cfg["empresa.cif"],
        "direccion": cfg["empresa.direccion"],
        "cp": cfg["empresa.cp"],
        "poblacion": cfg["empresa.poblacion"],
        "provincia": cfg["empresa.provincia"],
        "telefono": cfg["empresa.telefono"],
        "email": cfg["empresa.email"],
        "registro_sanitario": cfg["empresa.registro_sanitario"],
    }


@router.get("/config-empresa", response_class=HTMLResponse)
@requiere_permiso("franquicias")
async def config_empresa_get(request: Request):
    """Formulario de configuración de los datos fiscales del emisor."""
    usuario = request.state.usuario
    # Pantalla admin (razón social/CIF/etc del emisor), no operativa de tienda.
    if usuario.rol == Rol.TIENDAS:
        raise HTTPException(status_code=404)
    db = SessionLocal()
    try:
        cfg = _get_empresa_config(db)
        return templates.TemplateResponse("franquicias/config_empresa.html", {
            "request": request, "usuario": request.state.usuario,
            "cfg": cfg,
        })
    finally:
        db.close()


@router.post("/config-empresa")
@requiere_permiso("franquicias", editar=True)
async def config_empresa_post(request: Request):
    """Guarda los datos del emisor en la tabla config (upsert clave a clave)."""
    form = await request.form()
    db = SessionLocal()
    try:
        nuevos = {
            "empresa.razon_social": form.get("razon_social", "").strip(),
            "empresa.cif": form.get("cif", "").strip(),
            "empresa.direccion": form.get("direccion", "").strip(),
            "empresa.cp": form.get("cp", "").strip(),
            "empresa.poblacion": form.get("poblacion", "").strip(),
            "empresa.provincia": form.get("provincia", "").strip(),
            "empresa.telefono": form.get("telefono", "").strip(),
            "empresa.email": form.get("email", "").strip(),
            "empresa.registro_sanitario": form.get("registro_sanitario", "").strip(),
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
    return RedirectResponse(url="/franquicias/config-empresa", status_code=302)


# ── Albaranes de envío a franquicias ────────────────────────────────────────

def _fecha_o_manana(fecha: str) -> date:
    """Parsea una fecha ISO de query/form; por defecto (o si es inválida), mañana."""
    try:
        return date.fromisoformat(fecha) if fecha else (date.today() + timedelta(days=1))
    except ValueError:
        return date.today() + timedelta(days=1)


def numero_albaran(tienda: Tienda, fecha: date) -> str:
    """Número determinista del albarán: AF{codigo_albaran}-YYYY-DDMM.
    Mismo valor que se envía a Holded como docNumber/document_number."""
    return f"AF{tienda.codigo_albaran}-{fecha:%Y-%d%m}"


def _tiendas_franquicia_reparto(db, fecha: date) -> list[Tienda]:
    """Franquicias activas con reparto programado el día de semana de `fecha`
    (mismo patrón que envios_get() en app/api/stock.py)."""
    dia = fecha.weekday()
    reparto_ids = {
        dr.tienda_id
        for dr in db.query(DiasReparto).filter(DiasReparto.dia_semana == dia).all()
    }
    if not reparto_ids:
        return []
    return (
        db.query(Tienda)
        .filter(Tienda.activa == True, Tienda.es_franquicia == True, Tienda.id.in_(reparto_ids))
        .order_by(Tienda.nombre)
        .all()
    )


def build_preview(db, tienda: Tienda, fecha: date) -> dict:
    """
    Construye la previsualización del albarán de una franquicia: líneas
    (desde el envío confirmado por el obrador), importes y avisos/bloqueantes.

    Bloquean la generación (no se puede satisfacer el esquema NOT NULL):
      - tienda sin cliente_b2b_id, o el cliente_b2b no existe.
      - alguna línea del envío cuyo producto no tiene precio_franquicia.
      - el envío de esa tienda/fecha no está confirmado.
      - envío confirmado pero vacío (nada que enviar ese día).
    Solo aviso (no bloquea lo local, sí el envío a Holded):
      - cliente_b2b sin id_holded.
    """
    bloqueantes: list[str] = []
    avisos: list[str] = []
    cliente_b2b = None

    if not tienda.cliente_b2b_id:
        bloqueantes.append(
            "Esta franquicia no tiene cliente B2B asociado (receptor de facturación). "
            "Configúralo en la ficha de la tienda."
        )
    else:
        cliente_b2b = db.query(ClienteB2B).filter(ClienteB2B.id == tienda.cliente_b2b_id).first()
        if not cliente_b2b:
            bloqueantes.append("El cliente B2B asociado a esta franquicia no existe.")
        elif not cliente_b2b.id_holded:
            avisos.append(
                "El cliente B2B no tiene ID de Holded. Podrás generar el albarán local, "
                "pero no enviarlo a Holded hasta configurarlo."
            )

    envio_map = envio_confirmado_map(db, tienda.id, fecha)
    if envio_map is None:
        bloqueantes.append(
            "El envío de esta franquicia no está confirmado. Confírmalo en "
            "Stock › Envíos antes de generar el albarán."
        )
        envio_map = {}
    elif not envio_map:
        bloqueantes.append("No hay nada que enviar a esta franquicia en esta fecha.")

    productos_map = {p.id: p for p in db.query(Producto).all()}
    sabores_map = {s.id: s.nombre for s in db.query(Sabor).all()}

    lineas = []
    productos_sin_precio: set[str] = set()
    total_sin_iva = 0.0
    for (pid, sid), cantidad in envio_map.items():
        producto = productos_map.get(pid)
        sabor_nombre = sabores_map.get(sid, f"sabor#{sid}")
        producto_nombre = producto.nombre if producto else f"producto#{pid}"
        precio_unit = producto.precio_franquicia if producto else None
        if precio_unit is None:
            productos_sin_precio.add(producto_nombre)
            subtotal = None
        else:
            subtotal = cantidad * precio_unit
            total_sin_iva += subtotal
        lineas.append({
            "producto_id": pid, "sabor_id": sid,
            "producto_nombre": producto_nombre, "sabor_nombre": sabor_nombre,
            "descripcion": f"{sabor_nombre} {producto_nombre}",
            "cantidad": cantidad, "precio_unit": precio_unit, "subtotal": subtotal,
        })
    lineas.sort(key=lambda l: (l["producto_nombre"], l["sabor_nombre"]))

    if productos_sin_precio:
        bloqueantes.append(
            "Sin precio de franquicia configurado para: " + ", ".join(sorted(productos_sin_precio))
        )

    total_sin_iva = round(total_sin_iva, 2)
    total_iva = round(total_sin_iva * 0.10, 2)
    total = round(total_sin_iva + total_iva, 2)

    return {
        "tienda": tienda, "fecha": fecha,
        "cliente_b2b": cliente_b2b,
        "lineas": lineas,
        "bloqueantes": bloqueantes,
        "avisos": avisos,
        "total_sin_iva": total_sin_iva, "total_iva": total_iva, "total": total,
        "puede_generar": not bloqueantes,
    }


def generar_albaran(db, tienda: Tienda, fecha: date, usuario_id: int, recrear: bool) -> dict:
    """
    Genera (o regenera con recrear=True) el snapshot local del albarán.
    Devuelve {"ok", "albaran", "errores", "aviso_holded_previo", "preview"}.
    No inserta nada si hay bloqueantes o si ya existe y no se pide recrear.
    """
    preview = build_preview(db, tienda, fecha)
    if preview["bloqueantes"]:
        return {"ok": False, "albaran": None, "errores": preview["bloqueantes"],
                "aviso_holded_previo": None, "preview": preview}

    existente = db.query(AlbaranFranquicia).filter(
        AlbaranFranquicia.tienda_id == tienda.id, AlbaranFranquicia.fecha == fecha
    ).first()

    aviso_holded_previo = None
    if existente:
        if not recrear:
            return {"ok": False, "albaran": None,
                    "errores": ["Ya existe un albarán para esta franquicia y fecha. Marca 'recrear' para regenerarlo."],
                    "aviso_holded_previo": None, "preview": preview}
        if existente.holded_doc_id:
            # Borrar el snapshot local NO toca Holded: el doc anterior queda huérfano.
            aviso_holded_previo = (
                f"Holded ya tenía un documento ({existente.holded_doc_id}) para el albarán anterior "
                "de esta fecha; regenerar localmente no lo actualiza ni lo borra."
            )
        db.delete(existente)
        db.flush()

    numero = numero_albaran(tienda, fecha)
    albaran = AlbaranFranquicia(
        tienda_id=tienda.id,
        cliente_b2b_id=tienda.cliente_b2b_id,
        fecha=fecha,
        numero=numero,
        total_sin_iva=preview["total_sin_iva"],
        total_iva=preview["total_iva"],
        total=preview["total"],
        creado_por=usuario_id,
    )
    db.add(albaran)
    db.flush()
    for l in preview["lineas"]:
        db.add(LineaAlbaranFranquicia(
            albaran_id=albaran.id,
            producto_id=l["producto_id"], sabor_id=l["sabor_id"],
            producto_nombre=l["producto_nombre"], sabor_nombre=l["sabor_nombre"],
            descripcion=l["descripcion"], cantidad=l["cantidad"], precio_unit=l["precio_unit"],
        ))
    try:
        db.commit()
    except IntegrityError:
        # Doble submit concurrente: el otro request ganó la carrera del
        # UNIQUE(tienda_id, fecha) entre el check de "existente" y este commit.
        db.rollback()
        return {"ok": False, "albaran": None,
                "errores": ["Ya existe un albarán para esta franquicia y fecha. Marca 'recrear' para regenerarlo."],
                "aviso_holded_previo": None, "preview": preview}
    db.refresh(albaran)

    return {"ok": True, "albaran": albaran, "errores": [],
            "aviso_holded_previo": aviso_holded_previo, "preview": preview}


def editar_lineas_albaran(db, albaran: AlbaranFranquicia, cantidades: dict[int, int], usuario_id: int) -> dict:
    """
    Actualiza la `cantidad` de las líneas YA EXISTENTES de `albaran` (nunca
    añade/quita líneas ni toca producto/sabor/precio/descripción) y recalcula
    los totales con la misma fórmula/redondeo que generar_albaran(). Edición
    puramente local: no toca holded_doc_id ni llama a Holded.
    `cantidades` debe traer una entrada por cada línea del albarán (id de
    línea -> cantidad no negativa ya validada por el caller).
    Devuelve {"ok", "errores"}.
    """
    lineas_por_id = {l.id: l for l in albaran.lineas}
    if set(lineas_por_id) - set(cantidades):
        return {"ok": False, "errores": ["Faltan cantidades para alguna línea del albarán."]}

    total_sin_iva = 0.0
    for linea_id, linea in lineas_por_id.items():
        linea.cantidad = cantidades[linea_id]
        total_sin_iva += linea.cantidad * linea.precio_unit

    total_sin_iva = round(total_sin_iva, 2)
    total_iva = round(total_sin_iva * 0.10, 2)
    total = round(total_sin_iva + total_iva, 2)

    albaran.total_sin_iva = total_sin_iva
    albaran.total_iva = total_iva
    albaran.total = total
    albaran.actualizado_en = datetime.now()
    albaran.actualizado_por = usuario_id
    db.commit()
    db.refresh(albaran)
    return {"ok": True, "errores": []}


def construir_items_snapshot(albaran: AlbaranFranquicia) -> list[dict]:
    """Formato interno de crear_documento(), construido directamente desde las
    líneas congeladas del snapshot (NO desde construir_items/catálogo en vivo,
    para no desincronizar el documento de lo que realmente se generó)."""
    return [
        {"name": l.descripcion, "desc": "", "units": float(l.cantidad),
         "subtotal": float(l.precio_unit), "tax": 10}
        for l in albaran.lineas
    ]


@router.get("/albaranes", response_class=HTMLResponse)
@requiere_permiso("franquicias")
async def albaranes_get(request: Request, fecha: str = ""):
    """Lista de franquicias con reparto ese día y el estado de su albarán."""
    usuario = request.state.usuario
    # Vista operativa cross-franquicia: filtraría el negocio de otras tiendas
    # a un login de franquicia. Las tiendas usan /franquicias/mis-albaranes.
    if usuario.rol == Rol.TIENDAS:
        raise HTTPException(status_code=404)
    fecha_dt = _fecha_o_manana(fecha)
    db = SessionLocal()
    try:
        tiendas = _tiendas_franquicia_reparto(db, fecha_dt)
        existentes = {
            a.tienda_id: a
            for a in db.query(AlbaranFranquicia).filter(AlbaranFranquicia.fecha == fecha_dt).all()
        }
        filas = []
        for t in tiendas:
            alb = existentes.get(t.id)
            if alb and alb.holded_doc_id:
                estado = "en_holded"
            elif alb:
                estado = "generado"
            else:
                estado = "pendiente"
            filas.append({
                "tienda_id": t.id, "tienda_nombre": t.nombre,
                "estado": estado, "albaran_id": alb.id if alb else None,
            })
        return templates.TemplateResponse("franquicias/albaranes.html", {
            "request": request, "usuario": request.state.usuario,
            "fecha": fecha_dt, "filas": filas,
        })
    finally:
        db.close()


@router.get("/albaranes/{tienda_id}", response_class=HTMLResponse)
@requiere_permiso("franquicias")
async def albaran_preview_get(request: Request, tienda_id: int, fecha: str = ""):
    """Preview del albarán de una franquicia: líneas, importes y avisos."""
    usuario = request.state.usuario
    if usuario.rol == Rol.TIENDAS and tienda_id != usuario.tienda_id:
        raise HTTPException(status_code=404)
    fecha_dt = _fecha_o_manana(fecha)
    db = SessionLocal()
    try:
        tienda = db.query(Tienda).filter(Tienda.id == tienda_id).first()
        if not tienda:
            return RedirectResponse(url="/franquicias/albaranes", status_code=302)
        preview = build_preview(db, tienda, fecha_dt)
        existente = db.query(AlbaranFranquicia).filter(
            AlbaranFranquicia.tienda_id == tienda_id, AlbaranFranquicia.fecha == fecha_dt
        ).first()
        return templates.TemplateResponse("franquicias/albaran_preview.html", {
            "request": request, "usuario": request.state.usuario,
            "preview": preview, "existente": existente,
            "numero": existente.numero if existente else numero_albaran(tienda, fecha_dt),
            "resultado": None, "errores": [], "aviso_holded_previo": None,
        })
    finally:
        db.close()


@router.post("/albaranes/{tienda_id}", response_class=HTMLResponse)
@requiere_permiso("franquicias", editar=True)
async def albaran_generar_post(request: Request, tienda_id: int):
    """Genera (o regenera con recrear=1) el snapshot local del albarán."""
    form = await request.form()
    fecha_dt = _fecha_o_manana(form.get("fecha", ""))
    recrear = form.get("recrear") == "1"
    usuario = request.state.usuario

    db = SessionLocal()
    try:
        tienda = db.query(Tienda).filter(Tienda.id == tienda_id).first()
        if not tienda:
            return RedirectResponse(url="/franquicias/albaranes", status_code=302)

        resultado = generar_albaran(db, tienda, fecha_dt, usuario.id, recrear)
        existente = db.query(AlbaranFranquicia).filter(
            AlbaranFranquicia.tienda_id == tienda_id, AlbaranFranquicia.fecha == fecha_dt
        ).first()
        return templates.TemplateResponse("franquicias/albaran_preview.html", {
            "request": request, "usuario": usuario,
            "preview": resultado["preview"], "existente": existente,
            "numero": existente.numero if existente else numero_albaran(tienda, fecha_dt),
            "resultado": "ok" if resultado["ok"] else None,
            "errores": resultado["errores"],
            "aviso_holded_previo": resultado["aviso_holded_previo"],
        })
    finally:
        db.close()


def push_a_holded(db, albaran: AlbaranFranquicia, cliente_b2b: ClienteB2B | None, api_key: str,
                   recrear: bool = False) -> dict:
    """
    Envía a Holded el snapshot congelado de `albaran` (construir_items_snapshot),
    creando un waybill. Valida las mismas condiciones que antes comprobaba la
    ruta directamente, para que sean testeables sin pasar por HTTP.
    Devuelve {"ok", "errores", "resultado"} ("resultado" == "holded_ok" si fue bien).
    No escribe nada en BD si hay algún error; en éxito fija holded_doc_id y hace commit.
    """
    if albaran.holded_doc_id and not recrear:
        return {"ok": False, "errores": ["Este albarán ya tiene documento en Holded. Usa 'Recrear' para generar uno nuevo."],
                "resultado": None}
    if not cliente_b2b or not cliente_b2b.id_holded:
        return {"ok": False, "errores": ["El cliente B2B no tiene ID de Holded configurado."], "resultado": None}
    if not api_key:
        return {"ok": False, "errores": ["API key de Holded no configurada. Ve a Holded → Configuración."], "resultado": None}

    items = construir_items_snapshot(albaran)
    try:
        holded_doc_id = crear_documento(
            api_key=api_key,
            contact_id=cliente_b2b.id_holded,
            fecha=albaran.fecha,
            numero=albaran.numero,
            items=items,
            doc_tipo="waybill",
        )
    except Exception as e:
        return {"ok": False, "errores": [str(e)[:200]], "resultado": None}

    albaran.holded_doc_id = holded_doc_id
    db.commit()
    return {"ok": True, "errores": [], "resultado": "holded_ok"}


def _preview_desde_snapshot(preview: dict, albaran: AlbaranFranquicia) -> dict:
    """Copia `preview` sustituyendo líneas/totales por los del snapshot ya
    guardado en `albaran` (lo que realmente se envió a Holded), en vez de un
    recálculo en vivo que podría haber cambiado si la previsión/stock se tocó
    entre generar el albarán y enviarlo a Holded."""
    lineas = [{
        "producto_id": l.producto_id, "sabor_id": l.sabor_id,
        "producto_nombre": l.producto_nombre, "sabor_nombre": l.sabor_nombre,
        "descripcion": l.descripcion, "cantidad": l.cantidad,
        "precio_unit": l.precio_unit, "subtotal": l.cantidad * l.precio_unit,
    } for l in albaran.lineas]
    return {**preview, "lineas": lineas,
            "total_sin_iva": albaran.total_sin_iva, "total_iva": albaran.total_iva, "total": albaran.total}


@router.post("/albaranes/{tienda_id}/holded", response_class=HTMLResponse)
@requiere_permiso("franquicias", editar=True)
async def albaran_holded_post(request: Request, tienda_id: int):
    """Crea el waybill del albarán en Holded (requiere que ya exista el
    snapshot local, cliente B2B con id_holded y API key configurada)."""
    form = await request.form()
    fecha_dt = _fecha_o_manana(form.get("fecha", ""))
    recrear = form.get("recrear") == "1"
    usuario = request.state.usuario

    db = SessionLocal()
    try:
        tienda = db.query(Tienda).filter(Tienda.id == tienda_id).first()
        if not tienda:
            return RedirectResponse(url="/franquicias/albaranes", status_code=302)

        preview = build_preview(db, tienda, fecha_dt)
        albaran = db.query(AlbaranFranquicia).options(joinedload(AlbaranFranquicia.lineas)).filter(
            AlbaranFranquicia.tienda_id == tienda_id, AlbaranFranquicia.fecha == fecha_dt
        ).first()

        if not albaran:
            errores = ["Genera primero el albarán local antes de enviarlo a Holded."]
            resultado = None
        else:
            # La tabla de líneas/totales de la confirmación muestra el snapshot
            # realmente enviado, no un build_preview() recalculado en vivo.
            preview = _preview_desde_snapshot(preview, albaran)
            cliente = db.query(ClienteB2B).filter(ClienteB2B.id == albaran.cliente_b2b_id).first()
            api_key = _get_api_key(db)
            push = await run_in_threadpool(push_a_holded, db, albaran, cliente, api_key, recrear)
            errores = push["errores"]
            resultado = push["resultado"]

        existente = db.query(AlbaranFranquicia).filter(
            AlbaranFranquicia.tienda_id == tienda_id, AlbaranFranquicia.fecha == fecha_dt
        ).first()
        return templates.TemplateResponse("franquicias/albaran_preview.html", {
            "request": request, "usuario": usuario,
            "preview": preview, "existente": existente,
            "numero": existente.numero if existente else numero_albaran(tienda, fecha_dt),
            "resultado": resultado, "errores": errores, "aviso_holded_previo": None,
        })
    finally:
        db.close()


def _rol_puede_editar_lineas(usuario) -> bool:
    """Capacidad más estrecha que el nivel EDITAR de "franquicias": PASTELERAS
    y JEFE_PASTELEROS tienen EDITAR (generar/regenerar/enviar a Holded) pero
    NO pueden tocar a mano las cantidades de un snapshot ya generado. Solo
    JEFES/ADMINISTRACION."""
    return usuario.rol in (Rol.JEFES, Rol.ADMINISTRACION)


@router.get("/albaranes/{albaran_id}/editar", response_class=HTMLResponse)
@requiere_permiso("franquicias", editar=True)
async def albaran_editar_get(request: Request, albaran_id: int):
    """Formulario para editar manualmente las cantidades de un albarán ya
    generado (edición local, no toca Holded)."""
    usuario = request.state.usuario
    if not _rol_puede_editar_lineas(usuario):
        raise HTTPException(status_code=403)
    db = SessionLocal()
    try:
        albaran = db.query(AlbaranFranquicia).options(joinedload(AlbaranFranquicia.lineas)).filter(
            AlbaranFranquicia.id == albaran_id
        ).first()
        if not albaran:
            raise HTTPException(status_code=404)
        tienda = db.query(Tienda).filter(Tienda.id == albaran.tienda_id).first()
        return templates.TemplateResponse("franquicias/albaran_editar.html", {
            "request": request, "usuario": usuario,
            "albaran": albaran, "tienda": tienda, "errores": [],
        })
    finally:
        db.close()


@router.post("/albaranes/{albaran_id}/editar", response_class=HTMLResponse)
@requiere_permiso("franquicias", editar=True)
async def albaran_editar_post(request: Request, albaran_id: int):
    """Guarda las cantidades editadas de un albarán ya generado (solo
    cantidad por línea; recalcula totales; no toca Holded)."""
    usuario = request.state.usuario
    if not _rol_puede_editar_lineas(usuario):
        raise HTTPException(status_code=403)
    form = await request.form()
    db = SessionLocal()
    try:
        albaran = db.query(AlbaranFranquicia).options(joinedload(AlbaranFranquicia.lineas)).filter(
            AlbaranFranquicia.id == albaran_id
        ).first()
        if not albaran:
            raise HTTPException(status_code=404)
        tienda = db.query(Tienda).filter(Tienda.id == albaran.tienda_id).first()

        linea_ids = form.getlist("linea_id")
        cantidades_raw = form.getlist("cantidad")
        cantidades: dict[int, int] = {}
        error = None
        for i, linea_id_str in enumerate(linea_ids):
            valor = cantidades_raw[i] if i < len(cantidades_raw) else ""
            try:
                linea_id = int(linea_id_str)
                cantidad = int(valor)
            except (ValueError, TypeError):
                error = "Todas las cantidades deben ser números enteros."
                break
            if cantidad < 0:
                error = "Las cantidades no pueden ser negativas."
                break
            cantidades[linea_id] = cantidad

        if error is None:
            resultado = editar_lineas_albaran(db, albaran, cantidades, usuario.id)
            if not resultado["ok"]:
                error = resultado["errores"][0]

        if error:
            return templates.TemplateResponse("franquicias/albaran_editar.html", {
                "request": request, "usuario": usuario,
                "albaran": albaran, "tienda": tienda, "errores": [error],
            })

        return RedirectResponse(
            url=f"/franquicias/albaranes/{albaran.tienda_id}?fecha={albaran.fecha.isoformat()}",
            status_code=302,
        )
    finally:
        db.close()


@router.get("/albaranes/{albaran_id}/imprimir", response_class=HTMLResponse)
@requiere_permiso("franquicias")
async def albaran_imprimir(request: Request, albaran_id: int):
    """Vista imprimible A4 del albarán, desde el snapshot guardado (no se
    recalcula el envío): descripción, cantidades e importes (precio unit.,
    subtotales y totales con IVA)."""
    usuario = request.state.usuario
    db = SessionLocal()
    try:
        albaran = db.query(AlbaranFranquicia).options(joinedload(AlbaranFranquicia.lineas)).filter(
            AlbaranFranquicia.id == albaran_id
        ).first()
        # Para TIENDAS, albarán inexistente y albarán ajeno responden igual (404)
        # para no permitir enumerar qué ids existen (mismo patrón que pedidos.py).
        if usuario.rol == Rol.TIENDAS and (not albaran or albaran.tienda_id != usuario.tienda_id):
            raise HTTPException(status_code=404)
        if not albaran:
            return RedirectResponse(url="/franquicias/albaranes", status_code=302)
        tienda = db.query(Tienda).filter(Tienda.id == albaran.tienda_id).first()
        cliente = db.query(ClienteB2B).filter(ClienteB2B.id == albaran.cliente_b2b_id).first()
        empresa = _get_empresa_config(db)
        return templates.TemplateResponse("franquicias/albaran_print.html", {
            "request": request,
            "albaran": albaran, "tienda": tienda, "cliente": cliente, "empresa": empresa,
        })
    finally:
        db.close()


@router.get("/albaranes/{tienda_id}/historial", response_class=HTMLResponse)
@requiere_permiso("franquicias")
async def albaran_historial_get(request: Request, tienda_id: int):
    """Historial de albaranes pasados de una franquicia (VER basta), para que
    la propia tienda pueda repasar sus envíos de días anteriores."""
    usuario = request.state.usuario
    if usuario.rol == Rol.TIENDAS and tienda_id != usuario.tienda_id:
        raise HTTPException(status_code=404)
    db = SessionLocal()
    try:
        tienda = db.query(Tienda).filter(Tienda.id == tienda_id).first()
        if not tienda or not tienda.es_franquicia:
            return RedirectResponse(url="/franquicias/albaranes", status_code=302)
        albaranes = (
            db.query(AlbaranFranquicia)
            .filter(AlbaranFranquicia.tienda_id == tienda_id)
            .order_by(AlbaranFranquicia.fecha.desc())
            .limit(90)
            .all()
        )
        filas = [{
            "id": a.id, "fecha": a.fecha, "numero": a.numero,
            "estado": "en_holded" if a.holded_doc_id else "generado",
        } for a in albaranes]
        return templates.TemplateResponse("franquicias/historial.html", {
            "request": request, "usuario": usuario,
            "tienda": tienda, "filas": filas,
        })
    finally:
        db.close()


@router.get("/mis-albaranes")
@requiere_permiso("franquicias")
async def mis_albaranes_get(request: Request):
    """Redirect role-appropriate: TIENDAS a su propio historial, staff a la
    lista operativa cross-franquicia. Así el nav no necesita conocer un
    tienda_id concreto."""
    usuario = request.state.usuario
    if usuario.rol != Rol.TIENDAS:
        return RedirectResponse(url="/franquicias/albaranes", status_code=302)
    if not usuario.tienda_id:
        return RedirectResponse(url="/", status_code=302)
    db = SessionLocal()
    try:
        tienda = db.query(Tienda).filter(Tienda.id == usuario.tienda_id).first()
    finally:
        db.close()
    if not tienda or not tienda.es_franquicia:
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url=f"/franquicias/albaranes/{usuario.tienda_id}/historial", status_code=302)
