from datetime import date, timedelta

from app.models.usuario import Rol


def test_dias_reparto_ver_pero_no_tocar(como):
    for rol in (Rol.PASTELERAS, Rol.TIENDAS):
        c = como(rol)
        assert c.get("/stock/reparto/").status_code == 200
        assert c.post("/stock/reparto/toggle", data={"tienda_id": 1, "dia": 1}).status_code == 403


def test_prevision_oculta_para_tiendas_y_pasteleras(como):
    assert como(Rol.TIENDAS).get("/stock/prevision/").status_code == 403
    assert como(Rol.PASTELERAS).get("/stock/necesidades/").status_code == 403
    assert como(Rol.AREA_MANAGER).get("/stock/prevision/").status_code == 200


def test_mermas_tiendas_si_pasteleras_no(como):
    assert como(Rol.TIENDAS).get("/stock/mermas/").status_code == 200
    assert como(Rol.PASTELERAS).get("/stock/mermas/").status_code == 403


def test_repartidores_envios_si_partes_no(como):
    c = como(Rol.REPARTIDORES)
    assert c.get("/stock/envios/").status_code == 200
    assert c.get("/stock/").status_code == 403


def _crear_producto_sabor():
    """Get-or-create por nombre de un producto y un sabor de test; devuelve sus ids."""
    from app.database import SessionLocal
    from app.models.producto import Producto
    from app.models.sabor import Sabor

    s = SessionLocal()
    try:
        p = s.query(Producto).filter(Producto.nombre == "Test Producto Merma").first()
        if not p:
            p = Producto(nombre="Test Producto Merma")
            s.add(p)
            s.commit()
        sab = s.query(Sabor).filter(Sabor.nombre == "Test Sabor Merma").first()
        if not sab:
            sab = Sabor(nombre="Test Sabor Merma")
            s.add(sab)
            s.commit()
        return p.id, sab.id
    finally:
        s.close()


def test_merma_de_tienda_se_guarda_con_su_tienda(como, tienda, tienda2):
    """Aunque el form traiga otra tienda_id, se guarda con la del usuario."""
    producto_id, sabor_id = _crear_producto_sabor()
    c = como(Rol.TIENDAS, tienda_id=tienda.id)
    r = c.post("/stock/mermas/nuevo", data={
        "fecha": "2026-07-14", "tienda_id": tienda2.id, "producto_id": producto_id,
        "sabor_id": sabor_id, "cantidad": 2, "motivo": "CADUCIDAD", "comentario": "",
    })
    assert r.status_code == 302
    from app.database import SessionLocal
    from app.models.stock import Merma
    s = SessionLocal()
    try:
        m = s.query(Merma).order_by(Merma.id.desc()).first()
        assert m.tienda_id == tienda.id
    finally:
        s.close()


def test_envios_tienda_solo_ve_su_ficha(como, tienda, tienda2):
    """TIENDAS solo ve la ficha de envío de su tienda aunque otras tengan reparto ese día."""
    from app.database import SessionLocal
    from app.models.stock import DiasReparto

    # La vista de envíos por defecto prepara el envío de mañana
    dia = (date.today() + timedelta(days=1)).weekday()
    s = SessionLocal()
    try:
        for tid in (tienda.id, tienda2.id):
            existe = s.query(DiasReparto).filter(
                DiasReparto.tienda_id == tid, DiasReparto.dia_semana == dia).first()
            if not existe:
                s.add(DiasReparto(tienda_id=tid, dia_semana=dia))
        s.commit()
    finally:
        s.close()

    c = como(Rol.TIENDAS, tienda_id=tienda.id)
    r = c.get("/stock/envios/")
    assert r.status_code == 200
    assert tienda.nombre in r.text
    assert tienda2.nombre not in r.text


def test_tienda_no_accede_a_parte_ajeno(como, tienda, tienda2):
    """Un usuario TIENDAS no puede ver ni editar el parte de stock de otra tienda."""
    from app.database import SessionLocal
    from app.models.stock import ParteStock
    from app.models.usuario import Usuario

    c = como(Rol.TIENDAS, tienda_id=tienda.id)  # crea también el usuario en BD
    s = SessionLocal()
    try:
        usuario_id = s.query(Usuario).first().id
        parte = s.query(ParteStock).filter(
            ParteStock.tienda_id == tienda2.id, ParteStock.fecha == date(2026, 7, 1)).first()
        if not parte:
            parte = ParteStock(fecha=date(2026, 7, 1), tienda_id=tienda2.id, usuario_id=usuario_id)
            s.add(parte)
            s.commit()
            s.refresh(parte)
        parte_id = parte.id
    finally:
        s.close()

    for url in (f"/stock/{parte_id}", f"/stock/{parte_id}/editar"):
        r = c.get(url)
        assert r.status_code in (302, 403, 404)
        if r.status_code == 302:
            assert r.headers["location"] == "/stock/"
