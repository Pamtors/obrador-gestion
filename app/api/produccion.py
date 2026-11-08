"""Lista de horneado del obrador: propone qué hornear cada día (pedidos + reposición
de tiendas) y guarda la producción confirmada por las pasteleras (tabla produccion_dia).
Accesible para JEFES y PASTELERAS."""
from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete
from sqlalchemy.orm import joinedload

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.pedido import Pedido
from app.models.produccion import ProduccionDia
from app.models.producto import Producto
from app.models.stock import DiasReparto, ParteStock
from app.models.sabor import Sabor
from app.models.tienda import Tienda
from app.api.stock import DIAS_ANTICIPO_CONGELADO, _calc_necesidades, reposicion_congelado
from app.plantillas import templates

router = APIRouter(prefix="/horneado")

# A partir de cuántas unidades sobrantes en tienda se avisa a las pasteleras
UMBRAL_SOBRANTE = 5


@router.get("/", response_class=HTMLResponse)
@requiere_permiso("produccion")
async def lista_horneado(request: Request, fecha: str = ""):
    """Lista de horneado del día: propuesta = líneas de pedidos con fecha_horneado
    en la fecha + necesidades de reposición de tiendas (calculadas desde stock),
    comparada con la producción ya confirmada en produccion_dia."""
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today()
    except ValueError:
        fecha_dt = date.today()

    db = SessionLocal()
    try:
        productos_map = {p.id: p for p in db.query(Producto).all()}
        sabores_map = {s.id: s for s in db.query(Sabor).all()}

        # Pedidos confirmados para fecha_horneado
        pedidos = (
            db.query(Pedido)
            .options(joinedload(Pedido.lineas))
            .filter(Pedido.fecha_horneado == fecha_dt)
            .all()
        )

        # Reposición de tiendas
        necesidades_tiendas = _calc_necesidades(db, fecha_dt)
        reposicion: dict = {}
        for datos in necesidades_tiendas.values():
            for f in datos["filas"]:
                if f["necesidad"] <= 0:
                    continue
                key = (f["prod_id"], f["sabor_id"])
                reposicion[key] = reposicion.get(key, 0) + f["necesidad"]

        # Avisos de sobrante alto: un sobrante > 5 de un tipo de producto no se
        # descuenta solo (no se sabe el sabor), pero se avisa para que las
        # pasteleras ajusten la lista manualmente. Se mira el último parte de
        # cada tienda con reparto ese día (independiente de la reposición).
        tiendas_map = {t.id: t.nombre for t in db.query(Tienda).all()}
        dia = fecha_dt.weekday()
        reparto_ids = {
            dr.tienda_id
            for dr in db.query(DiasReparto).filter(DiasReparto.dia_semana == dia).all()
        }
        avisos_sobrante = []
        for tid in reparto_ids:
            ultimo = (
                db.query(ParteStock)
                .filter(ParteStock.tienda_id == tid, ParteStock.fecha <= fecha_dt)
                .order_by(ParteStock.fecha.desc(), ParteStock.id.desc())
                .first()
            )
            if not ultimo:
                continue
            for sob in ultimo.sobrantes:
                if sob.cantidad > UMBRAL_SOBRANTE:
                    prod = productos_map.get(sob.producto_id)
                    avisos_sobrante.append({
                        "tienda": tiendas_map.get(tid, "—"),
                        "tipo": prod.nombre if prod else "—",
                        "cantidad": sob.cantidad,
                    })

        # Pedidos agrupados por (prod, sabor): se separan de la reposición porque
        # son compromisos con cliente y SIEMPRE hay que hornearlos.
        pedidos_map: dict = {}
        for pedido in pedidos:
            for linea in pedido.lineas:
                key = (linea.producto_id, linea.sabor_id)
                pedidos_map[key] = pedidos_map.get(key, 0) + linea.cantidad

        # Propuesta total = pedidos + reposición
        propuesta: dict = {}
        for key, cant in pedidos_map.items():
            propuesta[key] = propuesta.get(key, 0) + cant
        for key, cant in reposicion.items():
            propuesta[key] = propuesta.get(key, 0) + cant

        # Producción ya confirmada por las pasteleras
        confirmada = {
            (p.producto_id, p.sabor_id): p.cantidad
            for p in db.query(ProduccionDia).filter(ProduccionDia.fecha == fecha_dt).all()
        }

        # Construir filas para el template agrupadas por producto expandido
        filas_por_producto: dict = {}
        for key, cant_prop in propuesta.items():
            pid, sid = key
            prod = productos_map.get(pid)
            if not prod:
                continue
            filas_por_producto.setdefault(prod.nombre, {"orden": prod.orden, "filas": []})
            filas_por_producto[prod.nombre]["filas"].append({
                "prod_id": pid,
                "sabor_id": sid,
                "prod_nombre": prod.nombre,
                "sabor_nombre": _nombre_base(sabores_map, sid),
                "sabor_real": sabores_map[sid].nombre if sid in sabores_map else "—",
                "pedidos": pedidos_map.get(key, 0),
                "reposicion": reposicion.get(key, 0),
                "propuesta": cant_prop,
                "confirmada": confirmada.get(key),
                "key": f"{pid}_{sid}",
            })

        for sec in filas_por_producto.values():
            sec["filas"].sort(key=lambda r: r["sabor_nombre"])

        filas_por_producto = dict(sorted(filas_por_producto.items(), key=lambda x: x[1]["orden"]))

        total_propuesto = sum(cant for cant in propuesta.values())
        total_pedidos = sum(pedidos_map.values())
        total_reposicion = sum(reposicion.values())
        total_confirmado = sum(v for v in confirmada.values())
        hay_confirmacion = bool(confirmada)

        hoy_iso = date.today().isoformat()
        manana_iso = (date.today() + timedelta(days=1)).isoformat()
        return templates.TemplateResponse("produccion/horneado.html", {
            "request": request,
            "usuario": request.state.usuario,
            "fecha": fecha_dt,
            "filas_por_producto": filas_por_producto,
            "total_propuesto": total_propuesto,
            "total_pedidos": total_pedidos,
            "total_reposicion": total_reposicion,
            "total_confirmado": total_confirmado,
            "hay_confirmacion": hay_confirmacion,
            "avisos_sobrante": avisos_sobrante,
            "hoy_iso": hoy_iso,
            "manana_iso": manana_iso,
        })
    finally:
        db.close()


@router.post("/", response_class=HTMLResponse)
@requiere_permiso("produccion", editar=True)
async def guardar_horneado(request: Request, fecha: str = ""):
    """Guarda las cantidades confirmadas: reemplaza todo produccion_dia de esa fecha
    con los campos cant_<producto>_<sabor> del formulario."""
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today()
    except ValueError:
        fecha_dt = date.today()

    form = await request.form()
    db = SessionLocal()
    try:
        # Borrar confirmaciones previas del día y reinsertar
        db.execute(delete(ProduccionDia).where(ProduccionDia.fecha == fecha_dt))
        for key, val in form.items():
            if not key.startswith("cant_"):
                continue
            try:
                _, pid, sid = key.split("_")
                cantidad = max(0, int(val) if val else 0)
            except (ValueError, AttributeError):
                continue
            db.add(ProduccionDia(
                fecha=fecha_dt,
                producto_id=int(pid),
                sabor_id=int(sid),
                cantidad=cantidad,
            ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/horneado/?fecha={fecha_dt.isoformat()}", status_code=302)


@router.get("/congeladas", response_class=HTMLResponse)
@requiere_permiso("produccion")
async def lista_congeladas(request: Request, fecha: str = ""):
    """Lista de horneado de tartas CONGELADAS (página aparte del horneado normal):
    reposición del congelador de las tiendas de congelados cuyo reparto cae
    DIAS_ANTICIPO_CONGELADO días después de la fecha vista. Solo informativa."""
    try:
        fecha_dt = date.fromisoformat(fecha) if fecha else date.today()
    except ValueError:
        fecha_dt = date.today()

    db = SessionLocal()
    try:
        productos_map = {p.id: p for p in db.query(Producto).all()}
        sabores_map = {s.id: s for s in db.query(Sabor).all()}

        fecha_reparto_cong = fecha_dt + timedelta(days=DIAS_ANTICIPO_CONGELADO)
        dia_reparto_cong = fecha_reparto_cong.weekday()
        tiendas_cong = db.query(Tienda).filter(
            Tienda.es_congelados == True, Tienda.activa == True).all()
        reparto_cong_ids = {
            dr.tienda_id
            for dr in db.query(DiasReparto).filter(DiasReparto.dia_semana == dia_reparto_cong).all()
        }
        congeladas: dict = {}
        for tienda in tiendas_cong:
            if tienda.id not in reparto_cong_ids:
                continue
            for key, cant in reposicion_congelado(db, tienda, fecha_reparto_cong).items():
                congeladas[key] = congeladas.get(key, 0) + cant

        congeladas_por_producto: dict = {}
        for (pid, sid), cant in congeladas.items():
            prod = productos_map.get(pid)
            if not prod:
                continue
            congeladas_por_producto.setdefault(prod.nombre, {"orden": prod.orden, "filas": []})
            congeladas_por_producto[prod.nombre]["filas"].append({
                "sabor_nombre": _nombre_base(sabores_map, sid),
                "sabor_real": sabores_map[sid].nombre if sid in sabores_map else "—",
                "cantidad": cant,
            })
        for sec in congeladas_por_producto.values():
            sec["filas"].sort(key=lambda r: r["sabor_nombre"])
        congeladas_por_producto = dict(sorted(congeladas_por_producto.items(), key=lambda x: x[1]["orden"]))
        total_congeladas = sum(congeladas.values())

        hoy_iso = date.today().isoformat()
        manana_iso = (date.today() + timedelta(days=1)).isoformat()
        ayer_iso = (fecha_dt - timedelta(days=1)).isoformat()
        siguiente_iso = (fecha_dt + timedelta(days=1)).isoformat()
        return templates.TemplateResponse("produccion/congeladas.html", {
            "request": request,
            "usuario": request.state.usuario,
            "fecha": fecha_dt,
            "fecha_reparto_cong": fecha_reparto_cong,
            "congeladas_por_producto": congeladas_por_producto,
            "total_congeladas": total_congeladas,
            "hoy_iso": hoy_iso, "manana_iso": manana_iso,
            "ayer_iso": ayer_iso, "siguiente_iso": siguiente_iso,
        })
    finally:
        db.close()


def _nombre_base(sabores_map: dict, sabor_id: int) -> str:
    """Devuelve el nombre de la base del sabor (para agrupar en horneado)."""
    sabor = sabores_map.get(sabor_id)
    if not sabor:
        return "—"
    if sabor.base_id and sabor.base_id in sabores_map:
        return sabores_map[sabor.base_id].nombre
    return sabor.nombre
