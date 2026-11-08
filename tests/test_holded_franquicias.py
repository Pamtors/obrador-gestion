"""Regresión anti-doble-facturación (Tarea 7): un pedido B2B recogido en una
tienda franquicia se factura vía su albarán (app/api/franquicias.py) y debe
quedar excluido del flujo Holded B2B normal (index, crear_todos, preview/crear
de albarán). Los pedidos entregados fuera de tienda o recogidos en tienda
propia deben seguir apareciendo sin cambios."""
from datetime import date

import pytest

from app.api.holded import _es_pedido_de_franquicia, _preview_data
from app.database import SessionLocal
from app.models.cliente_b2b import ClienteB2B, TipoCliente
from app.models.pedido import LineaPedido, Pedido
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.tienda import Tienda
from app.models.usuario import Rol


@pytest.fixture()
def cliente_b2b(db):
    c = db.query(ClienteB2B).filter(ClienteB2B.nombre_comercial == "Test B2B Holded").first()
    if not c:
        c = ClienteB2B(nombre_comercial="Test B2B Holded", tipo_cliente=TipoCliente.B2B, id_holded="holded_c1")
        db.add(c)
        db.commit()
        db.refresh(c)
    else:
        c.id_holded = "holded_c1"
        db.commit()
    return c


@pytest.fixture()
def tienda_franquicia(db):
    t = db.query(Tienda).filter(Tienda.nombre == "Test Franquicia Holded").first()
    if not t:
        t = Tienda(nombre="Test Franquicia Holded", es_franquicia=True, activa=True, codigo_albaran="FH")
        db.add(t)
        db.commit()
        db.refresh(t)
    return t


@pytest.fixture()
def tienda_propia(db):
    t = db.query(Tienda).filter(Tienda.nombre == "Test Tienda Propia Holded").first()
    if not t:
        t = Tienda(nombre="Test Tienda Propia Holded", es_franquicia=False, activa=True)
        db.add(t)
        db.commit()
        db.refresh(t)
    return t


@pytest.fixture()
def catalogo(db):
    p = db.query(Producto).filter(Producto.nombre == "Test Producto Holded").first()
    if not p:
        p = Producto(nombre="Test Producto Holded", precio_b2b=10.0)
        db.add(p)
        db.commit()
        db.refresh(p)
    s = db.query(Sabor).filter(Sabor.nombre == "Test Sabor Holded").first()
    if not s:
        s = Sabor(nombre="Test Sabor Holded")
        db.add(s)
        db.commit()
        db.refresh(s)
    return p, s


def _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=None, ubicacion_entrega="TIENDA"):
    producto, sabor = catalogo
    p = Pedido(
        fecha_pedido=date.today(), fecha_recogida=date.today(), tipo="B2B",
        ubicacion_entrega=ubicacion_entrega, tienda_id=tienda_id, cliente_b2b_id=cliente_b2b.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    db.add(LineaPedido(pedido_id=p.id, producto_id=producto.id, sabor_id=sabor.id, cantidad=2))
    db.commit()
    return p


@pytest.fixture(autouse=True)
def _limpiar(db):
    yield
    db.query(LineaPedido).delete(synchronize_session=False)
    db.query(Pedido).filter(Pedido.tipo == "B2B").delete(synchronize_session=False)
    db.commit()


# ── _es_pedido_de_franquicia (helper) ────────────────────────────────────────

def test_helper_true_si_tienda_es_franquicia(db, tienda_franquicia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_franquicia.id)
    tiendas_map = {tienda_franquicia.id: tienda_franquicia}
    assert _es_pedido_de_franquicia(p, tiendas_map) is True


def test_helper_false_si_tienda_propia(db, tienda_propia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_propia.id)
    tiendas_map = {tienda_propia.id: tienda_propia}
    assert _es_pedido_de_franquicia(p, tiendas_map) is False


def test_helper_false_si_sin_tienda(db, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=None, ubicacion_entrega="RESTAURANTE")
    assert _es_pedido_de_franquicia(p, {}) is False


# ── GET /holded/ (index) ──────────────────────────────────────────────────────

def test_pedido_franquicia_no_aparece_en_holded(como, db, tienda_franquicia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_franquicia.id)
    c = como(Rol.ADMINISTRACION)

    r = c.get("/holded/")
    assert r.status_code == 200
    assert f"/holded/albaran/{p.id}" not in r.text

    r_pend = c.get("/holded/?pendientes=1")
    assert r_pend.status_code == 200
    assert f"/holded/albaran/{p.id}" not in r_pend.text


def test_pedido_restaurante_sin_tienda_si_aparece_en_holded(como, db, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=None, ubicacion_entrega="RESTAURANTE")
    c = como(Rol.ADMINISTRACION)

    r = c.get("/holded/")
    assert r.status_code == 200
    assert f"/holded/albaran/{p.id}" in r.text


def test_pedido_tienda_propia_si_aparece_en_holded(como, db, tienda_propia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_propia.id)
    c = como(Rol.ADMINISTRACION)

    r = c.get("/holded/")
    assert r.status_code == 200
    assert f"/holded/albaran/{p.id}" in r.text


# ── POST /holded/crear-todos ─────────────────────────────────────────────────

def test_crear_todos_excluye_pedido_franquicia(como, db, tienda_franquicia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_franquicia.id)
    c = como(Rol.ADMINISTRACION)

    r = c.post("/holded/crear-todos")
    assert r.status_code == 200
    # No debe intentar crear documento (sin api key configurada -> error_global,
    # pero incluso así el pedido franquicia no debe figurar como pendiente).
    db.expire_all()
    pedido = db.query(Pedido).filter(Pedido.id == p.id).first()
    assert pedido.holded_doc_id is None


# ── _preview_data / GET-POST /holded/albaran/{id} ────────────────────────────

def test_preview_data_bloquea_pedido_franquicia(db, tienda_franquicia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_franquicia.id)
    pedido_dict, lineas, errores = _preview_data(p.id)
    assert pedido_dict is None
    assert lineas == []
    assert errores
    assert "franquicia" in errores[0].lower()


def test_albaran_preview_muestra_error_para_pedido_franquicia(como, db, tienda_franquicia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_franquicia.id)
    c = como(Rol.ADMINISTRACION)
    r = c.get(f"/holded/albaran/{p.id}")
    assert r.status_code == 200
    assert "franquicia" in r.text.lower()


def test_albaran_crear_no_crea_documento_para_pedido_franquicia(como, db, tienda_franquicia, cliente_b2b, catalogo):
    p = _crear_pedido_b2b(db, cliente_b2b, catalogo, tienda_id=tienda_franquicia.id)
    c = como(Rol.ADMINISTRACION)
    r = c.post(f"/holded/albaran/{p.id}", data={})
    assert r.status_code == 200
    assert "franquicia" in r.text.lower()

    db.expire_all()
    pedido = db.query(Pedido).filter(Pedido.id == p.id).first()
    assert pedido.holded_doc_id is None
