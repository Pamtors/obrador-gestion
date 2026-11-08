"""Regresiones de UI: nombre de tienda en la ficha de stock y filtro de tienda
en la bandeja de pedidos."""
from app.models.catalogo import SaborProducto
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.stock import PrevisionStock
from app.models.tienda import Tienda
from app.models.usuario import Rol


def _get_or_create(db, modelo, **kwargs):
    obj = db.query(modelo).filter_by(**kwargs).first()
    if not obj:
        obj = modelo(**kwargs)
        db.add(obj)
        db.commit()
        db.refresh(obj)
    return obj


def test_parte_nuevo_muestra_el_nombre_de_la_tienda(como, db):
    """El {% set %} dentro del {% for %} no salía del scope del bucle: la etiqueta
    "Tienda" siempre mostraba "—". Ahora nombre_sel llega calculado del backend."""
    t = _get_or_create(db, Tienda, nombre="Test Ficha Stock")
    p = _get_or_create(db, Producto, nombre="Test TARTA GRANDE")
    s = _get_or_create(db, Sabor, nombre="Test PISTACHO")
    _get_or_create(db, SaborProducto, producto_id=p.id, sabor_id=s.id, produccion=True)
    _get_or_create(db, PrevisionStock, tienda_id=t.id, dia_semana=0,
                   producto_id=p.id, sabor_id=s.id, cantidad=3)

    html = como(Rol.JEFES).get(f"/stock/nuevo?tienda_id={t.id}").text
    etiqueta = html.split("<label>Tienda</label>")[1].split("</div>")[0]
    assert "Test Ficha Stock" in etiqueta
    assert "—" not in etiqueta


def test_bandeja_tiendas_sin_desplegable_de_tienda(como, tienda, tienda2):
    """TIENDAS solo ve sus pedidos (el backend ignora el filtro), así que no se
    le ofrece el desplegable de tienda: elegir otra no haría nada."""
    html = como(Rol.TIENDAS, tienda.id).get("/pedidos/").text
    assert 'name="tienda_id"' not in html
    assert tienda2.nombre not in html


def test_bandeja_jefes_conserva_el_desplegable_de_tienda(como, tienda2):
    html = como(Rol.JEFES).get("/pedidos/").text
    assert 'name="tienda_id"' in html
    assert tienda2.nombre in html
