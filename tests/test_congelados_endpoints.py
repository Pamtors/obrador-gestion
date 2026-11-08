"""Tests de endpoint para tiendas de congelados: que las páginas de previsión,
parte (con descongelación), horneado (lista de congeladas) y envíos (reposición
del congelador) renderizan con datos reales sin romperse."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models.produccion import ProduccionDia  # noqa: F401 (asegura metadata)
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.catalogo import SaborProducto
from app.models.stock import (
    DiasReparto, LineaParteStock, ParteStock, PrevisionStock,
)
from app.models.tienda import Tienda
from app.models.usuario import Rol


def _setup(nombre, reparto_weekday):
    """Crea tienda congelados con 1 producto/sabor en producción, día de reparto,
    objetivo de vitrina y devuelve (tienda_id, producto_id, sabor_id)."""
    db = SessionLocal()
    try:
        p = db.query(Producto).filter(Producto.nombre == f"CE Prod {nombre}").first()
        if not p:
            p = Producto(nombre=f"CE Prod {nombre}"); db.add(p); db.commit()
        s = db.query(Sabor).filter(Sabor.nombre == f"CE Sabor {nombre}").first()
        if not s:
            s = Sabor(nombre=f"CE Sabor {nombre}"); db.add(s); db.commit()
        if not db.query(SaborProducto).filter(
                SaborProducto.producto_id == p.id, SaborProducto.sabor_id == s.id).first():
            db.add(SaborProducto(producto_id=p.id, sabor_id=s.id,
                                 produccion=True, out=False)); db.commit()
        t = db.query(Tienda).filter(Tienda.nombre == nombre).first()
        if not t:
            t = Tienda(nombre=nombre, es_congelados=True); db.add(t); db.commit()
        if not db.query(DiasReparto).filter(
                DiasReparto.tienda_id == t.id, DiasReparto.dia_semana == reparto_weekday).first():
            db.add(DiasReparto(tienda_id=t.id, dia_semana=reparto_weekday))
        if not db.query(PrevisionStock).filter(
                PrevisionStock.tienda_id == t.id, PrevisionStock.dia_semana == reparto_weekday,
                PrevisionStock.producto_id == p.id, PrevisionStock.sabor_id == s.id).first():
            db.add(PrevisionStock(tienda_id=t.id, dia_semana=reparto_weekday,
                                  producto_id=p.id, sabor_id=s.id, cantidad=7))
        db.commit()
        return t.id, p.id, s.id
    finally:
        db.close()


def test_prevision_congelados_siete_dias(como):
    tid, _, _ = _setup("CE Tienda Prev", 2)  # miércoles
    r = como(Rol.JEFES).get(f"/stock/prevision/{tid}")
    assert r.status_code == 200
    assert "vitrina" in r.text.lower()


def test_congeladas_pagina_propia(como):
    # reparto miércoles; la página de congeladas se mira 2 días antes (lunes)
    tid, pid, sid = _setup("CE Tienda Horn", 2)
    hoy = date.today()
    lunes = hoy + timedelta(days=(7 - hoy.weekday()) % 7)  # próximo lunes (o hoy si lunes)
    r = como(Rol.JEFES).get(f"/horneado/congeladas?fecha={lunes.isoformat()}")
    assert r.status_code == 200
    assert "Tartas congeladas" in r.text


def test_horneado_normal_no_muestra_congeladas(como):
    # el horneado normal ya NO lleva la lista de congeladas (está en su página)
    r = como(Rol.JEFES).get("/horneado/")
    assert r.status_code == 200
    assert "Tartas congeladas" not in r.text


def test_parte_congelador_upsert(como):
    tid, pid, sid = _setup("CE Tienda Cong", 2)
    cli = como(Rol.JEFES)
    # GET del formulario
    r = cli.get(f"/stock/congelador/nuevo?tienda_id={tid}")
    assert r.status_code == 200
    assert "Parte de congeladas" in r.text
    # POST guarda el conteo
    hoy = date.today().isoformat()
    r2 = cli.post("/stock/congelador/nuevo",
                  data={"tienda_id": str(tid), "fecha": hoy, f"ent_{pid}_{sid}": "12"})
    assert r2.status_code == 302
    from app.database import SessionLocal
    from app.models.stock import ParteCongelador
    s = SessionLocal()
    try:
        parte = s.query(ParteCongelador).filter(
            ParteCongelador.tienda_id == tid, ParteCongelador.fecha == date.today()).first()
        assert parte is not None
        assert parte.lineas[0].cantidad == 12
    finally:
        s.close()


def test_envios_reposicion_congelador(como):
    tid, pid, sid = _setup("CE Tienda Env", 2)
    hoy = date.today()
    # próximo miércoles (día de reparto de la tienda)
    miercoles = hoy + timedelta(days=(2 - hoy.weekday()) % 7)
    r = como(Rol.JEFES).get(f"/stock/envios/?fecha={miercoles.isoformat()}")
    assert r.status_code == 200
    assert "Reposición congelador" in r.text


def test_congelado_obrador_roster_y_guardado(como):
    # el roster sale de la previsión de la tienda de congelados
    tid, pid, sid = _setup("CE Tienda Obr", 2)
    cli = como(Rol.JEFES)
    r = cli.get("/stock/congelado-obrador")
    assert r.status_code == 200
    assert "Congelado en obrador" in r.text
    # guardar existencias
    r2 = cli.post("/stock/congelado-obrador", data={f"ent_{pid}_{sid}": "20"})
    assert r2.status_code == 302
    from app.database import SessionLocal
    from app.models.stock import StockCongeladoObrador
    s = SessionLocal()
    try:
        row = s.query(StockCongeladoObrador).filter(
            StockCongeladoObrador.producto_id == pid, StockCongeladoObrador.sabor_id == sid).first()
        assert row is not None and row.cantidad == 20
    finally:
        s.close()


def test_congelado_obrador_bloqueado_para_tiendas(como, tienda):
    # una tienda no gestiona el inventario del obrador (permiso produccion)
    r = como(Rol.TIENDAS, tienda_id=tienda.id).get("/stock/congelado-obrador")
    assert r.status_code == 403


def test_parte_detalle_muestra_descongelacion(como, db):
    tid, pid, sid = _setup("CE Tienda Parte", 2)
    # parte con algo en vitrina; objetivo del día siguiente dispara descongelación
    manana = date.today() + timedelta(days=1)
    noche = date.today()
    # objetivo de vitrina para mañana
    if not db.query(PrevisionStock).filter(
            PrevisionStock.tienda_id == tid, PrevisionStock.dia_semana == manana.weekday(),
            PrevisionStock.producto_id == pid, PrevisionStock.sabor_id == sid).first():
        db.add(PrevisionStock(tienda_id=tid, dia_semana=manana.weekday(),
                              producto_id=pid, sabor_id=sid, cantidad=6))
        db.commit()
    from app.models.usuario import Usuario
    uid = db.query(Usuario).filter(Usuario.rol == Rol.JEFES).first()
    if uid is None:
        como(Rol.JEFES)  # fuerza creación
        uid = db.query(Usuario).filter(Usuario.rol == Rol.JEFES).first()
    parte = ParteStock(fecha=noche, tienda_id=tid, usuario_id=uid.id)
    db.add(parte); db.commit()
    db.add(LineaParteStock(parte_stock_id=parte.id, producto_id=pid, sabor_id=sid,
                           cantidad=2, raciones=0))
    db.commit()

    r = como(Rol.JEFES).get(f"/stock/{parte.id}")
    assert r.status_code == 200
    assert "Descongelar" in r.text
