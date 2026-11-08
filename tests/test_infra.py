from app.models.usuario import Rol


def test_sin_sesion_redirige_a_login(anonimo):
    r = anonimo.get("/")
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_con_sesion_inicio_carga(como):
    r = como(Rol.JEFES).get("/")
    assert r.status_code == 200
