"""Tests de los albaranes de envío a franquicias (numeración, preview, generar,
push a Holded, impresión). La lógica de dominio se prueba directo, sin pasar
por HTTP; las rutas HTTP se prueban aparte para verificar la matriz de
permisos "franquicias" (registrada en la Tarea 6)."""
from datetime import date
from unittest.mock import patch

import pytest

from app.api.franquicias import (
    build_preview,
    construir_items_snapshot,
    editar_lineas_albaran,
    generar_albaran,
    numero_albaran,
    push_a_holded,
)
from app.database import SessionLocal
from app.models.albaran_franquicia import AlbaranFranquicia, LineaAlbaranFranquicia
from app.models.cliente_b2b import ClienteB2B, TipoCliente
from app.models.envio import EnvioTienda, LineaEnvioTienda
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.stock import DiasReparto, PrevisionStock
from app.models.tienda import Tienda
from app.models.usuario import Rol


# ── Fixtures de dominio ──────────────────────────────────────────────────────

@pytest.fixture()
def catalogo(db):
    """Producto con precio_franquicia + sabor, get-or-create por nombre."""
    p = db.query(Producto).filter(Producto.nombre == "Test Tarta Franquicia").first()
    if not p:
        p = Producto(nombre="Test Tarta Franquicia", precio_franquicia=12.5)
        db.add(p)
        db.commit()
        db.refresh(p)
    elif p.precio_franquicia != 12.5:
        p.precio_franquicia = 12.5
        db.commit()
    s = db.query(Sabor).filter(Sabor.nombre == "Test Sabor Franquicia").first()
    if not s:
        s = Sabor(nombre="Test Sabor Franquicia")
        db.add(s)
        db.commit()
        db.refresh(s)
    return p, s


@pytest.fixture()
def producto_sin_precio(db):
    p = db.query(Producto).filter(Producto.nombre == "Test Producto Sin Precio").first()
    if not p:
        p = Producto(nombre="Test Producto Sin Precio", precio_franquicia=None)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


@pytest.fixture()
def cliente_b2b(db):
    c = db.query(ClienteB2B).filter(ClienteB2B.nombre_comercial == "Test Franquicia SL").first()
    if not c:
        c = ClienteB2B(nombre_comercial="Test Franquicia SL", tipo_cliente=TipoCliente.FRANQUICIA)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


@pytest.fixture()
def tienda_franquicia(db, cliente_b2b):
    t = db.query(Tienda).filter(Tienda.nombre == "Test Franquicia Reparto").first()
    if not t:
        t = Tienda(
            nombre="Test Franquicia Reparto", es_franquicia=True, activa=True,
            cliente_b2b_id=cliente_b2b.id, codigo_albaran="TF",
        )
        db.add(t)
        db.commit()
        db.refresh(t)
    else:
        t.cliente_b2b_id = cliente_b2b.id
        t.codigo_albaran = "TF"
        db.commit()
    return t


def _fecha_con_reparto(db, tienda, dia_semana=1):
    """Asegura que la tienda tiene reparto el día indicado (1=martes) y
    devuelve la fecha del próximo día de esa semana coincidente."""
    existente = db.query(DiasReparto).filter(
        DiasReparto.tienda_id == tienda.id, DiasReparto.dia_semana == dia_semana
    ).first()
    if not existente:
        db.add(DiasReparto(tienda_id=tienda.id, dia_semana=dia_semana))
        db.commit()
    # 2026-07-14 es martes (dia_semana=1)
    return date(2026, 7, 14)


def _con_envio(db, tienda, producto, sabor, fecha, cantidad=5):
    """Crea un EnvioTienda confirmado para esa tienda/fecha (fuente de verdad
    del albarán tras ENVIO_CONFIRMADO_PLAN.md, ya no calcular_envio() en vivo)."""
    envio = db.query(EnvioTienda).filter(
        EnvioTienda.tienda_id == tienda.id, EnvioTienda.fecha == fecha).first()
    if not envio:
        envio = EnvioTienda(tienda_id=tienda.id, fecha=fecha, confirmado=True)
        db.add(envio)
        db.commit()
        db.refresh(envio)
    else:
        envio.confirmado = True

    linea = db.query(LineaEnvioTienda).filter(
        LineaEnvioTienda.envio_tienda_id == envio.id,
        LineaEnvioTienda.producto_id == producto.id, LineaEnvioTienda.sabor_id == sabor.id,
    ).first()
    if linea:
        linea.cantidad = cantidad
    else:
        db.add(LineaEnvioTienda(
            envio_tienda_id=envio.id,
            producto_id=producto.id, sabor_id=sabor.id, cantidad=cantidad,
        ))
    db.commit()


@pytest.fixture(autouse=True)
def _limpiar_albaranes(db):
    """Los tests de este módulo reutilizan la misma tienda/producto/sabor de
    prueba (get-or-create); sin limpiar entre tests, el UNIQUE(tienda,fecha)
    de albaranes_franquicia haría fallar los que no esperan uno preexistente,
    y los envíos confirmados de un test (build_preview) se filtrarían al siguiente."""
    yield
    for alb in db.query(AlbaranFranquicia).all():
        db.delete(alb)
    db.query(PrevisionStock).delete(synchronize_session=False)
    db.query(LineaEnvioTienda).delete(synchronize_session=False)
    db.query(EnvioTienda).delete(synchronize_session=False)
    db.commit()


def _usuario_id(db):
    from app.models.usuario import Usuario
    from app.auth.contrasena import hashear
    u = db.query(Usuario).filter(Usuario.email == "franquicia_test@test.com").first()
    if not u:
        u = Usuario(nombre="Test Franquicia", email="franquicia_test@test.com",
                    hash_contrasena=hashear("1234"), rol=Rol.JEFES)
        db.add(u)
        db.commit()
        db.refresh(u)
    return u.id


# ── numero_albaran ───────────────────────────────────────────────────────────

def test_numero_albaran_formato_exacto():
    tienda = Tienda(nombre="Fuengirola", codigo_albaran="F")
    fecha = date(2026, 7, 15)
    assert numero_albaran(tienda, fecha) == "AFF-2026-1507"


# ── build_preview: bloqueantes/avisos independientes ─────────────────────────

def test_preview_bloquea_sin_cliente_b2b(db, catalogo):
    producto, sabor = catalogo
    tienda = Tienda(nombre="Test Sin B2B", es_franquicia=True, activa=True, codigo_albaran="SB")
    db.add(tienda)
    db.commit()
    fecha = _fecha_con_reparto(db, tienda)
    _con_envio(db, tienda, producto, sabor, fecha)

    preview = build_preview(db, tienda, fecha)
    assert not preview["puede_generar"]
    assert any("cliente B2B" in b for b in preview["bloqueantes"])


def test_preview_bloquea_producto_sin_precio_franquicia(db, tienda_franquicia, producto_sin_precio, catalogo):
    _, sabor = catalogo
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto_sin_precio, sabor, fecha)

    preview = build_preview(db, tienda_franquicia, fecha)
    assert not preview["puede_generar"]
    assert any("precio de franquicia" in b for b in preview["bloqueantes"])
    assert any("Sin precio" not in a for a in preview["avisos"])  # no es solo aviso, bloquea


def test_preview_avisa_sin_id_holded_pero_no_bloquea(db, tienda_franquicia, cliente_b2b, catalogo):
    producto, sabor = catalogo
    cliente_b2b.id_holded = None
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha)

    preview = build_preview(db, tienda_franquicia, fecha)
    assert preview["puede_generar"]  # no bloquea lo local
    assert any("Holded" in a for a in preview["avisos"])


def test_preview_bloquea_envio_no_confirmado(db, cliente_b2b):
    # Tienda propia, sin ningún EnvioTienda confirmado ese día -> bloqueante distinto de "vacío"
    tienda = db.query(Tienda).filter(Tienda.nombre == "Test Franquicia Sin Confirmar").first()
    if not tienda:
        tienda = Tienda(nombre="Test Franquicia Sin Confirmar", es_franquicia=True, activa=True,
                        cliente_b2b_id=cliente_b2b.id, codigo_albaran="SC")
        db.add(tienda)
        db.commit()
    fecha = _fecha_con_reparto(db, tienda)
    preview = build_preview(db, tienda, fecha)
    assert not preview["puede_generar"]
    assert any("no está confirmado" in b for b in preview["bloqueantes"])


def test_preview_bloquea_envio_vacio(db, cliente_b2b):
    # Envío confirmado pero sin líneas -> "nada que enviar"
    tienda = db.query(Tienda).filter(Tienda.nombre == "Test Franquicia Envio Vacio").first()
    if not tienda:
        tienda = Tienda(nombre="Test Franquicia Envio Vacio", es_franquicia=True, activa=True,
                        cliente_b2b_id=cliente_b2b.id, codigo_albaran="EV")
        db.add(tienda)
        db.commit()
    fecha = _fecha_con_reparto(db, tienda)
    envio = db.query(EnvioTienda).filter(
        EnvioTienda.tienda_id == tienda.id, EnvioTienda.fecha == fecha).first()
    if not envio:
        db.add(EnvioTienda(tienda_id=tienda.id, fecha=fecha, confirmado=True))
        db.commit()
    preview = build_preview(db, tienda, fecha)
    assert not preview["puede_generar"]
    assert any("nada que enviar" in b for b in preview["bloqueantes"])


def test_preview_calcula_totales_correctamente(db, tienda_franquicia, cliente_b2b, catalogo):
    producto, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=4)

    preview = build_preview(db, tienda_franquicia, fecha)
    assert preview["puede_generar"]
    assert len(preview["lineas"]) == 1
    linea = preview["lineas"][0]
    assert linea["cantidad"] == 4
    assert linea["precio_unit"] == 12.5
    assert linea["subtotal"] == 50.0
    assert linea["descripcion"] == "Test Sabor Franquicia Test Tarta Franquicia"
    assert preview["total_sin_iva"] == 50.0
    assert preview["total_iva"] == pytest.approx(5.0)
    assert preview["total"] == pytest.approx(55.0)


# ── generar_albaran: snapshot, idempotencia, refuse conditions ───────────────

def test_generar_crea_snapshot_correcto(db, tienda_franquicia, cliente_b2b, catalogo):
    producto, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=3)
    uid = _usuario_id(db)

    resultado = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    assert resultado["ok"]
    albaran = resultado["albaran"]
    assert albaran.numero == numero_albaran(tienda_franquicia, fecha)
    assert albaran.cliente_b2b_id == cliente_b2b.id
    assert albaran.creado_por == uid
    assert len(albaran.lineas) == 1
    assert albaran.lineas[0].cantidad == 3
    assert albaran.total_sin_iva == pytest.approx(37.5)
    assert albaran.total == pytest.approx(41.25)


def test_generar_es_idempotente_sin_recrear(db, tienda_franquicia, cliente_b2b, catalogo):
    producto, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=2)
    uid = _usuario_id(db)

    r1 = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    assert r1["ok"]

    r2 = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    assert not r2["ok"]
    assert "recrear" in r2["errores"][0].lower()

    assert db.query(AlbaranFranquicia).filter(
        AlbaranFranquicia.tienda_id == tienda_franquicia.id, AlbaranFranquicia.fecha == fecha
    ).count() == 1


def test_generar_con_recrear_regenera_sin_lineas_huerfanas(db, tienda_franquicia, cliente_b2b, catalogo):
    producto, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=2)
    uid = _usuario_id(db)

    generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)

    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=7)
    r2 = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=True)
    assert r2["ok"]
    assert r2["albaran"].lineas[0].cantidad == 7

    # Solo queda un albarán para tienda+fecha, y sin líneas huérfanas con la
    # cantidad vieja (2) del snapshot anterior (cascade al borrar el padre)
    assert db.query(AlbaranFranquicia).filter(
        AlbaranFranquicia.tienda_id == tienda_franquicia.id, AlbaranFranquicia.fecha == fecha
    ).count() == 1
    assert db.query(LineaAlbaranFranquicia).filter(LineaAlbaranFranquicia.cantidad == 2).count() == 0


def test_generar_avisa_de_doc_holded_previo_al_recrear(db, tienda_franquicia, cliente_b2b, catalogo):
    producto, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=2)
    uid = _usuario_id(db)

    r1 = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    r1["albaran"].holded_doc_id = "hd_12345"
    db.commit()

    r2 = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=True)
    assert r2["ok"]
    assert r2["aviso_holded_previo"] is not None
    assert "hd_12345" in r2["aviso_holded_previo"]
    # El nuevo albarán no arrastra el holded_doc_id anterior
    assert r2["albaran"].holded_doc_id is None


def test_generar_refusa_sin_cliente_b2b(db, catalogo):
    producto, sabor = catalogo
    tienda = Tienda(nombre="Test Refusa B2B", es_franquicia=True, activa=True, codigo_albaran="RB")
    db.add(tienda)
    db.commit()
    fecha = date(2026, 7, 15)  # miércoles
    db.add(DiasReparto(tienda_id=tienda.id, dia_semana=fecha.weekday()))
    db.commit()
    _con_envio(db, tienda, producto, sabor, fecha)
    uid = _usuario_id(db)

    resultado = generar_albaran(db, tienda, fecha, uid, recrear=False)
    assert not resultado["ok"]
    assert resultado["albaran"] is None
    assert db.query(AlbaranFranquicia).filter(AlbaranFranquicia.tienda_id == tienda.id).count() == 0


def test_generar_refusa_producto_sin_precio(db, tienda_franquicia, cliente_b2b, producto_sin_precio, catalogo):
    _, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto_sin_precio, sabor, fecha)
    uid = _usuario_id(db)

    resultado = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    assert not resultado["ok"]
    assert db.query(AlbaranFranquicia).filter(AlbaranFranquicia.tienda_id == tienda_franquicia.id).count() == 0


# ── construir_items_snapshot / push a Holded ─────────────────────────────────

def test_construir_items_snapshot_usa_datos_congelados(db, tienda_franquicia, cliente_b2b, catalogo):
    producto, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=6)
    uid = _usuario_id(db)

    resultado = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    items = construir_items_snapshot(resultado["albaran"])
    assert items == [{
        "name": "Test Sabor Franquicia Test Tarta Franquicia",
        "desc": "", "units": 6.0, "subtotal": 12.5, "tax": 10,
    }]


def _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=6):
    producto, sabor = catalogo
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=cantidad)
    uid = _usuario_id(db)
    resultado = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    assert resultado["ok"]
    return resultado["albaran"]


def _holded_doc_id_en_bd(db, albaran_id):
    """Relee el albarán directamente de la BD (no el objeto en memoria), para
    comprobar que un commit (o la ausencia de uno) realmente ocurrió."""
    db.expire_all()
    return db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran_id).first().holded_doc_id


def test_push_a_holded_llama_crear_documento_y_guarda_doc_id(db, tienda_franquicia, cliente_b2b, catalogo):
    cliente_b2b.id_holded = "holded_contact_1"
    db.commit()
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=6)

    with patch("app.api.franquicias.crear_documento", return_value="doc_nuevo_123") as mock_crear:
        resultado = push_a_holded(db, albaran, cliente_b2b, "pat_testkey", recrear=False)

    mock_crear.assert_called_once_with(
        api_key="pat_testkey", contact_id="holded_contact_1",
        fecha=albaran.fecha, numero=albaran.numero,
        items=[{"name": "Test Sabor Franquicia Test Tarta Franquicia",
                "desc": "", "units": 6.0, "subtotal": 12.5, "tax": 10}],
        doc_tipo="waybill",
    )
    assert resultado == {"ok": True, "errores": [], "resultado": "holded_ok"}
    assert _holded_doc_id_en_bd(db, albaran.id) == "doc_nuevo_123"


def test_push_a_holded_si_crear_documento_falla_no_deja_escritura_parcial(db, tienda_franquicia, cliente_b2b, catalogo):
    cliente_b2b.id_holded = "holded_contact_1"
    db.commit()
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo)

    with patch("app.api.franquicias.crear_documento", side_effect=RuntimeError("Holded caído")) as mock_crear:
        resultado = push_a_holded(db, albaran, cliente_b2b, "pat_testkey", recrear=False)

    mock_crear.assert_called_once()
    assert resultado["ok"] is False
    assert "Holded caído" in resultado["errores"][0]
    assert _holded_doc_id_en_bd(db, albaran.id) is None


def test_push_a_holded_refusa_si_ya_tiene_doc_id_sin_recrear(db, tienda_franquicia, cliente_b2b, catalogo):
    cliente_b2b.id_holded = "holded_contact_1"
    db.commit()
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo)
    albaran.holded_doc_id = "doc_previo"
    db.commit()

    with patch("app.api.franquicias.crear_documento") as mock_crear:
        resultado = push_a_holded(db, albaran, cliente_b2b, "pat_testkey", recrear=False)

    mock_crear.assert_not_called()
    assert resultado["ok"] is False
    assert "ya tiene documento" in resultado["errores"][0]
    assert _holded_doc_id_en_bd(db, albaran.id) == "doc_previo"


def test_push_a_holded_refusa_si_cliente_sin_id_holded(db, tienda_franquicia, cliente_b2b, catalogo):
    cliente_b2b.id_holded = None
    db.commit()
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo)

    with patch("app.api.franquicias.crear_documento") as mock_crear:
        resultado = push_a_holded(db, albaran, cliente_b2b, "pat_testkey", recrear=False)

    mock_crear.assert_not_called()
    assert resultado["ok"] is False
    assert "ID de Holded" in resultado["errores"][0]
    assert _holded_doc_id_en_bd(db, albaran.id) is None


def test_push_a_holded_refusa_si_no_hay_api_key(db, tienda_franquicia, cliente_b2b, catalogo):
    cliente_b2b.id_holded = "holded_contact_1"
    db.commit()
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo)

    with patch("app.api.franquicias.crear_documento") as mock_crear:
        resultado = push_a_holded(db, albaran, cliente_b2b, "", recrear=False)

    mock_crear.assert_not_called()
    assert resultado["ok"] is False
    assert "API key" in resultado["errores"][0]
    assert _holded_doc_id_en_bd(db, albaran.id) is None


# ── Rutas HTTP: matriz real de permisos (Tarea 6 registró "franquicias") ─────

def test_rutas_albaranes_200_roles_con_permiso(db, como, tienda_franquicia):
    _fecha_con_reparto(db, tienda_franquicia)  # asegura reparto el martes 2026-07-14
    for rol in (Rol.JEFES, Rol.ADMINISTRACION, Rol.JEFE_PASTELEROS, Rol.PASTELERAS):
        c = como(rol)
        r_lista = c.get("/franquicias/albaranes?fecha=2026-07-14")
        assert r_lista.status_code == 200
        assert tienda_franquicia.nombre in r_lista.text

        r_preview = c.get(f"/franquicias/albaranes/{tienda_franquicia.id}")
        assert r_preview.status_code == 200

        r_post = c.post(f"/franquicias/albaranes/{tienda_franquicia.id}", data={"fecha": "2026-07-14"})
        assert r_post.status_code == 200

        r_holded = c.post(f"/franquicias/albaranes/{tienda_franquicia.id}/holded", data={"fecha": "2026-07-14"})
        assert r_holded.status_code == 200
        assert "Genera primero el albarán local" in r_holded.text


def test_rutas_albaranes_403_roles_sin_permiso(como, tienda_franquicia):
    for rol in (Rol.REPARTIDORES, Rol.COMERCIAL, Rol.AREA_MANAGER):
        c = como(rol)
        assert c.get("/franquicias/albaranes").status_code == 403
        assert c.get(f"/franquicias/albaranes/{tienda_franquicia.id}").status_code == 403
        assert c.post(f"/franquicias/albaranes/{tienda_franquicia.id}", data={"fecha": "2026-07-14"}).status_code == 403
        assert c.post(f"/franquicias/albaranes/{tienda_franquicia.id}/holded", data={"fecha": "2026-07-14"}).status_code == 403


# ── TIENDAS: acceso VER, limitado a su propia tienda_id ──────────────────────

def test_tiendas_lista_cruzada_404(como, tienda_franquicia):
    """La lista operativa cross-franquicia lista TODAS las franquicias:
    no es apropiada para un login de tienda (filtraría el negocio de otras)."""
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    assert c.get("/franquicias/albaranes").status_code == 404


def test_tiendas_ve_preview_de_su_propia_tienda(como, tienda_franquicia):
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get(f"/franquicias/albaranes/{tienda_franquicia.id}")
    assert r.status_code == 200


def test_tiendas_404_preview_de_otra_tienda(como, db, tienda_franquicia):
    otra = Tienda(nombre="Test Otra Franquicia", es_franquicia=True, activa=True, codigo_albaran="OF")
    db.add(otra)
    db.commit()
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get(f"/franquicias/albaranes/{otra.id}")
    assert r.status_code == 404


def test_tiendas_403_en_generar_y_holded_aunque_sea_su_tienda(como, tienda_franquicia):
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    assert c.post(f"/franquicias/albaranes/{tienda_franquicia.id}", data={"fecha": "2026-07-14"}).status_code == 403
    assert c.post(f"/franquicias/albaranes/{tienda_franquicia.id}/holded", data={"fecha": "2026-07-14"}).status_code == 403


def test_tiendas_ve_su_historial(como, db, tienda_franquicia, cliente_b2b, catalogo):
    _fecha_con_reparto(db, tienda_franquicia)
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo)
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get(f"/franquicias/albaranes/{tienda_franquicia.id}/historial")
    assert r.status_code == 200
    assert albaran.numero in r.text


def test_tiendas_404_historial_de_otra_tienda(como, db, tienda_franquicia):
    otra = Tienda(nombre="Test Otra Franquicia Hist", es_franquicia=True, activa=True, codigo_albaran="OH")
    db.add(otra)
    db.commit()
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get(f"/franquicias/albaranes/{otra.id}/historial")
    assert r.status_code == 404


def test_historial_solo_lista_albaranes_de_esa_tienda(como, db, cliente_b2b, catalogo):
    """Dos franquicias distintas: el historial de una no debe mostrar los
    albaranes de la otra."""
    ta = db.query(Tienda).filter(Tienda.nombre == "Test Historial A").first()
    if not ta:
        ta = Tienda(nombre="Test Historial A", es_franquicia=True, activa=True,
                    cliente_b2b_id=cliente_b2b.id, codigo_albaran="HA")
        db.add(ta)
        db.commit()
        db.refresh(ta)
    tb = db.query(Tienda).filter(Tienda.nombre == "Test Historial B").first()
    if not tb:
        tb = Tienda(nombre="Test Historial B", es_franquicia=True, activa=True,
                    cliente_b2b_id=cliente_b2b.id, codigo_albaran="HB")
        db.add(tb)
        db.commit()
        db.refresh(tb)

    alb_a = _albaran_generado(db, ta, cliente_b2b, catalogo, cantidad=1)
    alb_b = _albaran_generado(db, tb, cliente_b2b, catalogo, cantidad=1)

    c = como(Rol.JEFES)
    r = c.get(f"/franquicias/albaranes/{ta.id}/historial")
    assert r.status_code == 200
    assert alb_a.numero in r.text
    assert alb_b.numero not in r.text


def test_tiendas_ve_imprimir_de_su_propio_albaran(como, db, tienda_franquicia, cliente_b2b, catalogo):
    _fecha_con_reparto(db, tienda_franquicia)
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo)
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get(f"/franquicias/albaranes/{albaran.id}/imprimir")
    assert r.status_code == 200


def test_tiendas_404_imprimir_de_albaran_ajeno(como, db, tienda_franquicia, cliente_b2b, catalogo):
    otra = Tienda(nombre="Test Otra Franquicia Imp", es_franquicia=True, activa=True,
                  cliente_b2b_id=cliente_b2b.id, codigo_albaran="OI")
    db.add(otra)
    db.commit()
    db.refresh(otra)
    albaran_ajeno = _albaran_generado(db, otra, cliente_b2b, catalogo)

    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get(f"/franquicias/albaranes/{albaran_ajeno.id}/imprimir")
    assert r.status_code == 404


def test_tiendas_404_imprimir_albaran_inexistente(como, tienda_franquicia):
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get("/franquicias/albaranes/999999/imprimir")
    assert r.status_code == 404


def test_mis_albaranes_redirige_tienda_a_su_historial(como, tienda_franquicia):
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    r = c.get("/franquicias/mis-albaranes")
    assert r.status_code == 302
    assert r.headers["location"] == f"/franquicias/albaranes/{tienda_franquicia.id}/historial"


def test_mis_albaranes_redirige_staff_a_lista_operativa(como):
    c = como(Rol.JEFES)
    r = c.get("/franquicias/mis-albaranes")
    assert r.status_code == 302
    assert r.headers["location"] == "/franquicias/albaranes"


# ── Impresión: cantidades sí, importes no ────────────────────────────────────

# ── editar_lineas_albaran: recalculo local, sin tocar Holded ─────────────────

def test_editar_lineas_actualiza_cantidades_y_recalcula_totales(db, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=6)
    linea1 = albaran.lineas[0]
    linea2 = LineaAlbaranFranquicia(
        albaran_id=albaran.id, producto_id=linea1.producto_id, sabor_id=linea1.sabor_id,
        producto_nombre="Otro producto", sabor_nombre="Otro sabor",
        descripcion="Otro sabor Otro producto", cantidad=2, precio_unit=3.0,
    )
    db.add(linea2)
    db.commit()
    db.refresh(albaran)
    uid = _usuario_id(db)

    assert albaran.actualizado_en is None
    assert albaran.actualizado_por is None

    resultado = editar_lineas_albaran(db, albaran, {linea1.id: 10, linea2.id: 5}, uid)
    assert resultado["ok"]

    db.expire_all()
    albaran = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
    lineas_por_id = {l.id: l for l in albaran.lineas}
    assert lineas_por_id[linea1.id].cantidad == 10
    assert lineas_por_id[linea2.id].cantidad == 5
    # 10*12.5 + 5*3.0 = 140.0 ; IVA 10% = 14.0 ; total = 154.0
    assert albaran.total_sin_iva == pytest.approx(140.0)
    assert albaran.total_iva == pytest.approx(14.0)
    assert albaran.total == pytest.approx(154.0)
    assert albaran.actualizado_en is not None
    assert albaran.actualizado_por == uid


def test_editar_lineas_falla_si_faltan_cantidades(db, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=6)
    linea = albaran.lineas[0]
    uid = _usuario_id(db)

    resultado = editar_lineas_albaran(db, albaran, {}, uid)
    assert not resultado["ok"]
    assert resultado["errores"]

    db.expire_all()
    albaran = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
    assert albaran.lineas[0].cantidad == 6  # no se tocó nada
    assert albaran.actualizado_en is None


def test_editar_lineas_no_toca_holded_doc_id(db, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=6)
    albaran.holded_doc_id = "doc_previo"
    db.commit()
    linea = albaran.lineas[0]
    uid = _usuario_id(db)

    resultado = editar_lineas_albaran(db, albaran, {linea.id: 9}, uid)
    assert resultado["ok"]
    assert _holded_doc_id_en_bd(db, albaran.id) == "doc_previo"


# ── Rutas HTTP de edición: solo JEFES/ADMINISTRACION, pese a EDITAR ──────────

def test_editar_rutas_200_jefes_y_administracion(db, como, tienda_franquicia, cliente_b2b, catalogo):
    for rol in (Rol.JEFES, Rol.ADMINISTRACION):
        albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
        linea = albaran.lineas[0]
        c = como(rol)

        r_get = c.get(f"/franquicias/albaranes/{albaran.id}/editar")
        assert r_get.status_code == 200

        r_post = c.post(
            f"/franquicias/albaranes/{albaran.id}/editar",
            data={"linea_id": [str(linea.id)], "cantidad": ["9"]},
        )
        assert r_post.status_code == 302

        db.expire_all()
        albaran_actualizado = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
        assert albaran_actualizado.lineas[0].cantidad == 9
        db.delete(albaran_actualizado)
        db.commit()


def test_editar_rutas_403_pasteleras_y_jefe_pasteleros_pese_a_editar(db, como, tienda_franquicia, cliente_b2b, catalogo):
    """PASTELERAS y JEFE_PASTELEROS tienen Nivel.EDITAR en "franquicias" (para
    generar/enviar a Holded) pero NO deben poder editar a mano las cantidades
    de un albarán ya generado: es la regla de negocio central de esta tarea."""
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
    linea = albaran.lineas[0]
    for rol in (Rol.PASTELERAS, Rol.JEFE_PASTELEROS):
        c = como(rol)
        assert c.get(f"/franquicias/albaranes/{albaran.id}/editar").status_code == 403
        assert c.post(
            f"/franquicias/albaranes/{albaran.id}/editar",
            data={"linea_id": [str(linea.id)], "cantidad": ["99"]},
        ).status_code == 403

    db.expire_all()
    albaran_sin_tocar = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
    assert albaran_sin_tocar.lineas[0].cantidad == 4


def test_editar_rutas_403_tiendas(db, como, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
    linea = albaran.lineas[0]
    c = como(Rol.TIENDAS, tienda_id=tienda_franquicia.id)
    assert c.get(f"/franquicias/albaranes/{albaran.id}/editar").status_code == 403
    assert c.post(
        f"/franquicias/albaranes/{albaran.id}/editar",
        data={"linea_id": [str(linea.id)], "cantidad": ["9"]},
    ).status_code == 403


def test_editar_get_muestra_aviso_si_ya_esta_en_holded(db, como, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
    albaran.holded_doc_id = "doc_ya_en_holded"
    db.commit()
    c = como(Rol.JEFES)

    r = c.get(f"/franquicias/albaranes/{albaran.id}/editar")
    assert r.status_code == 200
    assert "doc_ya_en_holded" in r.text
    assert "Holded" in r.text


def test_editar_post_permite_guardar_aunque_ya_este_en_holded_sin_alterar_doc_id(db, como, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
    albaran.holded_doc_id = "doc_ya_en_holded"
    db.commit()
    linea = albaran.lineas[0]
    c = como(Rol.JEFES)

    r = c.post(
        f"/franquicias/albaranes/{albaran.id}/editar",
        data={"linea_id": [str(linea.id)], "cantidad": ["7"]},
    )
    assert r.status_code == 302

    db.expire_all()
    albaran_actualizado = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
    assert albaran_actualizado.lineas[0].cantidad == 7
    assert albaran_actualizado.holded_doc_id == "doc_ya_en_holded"  # no lo tocó


def test_editar_post_rechaza_cantidad_negativa(db, como, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
    linea = albaran.lineas[0]
    c = como(Rol.JEFES)

    r = c.post(
        f"/franquicias/albaranes/{albaran.id}/editar",
        data={"linea_id": [str(linea.id)], "cantidad": ["-1"]},
    )
    assert r.status_code == 200
    assert "negativ" in r.text.lower()

    db.expire_all()
    albaran_sin_tocar = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
    assert albaran_sin_tocar.lineas[0].cantidad == 4
    assert albaran_sin_tocar.actualizado_en is None


def test_editar_post_rechaza_cantidad_no_numerica(db, como, tienda_franquicia, cliente_b2b, catalogo):
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
    linea = albaran.lineas[0]
    c = como(Rol.JEFES)

    r = c.post(
        f"/franquicias/albaranes/{albaran.id}/editar",
        data={"linea_id": [str(linea.id)], "cantidad": ["abc"]},
    )
    assert r.status_code == 200
    assert "número" in r.text.lower() or "numer" in r.text.lower()

    db.expire_all()
    albaran_sin_tocar = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
    assert albaran_sin_tocar.lineas[0].cantidad == 4


def test_editar_post_rechaza_linea_id_no_numerico(db, como, tienda_franquicia, cliente_b2b, catalogo):
    """Un linea_id manipulado (no numérico) debe dar un error controlado, no un 500."""
    albaran = _albaran_generado(db, tienda_franquicia, cliente_b2b, catalogo, cantidad=4)
    c = como(Rol.JEFES)

    r = c.post(
        f"/franquicias/albaranes/{albaran.id}/editar",
        data={"linea_id": ["abc"], "cantidad": ["3"]},
    )
    assert r.status_code == 200
    assert "número" in r.text.lower() or "numer" in r.text.lower()

    db.expire_all()
    albaran_sin_tocar = db.query(AlbaranFranquicia).filter(AlbaranFranquicia.id == albaran.id).first()
    assert albaran_sin_tocar.lineas[0].cantidad == 4


def test_editar_get_404_albaran_inexistente(como):
    c = como(Rol.JEFES)
    assert c.get("/franquicias/albaranes/999999/editar").status_code == 404


def test_print_html_muestra_importes_y_datos_emisor(db, tienda_franquicia, cliente_b2b, catalogo):
    from fastapi.templating import Jinja2Templates
    producto, sabor = catalogo
    cliente_b2b.id_holded = "abc123"
    db.commit()
    fecha = _fecha_con_reparto(db, tienda_franquicia)
    _con_envio(db, tienda_franquicia, producto, sabor, fecha, cantidad=6)
    uid = _usuario_id(db)
    resultado = generar_albaran(db, tienda_franquicia, fecha, uid, recrear=False)
    albaran = resultado["albaran"]

    from app.api.franquicias import _get_empresa_config
    empresa = _get_empresa_config(db)
    templates = Jinja2Templates(directory="app/templates")
    tmpl = templates.get_template("franquicias/albaran_print.html")
    html = tmpl.render(
        albaran=albaran, tienda=tienda_franquicia, cliente=cliente_b2b,
        empresa=empresa,
    )
    # Descripción y cantidad
    assert "Test Sabor Franquicia Test Tarta Franquicia" in html
    assert "6" in html
    # Importes: precio unitario, base, IVA y total con símbolo €
    assert "€" in html
    assert f"{albaran.total_sin_iva:.2f} €" in html
    assert f"{albaran.total_iva:.2f} €" in html
    assert f"{albaran.total:.2f} €" in html
    # Datos sociales del emisor (Obrador Demo)
    assert (empresa["razon_social"] or "") in html
