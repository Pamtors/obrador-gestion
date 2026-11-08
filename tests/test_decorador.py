from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth.permisos import requiere_permiso
from app.models.usuario import Rol

mini = FastAPI()


@mini.get("/ver")
@requiere_permiso("stock.mermas")
async def ver(request: Request):
    return {"ok": True}


@mini.post("/editar")
@requiere_permiso("stock.mermas", editar=True)
async def editar(request: Request):
    return {"ok": True}


def _cliente(como, rol, tienda_id=None):
    """Reutiliza la factoría de usuarios del conftest pero contra la mini-app."""
    real = como(rol, tienda_id)  # crea el usuario y devuelve client con cookie
    c = TestClient(mini, follow_redirects=False)
    c.cookies.set("sesion", real.cookies.get("sesion"))
    return c


def test_sin_sesion_redirige():
    c = TestClient(mini, follow_redirects=False)
    assert c.get("/ver").status_code == 302


def test_editar_puede_ver_y_editar(como):
    c = _cliente(como, Rol.TIENDAS, tienda_id=None)
    assert c.get("/ver").status_code == 200          # TIENDAS: stock.mermas EDITAR
    assert c.post("/editar").status_code == 200


def test_nada_recibe_403(como):
    c = _cliente(como, Rol.COMERCIAL)                # COMERCIAL: stock NADA
    assert c.get("/ver").status_code == 403


def test_ver_no_puede_editar(como):
    c = _cliente(como, Rol.PASTELERAS)               # stock.mermas NADA para PASTELERAS
    assert c.post("/editar").status_code == 403
