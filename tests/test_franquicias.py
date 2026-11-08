from app.api.franquicias import _get_empresa_config
from app.models.config import Config
from app.models.usuario import Rol


def test_get_empresa_config_devuelve_defaults(db):
    db.query(Config).filter(Config.key.like("empresa.%")).delete(synchronize_session=False)
    db.commit()
    cfg = _get_empresa_config(db)
    # Sin config en BD, se usan los datos fiscales de ejemplo del emisor (defaults en código)
    assert cfg["razon_social"] == "OBRADOR DEMO SL"
    assert cfg["cif"] == "B00000000"
    assert cfg["registro_sanitario"] == ""  # no informado
    assert set(cfg.keys()) == {
        "razon_social", "cif", "direccion", "cp", "poblacion",
        "provincia", "telefono", "email", "registro_sanitario",
    }


def test_get_empresa_config_lee_valores_guardados(db):
    db.query(Config).filter(Config.key.like("empresa.%")).delete(synchronize_session=False)
    db.add(Config(key="empresa.razon_social", value="Obrador Demo SL"))
    db.add(Config(key="empresa.cif", value="B12345678"))
    db.commit()

    cfg = _get_empresa_config(db)
    assert cfg["razon_social"] == "Obrador Demo SL"
    assert cfg["cif"] == "B12345678"
    assert cfg["direccion"] == "Calle Ejemplo, 1"  # sin fila guardada → default


def test_config_empresa_get_200_roles_con_permiso(como):
    # "franquicias" está registrado en la matriz (Tarea 6) para estos 4 roles.
    for rol in (Rol.JEFES, Rol.ADMINISTRACION, Rol.JEFE_PASTELEROS, Rol.PASTELERAS):
        r = como(rol).get("/franquicias/config-empresa")
        assert r.status_code == 200
        assert 'action="/franquicias/config-empresa"' in r.text


def test_config_empresa_get_403_roles_sin_permiso(como):
    for rol in (Rol.REPARTIDORES, Rol.COMERCIAL, Rol.AREA_MANAGER):
        r = como(rol).get("/franquicias/config-empresa")
        assert r.status_code == 403


def test_config_empresa_get_404_tiendas(como):
    # TIENDAS tiene VER en "franquicias" (comparte la clave de permiso con la
    # config del emisor), pero esta pantalla admin no es para logins de
    # tienda: el propio handler la bloquea con 404 (mismo patrón que
    # albaranes_get en app/api/franquicias.py).
    r = como(Rol.TIENDAS).get("/franquicias/config-empresa")
    assert r.status_code == 404


def test_config_empresa_post_200_roles_con_permiso(como):
    r = como(Rol.JEFES).post("/franquicias/config-empresa", data={"razon_social": "X"})
    assert r.status_code == 302
    assert r.headers["location"] == "/franquicias/config-empresa"


def test_config_empresa_post_403_roles_sin_permiso(como):
    for rol in (Rol.TIENDAS, Rol.REPARTIDORES, Rol.COMERCIAL, Rol.AREA_MANAGER):
        r = como(rol).post("/franquicias/config-empresa", data={"razon_social": "X"})
        assert r.status_code == 403


def test_config_empresa_post_upsert_directo(db):
    """Prueba la lógica de upsert clave a clave directamente (complementa el
    test HTTP anterior, que solo verifica el status code)."""
    db.query(Config).filter(Config.key.like("empresa.%")).delete(synchronize_session=False)
    db.commit()

    nuevos = {
        "empresa.razon_social": "Obrador Demo SL",
        "empresa.cif": "B12345678",
        "empresa.direccion": "Calle Falsa 123",
        "empresa.cp": "29001",
        "empresa.poblacion": "Málaga",
        "empresa.provincia": "Málaga",
        "empresa.telefono": "600000000",
        "empresa.email": "info@obrador-demo.example",
        "empresa.registro_sanitario": "",
    }
    for key, value in nuevos.items():
        row = db.query(Config).filter(Config.key == key).first()
        if row:
            row.value = value
        else:
            db.add(Config(key=key, value=value))
    db.commit()

    cfg = _get_empresa_config(db)
    assert cfg["razon_social"] == "Obrador Demo SL"
    assert cfg["poblacion"] == "Málaga"
    assert cfg["registro_sanitario"] == ""

    # upsert de nuevo con otro valor debe actualizar, no duplicar
    row = db.query(Config).filter(Config.key == "empresa.cif").first()
    row.value = "B87654321"
    db.commit()
    assert db.query(Config).filter(Config.key == "empresa.cif").count() == 1
    assert _get_empresa_config(db)["cif"] == "B87654321"
