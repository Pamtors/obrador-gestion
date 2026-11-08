from app.auth.permisos import Nivel, nivel_permiso
from app.models.usuario import Rol


def test_jefes_todo_editar():
    for clave in ["clientes", "pedidos", "pedidos.rutas", "impresion", "stock.partes",
                  "stock.mermas", "produccion", "holded", "catalogo", "admin"]:
        assert nivel_permiso(Rol.JEFES, clave) == Nivel.EDITAR


def test_administracion_sin_admin():
    assert nivel_permiso(Rol.ADMINISTRACION, "admin") == Nivel.NADA
    assert nivel_permiso(Rol.ADMINISTRACION, "holded") == Nivel.EDITAR


def test_repartidores():
    assert nivel_permiso(Rol.REPARTIDORES, "pedidos") == Nivel.NADA        # bandeja
    assert nivel_permiso(Rol.REPARTIDORES, "pedidos.rutas") == Nivel.EDITAR
    assert nivel_permiso(Rol.REPARTIDORES, "impresion") == Nivel.EDITAR
    assert nivel_permiso(Rol.REPARTIDORES, "stock.envios") == Nivel.EDITAR
    assert nivel_permiso(Rol.REPARTIDORES, "stock.partes") == Nivel.NADA
    assert nivel_permiso(Rol.REPARTIDORES, "catalogo") == Nivel.NADA


def test_pasteleras():
    assert nivel_permiso(Rol.PASTELERAS, "pedidos") == Nivel.VER
    assert nivel_permiso(Rol.PASTELERAS, "pedidos.rutas") == Nivel.NADA
    assert nivel_permiso(Rol.PASTELERAS, "stock.partes") == Nivel.EDITAR
    assert nivel_permiso(Rol.PASTELERAS, "stock.dias_reparto") == Nivel.VER
    assert nivel_permiso(Rol.PASTELERAS, "stock.mermas") == Nivel.NADA
    assert nivel_permiso(Rol.PASTELERAS, "holded") == Nivel.NADA
    assert nivel_permiso(Rol.PASTELERAS, "catalogo") == Nivel.NADA
    assert nivel_permiso(Rol.PASTELERAS, "produccion") == Nivel.EDITAR


def test_jefe_pasteleros():
    assert nivel_permiso(Rol.JEFE_PASTELEROS, "catalogo") == Nivel.EDITAR
    assert nivel_permiso(Rol.JEFE_PASTELEROS, "pedidos") == Nivel.EDITAR
    assert nivel_permiso(Rol.JEFE_PASTELEROS, "stock.mermas") == Nivel.EDITAR
    assert nivel_permiso(Rol.JEFE_PASTELEROS, "admin") == Nivel.NADA


def test_tiendas():
    assert nivel_permiso(Rol.TIENDAS, "pedidos") == Nivel.VER
    assert nivel_permiso(Rol.TIENDAS, "stock.mermas") == Nivel.EDITAR
    assert nivel_permiso(Rol.TIENDAS, "stock.dias_reparto") == Nivel.VER
    assert nivel_permiso(Rol.TIENDAS, "stock.prevision") == Nivel.NADA
    assert nivel_permiso(Rol.TIENDAS, "impresion") == Nivel.NADA


def test_area_manager_y_comercial():
    assert nivel_permiso(Rol.AREA_MANAGER, "pedidos") == Nivel.EDITAR
    assert nivel_permiso(Rol.AREA_MANAGER, "stock.prevision") == Nivel.EDITAR
    assert nivel_permiso(Rol.AREA_MANAGER, "clientes") == Nivel.NADA
    assert nivel_permiso(Rol.COMERCIAL, "clientes") == Nivel.EDITAR
    assert nivel_permiso(Rol.COMERCIAL, "pedidos") == Nivel.EDITAR
    assert nivel_permiso(Rol.COMERCIAL, "stock.partes") == Nivel.NADA


def test_clave_desconocida_es_nada():
    assert nivel_permiso(Rol.JEFES, "inexistente") == Nivel.NADA


def test_puede_servicio_por_subapartado():
    from app.auth.permisos import UsuarioSesion
    u = UsuarioSesion(id=1, nombre="x", email="x@x", rol=Rol.REPARTIDORES,
                      activo=True, tienda_id=None, tienda_nombre=None)
    assert u.puede_servicio("pedidos")      # solo por pedidos.rutas
    assert u.puede_servicio("stock")        # solo por stock.envios
    assert u.puede_servicio("impresion")
    assert not u.puede_servicio("produccion")
    assert not u.puede_servicio("admin")
