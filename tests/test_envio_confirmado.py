"""Tests del envío confirmado (ENVIO_CONFIRMADO_PLAN.md): envio_confirmado_map,
guard de rol y POST /stock/envios/{tienda_id}/confirmar."""
from datetime import date, timedelta

from app.api.stock import envio_confirmado_map
from app.database import SessionLocal
from app.models.envio import EnvioTienda, LineaEnvioTienda
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.usuario import Rol


def _crear_producto_sabor(sufijo):
    s = SessionLocal()
    try:
        p = s.query(Producto).filter(Producto.nombre == f"Test Prod EnvioConf {sufijo}").first()
        if not p:
            p = Producto(nombre=f"Test Prod EnvioConf {sufijo}")
            s.add(p)
            s.commit()
        sab = s.query(Sabor).filter(Sabor.nombre == f"Test Sabor EnvioConf {sufijo}").first()
        if not sab:
            sab = Sabor(nombre=f"Test Sabor EnvioConf {sufijo}")
            s.add(sab)
            s.commit()
        return p.id, sab.id
    finally:
        s.close()


def test_envio_confirmado_map_none_sin_confirmacion(db, tienda):
    fecha = date.today() + timedelta(days=40)
    assert envio_confirmado_map(db, tienda.id, fecha) is None


def test_envio_confirmado_map_devuelve_lineas_confirmadas(db, tienda):
    producto_id, sabor_id = _crear_producto_sabor("A")
    fecha = date.today() + timedelta(days=41)

    envio = EnvioTienda(tienda_id=tienda.id, fecha=fecha, confirmado=True)
    db.add(envio)
    db.commit()
    db.add(LineaEnvioTienda(envio_tienda_id=envio.id, producto_id=producto_id,
                             sabor_id=sabor_id, cantidad=7))
    db.commit()

    resultado = envio_confirmado_map(db, tienda.id, fecha)
    assert resultado == {(producto_id, sabor_id): 7}


def test_confirmar_guarda_lineas_y_marca_confirmado(como, tienda):
    producto_id, sabor_id = _crear_producto_sabor("B")
    fecha = date.today() + timedelta(days=42)
    c = como(Rol.PASTELERAS)

    r = c.post(f"/stock/envios/{tienda.id}/confirmar", data={
        "fecha": fecha.isoformat(),
        f"cant_{producto_id}_{sabor_id}": "5",
    })
    assert r.status_code == 302

    db = SessionLocal()
    try:
        envio = db.query(EnvioTienda).filter(
            EnvioTienda.tienda_id == tienda.id, EnvioTienda.fecha == fecha).first()
        assert envio is not None
        assert envio.confirmado is True
        assert envio.confirmado_en is not None
        assert envio.confirmado_por is not None
        lineas = {(l.producto_id, l.sabor_id): l.cantidad for l in envio.lineas}
        assert lineas == {(producto_id, sabor_id): 5}
    finally:
        db.close()


def test_reconfirmar_reemplaza_lineas(como, tienda):
    producto_id, sabor_id = _crear_producto_sabor("C")
    fecha = date.today() + timedelta(days=43)
    c = como(Rol.JEFES)

    c.post(f"/stock/envios/{tienda.id}/confirmar", data={
        "fecha": fecha.isoformat(),
        f"cant_{producto_id}_{sabor_id}": "3",
    })
    c.post(f"/stock/envios/{tienda.id}/confirmar", data={
        "fecha": fecha.isoformat(),
        f"cant_{producto_id}_{sabor_id}": "9",
    })

    db = SessionLocal()
    try:
        envio = db.query(EnvioTienda).filter(
            EnvioTienda.tienda_id == tienda.id, EnvioTienda.fecha == fecha).first()
        assert len(envio.lineas) == 1
        assert envio.lineas[0].cantidad == 9
    finally:
        db.close()


def test_confirmar_bloqueado_para_tiendas_y_repartidores(como, tienda):
    fecha = date.today() + timedelta(days=44)
    for rol in (Rol.TIENDAS, Rol.REPARTIDORES):
        c = como(rol, tienda_id=tienda.id if rol == Rol.TIENDAS else None)
        r = c.post(f"/stock/envios/{tienda.id}/confirmar", data={"fecha": fecha.isoformat()})
        assert r.status_code == 403


def test_ficha_confirmada_congela_valores_aunque_cambie_la_prevision(como, tienda):
    """Una vez confirmado, la ficha muestra lo congelado aunque prevision_stock cambie después."""
    from app.models.stock import DiasReparto, PrevisionStock

    producto_id, sabor_id = _crear_producto_sabor("D")
    fecha = date.today() + timedelta(days=1)
    dia = fecha.weekday()

    db = SessionLocal()
    try:
        if not db.query(DiasReparto).filter(
                DiasReparto.tienda_id == tienda.id, DiasReparto.dia_semana == dia).first():
            db.add(DiasReparto(tienda_id=tienda.id, dia_semana=dia))
        db.add(PrevisionStock(tienda_id=tienda.id, dia_semana=dia,
                               producto_id=producto_id, sabor_id=sabor_id, cantidad=10))
        db.commit()
    finally:
        db.close()

    c = como(Rol.PASTELERAS)
    c.post(f"/stock/envios/{tienda.id}/confirmar", data={
        "fecha": fecha.isoformat(),
        f"cant_{producto_id}_{sabor_id}": "6",
    })

    # Cambia la previsión después de confirmar: no debe afectar a la ficha ya confirmada
    db = SessionLocal()
    try:
        db.query(PrevisionStock).filter(
            PrevisionStock.tienda_id == tienda.id, PrevisionStock.dia_semana == dia,
            PrevisionStock.producto_id == producto_id, PrevisionStock.sabor_id == sabor_id,
        ).update({"cantidad": 99})
        db.commit()
    finally:
        db.close()

    r = c.get(f"/stock/envios/?fecha={fecha.isoformat()}")
    assert r.status_code == 200
    assert "✓ Envío confirmado" in r.text
    assert 'value="6"' in r.text


def test_tiendas_no_ve_botones_editar_en_ficha(como, tienda):
    from app.models.stock import DiasReparto

    fecha = date.today() + timedelta(days=1)
    dia = fecha.weekday()
    db = SessionLocal()
    try:
        if not db.query(DiasReparto).filter(
                DiasReparto.tienda_id == tienda.id, DiasReparto.dia_semana == dia).first():
            db.add(DiasReparto(tienda_id=tienda.id, dia_semana=dia))
            db.commit()
    finally:
        db.close()

    c = como(Rol.TIENDAS, tienda_id=tienda.id)
    r = c.get(f"/stock/envios/?fecha={fecha.isoformat()}")
    assert r.status_code == 200
    assert "Confirmar envío" not in r.text
    assert f"toggleEditar({tienda.id})" not in r.text
