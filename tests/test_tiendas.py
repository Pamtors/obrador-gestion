from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.cliente_b2b import ClienteB2B, TipoCliente
from app.models.tienda import Tienda
from app.models.usuario import Rol


def test_toggle_franquicia_asigna_codigo_default(como, db):
    t = Tienda(nombre="Fuengirola Test")
    db.add(t)
    db.commit()
    db.refresh(t)

    r = como(Rol.JEFES).post(f"/tiendas/{t.id}/toggle-franquicia")
    assert r.status_code == 302

    db.refresh(t)
    assert t.es_franquicia is True
    assert t.codigo_albaran == "F"


def test_toggle_franquicia_evita_colision_de_codigo(como, db):
    existente = Tienda(nombre="Zaragoza Uno", es_franquicia=True, codigo_albaran="Z")
    nueva = Tienda(nombre="Zaragoza Dos")
    db.add_all([existente, nueva])
    db.commit()
    db.refresh(nueva)

    como(Rol.JEFES).post(f"/tiendas/{nueva.id}/toggle-franquicia")

    db.refresh(nueva)
    assert nueva.codigo_albaran == "Z2"


def test_editar_tienda_rechaza_codigo_albaran_duplicado(como, db):
    uno = Tienda(nombre="Larios Uno", es_franquicia=True, codigo_albaran="L")
    dos = Tienda(nombre="Larios Dos", es_franquicia=True, codigo_albaran="M")
    db.add_all([uno, dos])
    db.commit()
    db.refresh(dos)

    r = como(Rol.JEFES).post(
        f"/tiendas/{dos.id}/editar",
        data={"nombre": dos.nombre, "es_franquicia": "on", "codigo_albaran": "l"},
    )
    assert r.status_code == 302
    assert "error=" in r.headers["location"]

    db.refresh(dos)
    assert dos.codigo_albaran == "M"


def test_editar_tienda_asigna_cliente_b2b_franquicia(como, db):
    cliente = ClienteB2B(nombre_comercial="Franquicia Centro", tipo_cliente=TipoCliente.FRANQUICIA)
    t = Tienda(nombre="Centro Test", es_franquicia=True, codigo_albaran="C")
    db.add_all([cliente, t])
    db.commit()
    db.refresh(cliente)
    db.refresh(t)

    r = como(Rol.JEFES).post(
        f"/tiendas/{t.id}/editar",
        data={
            "nombre": t.nombre,
            "es_franquicia": "on",
            "codigo_albaran": t.codigo_albaran,
            "cliente_b2b_id": str(cliente.id),
        },
    )
    assert r.status_code == 302

    db.refresh(t)
    assert t.cliente_b2b_id == cliente.id


def test_crear_tienda_codigo_albaran_duplicado_rechazado_a_nivel_bd(como, db):
    """Aunque se salte el pre-check de la API, la BD debe rechazar el duplicado (índice único)."""
    existente = Tienda(nombre="Rincon Uno", es_franquicia=True, codigo_albaran="R")
    db.add(existente)
    db.commit()

    otra = Tienda(nombre="Rincon Dos", es_franquicia=True, codigo_albaran="R")
    db.add(otra)
    try:
        db.commit()
        assert False, "se esperaba un IntegrityError por el índice único"
    except IntegrityError:
        db.rollback()

    assert db.query(Tienda).filter(Tienda.codigo_albaran == "R").count() == 1


def test_editar_tienda_sin_franquicia_limpia_codigo_y_cliente(como, db):
    cliente = ClienteB2B(nombre_comercial="Franquicia Norte", tipo_cliente=TipoCliente.FRANQUICIA)
    t = Tienda(nombre="Norte Test", es_franquicia=True, codigo_albaran="N")
    db.add_all([cliente, t])
    db.commit()
    db.refresh(cliente)
    db.refresh(t)
    t.cliente_b2b_id = cliente.id
    db.commit()

    r = como(Rol.JEFES).post(
        f"/tiendas/{t.id}/editar",
        data={"nombre": t.nombre},
    )
    assert r.status_code == 302

    db.refresh(t)
    assert t.es_franquicia is False
    assert t.codigo_albaran is None
    assert t.cliente_b2b_id is None
