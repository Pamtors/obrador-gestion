"""Gestión de stock diario por tienda: partes de stock (recuento nocturno),
previsión objetivo por día de semana, días de reparto, necesidades de producción,
fichas de envío y mermas. Flujo general: previsión − stock del último parte
= necesidad → producción → envío → nuevo parte de stock al cierre de tienda."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.catalogo import SaborProducto
from app.models.cliente_b2b import ClienteB2B
from app.models.pedido import LineaPedido, Pedido
from app.models.produccion import ProduccionDia
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.envio import EnvioTienda, LineaEnvioTienda
from app.models.stock import (
    DiasReparto, LineaParteCongelador, LineaParteStock,
    Merma, ParteCongelador, ParteStock, PrevisionStock, SobranteParte,
    StockCongeladoObrador,
)
from app.models.tienda import Tienda
from app.models.usuario import Rol
from app.plantillas import templates

# Roles del obrador: únicos autorizados a confirmar (editar) un envío. stock.envios
# da EDITAR también a REPARTIDORES y TIENDAS para que vean/impriman la ficha, pero
# confirmar el envío que sale del almacén es decisión exclusiva del obrador.
_ROLES_OBRADOR = {Rol.PASTELERAS, Rol.JEFE_PASTELEROS, Rol.JEFES, Rol.ADMINISTRACION}


def _rol_obrador(usuario) -> bool:
    return usuario.rol in _ROLES_OBRADOR

router = APIRouter(prefix="/stock")

MOTIVOS = ["CADUCIDAD", "ROTURA", "DEVOLUCION", "OTRO"]
DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# A efectos de stock, las porciones de tartas grandes se cuentan como tartas
# enteras: cada 6 porciones = 1 tarta grande (redondeo hacia arriba del stock
# para no sobreproducir). Solo las tartas grandes tienen porciones.
PORCIONES_POR_TARTA = 6


def _tartas_equiv(cantidad: int, raciones: int) -> int:
    """Stock en tartas enteras equivalentes: enteras + porciones // 6."""
    return cantidad + (raciones or 0) // PORCIONES_POR_TARTA


# Colores de sección: las categorías históricas mantienen su color y cualquier
# producto nuevo recibe uno estable de la paleta (según su id), en lugar de
# caer en el gris genérico de "otros".
COLORES_CATEGORIA = {"grande": "#1e3a5f", "pequena": "#2d6a4f", "mini": "#4a1942",
                     "tarrina": "#7c3d12", "cookie": "#1a4068"}
PALETA_SECCIONES = ["#0f766e", "#7c2d5e", "#3f6212", "#9a3412", "#1d4ed8", "#6d28d9", "#a16207", "#334155"]


def _color_seccion(nombre: str, producto_id: int) -> str:
    """Color de cabecera de la sección de un producto en listas y fichas."""
    color = COLORES_CATEGORIA.get(_cat_producto(nombre))
    return color or PALETA_SECCIONES[producto_id % len(PALETA_SECCIONES)]


def _sobrantes_de_parte(parte, productos_nombres: dict) -> dict:
    """{nombre_producto: cantidad} con los sobrantes > 0 de un parte."""
    if not parte:
        return {}
    return {
        productos_nombres.get(s.producto_id, "—"): s.cantidad
        for s in parte.sobrantes if s.cantidad > 0
    }


# ─── helpers ──────────────────────────────────────────────────────────────────

def _build_catalogo(db) -> dict:
    """
    {prod_nombre: {sabor_nombre: {prod_id, sabor_id, permite_porciones}}}
    Catálogo de productos activos con sus sabores disponibles (no OUT).
    """
    sp_set = {
        (sp.producto_id, sp.sabor_id)
        for sp in db.query(SaborProducto).filter(SaborProducto.out == False).all()
    }
    productos = {p.id: p for p in db.query(Producto).filter(Producto.activo == True).all()}
    sabores = {s.id: s.nombre for s in db.query(Sabor).all()}

    catalogo: dict = {}
    for pid, sid in sp_set:
        prod = productos.get(pid)
        snom = sabores.get(sid)
        if not (prod and snom):
            continue
        catalogo.setdefault(prod.nombre, {})[snom] = {
            "prod_id": pid,
            "sabor_id": sid,
            "permite_porciones": prod.permite_porciones,
        }
    return catalogo


def calcular_envio(db, tienda, fecha: date) -> dict:
    """
    Devuelve {(producto_id, sabor_id): cantidad} con las unidades a enviar a
    `tienda` para `fecha`: previsión − stock del día anterior + pedidos a
    recoger ese día, capado a lo horneado (ProduccionDia) si existe. Solo
    incluye claves con envío > 0. Cálculo puro, reutilizable, no depende de
    usuario.rol ni de filtrado de tiendas (eso es responsabilidad del caller).
    """
    dia = fecha.weekday()

    prod_confirmada = {
        (p.producto_id, p.sabor_id): p.cantidad
        for p in db.query(ProduccionDia).filter(ProduccionDia.fecha == fecha).all()
    }

    ultimo_parte = (
        db.query(ParteStock)
        .filter(ParteStock.tienda_id == tienda.id, ParteStock.fecha == fecha - timedelta(days=1))
        .first()
    )
    stock_hoy = {}
    if ultimo_parte:
        for linea in ultimo_parte.lineas:
            key = (linea.producto_id, linea.sabor_id)
            stock_hoy[key] = _tartas_equiv(linea.cantidad, linea.raciones)

    pedidos_tienda = (
        db.query(Pedido)
        .filter(Pedido.fecha_recogida == fecha, Pedido.tienda_id == tienda.id)
        .all()
    )
    pedidos_map = {}
    for ped in pedidos_tienda:
        for linea in ped.lineas:
            key = (linea.producto_id, linea.sabor_id)
            pedidos_map[key] = pedidos_map.get(key, 0) + linea.cantidad

    prevision = (
        db.query(PrevisionStock)
        .filter(PrevisionStock.tienda_id == tienda.id, PrevisionStock.dia_semana == dia)
        .all()
    )
    prevision_map = {(pv.producto_id, pv.sabor_id): pv.cantidad for pv in prevision}

    envio_map = {}
    for key in set(prevision_map) | set(pedidos_map):
        stock = stock_hoy.get(key, 0)
        pedido = pedidos_map.get(key, 0)
        cantidad_prod = prod_confirmada.get(key)
        # Envío = faltante (previsión − stock) + pedidos, pero nunca más de lo horneado
        necesidad = max(0, prevision_map.get(key, 0) - stock) + pedido
        envio = min(necesidad, cantidad_prod) if cantidad_prod is not None else necesidad
        if envio > 0:
            envio_map[key] = envio

    return envio_map


def envio_confirmado_map(db, tienda_id: int, fecha: date) -> dict | None:
    """
    {(producto_id, sabor_id): cantidad} del EnvioTienda confirmado para esa
    tienda/fecha, o None si no hay confirmación (el caller debe usar la
    propuesta en vivo de calcular_envio en ese caso).
    """
    envio = (
        db.query(EnvioTienda)
        .filter(EnvioTienda.tienda_id == tienda_id, EnvioTienda.fecha == fecha,
                EnvioTienda.confirmado == True)
        .first()
    )
    if not envio:
        return None
    return {(l.producto_id, l.sabor_id): l.cantidad for l in envio.lineas}


def _calc_necesidades(db, fecha_dt: date) -> dict:
    """
    Devuelve {tienda_id: [{prod_nombre, sabor_nombre, prevision, stock_ayer, necesidad}]}
    Solo para tiendas con reparto ese día de semana.
    """
    dia = fecha_dt.weekday()  # 0=Lun

    reparto_tienda_ids = {
        dr.tienda_id
        for dr in db.query(DiasReparto).filter(DiasReparto.dia_semana == dia).all()
    }
    # Las tiendas de congelados van por su propio flujo (reposición del congelador),
    # no por la reposición diaria: se excluyen de las necesidades del obrador.
    congelados_ids = {t.id for t in db.query(Tienda).filter(Tienda.es_congelados == True).all()}
    reparto_tienda_ids -= congelados_ids
    if not reparto_tienda_ids:
        return {}

    productos = {p.id: p.nombre for p in db.query(Producto).all()}
    sabores = {s.id: s.nombre for s in db.query(Sabor).all()}

    previsiones = (
        db.query(PrevisionStock)
        .filter(PrevisionStock.dia_semana == dia,
                PrevisionStock.tienda_id.in_(reparto_tienda_ids))
        .all()
    )
    if not previsiones:
        return {}

    resultado: dict = {}
    for tid in reparto_tienda_ids:
        prevs_tienda = [p for p in previsiones if p.tienda_id == tid]
        if not prevs_tienda:
            continue

        # Último parte conocido anterior a la fecha
        ultimo_parte = (
            db.query(ParteStock)
            .filter(ParteStock.tienda_id == tid, ParteStock.fecha < fecha_dt)
            .order_by(ParteStock.fecha.desc(), ParteStock.id.desc())
            .first()
        )
        stock_map: dict = {}
        if ultimo_parte:
            for linea in ultimo_parte.lineas:
                stock_map[(linea.producto_id, linea.sabor_id)] = \
                    _tartas_equiv(linea.cantidad, linea.raciones)

        filas = []
        for pv in prevs_tienda:
            key = (pv.producto_id, pv.sabor_id)
            stock_ayer = stock_map.get(key, 0)
            # Necesidad = objetivo de previsión menos lo que ya hay en tienda
            necesidad = max(0, pv.cantidad - stock_ayer)
            filas.append({
                "prod_id": pv.producto_id,
                "sabor_id": pv.sabor_id,
                "prod_nombre": productos.get(pv.producto_id, "—"),
                "sabor_nombre": sabores.get(pv.sabor_id, "—"),
                "prevision": pv.cantidad,
                "stock_ayer": stock_ayer,
                "necesidad": necesidad,
            })
        if filas:
            resultado[tid] = {
                "filas": filas,
                "sobrantes": _sobrantes_de_parte(ultimo_parte, productos),
            }

    return resultado


# ─── congelados ─────────────────────────────────────────────────────────────
# Las tiendas de congelados (Tienda.es_congelados) no reciben reparto diario:
# reciben una reposición de su CONGELADOR 2 días antes del reparto y cada noche
# descongelan de congelador a VITRINA. La previsión de estas tiendas se interpreta
# como el "objetivo de vitrina diario" (por día de semana), no como envío directo.

# Margen entre el conteo del congelador y el día de reparto (da tiempo a hornear
# y congelar sin saturar el obrador). Fijo por ahora; fácil de parametrizar.
DIAS_ANTICIPO_CONGELADO = 2


def _dias_ciclo_congelado(dias_reparto: set[int], fecha_reparto: date) -> list[date]:
    """Días que debe cubrir un reparto de congelados: desde el propio día de
    reparto hasta el día antes del siguiente reparto (según los días de reparto
    de la tienda). Un solo día de reparto a la semana ⇒ cubre los 7 días."""
    if not dias_reparto:
        return [fecha_reparto]
    for delta in range(1, 8):
        if (fecha_reparto + timedelta(days=delta)).weekday() in dias_reparto:
            break
    return [fecha_reparto + timedelta(days=i) for i in range(delta)]


def _objetivo_vitrina_ciclo(db, tienda_id: int, dias_ciclo: list[date]) -> dict:
    """{(producto_id, sabor_id): Σ objetivo de vitrina} sumando la previsión de la
    tienda para cada día de semana del ciclo (un día repetido suma su objetivo N veces)."""
    weekdays = [d.weekday() for d in dias_ciclo]
    prevs = (
        db.query(PrevisionStock)
        .filter(PrevisionStock.tienda_id == tienda_id,
                PrevisionStock.dia_semana.in_(set(weekdays)))
        .all()
    )
    por_dia: dict = {}
    for pv in prevs:
        por_dia.setdefault(pv.dia_semana, []).append((pv.producto_id, pv.sabor_id, pv.cantidad))

    total: dict = {}
    for wd in weekdays:
        for pid, sid, cant in por_dia.get(wd, []):
            key = (pid, sid)
            total[key] = total.get(key, 0) + cant
    return total


def _congelador_contado(db, tienda_id: int, fecha: date) -> dict:
    """{(producto_id, sabor_id): cantidad} del congelador contado en el parte de
    congelador (ParteCongelador) de esa tienda y fecha."""
    parte = (
        db.query(ParteCongelador)
        .filter(ParteCongelador.tienda_id == tienda_id, ParteCongelador.fecha == fecha)
        .first()
    )
    if not parte:
        return {}
    return {(l.producto_id, l.sabor_id): l.cantidad for l in parte.lineas}


def reposicion_congelado(db, tienda, fecha_reparto: date) -> dict:
    """{(producto_id, sabor_id): cantidad>0} a mandar al congelador de `tienda` en
    `fecha_reparto`: Σ objetivo de vitrina del ciclo − congelador contado la noche
    del conteo (fecha_reparto − DIAS_ANTICIPO_CONGELADO). Cálculo puro, reutilizable."""
    dias_reparto = {
        dr.dia_semana
        for dr in db.query(DiasReparto).filter(DiasReparto.tienda_id == tienda.id).all()
    }
    dias_ciclo = _dias_ciclo_congelado(dias_reparto, fecha_reparto)
    objetivo = _objetivo_vitrina_ciclo(db, tienda.id, dias_ciclo)
    fecha_conteo = fecha_reparto - timedelta(days=DIAS_ANTICIPO_CONGELADO)
    congelador = _congelador_contado(db, tienda.id, fecha_conteo)

    result: dict = {}
    for key, obj in objetivo.items():
        rep = max(0, obj - congelador.get(key, 0))
        if rep > 0:
            result[key] = rep
    return result


def descongelacion_congelado(db, tienda, fecha_noche: date) -> dict:
    """{(producto_id, sabor_id): cantidad>0} a descongelar la noche de `fecha_noche`:
    objetivo de vitrina del día siguiente − lo que ya queda en vitrina (parte de esa
    noche). Es lo que la tienda saca del congelador a la vitrina para el día siguiente."""
    manana = fecha_noche + timedelta(days=1)
    objetivo = {
        (pv.producto_id, pv.sabor_id): pv.cantidad
        for pv in db.query(PrevisionStock).filter(
            PrevisionStock.tienda_id == tienda.id,
            PrevisionStock.dia_semana == manana.weekday()).all()
    }
    parte = (
        db.query(ParteStock)
        .filter(ParteStock.tienda_id == tienda.id, ParteStock.fecha == fecha_noche)
        .first()
    )
    vitrina: dict = {}
    if parte:
        for l in parte.lineas:
            key = (l.producto_id, l.sabor_id)
            vitrina[key] = _tartas_equiv(l.cantidad, l.raciones)

    result: dict = {}
    for key, obj in objetivo.items():
        falta = max(0, obj - vitrina.get(key, 0))
        if falta > 0:
            result[key] = falta
    return result


def _roster_congelado_obrador(db) -> list[dict]:
    """Secciones (una por producto) con las combinaciones que las tiendas de
    congelados tienen en previsión, para el inventario congelado del obrador:
    solo aparece lo que de verdad se congela y se manda.
    [{prod_id, nombre, color, filas:[{sabor, prod_id, sabor_id}]}]"""
    tiendas_cong = {t.id for t in db.query(Tienda).filter(Tienda.es_congelados == True).all()}
    if not tiendas_cong:
        return []
    combos = {
        (pv.producto_id, pv.sabor_id)
        for pv in db.query(PrevisionStock).filter(PrevisionStock.tienda_id.in_(tiendas_cong)).all()
    }
    if not combos:
        return []

    productos = db.query(Producto).filter(Producto.activo == True).order_by(Producto.orden, Producto.nombre).all()
    sabores = {s.id: s.nombre for s in db.query(Sabor).all()}
    sp_orden = {(sp.producto_id, sp.sabor_id): sp.orden for sp in db.query(SaborProducto).all()}

    secciones: list[dict] = []
    for prod in productos:
        sids = sorted(
            (sid for pid, sid in combos if pid == prod.id and sid in sabores),
            key=lambda sid: sp_orden.get((prod.id, sid), 99),
        )
        if not sids:
            continue
        secciones.append({
            "prod_id": prod.id,
            "nombre": prod.nombre,
            "color": _color_seccion(prod.nombre, prod.id),
            "filas": [{"sabor": sabores[sid], "prod_id": prod.id, "sabor_id": sid} for sid in sids],
        })
    return secciones


def _cat_producto(nombre: str) -> str:
    """Clasifica un producto expandido (ej. "TARTA GRANDE", "COOKIE") en una de
    las categorías visuales del parte de stock, a partir de su propio nombre."""
    n = nombre.lower()
    if "cookie" in n or "galleta" in n: return "cookie"
    if "tarrin" in n:   return "tarrina"
    if "grande" in n:   return "grande"
    if "peque" in n:    return "pequena"
    if "mini" in n:     return "mini"
    return "otro"


def _build_catalogo_parte(db, tienda_id: int | None = None,
                          extra_keys: set | None = None) -> list[dict]:
    """
    Catálogo para el formulario de partes de stock: una sección por producto
    activo (cualquier producto nuevo genera la suya sin tocar código):
    [{prod_id, nombre, color, permite_porciones, filas: [{sabor, prod_id, sabor_id}]}]

    Si se pasa `tienda_id`, el parte se guía por la PREVISIÓN de esa tienda: solo
    aparecen las combinaciones (producto, sabor) que la tienda tiene en previsión
    (unión de todos sus días). Sin `tienda_id` se devuelve el catálogo completo.
    """
    # Combinaciones permitidas: previsión de la tienda + (al editar) las que ya
    # tenga guardadas el parte, para no perder líneas si la previsión cambió.
    prevision_keys: set | None = None
    if tienda_id is not None:
        prevision_keys = {
            (pv.producto_id, pv.sabor_id)
            for pv in db.query(PrevisionStock).filter(
                PrevisionStock.tienda_id == tienda_id).all()
        }
        if extra_keys:
            prevision_keys = prevision_keys | extra_keys

    # Solo PRODUCCION: el parte se guía por la previsión, que a su vez solo contiene
    # producción regular. Las filas ya guardadas (extra_keys) se preservan aunque el
    # sabor haya pasado a ENCARGO/OUT, para no perder un recuento en curso.
    sp_rows = db.query(SaborProducto).filter(
        SaborProducto.produccion == True, SaborProducto.out == False).all()
    sp_set = {(sp.producto_id, sp.sabor_id) for sp in sp_rows}
    sp_orden = {(sp.producto_id, sp.sabor_id): sp.orden for sp in sp_rows}
    if extra_keys:
        sp_set = sp_set | extra_keys
    productos = db.query(Producto).filter(Producto.activo == True).order_by(Producto.orden, Producto.nombre).all()
    sabores = {s.id: s.nombre for s in db.query(Sabor).all()}

    secciones: list[dict] = []
    for prod in productos:
        sids = sorted(
            (sid for pid, sid in sp_set
             if pid == prod.id and sid in sabores
             and (prevision_keys is None or (pid, sid) in prevision_keys)),
            key=lambda sid: sp_orden.get((prod.id, sid), 99),
        )
        if not sids:
            continue
        secciones.append({
            "prod_id": prod.id,
            "nombre": prod.nombre,
            "color": _color_seccion(prod.nombre, prod.id),
            "permite_porciones": prod.permite_porciones,
            "filas": [{"sabor": sabores[sid], "prod_id": prod.id, "sabor_id": sid} for sid in sids],
        })
    return secciones


def _build_catalogo_grid(db) -> list[dict]:
    """
    Catálogo plano para la previsión-grid: agrupado por producto (en orden de
    catálogo) y dentro de cada producto por el orden propio de ESE producto
    (sabor_producto.orden), con el color de sección del producto. Solo
    combinaciones marcadas como PRODUCCION: la previsión es el objetivo de
    stock regular, no incluye lo de ENCARGO.
    """
    sp_rows = db.query(SaborProducto).filter(
        SaborProducto.produccion == True, SaborProducto.out == False).all()
    sp_set = {(sp.producto_id, sp.sabor_id) for sp in sp_rows}
    sp_orden = {(sp.producto_id, sp.sabor_id): sp.orden for sp in sp_rows}
    productos = db.query(Producto).filter(Producto.activo == True).order_by(Producto.orden, Producto.nombre).all()
    prod_orden = {p.id: i for i, p in enumerate(productos)}
    prod_por_id = {p.id: p for p in productos}
    sabores = {s.id: s.nombre for s in db.query(Sabor).all()}

    filas = []
    for pid, sid in sp_set:
        prod = prod_por_id.get(pid)
        snom = sabores.get(sid)
        if not (prod and snom):
            continue
        filas.append({
            "prod_id": pid, "sabor_id": sid,
            "prod_nombre": prod.nombre,
            "sabor_nombre": snom,
            "color": _color_seccion(prod.nombre, pid),
        })

    filas.sort(key=lambda f: (prod_orden.get(f["prod_id"], 99), sp_orden.get((f["prod_id"], f["sabor_id"]), 99)))
    return filas


# ─── días de reparto ───────────────────────────────────────────────────────────

@router.get("/reparto/", response_class=HTMLResponse)
@requiere_permiso("stock.dias_reparto")
async def reparto_get(request: Request):
    """Matriz tienda × día de semana con los días de reparto activos (tabla dias_reparto)."""
    db = SessionLocal()
    try:
        tiendas = db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()
        activos = {f"{dr.tienda_id}_{dr.dia_semana}" for dr in db.query(DiasReparto).all()}
        tiendas_data = [{"id": t.id, "nombre": t.nombre} for t in tiendas]
        return templates.TemplateResponse("stock/reparto.html", {
            "request": request,
            "usuario": request.state.usuario,
            "tiendas": tiendas_data,
            "activos": activos,
            "dias": DIAS_SEMANA,
        })
    finally:
        db.close()


@router.post("/reparto/toggle")
@requiere_permiso("stock.dias_reparto", editar=True)
async def reparto_toggle(request: Request):
    """Añade o quita un único (tienda, día) en dias_reparto. Auto-guardado por celda."""
    form = await request.form()
    try:
        tienda_id = int(form.get("tienda_id", 0))
        dia = int(form.get("dia", -1))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False}, status_code=400)
    if not tienda_id or dia < 0 or dia > 6:
        return JSONResponse({"ok": False}, status_code=400)

    db = SessionLocal()
    try:
        existente = db.query(DiasReparto).filter(
            DiasReparto.tienda_id == tienda_id, DiasReparto.dia_semana == dia
        ).first()
        if existente:
            db.delete(existente)
            activo = False
        else:
            db.add(DiasReparto(tienda_id=tienda_id, dia_semana=dia))
            activo = True
        db.commit()
        return JSONResponse({"ok": True, "activo": activo})
    finally:
        db.close()


# ─── previsión ────────────────────────────────────────────────────────────────

@router.get("/prevision/", response_class=HTMLResponse)
@requiere_permiso("stock.prevision")
async def prevision_lista(request: Request):
    """Lista de tiendas con sus días de reparto, punto de entrada a editar previsiones."""
    db = SessionLocal()
    try:
        tiendas = db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()
        # días con reparto por tienda
        reparto = {}
        for dr in db.query(DiasReparto).all():
            reparto.setdefault(dr.tienda_id, []).append(dr.dia_semana)
        tiendas_data = [
            {"id": t.id, "nombre": t.nombre, "dias": reparto.get(t.id, []),
             "es_congelados": t.es_congelados}
            for t in tiendas
        ]
        return templates.TemplateResponse("stock/prevision_lista.html", {
            "request": request,
            "usuario": request.state.usuario,
            "tiendas": tiendas_data,
            "dias": DIAS_SEMANA,
        })
    finally:
        db.close()


@router.get("/prevision/{tienda_id}", response_class=HTMLResponse)
@requiere_permiso("stock.prevision")
async def prevision_editar_get(request: Request, tienda_id: int):
    """Grid de previsión de una tienda: cantidades objetivo por combinación y día de reparto (prevision_stock)."""
    db = SessionLocal()
    try:
        tienda = db.query(Tienda).filter(Tienda.id == tienda_id).first()
        es_congelados = bool(tienda and tienda.es_congelados)
        filas = _build_catalogo_grid(db)
        dias_reparto = sorted(
            dr.dia_semana for dr in db.query(DiasReparto).filter(
                DiasReparto.tienda_id == tienda_id).all()
        )
        # En congelados la previsión es el objetivo de VITRINA de cada día: se
        # editan los 7 días. En el resto, solo los días con reparto.
        dias_columnas = list(range(7)) if es_congelados else dias_reparto
        previsiones = {
            (pv.dia_semana, pv.producto_id, pv.sabor_id): pv.cantidad
            for pv in db.query(PrevisionStock).filter(PrevisionStock.tienda_id == tienda_id).all()
        }
        return templates.TemplateResponse("stock/prevision.html", {
            "request": request,
            "usuario": request.state.usuario,
            "tienda": {"id": tienda_id, "nombre": tienda.nombre if tienda else "—"},
            "filas": filas,
            "previsiones": previsiones,
            "dias_reparto": dias_reparto,
            "dias_columnas": dias_columnas,
            "es_congelados": es_congelados,
            "dias": DIAS_SEMANA,
        })
    finally:
        db.close()


@router.post("/prevision/{tienda_id}", response_class=HTMLResponse)
@requiere_permiso("stock.prevision", editar=True)
async def prevision_editar_post(request: Request, tienda_id: int):
    """Guarda la previsión de la tienda: borra todo y reinserta lo enviado (solo cantidades > 0)."""
    form = await request.form()
    db = SessionLocal()
    try:
        # Estrategia reemplazo total: los inputs vienen como pv_<dia>_<prod>_<sabor>
        db.execute(delete(PrevisionStock).where(PrevisionStock.tienda_id == tienda_id))
        for key, val in form.items():
            if not key.startswith("pv_"):
                continue
            try:
                _, dia, pid, sid = key.split("_")
                cantidad = max(0, int(val) if val else 0)
            except (ValueError, AttributeError):
                continue
            if cantidad == 0:
                continue
            db.add(PrevisionStock(
                tienda_id=tienda_id,
                dia_semana=int(dia),
                producto_id=int(pid),
                sabor_id=int(sid),
                cantidad=cantidad,
            ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/stock/prevision/{tienda_id}", status_code=302)


# ─── necesidades ──────────────────────────────────────────────────────────────

@router.get("/necesidades/", response_class=HTMLResponse)
@requiere_permiso("stock.prevision")
async def necesidades_get(request: Request, fecha: str = ""):
    """Necesidades de producción por tienda para una fecha (previsión − stock del último parte)
    y totales globales para el obrador. Lee prevision_stock, partes_stock y dias_reparto."""
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today()
    except ValueError:
        fecha_dt = date.today()

    db = SessionLocal()
    try:
        nec = _calc_necesidades(db, fecha_dt)
        tiendas_map = {t.id: t.nombre for t in db.query(Tienda).all()}

        # Totales globales para dar a obrador
        totales: dict = {}
        for tid, datos in nec.items():
            for f in datos["filas"]:
                key = (f["prod_nombre"], f["sabor_nombre"])
                totales[key] = totales.get(key, 0) + f["necesidad"]

        nec_data = {tiendas_map.get(tid, str(tid)): datos for tid, datos in nec.items()}
        hoy_iso = date.today().isoformat()
        manana_iso = (fecha_dt + timedelta(days=1)).isoformat()
        ayer_iso = (fecha_dt - timedelta(days=1)).isoformat()

        return templates.TemplateResponse("stock/necesidades.html", {
            "request": request,
            "usuario": request.state.usuario,
            "fecha": fecha_dt,
            "nec_data": nec_data,
            "totales": totales,
            "hoy_iso": hoy_iso,
            "manana_iso": manana_iso,
            "ayer_iso": ayer_iso,
        })
    finally:
        db.close()


# ─── envíos ───────────────────────────────────────────────────────────────────

@router.get("/envios/", response_class=HTMLResponse)
@requiere_permiso("stock.envios")
async def envios_get(request: Request, fecha: str = ""):
    """Fichas de envío por tienda con reparto ese día: stock actual, unidades a enviar
    y pedidos a entregar. Cruza partes_stock, prevision_stock, produccion_dia y pedidos."""
    try:
        # Por defecto se prepara el envío de mañana
        fecha_dt = date.fromisoformat(fecha) if fecha else (date.today() + timedelta(days=1))
    except ValueError:
        fecha_dt = date.today() + timedelta(days=1)

    usuario = request.state.usuario
    db = SessionLocal()
    try:
        dia = fecha_dt.weekday()
        tiendas_reparto = {
            dr.tienda_id
            for dr in db.query(DiasReparto).filter(DiasReparto.dia_semana == dia).all()
        }
        if usuario.rol == Rol.TIENDAS:
            tiendas_reparto &= {usuario.tienda_id or -1}
        tiendas = db.query(Tienda).filter(Tienda.activa == True, Tienda.id.in_(tiendas_reparto)).order_by(Tienda.nombre).all() if tiendas_reparto else []

        productos_map = {p.id: p for p in db.query(Producto).all()}
        sabores_map = {s.id: s for s in db.query(Sabor).all()}

        fichas = []
        for tienda in tiendas:
            es_cong = tienda.es_congelados
            # HOY: parte de stock de la tienda del día exacto anterior a fecha_dt.
            # En congelados no aplica (el envío repone congelador, no vitrina).
            ultimo_parte = (
                db.query(ParteStock)
                .filter(ParteStock.tienda_id == tienda.id, ParteStock.fecha == fecha_dt - timedelta(days=1))
                .first()
            )
            stock_hoy = {}
            if ultimo_parte and not es_cong:
                for linea in ultimo_parte.lineas:
                    key = (linea.producto_id, linea.sabor_id)
                    stock_hoy[key] = _tartas_equiv(linea.cantidad, linea.raciones)

            # PEDIDOS: B2B y particulares que se RECOGEN en esta tienda en fecha_dt
            # (se hornearon el día anterior y van en el envío de esta mañana)
            pedidos_tienda = (
                db.query(Pedido)
                .filter(Pedido.fecha_recogida == fecha_dt, Pedido.tienda_id == tienda.id)
                .all()
            )
            pedidos_map = {}
            pedidos_detalle = []
            for ped in pedidos_tienda:
                lineas_txt = []
                for linea in ped.lineas:
                    key = (linea.producto_id, linea.sabor_id)
                    pedidos_map[key] = pedidos_map.get(key, 0) + linea.cantidad
                    prod = productos_map.get(linea.producto_id)
                    sab = sabores_map.get(linea.sabor_id)
                    lineas_txt.append(f"{linea.cantidad}× {prod.nombre if prod else '—'} {sab.nombre if sab else '—'}")
                for linea in ped.lineas_otros:
                    lineas_txt.append(f"{linea.cantidad}× {linea.descripcion}")
                if ped.tipo == "B2B" and ped.cliente_b2b_id:
                    cliente_b2b = db.query(ClienteB2B).get(ped.cliente_b2b_id)
                    nombre = cliente_b2b.nombre_comercial if cliente_b2b else "—"
                else:
                    nombre = ped.nombre_cliente or "—"
                pedidos_detalle.append({
                    "id": ped.id,
                    "referencia": ped.referencia,
                    "cliente": nombre,
                    "telefono": ped.telefono_cliente,
                    "lineas": lineas_txt,
                    "comentario": ped.comentario,
                })

            # ENVÍO: lo ya confirmado por el obrador (fuente de verdad) o, si aún
            # no se confirmó, la propuesta en vivo. En congelados la propuesta es la
            # reposición del congelador (Σ objetivo vitrina del ciclo − congelador);
            # en el resto, previsión − stock + pedidos.
            conf = envio_confirmado_map(db, tienda.id, fecha_dt)
            confirmado = conf is not None
            if confirmado:
                envio_map = conf
            elif es_cong:
                envio_map = reposicion_congelado(db, tienda, fecha_dt)
            else:
                envio_map = calcular_envio(db, tienda, fecha_dt)
            # La previsión (objetivo de vitrina en congelados) no debe engordar la
            # ficha de reparto: solo interesa lo que realmente se envía.
            if es_cong:
                prevision_map = {}
            else:
                prevision = (
                    db.query(PrevisionStock)
                    .filter(PrevisionStock.tienda_id == tienda.id, PrevisionStock.dia_semana == dia)
                    .all()
                )
                prevision_map = {(pv.producto_id, pv.sabor_id): pv.cantidad for pv in prevision}

            # Agrupar por producto expandido para la ficha. Se incluye TODO el roster
            # de la previsión del día (aunque envío/pedidos sean 0) para que la ficha
            # imprimible liste la lista completa con guiones, como el Excel original.
            sobrantes_parte = {s.producto_id: s.cantidad for s in ultimo_parte.sobrantes} if (ultimo_parte and not es_cong) else {}
            secciones: dict = {}
            todas_keys = set(prevision_map) | set(stock_hoy) | set(pedidos_map) | set(envio_map)
            for key in todas_keys:
                pid, sid = key
                prod = productos_map.get(pid)
                if not prod:
                    continue
                secciones.setdefault(prod.nombre, {
                    "orden": prod.orden,
                    "color": _color_seccion(prod.nombre, prod.id),
                    "sobrante": sobrantes_parte.get(prod.id, 0),
                    "filas": [],
                })
                secciones[prod.nombre]["filas"].append({
                    "sabor": sabores_map[sid].nombre if sid in sabores_map else "—",
                    "hoy": stock_hoy.get(key, 0),
                    "envio": envio_map.get(key, 0),
                    "pedidos": pedidos_map.get(key, 0),
                    "key": f"{pid}_{sid}",
                })

            for sec in secciones.values():
                sec["filas"].sort(key=lambda r: r["sabor"])

            fichas.append({
                "tienda_id": tienda.id,
                "tienda_nombre": tienda.nombre,
                "pedidos_detalle": pedidos_detalle,
                "secciones": dict(sorted(secciones.items(), key=lambda x: x[1]["orden"])),
                "total_envio": sum(r["envio"] for sec in secciones.values() for r in sec["filas"]),
                "total_pedidos": sum(r["pedidos"] for sec in secciones.values() for r in sec["filas"]),
                "confirmado": confirmado,
                "puede_editar": _rol_obrador(usuario),
                "es_congelados": es_cong,
            })

        hoy_iso = date.today().isoformat()
        manana_iso = (date.today() + timedelta(days=1)).isoformat()
        pasado_iso = (fecha_dt + timedelta(days=1)).isoformat()
        anterior_iso = (fecha_dt - timedelta(days=1)).isoformat()

        return templates.TemplateResponse("stock/envios.html", {
            "request": request,
            "usuario": request.state.usuario,
            "fecha": fecha_dt,
            "fichas": fichas,
            "hoy_iso": hoy_iso,
            "manana_iso": manana_iso,
            "pasado_iso": pasado_iso,
            "anterior_iso": anterior_iso,
        })
    finally:
        db.close()


@router.post("/envios/{tienda_id}/confirmar")
@requiere_permiso("stock.envios", editar=True)
async def envio_confirmar(request: Request, tienda_id: int):
    """Congela el envío a una tienda para una fecha: reemplaza sus líneas con las
    cantidades enviadas. Solo el obrador puede confirmar (stock.envios también da
    EDITAR a REPARTIDORES/TIENDAS, que solo pueden ver la ficha)."""
    usuario = request.state.usuario
    if not _rol_obrador(usuario):
        raise HTTPException(status_code=403, detail="Solo el obrador puede confirmar envíos.")

    form = await request.form()
    fecha_str = form.get("fecha", "")
    try:
        fecha_dt = date.fromisoformat(fecha_str) if fecha_str else date.today() + timedelta(days=1)
    except ValueError:
        fecha_dt = date.today() + timedelta(days=1)

    db = SessionLocal()
    try:
        envio = db.query(EnvioTienda).filter(
            EnvioTienda.tienda_id == tienda_id, EnvioTienda.fecha == fecha_dt
        ).first()
        if not envio:
            envio = EnvioTienda(tienda_id=tienda_id, fecha=fecha_dt)
            db.add(envio)
            try:
                db.flush()
            except IntegrityError:
                # Carrera (doble click): otro envío de la misma tienda y fecha se
                # coló entre la comprobación y el flush → recuperar el existente
                db.rollback()
                envio = db.query(EnvioTienda).filter(
                    EnvioTienda.tienda_id == tienda_id, EnvioTienda.fecha == fecha_dt
                ).first()

        db.query(LineaEnvioTienda).filter(
            LineaEnvioTienda.envio_tienda_id == envio.id).delete()
        for key, val in form.items():
            if not key.startswith("cant_"):
                continue
            try:
                _, pid, sid = key.split("_")
                cantidad = max(0, int(val) if val else 0)
            except (ValueError, AttributeError):
                continue
            if cantidad == 0:
                continue
            db.add(LineaEnvioTienda(
                envio_tienda_id=envio.id,
                producto_id=int(pid), sabor_id=int(sid), cantidad=cantidad,
            ))

        envio.confirmado = True
        envio.confirmado_en = datetime.now()
        envio.confirmado_por = usuario.id
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/stock/envios/?fecha={fecha_dt.isoformat()}", status_code=302)


# ─── mermas (sin cambios de lógica) ───────────────────────────────────────────

@router.get("/mermas/", response_class=HTMLResponse)
@requiere_permiso("stock.mermas")
async def mermas_lista(request: Request, tienda_id: int = 0, desde: str = "", hasta: str = ""):
    """Listado de mermas con filtros por tienda y rango de fechas. Rol TIENDAS solo ve su tienda."""
    usuario = request.state.usuario
    db = SessionLocal()
    try:
        q = db.query(Merma)
        if usuario.rol == Rol.TIENDAS:
            q = q.filter(Merma.tienda_id == (usuario.tienda_id or -1))
        elif tienda_id:
            q = q.filter(Merma.tienda_id == tienda_id)
        if desde:
            try:
                q = q.filter(Merma.fecha >= date.fromisoformat(desde))
            except ValueError:
                pass
        if hasta:
            try:
                q = q.filter(Merma.fecha <= date.fromisoformat(hasta))
            except ValueError:
                pass

        mermas = q.order_by(Merma.fecha.desc(), Merma.id.desc()).all()
        productos = {p.id: p.nombre for p in db.query(Producto).all()}
        sabores = {s.id: s.nombre for s in db.query(Sabor).all()}
        tiendas_map = {t.id: t.nombre for t in db.query(Tienda).all()}

        filas = [
            {
                "id": m.id, "fecha": m.fecha,
                "tienda": tiendas_map.get(m.tienda_id, "—"),
                "producto": productos.get(m.producto_id, "—"),
                "sabor": sabores.get(m.sabor_id, "—"),
                "cantidad": m.cantidad, "motivo": m.motivo,
                "comentario": m.comentario or "",
            }
            for m in mermas
        ]
        tiendas_lista = [{"id": t.id, "nombre": t.nombre}
                         for t in db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]

        return templates.TemplateResponse("stock/mermas.html", {
            "request": request, "usuario": usuario,
            "filas": filas, "tiendas": tiendas_lista,
            "filtro_tienda": tienda_id, "filtro_desde": desde, "filtro_hasta": hasta,
        })
    finally:
        db.close()


@router.get("/mermas/nuevo", response_class=HTMLResponse)
@requiere_permiso("stock.mermas", editar=True)
async def merma_form_get(request: Request):
    """Formulario de alta de merma con el catálogo activo completo."""
    db = SessionLocal()
    try:
        catalogo = _build_catalogo(db)
        tiendas = [{"id": t.id, "nombre": t.nombre}
                   for t in db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]
        return templates.TemplateResponse("stock/merma_form.html", {
            "request": request, "usuario": request.state.usuario,
            "catalogo": catalogo, "tiendas": tiendas,
            "motivos": MOTIVOS, "hoy": date.today().isoformat(), "error": None,
        })
    finally:
        db.close()


@router.post("/mermas/nuevo", response_class=HTMLResponse)
@requiere_permiso("stock.mermas", editar=True)
async def merma_form_post(
    request: Request,
    fecha: str = Form(...),
    tienda_id: int = Form(...),
    producto_id: int = Form(...),
    sabor_id: int = Form(...),
    cantidad: int = Form(...),
    motivo: str = Form(...),
    comentario: str = Form(""),
):
    """Registra una merma. Rol TIENDAS solo puede registrar en su propia tienda."""
    usuario = request.state.usuario
    if cantidad < 1:
        return RedirectResponse(url="/stock/mermas/nuevo", status_code=302)
    if usuario.rol == Rol.TIENDAS:
        tienda_id = usuario.tienda_id
        if not tienda_id:
            return RedirectResponse(url="/stock/mermas/", status_code=302)
    db = SessionLocal()
    try:
        try:
            fecha_dt = date.fromisoformat(fecha)
        except ValueError:
            fecha_dt = date.today()
        db.add(Merma(
            fecha=fecha_dt, tienda_id=tienda_id, usuario_id=usuario.id,
            producto_id=producto_id, sabor_id=sabor_id,
            cantidad=cantidad, motivo=motivo, comentario=comentario.strip() or None,
        ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/stock/mermas/", status_code=302)


# ─── partes de stock ──────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@requiere_permiso("stock.partes")
async def stock_index(request: Request, fecha: str = "", tienda_id: str = ""):
    """Vista principal: matriz comparativa de los partes de stock de todas las tiendas
    en una fecha (filas = combinaciones reportadas, columnas = tiendas). Lee partes_stock."""
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today()
    except ValueError:
        fecha_dt = date.today()

    # "" (Todas las tiendas) → 0; cualquier valor no numérico también cae a 0
    try:
        tienda_id = int(tienda_id) if tienda_id else 0
    except ValueError:
        tienda_id = 0

    usuario = request.state.usuario
    db = SessionLocal()
    try:
        catalogo = _build_catalogo(db)

        # Tiendas a mostrar
        if usuario.rol == Rol.TIENDAS:
            tiendas = db.query(Tienda).filter(Tienda.id == usuario.tienda_id).all()
        elif tienda_id:
            tiendas = db.query(Tienda).filter(Tienda.id == tienda_id).all()
        else:
            tiendas = db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()

        # Parte de cada tienda para la fecha dada
        partes_map: dict = {}  # tienda_id → ParteStock
        for t in tiendas:
            p = db.query(ParteStock).filter(
                ParteStock.tienda_id == t.id, ParteStock.fecha == fecha_dt
            ).first()
            if p:
                partes_map[t.id] = p

        # Construir datos de celda {tienda_id: {(pid,sid): (enteras, raciones)}}
        productos_nombres = {p.id: p.nombre for p in db.query(Producto).all()}
        celdas: dict = {}
        sobrantes_por_tienda: dict = {}
        for tid, parte in partes_map.items():
            celdas[tid] = {
                (l.producto_id, l.sabor_id): (l.cantidad, l.raciones)
                for l in parte.lineas
            }
            sobrantes_por_tienda[tid] = _sobrantes_de_parte(parte, productos_nombres)

        # ── Matriz comparativa: filas = unión de sabores reportados, columnas = tiendas ──
        # Metadatos de cada combinación (grupo, etiqueta, porciones) desde el catálogo,
        # clasificados por el nombre del propio producto expandido (ya incluye el tamaño)
        _grupos = {"grande": (0, "Tartas grandes"), "pequena": (1, "Pequeñas"), "mini": (2, "Mini"),
                   "tarrina": (3, "Tarrinas"), "cookie": (4, "Cookies"), "otro": (5, "Otros")}
        meta_por_key: dict = {}
        for _pnom, _sabores in catalogo.items():
            _orden, _grupo = _grupos[_cat_producto(_pnom)]
            for _snom, _it in _sabores.items():
                _etiqueta = _snom if _orden < 5 else f"{_pnom} · {_snom}"
                meta_por_key[f"{_it['prod_id']}_{_it['sabor_id']}"] = {
                    "orden": _orden, "grupo": _grupo, "etiqueta": _etiqueta,
                    "permite_porciones": _it["permite_porciones"],
                }

        # Unión de las combinaciones reportadas con valor > 0 por cualquier tienda
        keys_union = set()
        total_por_tienda: dict = {}
        for tid, cells in celdas.items():
            total = 0
            for (a, b), (ent, rac) in cells.items():
                total += ent + (rac // PORCIONES_POR_TARTA)
                if ent > 0 or rac > 0:
                    keys_union.add(f"{a}_{b}")
            total_por_tienda[str(tid)] = total

        filas = [dict(meta_por_key[k], key=k) for k in keys_union if k in meta_por_key]
        filas.sort(key=lambda r: (r["orden"], r["etiqueta"].lower()))
        secciones = []
        for _orden, _label in [(0, "Tartas grandes"), (1, "Pequeñas"), (2, "Mini"),
                               (3, "Tarrinas"), (4, "Cookies"), (5, "Otros")]:
            grp = [f for f in filas if f["orden"] == _orden]
            if grp:
                secciones.append({"label": _label, "filas": grp})

        # ¿Tiene parte abierto hoy el usuario TIENDAS?
        parte_hoy_id = None
        usuario_congelados = False
        if usuario.rol == Rol.TIENDAS and usuario.tienda_id:
            p = partes_map.get(usuario.tienda_id)
            parte_hoy_id = p.id if p else None
            tu = db.query(Tienda).filter(Tienda.id == usuario.tienda_id).first()
            usuario_congelados = bool(tu and tu.es_congelados)
        # El parte de congeladas se ofrece a las tiendas de congelados y al obrador
        mostrar_congeladas = usuario_congelados or (
            usuario.rol != Rol.TIENDAS and usuario.puede_editar("stock.partes"))

        tiendas_data = [{"id": t.id, "nombre": t.nombre,
                         "parte_id": partes_map[t.id].id if t.id in partes_map else None,
                         "cerrado": partes_map[t.id].cerrado if t.id in partes_map else None}
                        for t in tiendas]
        todas_tiendas = [{"id": t.id, "nombre": t.nombre}
                         for t in db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]

        hoy_iso = date.today().isoformat()
        ayer_iso = (fecha_dt - timedelta(days=1)).isoformat()
        manana_iso = (fecha_dt + timedelta(days=1)).isoformat()

        return templates.TemplateResponse("stock/index.html", {
            "request": request,
            "usuario": usuario,
            "fecha": fecha_dt,
            "hoy_iso": hoy_iso,
            "ayer_iso": ayer_iso,
            "manana_iso": manana_iso,
            "catalogo": catalogo,
            "tiendas": tiendas_data,
            "todas_tiendas": todas_tiendas,
            "celdas": {str(k): {f"{a}_{b}": list(v) for (a, b), v in vv.items()}
                       for k, vv in celdas.items()},
            "sobrantes_por_tienda": {str(k): v for k, v in sobrantes_por_tienda.items()},
            "secciones": secciones,
            "total_por_tienda": total_por_tienda,
            "parte_hoy_id": parte_hoy_id,
            "mostrar_congeladas": mostrar_congeladas,
            "filtro_tienda": tienda_id,
        })
    finally:
        db.close()


@router.get("/nuevo", response_class=HTMLResponse)
@requiere_permiso("stock.partes", editar=True)
async def parte_nuevo_get(request: Request, tienda_id: int = 0):
    """Formulario de parte de stock del día. Si la tienda ya tiene parte hoy, redirige a él."""
    usuario = request.state.usuario
    db = SessionLocal()
    try:
        hoy = date.today()

        # Tienda objetivo del parte: implícita para TIENDAS, elegida por JEFES/ADMINISTRACION
        if usuario.rol == Rol.TIENDAS:
            tienda_sel = usuario.tienda_id
        else:
            tienda_sel = tienda_id or None

        if tienda_sel:
            existente = db.query(ParteStock).filter(
                ParteStock.fecha == hoy, ParteStock.tienda_id == tienda_sel
            ).first()
            if existente:
                return RedirectResponse(url=f"/stock/{existente.id}", status_code=302)

        # El parte se guía por la previsión de la tienda; sin tienda elegida no hay catálogo
        catalogo = _build_catalogo_parte(db, tienda_sel) if tienda_sel else None
        sin_prevision = catalogo is not None and not catalogo

        tienda_obj = db.query(Tienda).filter(Tienda.id == tienda_sel).first() if tienda_sel else None
        es_congelados = bool(tienda_obj and tienda_obj.es_congelados)
        nombre_sel = tienda_obj.nombre if tienda_obj else None

        tiendas = [{"id": t.id, "nombre": t.nombre}
                   for t in db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]
        return templates.TemplateResponse("stock/parte_form.html", {
            "request": request, "usuario": usuario,
            "catalogo": catalogo, "tiendas": tiendas,
            "tienda_sel": tienda_sel, "nombre_sel": nombre_sel,
            "sin_prevision": sin_prevision,
            "es_congelados": es_congelados,
            "hoy": hoy.isoformat(), "error": None,
            "editar": False, "parte_id": None,
            "valores": {}, "sobrantes": {},
        })
    finally:
        db.close()


@router.post("/nuevo", response_class=HTMLResponse)
@requiere_permiso("stock.partes", editar=True)
async def parte_nuevo_post(request: Request):
    """Crea el parte de stock con sus líneas (partes_stock + lineas_parte_stock).
    Si ya existe parte para esa tienda y fecha, redirige al existente (uno por día)."""
    usuario = request.state.usuario
    form = await request.form()
    fecha_str = form.get("fecha", date.today().isoformat())
    try:
        fecha_dt = date.fromisoformat(fecha_str)
    except ValueError:
        fecha_dt = date.today()

    db = SessionLocal()
    try:
        tienda_id = usuario.tienda_id if usuario.rol == Rol.TIENDAS else int(form.get("tienda_id", 0) or 0)
        if not tienda_id:
            return RedirectResponse(url="/stock/nuevo", status_code=302)

        existente = db.query(ParteStock).filter(
            ParteStock.fecha == fecha_dt, ParteStock.tienda_id == tienda_id
        ).first()
        if existente:
            return RedirectResponse(url=f"/stock/{existente.id}", status_code=302)

        parte = ParteStock(fecha=fecha_dt, tienda_id=tienda_id, usuario_id=usuario.id)
        db.add(parte)
        db.flush()

        # Inputs por combinación: ent_<pid>_<sid> (enteras) + rac_... (porciones)
        # y sobrante_<pid> (sobrante por producto, sin sabor)
        for key, val in form.items():
            if key.startswith("ent_"):
                _, pid, sid = key.split("_")
                rac_key = f"rac_{pid}_{sid}"
                enteras = int(val) if val else 0
                raciones = int(form.get(rac_key, 0) or 0)
                db.add(LineaParteStock(
                    parte_stock_id=parte.id,
                    producto_id=int(pid), sabor_id=int(sid),
                    cantidad=enteras, raciones=raciones,
                ))
            elif key.startswith("sobrante_"):
                cantidad = int(val) if val else 0
                if cantidad > 0:
                    db.add(SobranteParte(
                        parte_stock_id=parte.id,
                        producto_id=int(key.split("_")[1]),
                        cantidad=cantidad,
                    ))

        try:
            db.commit()
        except IntegrityError:
            # Carrera (doble click): otro parte de la misma tienda y fecha se
            # coló entre la comprobación y el commit → redirigir al existente
            db.rollback()
            existente = db.query(ParteStock).filter(
                ParteStock.fecha == fecha_dt, ParteStock.tienda_id == tienda_id
            ).first()
            return RedirectResponse(
                url=f"/stock/{existente.id}" if existente else "/stock/", status_code=302
            )
        parte_id = parte.id
    finally:
        db.close()

    return RedirectResponse(url=f"/stock/{parte_id}", status_code=302)


@router.get("/{parte_id}/editar", response_class=HTMLResponse)
@requiere_permiso("stock.partes", editar=True)
async def parte_editar_get(request: Request, parte_id: int):
    """Formulario de edición de un parte abierto (los cerrados no se editan)."""
    usuario = request.state.usuario
    db = SessionLocal()
    try:
        parte = db.query(ParteStock).filter(ParteStock.id == parte_id).first()
        if not parte:
            return RedirectResponse(url="/stock/", status_code=302)
        if usuario.rol == Rol.TIENDAS and parte.tienda_id != usuario.tienda_id:
            return RedirectResponse(url="/stock/", status_code=302)
        if parte.cerrado:
            # Un parte cerrado no se edita
            return RedirectResponse(url=f"/stock/{parte_id}", status_code=302)

        # Valores ya guardados, para precargar el formulario
        valores = {
            f"{l.producto_id}_{l.sabor_id}": [l.cantidad, l.raciones]
            for l in parte.lineas
        }
        extra_keys = {(l.producto_id, l.sabor_id) for l in parte.lineas}
        catalogo = _build_catalogo_parte(db, parte.tienda_id, extra_keys=extra_keys)
        sin_prevision = not catalogo

        tienda_obj = db.query(Tienda).filter(Tienda.id == parte.tienda_id).first()
        es_congelados = bool(tienda_obj and tienda_obj.es_congelados)
        nombre_sel = tienda_obj.nombre if tienda_obj else None

        tiendas = [{"id": t.id, "nombre": t.nombre}
                   for t in db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.nombre).all()]
        return templates.TemplateResponse("stock/parte_form.html", {
            "request": request, "usuario": usuario,
            "catalogo": catalogo, "tiendas": tiendas,
            "tienda_sel": parte.tienda_id, "nombre_sel": nombre_sel,
            "sin_prevision": sin_prevision,
            "es_congelados": es_congelados,
            "hoy": parte.fecha.isoformat(), "error": None,
            "editar": True, "parte_id": parte.id,
            "valores": valores,
            "sobrantes": {s.producto_id: s.cantidad for s in parte.sobrantes},
        })
    finally:
        db.close()


@router.post("/{parte_id}/editar", response_class=HTMLResponse)
@requiere_permiso("stock.partes", editar=True)
async def parte_editar_post(request: Request, parte_id: int):
    """Guarda la edición de un parte: reemplaza todas las líneas y los sobrantes."""
    usuario = request.state.usuario
    form = await request.form()
    db = SessionLocal()
    try:
        parte = db.query(ParteStock).filter(ParteStock.id == parte_id).first()
        if not parte:
            return RedirectResponse(url="/stock/", status_code=302)
        if usuario.rol == Rol.TIENDAS and parte.tienda_id != usuario.tienda_id:
            return RedirectResponse(url="/stock/", status_code=302)
        if parte.cerrado:
            return RedirectResponse(url=f"/stock/{parte_id}", status_code=302)

        # Reemplazar líneas y sobrantes
        db.query(LineaParteStock).filter(
            LineaParteStock.parte_stock_id == parte.id).delete()
        db.query(SobranteParte).filter(
            SobranteParte.parte_stock_id == parte.id).delete()
        for key, val in form.items():
            if key.startswith("ent_"):
                _, pid, sid = key.split("_")
                rac_key = f"rac_{pid}_{sid}"
                enteras = int(val) if val else 0
                raciones = int(form.get(rac_key, 0) or 0)
                db.add(LineaParteStock(
                    parte_stock_id=parte.id,
                    producto_id=int(pid), sabor_id=int(sid),
                    cantidad=enteras, raciones=raciones,
                ))
            elif key.startswith("sobrante_"):
                cantidad = int(val) if val else 0
                if cantidad > 0:
                    db.add(SobranteParte(
                        parte_stock_id=parte.id,
                        producto_id=int(key.split("_")[1]),
                        cantidad=cantidad,
                    ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/stock/{parte_id}", status_code=302)


@router.post("/{parte_id}/cerrar", response_class=HTMLResponse)
@requiere_permiso("stock.partes", editar=True)
async def cerrar_parte(request: Request, parte_id: int):
    """Marca el parte como cerrado (deja de ser editable)."""
    usuario = request.state.usuario
    db = SessionLocal()
    try:
        parte = db.query(ParteStock).filter(ParteStock.id == parte_id).first()
        if parte:
            if usuario.rol != Rol.TIENDAS or parte.tienda_id == usuario.tienda_id:
                parte.cerrado = True
                db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/stock/{parte_id}", status_code=302)


# ─── parte de congeladas (solo tiendas de congelados) ──────────────────────────

@router.get("/congelador/nuevo", response_class=HTMLResponse)
@requiere_permiso("stock.partes", editar=True)
async def congelador_get(request: Request, tienda_id: int = 0, fecha: str = ""):
    """Parte del congelador de una tienda de congelados: cuenta la reserva congelada
    por producto/sabor. Página única de upsert (se rellena y se guarda). Muestra la
    reposición que saldría para el reparto de dentro de DIAS_ANTICIPO_CONGELADO días."""
    usuario = request.state.usuario
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today()
    except ValueError:
        fecha_dt = date.today()

    db = SessionLocal()
    try:
        tienda_sel = usuario.tienda_id if usuario.rol == Rol.TIENDAS else (tienda_id or None)
        tienda_obj = db.query(Tienda).filter(Tienda.id == tienda_sel).first() if tienda_sel else None

        # Roster: mismas combinaciones que la previsión (objetivo de vitrina) de la tienda
        catalogo = _build_catalogo_parte(db, tienda_sel) if tienda_sel else None
        sin_prevision = catalogo is not None and not catalogo

        valores: dict = {}
        parte = None
        if tienda_sel:
            parte = (
                db.query(ParteCongelador)
                .filter(ParteCongelador.tienda_id == tienda_sel, ParteCongelador.fecha == fecha_dt)
                .first()
            )
            if parte:
                valores = {f"{l.producto_id}_{l.sabor_id}": l.cantidad for l in parte.lineas}

        # Previsualización de la reposición (para el reparto de dentro de 2 días)
        reposicion = []
        if tienda_obj:
            productos = {p.id: p.nombre for p in db.query(Producto).all()}
            sabores = {s.id: s.nombre for s in db.query(Sabor).all()}
            fecha_reparto = fecha_dt + timedelta(days=DIAS_ANTICIPO_CONGELADO)
            rep_map = reposicion_congelado(db, tienda_obj, fecha_reparto)
            reposicion = sorted(
                ({"producto": productos.get(pid, "—"), "sabor": sabores.get(sid, "—"), "cantidad": cant}
                 for (pid, sid), cant in rep_map.items()),
                key=lambda x: (x["producto"], x["sabor"]),
            )

        tiendas = [{"id": t.id, "nombre": t.nombre}
                   for t in db.query(Tienda).filter(Tienda.activa == True, Tienda.es_congelados == True).order_by(Tienda.nombre).all()]
        nombre_sel = tienda_obj.nombre if tienda_obj else None
        return templates.TemplateResponse("stock/congelador_form.html", {
            "request": request, "usuario": usuario,
            "catalogo": catalogo, "tiendas": tiendas,
            "tienda_sel": tienda_sel, "nombre_sel": nombre_sel,
            "sin_prevision": sin_prevision,
            "fecha": fecha_dt.isoformat(),
            "fecha_reparto": (fecha_dt + timedelta(days=DIAS_ANTICIPO_CONGELADO)),
            "valores": valores, "reposicion": reposicion,
            "guardado": request.query_params.get("guardado") == "1",
        })
    finally:
        db.close()


@router.post("/congelador/nuevo", response_class=HTMLResponse)
@requiere_permiso("stock.partes", editar=True)
async def congelador_post(request: Request):
    """Upsert del parte del congelador de (tienda, fecha): reemplaza sus líneas."""
    usuario = request.state.usuario
    form = await request.form()
    try:
        fecha_dt = date.fromisoformat(form.get("fecha", "")) if form.get("fecha") else date.today()
    except ValueError:
        fecha_dt = date.today()

    db = SessionLocal()
    try:
        tienda_id = usuario.tienda_id if usuario.rol == Rol.TIENDAS else int(form.get("tienda_id", 0) or 0)
        if not tienda_id:
            return RedirectResponse(url="/stock/congelador/nuevo", status_code=302)

        parte = (
            db.query(ParteCongelador)
            .filter(ParteCongelador.tienda_id == tienda_id, ParteCongelador.fecha == fecha_dt)
            .first()
        )
        if not parte:
            parte = ParteCongelador(fecha=fecha_dt, tienda_id=tienda_id, usuario_id=usuario.id)
            db.add(parte)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                parte = (
                    db.query(ParteCongelador)
                    .filter(ParteCongelador.tienda_id == tienda_id, ParteCongelador.fecha == fecha_dt)
                    .first()
                )

        db.query(LineaParteCongelador).filter(
            LineaParteCongelador.parte_congelador_id == parte.id).delete()
        for key, val in form.items():
            if not key.startswith("ent_"):
                continue
            _, pid, sid = key.split("_")
            cantidad = max(0, int(val) if val else 0)
            if cantidad > 0:
                db.add(LineaParteCongelador(
                    parte_congelador_id=parte.id,
                    producto_id=int(pid), sabor_id=int(sid), cantidad=cantidad,
                ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(
        url=f"/stock/congelador/nuevo?tienda_id={tienda_id}&fecha={fecha_dt.isoformat()}&guardado=1",
        status_code=302,
    )


# ─── inventario congelado del obrador ──────────────────────────────────────────

@router.get("/congelado-obrador", response_class=HTMLResponse)
@requiere_permiso("produccion")
async def congelado_obrador_get(request: Request):
    """Inventario de tartas congeladas que hay en el obrador. El roster sale de las
    previsiones de las tiendas de congelados (solo lo que se congela)."""
    db = SessionLocal()
    try:
        secciones = _roster_congelado_obrador(db)
        valores = {
            f"{s.producto_id}_{s.sabor_id}": s.cantidad
            for s in db.query(StockCongeladoObrador).all()
        }
        total = sum(valores.values())
        return templates.TemplateResponse("stock/congelado_obrador.html", {
            "request": request, "usuario": request.state.usuario,
            "secciones": secciones, "valores": valores, "total": total,
            "puede_editar": request.state.usuario.puede_editar("produccion"),
            "guardado": request.query_params.get("guardado") == "1",
        })
    finally:
        db.close()


@router.post("/congelado-obrador", response_class=HTMLResponse)
@requiere_permiso("produccion", editar=True)
async def congelado_obrador_post(request: Request):
    """Guarda el inventario congelado del obrador: reemplaza las existencias con
    los campos ent_<prod>_<sabor> del formulario (solo cantidades > 0)."""
    form = await request.form()
    db = SessionLocal()
    try:
        db.query(StockCongeladoObrador).delete()
        for key, val in form.items():
            if not key.startswith("ent_"):
                continue
            try:
                _, pid, sid = key.split("_")
                cantidad = max(0, int(val) if val else 0)
            except (ValueError, AttributeError):
                continue
            if cantidad == 0:
                continue
            db.add(StockCongeladoObrador(
                producto_id=int(pid), sabor_id=int(sid), cantidad=cantidad))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/stock/congelado-obrador?guardado=1", status_code=302)


@router.get("/{parte_id}", response_class=HTMLResponse)
@requiere_permiso("stock.partes")
async def parte_detalle(request: Request, parte_id: int):
    """Detalle de un parte: líneas agrupadas por producto, sobrantes y totales equivalentes."""
    usuario = request.state.usuario
    db = SessionLocal()
    try:
        parte = db.query(ParteStock).filter(ParteStock.id == parte_id).first()
        if not parte:
            return RedirectResponse(url="/stock/", status_code=302)
        if usuario.rol == Rol.TIENDAS and parte.tienda_id != usuario.tienda_id:
            return RedirectResponse(url="/stock/", status_code=302)

        productos_q = db.query(Producto).order_by(Producto.orden, Producto.nombre).all()
        productos = {p.id: p.nombre for p in productos_q}
        sabores = {s.id: s.nombre for s in db.query(Sabor).all()}
        tienda = db.query(Tienda).filter(Tienda.id == parte.tienda_id).first()

        # Una sección por producto (en orden de catálogo, con su color)
        por_pid: dict = {}
        for l in parte.lineas:
            if l.cantidad > 0 or l.raciones > 0:
                por_pid.setdefault(l.producto_id, []).append({
                    "sabor": sabores.get(l.sabor_id, "—"),
                    "enteras": l.cantidad,
                    "raciones": l.raciones,
                })
        secciones = [
            {
                "nombre": p.nombre,
                "color": _color_seccion(p.nombre, p.id),
                "permite_porciones": p.permite_porciones,
                "lineas": por_pid[p.id],
            }
            for p in productos_q if p.id in por_pid
        ]

        sobrantes = _sobrantes_de_parte(parte, productos)
        total_sobrante = sum(sobrantes.values())
        # Total en tartas enteras equivalentes (6 porciones = 1 tarta)
        total_ent = sum(_tartas_equiv(l.cantidad, l.raciones) for l in parte.lineas) + total_sobrante
        total_rac = sum(l.raciones for l in parte.lineas)

        # Congelados: en el parte de VITRINA se muestra la descongelación de esta
        # noche (objetivo de mañana − vitrina), para que la tienda sepa qué sacar
        # del congelador. El recuento del congelador va en su parte aparte.
        es_congelados = bool(tienda and tienda.es_congelados)
        descongelacion = []
        if es_congelados:
            desc_map = descongelacion_congelado(db, tienda, parte.fecha)
            descongelacion = sorted(
                ({"producto": productos.get(pid, "—"), "sabor": sabores.get(sid, "—"),
                  "cantidad": cant} for (pid, sid), cant in desc_map.items()),
                key=lambda x: (x["producto"], x["sabor"]),
            )

        parte_dict = {
            "id": parte.id, "fecha": parte.fecha,
            "tienda": tienda.nombre if tienda else "—",
            "cerrado": parte.cerrado,
            "total_ent": total_ent, "total_rac": total_rac,
            "sobrantes": sobrantes, "total_sobrante": total_sobrante,
        }
        return templates.TemplateResponse("stock/parte_detalle.html", {
            "request": request, "usuario": usuario,
            "parte": parte_dict, "secciones": secciones,
            "es_congelados": es_congelados,
            "descongelacion": descongelacion,
        })
    finally:
        db.close()
