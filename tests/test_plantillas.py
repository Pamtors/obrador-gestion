from app.models.usuario import Rol


def test_menu_pasteleras_sin_holded_ni_catalogo(como):
    html = como(Rol.PASTELERAS).get("/").text
    assert "/holded" not in html
    assert "/catalogo" not in html
    assert "/horneado" in html


def test_menu_comercial_solo_clientes_y_pedidos(como):
    html = como(Rol.COMERCIAL).get("/").text
    assert "/clientes" in html
    assert "/pedidos" in html
    assert "/stock" not in html
    assert "/usuarios" not in html


def test_bandeja_pasteleras_sin_boton_crear(como):
    html = como(Rol.PASTELERAS).get("/pedidos/").text
    assert "/pedidos/crear" not in html


def test_bandeja_jefes_con_boton_crear(como):
    html = como(Rol.JEFES).get("/pedidos/").text
    assert "/pedidos/crear" in html


def test_reparto_pasteleras_sin_toggle_clicable(como):
    # PASTELERAS tiene stock.dias_reparto en VER: ve el calendario pero sin botones
    html = como(Rol.PASTELERAS).get("/stock/reparto/").text
    assert 'onclick="toggleDia(this)"' not in html


def test_stock_tiendas_sin_boton_nuevo_parte(como, tienda):
    # TIENDAS usa su bloque propio "+ Parte de hoy"; el genérico "+ Nuevo parte" no aparece
    html = como(Rol.TIENDAS, tienda.id).get("/stock/").text
    assert "+ Nuevo parte" not in html
