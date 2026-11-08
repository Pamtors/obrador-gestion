import pytest
from app.models.usuario import Rol

# (rol, ruta GET, status esperado)
# Nota: produccion.py monta su router en prefix "/horneado" (no "/produccion"),
# se usa esa ruta real para probar el permiso "produccion".
CASOS = [
    (Rol.JEFES, "/usuarios/", 200),
    (Rol.ADMINISTRACION, "/usuarios/", 403),      # admin solo Jefes
    (Rol.ADMINISTRACION, "/holded/", 200),
    (Rol.JEFE_PASTELEROS, "/catalogo/productos", 200),
    (Rol.PASTELERAS, "/catalogo/productos", 403),
    (Rol.PASTELERAS, "/holded/", 403),
    (Rol.PASTELERAS, "/horneado/", 200),
    (Rol.PASTELERAS, "/imprimir/", 200),
    (Rol.TIENDAS, "/imprimir/", 403),             # Tiendas sin Impresión (PDF)
    (Rol.COMERCIAL, "/clientes/", 200),
    (Rol.COMERCIAL, "/horneado/", 403),
    (Rol.REPARTIDORES, "/imprimir/", 200),
    (Rol.AREA_MANAGER, "/clientes/", 403),
]


@pytest.mark.parametrize("rol,ruta,esperado", CASOS)
def test_acceso(como, rol, ruta, esperado):
    assert como(rol).get(ruta).status_code == esperado


def test_administracion_no_puede_crear_usuarios(como):
    r = como(Rol.ADMINISTRACION).post("/usuarios/crear", data={
        "nombre": "x", "email": "x@x.com", "contrasena": "1", "rol": "TIENDAS"})
    assert r.status_code == 403
