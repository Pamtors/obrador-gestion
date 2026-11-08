"""Tests del helper puro calcular_envio (extraído de stock.envios_get, Task 3
del plan Albarán franquicias): previsión − stock + pedidos, capado a lo
horneado si hay ProduccionDia de la fecha."""
from datetime import date, timedelta

from app.api.stock import calcular_envio
from app.database import SessionLocal
from app.auth.contrasena import hashear
from app.models.pedido import LineaPedido, Pedido
from app.models.produccion import ProduccionDia
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.stock import LineaParteStock, ParteStock, PrevisionStock
from app.models.usuario import Rol, Usuario


def _crear_usuario_test(db) -> int:
    u = db.query(Usuario).filter(Usuario.email == "envio_helper@test.com").first()
    if not u:
        u = Usuario(nombre="Test Envio Helper", email="envio_helper@test.com",
                    hash_contrasena=hashear("1234"), rol=Rol.JEFES)
        db.add(u)
        db.commit()
    return u.id


def _crear_producto_sabor(db, sufijo):
    p = db.query(Producto).filter(Producto.nombre == f"Test Prod Envio {sufijo}").first()
    if not p:
        p = Producto(nombre=f"Test Prod Envio {sufijo}")
        db.add(p)
        db.commit()
    sab = db.query(Sabor).filter(Sabor.nombre == f"Test Sabor Envio {sufijo}").first()
    if not sab:
        sab = Sabor(nombre=f"Test Sabor Envio {sufijo}")
        db.add(sab)
        db.commit()
    return p.id, sab.id


def test_calcular_envio_prevision_menos_stock_mas_pedidos(db, tienda):
    """necesidad = max(0, prevision - stock) + pedido, sin producción confirmada."""
    producto_id, sabor_id = _crear_producto_sabor(db, "A")
    usuario_id = _crear_usuario_test(db)
    fecha = date.today() + timedelta(days=30)

    db.add(PrevisionStock(tienda_id=tienda.id, dia_semana=fecha.weekday(),
                           producto_id=producto_id, sabor_id=sabor_id, cantidad=10))

    parte = ParteStock(fecha=fecha - timedelta(days=1), tienda_id=tienda.id, usuario_id=usuario_id)
    db.add(parte)
    db.commit()
    db.add(LineaParteStock(parte_stock_id=parte.id, producto_id=producto_id,
                            sabor_id=sabor_id, cantidad=3, raciones=0))

    ped = Pedido(fecha_pedido=fecha, fecha_recogida=fecha, tipo="PARTICULAR",
                 tienda_id=tienda.id, nombre_cliente="Cliente Test")
    db.add(ped)
    db.commit()
    db.add(LineaPedido(pedido_id=ped.id, producto_id=producto_id, sabor_id=sabor_id, cantidad=2))
    db.commit()

    envio_map = calcular_envio(db, tienda, fecha)
    # necesidad = max(0, 10 - 3) + 2 = 9, sin producción confirmada -> envio = necesidad
    assert envio_map[(producto_id, sabor_id)] == 9


def test_calcular_envio_capado_a_produccion_confirmada(db, tienda):
    """Si hay ProduccionDia para la fecha, el envío nunca supera lo horneado."""
    producto_id, sabor_id = _crear_producto_sabor(db, "B")
    fecha = date.today() + timedelta(days=31)

    db.add(PrevisionStock(tienda_id=tienda.id, dia_semana=fecha.weekday(),
                           producto_id=producto_id, sabor_id=sabor_id, cantidad=10))
    db.add(ProduccionDia(fecha=fecha, producto_id=producto_id, sabor_id=sabor_id, cantidad=4))
    db.commit()

    envio_map = calcular_envio(db, tienda, fecha)
    # necesidad = max(0, 10 - 0) + 0 = 10, pero capado a lo horneado (4)
    assert envio_map[(producto_id, sabor_id)] == 4


def test_calcular_envio_sin_necesidad_no_aparece(db, tienda):
    """Si necesidad/envío es 0 la clave no aparece en el mapa devuelto."""
    producto_id, sabor_id = _crear_producto_sabor(db, "C")
    usuario_id = _crear_usuario_test(db)
    fecha = date.today() + timedelta(days=32)

    db.add(PrevisionStock(tienda_id=tienda.id, dia_semana=fecha.weekday(),
                           producto_id=producto_id, sabor_id=sabor_id, cantidad=5))
    db.commit()

    parte = ParteStock(fecha=fecha - timedelta(days=1), tienda_id=tienda.id, usuario_id=usuario_id)
    db.add(parte)
    db.commit()
    db.add(LineaParteStock(parte_stock_id=parte.id, producto_id=producto_id,
                            sabor_id=sabor_id, cantidad=5, raciones=0))
    db.commit()

    envio_map = calcular_envio(db, tienda, fecha)
    assert (producto_id, sabor_id) not in envio_map
