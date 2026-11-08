from datetime import date

from sqlalchemy.exc import IntegrityError

from app.models.albaran_franquicia import AlbaranFranquicia, LineaAlbaranFranquicia
from app.models.cliente_b2b import ClienteB2B, TipoCliente
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.usuario import Rol, Usuario
from app.auth.contrasena import hashear


def _crear_producto_y_sabor(db):
    producto = db.query(Producto).filter(Producto.nombre == "TARTA GRANDE TEST").first()
    if not producto:
        producto = Producto(nombre="TARTA GRANDE TEST")
        db.add(producto)
        db.commit()
        db.refresh(producto)
    sabor = db.query(Sabor).filter(Sabor.nombre == "Lotus Test").first()
    if not sabor:
        sabor = Sabor(nombre="Lotus Test")
        db.add(sabor)
        db.commit()
        db.refresh(sabor)
    return producto, sabor


def _crear_cliente_franquicia(db):
    cliente = ClienteB2B(nombre_comercial="Franquicia Test", tipo_cliente=TipoCliente.FRANQUICIA)
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


def _crear_usuario(db):
    u = db.query(Usuario).filter(Usuario.email == "albaran_test@test.com").first()
    if u:
        return u
    u = Usuario(nombre="Test Albaran", email="albaran_test@test.com",
                hash_contrasena=hashear("1234"), rol=Rol.ADMINISTRACION)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_crear_albaran_con_lineas(db, tienda):
    cliente = _crear_cliente_franquicia(db)
    usuario = _crear_usuario(db)
    producto, sabor = _crear_producto_y_sabor(db)

    albaran = AlbaranFranquicia(
        tienda_id=tienda.id,
        cliente_b2b_id=cliente.id,
        fecha=date(2026, 7, 15),
        total_sin_iva=10.0,
        total_iva=1.0,
        total=11.0,
        creado_por=usuario.id,
        lineas=[
            LineaAlbaranFranquicia(
                producto_id=producto.id,
                sabor_id=sabor.id,
                producto_nombre=producto.nombre,
                sabor_nombre=sabor.nombre,
                descripcion=f"{sabor.nombre} {producto.nombre}",
                cantidad=2,
                precio_unit=5.0,
            )
        ],
    )
    db.add(albaran)
    db.commit()
    db.refresh(albaran)

    assert albaran.id is not None
    assert len(albaran.lineas) == 1
    assert albaran.lineas[0].albaran_id == albaran.id

    # cascade delete
    linea_id = albaran.lineas[0].id
    db.delete(albaran)
    db.commit()
    assert db.get(LineaAlbaranFranquicia, linea_id) is None


def test_unique_tienda_fecha(db, tienda):
    cliente = _crear_cliente_franquicia(db)
    usuario = _crear_usuario(db)

    db.add(AlbaranFranquicia(
        tienda_id=tienda.id, cliente_b2b_id=cliente.id, fecha=date(2026, 7, 16),
        total_sin_iva=0, total_iva=0, total=0, creado_por=usuario.id,
    ))
    db.commit()

    db.add(AlbaranFranquicia(
        tienda_id=tienda.id, cliente_b2b_id=cliente.id, fecha=date(2026, 7, 16),
        total_sin_iva=0, total_iva=0, total=0, creado_por=usuario.id,
    ))
    try:
        db.commit()
        assert False, "esperaba IntegrityError por UNIQUE(tienda_id, fecha)"
    except IntegrityError:
        db.rollback()
