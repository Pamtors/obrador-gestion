from datetime import date

from app.database import SessionLocal
from app.models.usuario import Rol
from app.models.pedido import Pedido


def _crear_pedido(tienda_id):
    """Pedido mínimo para tests; campos ajustados al modelo real."""
    s = SessionLocal()
    try:
        p = Pedido(fecha_pedido=date.today(), fecha_recogida=date.today(), tipo="TIENDA",
                   tienda_id=tienda_id, nombre_cliente="Test", telefono_cliente="600000000")
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id
    finally:
        s.close()


def test_pasteleras_ve_bandeja_pero_no_crea(como):
    c = como(Rol.PASTELERAS)
    assert c.get("/pedidos/").status_code == 200
    assert c.get("/pedidos/crear").status_code == 403
    assert c.post("/pedidos/crear", data={}).status_code == 403


def test_repartidores_rutas_si_bandeja_no(como):
    c = como(Rol.REPARTIDORES)
    assert c.get("/pedidos/rutas").status_code == 200
    assert c.get("/pedidos/").status_code == 403


def test_tienda_solo_ve_pedidos_de_su_tienda(como, tienda, tienda2):
    pid_mia = _crear_pedido(tienda.id)
    pid_ajena = _crear_pedido(tienda2.id)
    c = como(Rol.TIENDAS, tienda_id=tienda.id)
    assert c.get(f"/pedidos/{pid_mia}").status_code == 200
    assert c.get(f"/pedidos/{pid_ajena}").status_code == 404
    html = c.get("/pedidos/").text
    assert f"/pedidos/{pid_mia}" in html
    assert f"/pedidos/{pid_ajena}" not in html


def test_tienda_no_edita_ni_elimina_pedido_ajeno(como, tienda, tienda2):
    pid_ajena = _crear_pedido(tienda2.id)
    c = como(Rol.TIENDAS, tienda_id=tienda.id)
    # hoy el decorador ya devuelve 403 (TIENDAS es VER); el check interno daría 404
    assert c.post(f"/pedidos/{pid_ajena}/eliminar").status_code in (403, 404)
    assert c.get(f"/pedidos/{pid_ajena}/editar").status_code in (403, 404)
