"""Tests de los helpers de tiendas de congelados: ciclo de días que cubre un
reparto, reposición del congelador (Σ objetivo de vitrina del ciclo − congelador
contado 2 días antes) y descongelación nocturna (objetivo de mañana − vitrina)."""
from datetime import date, timedelta

from app.api.stock import (
    _dias_ciclo_congelado, descongelacion_congelado, reposicion_congelado,
)
from app.auth.contrasena import hashear
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.stock import (
    DiasReparto, LineaParteCongelador, LineaParteStock, ParteCongelador,
    ParteStock, PrevisionStock,
)
from app.models.tienda import Tienda
from app.models.usuario import Rol, Usuario

LUN, MAR, MIE, JUE, VIE, SAB, DOM = 0, 1, 2, 3, 4, 5, 6
_MARTES = date(2026, 7, 21)   # martes
_VIERNES = date(2026, 7, 24)  # viernes


def _usuario(db) -> int:
    u = db.query(Usuario).filter(Usuario.email == "congelado_helper@test.com").first()
    if not u:
        u = Usuario(nombre="Test Congelado", email="congelado_helper@test.com",
                    hash_contrasena=hashear("1234"), rol=Rol.JEFES)
        db.add(u); db.commit()
    return u.id


def _prod_sabor(db, sufijo):
    p = db.query(Producto).filter(Producto.nombre == f"Cong Prod {sufijo}").first()
    if not p:
        p = Producto(nombre=f"Cong Prod {sufijo}"); db.add(p); db.commit()
    s = db.query(Sabor).filter(Sabor.nombre == f"Cong Sabor {sufijo}").first()
    if not s:
        s = Sabor(nombre=f"Cong Sabor {sufijo}"); db.add(s); db.commit()
    return p.id, s.id


def _tienda_congelados(db, nombre, dias):
    t = db.query(Tienda).filter(Tienda.nombre == nombre).first()
    if not t:
        t = Tienda(nombre=nombre, es_congelados=True); db.add(t); db.commit(); db.refresh(t)
    for d in dias:
        if not db.query(DiasReparto).filter(
                DiasReparto.tienda_id == t.id, DiasReparto.dia_semana == d).first():
            db.add(DiasReparto(tienda_id=t.id, dia_semana=d))
    db.commit()
    return t


# ─── ciclo (función pura) ───────────────────────────────────────────────────

def test_ciclo_dos_repartos_semana():
    # reparto martes+viernes: el del martes cubre mar, mié, jue (3 días)
    assert _dias_ciclo_congelado({MAR, VIE}, _MARTES) == [
        _MARTES, _MARTES + timedelta(days=1), _MARTES + timedelta(days=2)]
    # el del viernes cubre vie, sáb, dom, lun (4 días)
    assert _dias_ciclo_congelado({MAR, VIE}, _VIERNES) == [
        _VIERNES + timedelta(days=i) for i in range(4)]


def test_ciclo_un_reparto_semana_cubre_siete_dias():
    dias = _dias_ciclo_congelado({MAR}, _MARTES)
    assert len(dias) == 7


# ─── reposición del congelador ──────────────────────────────────────────────

def test_reposicion_suma_ciclo_menos_congelador(db):
    pid, sid = _prod_sabor(db, "A")
    uid = _usuario(db)
    t = _tienda_congelados(db, "Test Cong A", {MAR, VIE})

    # objetivo de vitrina: mar=5, mié=4, jue=6 → Σ ciclo del martes = 15
    for dia, cant in [(MAR, 5), (MIE, 4), (JUE, 6)]:
        db.add(PrevisionStock(tienda_id=t.id, dia_semana=dia,
                              producto_id=pid, sabor_id=sid, cantidad=cant))
    db.commit()

    # congelador contado 2 días antes del reparto (martes 21 → conteo domingo 19)
    conteo = ParteCongelador(fecha=_MARTES - timedelta(days=2), tienda_id=t.id, usuario_id=uid)
    db.add(conteo); db.commit()
    db.add(LineaParteCongelador(parte_congelador_id=conteo.id, producto_id=pid, sabor_id=sid, cantidad=4))
    db.commit()

    rep = reposicion_congelado(db, t, _MARTES)
    assert rep[(pid, sid)] == 15 - 4  # 11


def test_reposicion_sin_congelador_contado_es_todo_el_objetivo(db):
    pid, sid = _prod_sabor(db, "B")
    t = _tienda_congelados(db, "Test Cong B", {MAR, VIE})
    db.add(PrevisionStock(tienda_id=t.id, dia_semana=MAR,
                          producto_id=pid, sabor_id=sid, cantidad=8))
    db.commit()
    # martes cubre mar+mié+jue, pero solo hay objetivo el martes → Σ = 8, sin conteo
    rep = reposicion_congelado(db, t, _MARTES)
    assert rep[(pid, sid)] == 8


# ─── descongelación nocturna ────────────────────────────────────────────────

def test_descongelacion_objetivo_manana_menos_vitrina(db):
    pid, sid = _prod_sabor(db, "C")
    uid = _usuario(db)
    t = _tienda_congelados(db, "Test Cong C", {MAR, VIE})

    # objetivo de vitrina del martes = 5; la noche del lunes se descongela para el martes
    db.add(PrevisionStock(tienda_id=t.id, dia_semana=MAR,
                          producto_id=pid, sabor_id=sid, cantidad=5))
    noche = _MARTES - timedelta(days=1)  # lunes
    parte = ParteStock(fecha=noche, tienda_id=t.id, usuario_id=uid)
    db.add(parte); db.commit()
    db.add(LineaParteStock(parte_stock_id=parte.id, producto_id=pid, sabor_id=sid,
                           cantidad=2, raciones=0))
    db.commit()

    desc = descongelacion_congelado(db, t, noche)
    assert desc[(pid, sid)] == 5 - 2  # 3


def test_descongelacion_vitrina_completa_no_aparece(db):
    pid, sid = _prod_sabor(db, "D")
    uid = _usuario(db)
    t = _tienda_congelados(db, "Test Cong D", {MAR, VIE})
    db.add(PrevisionStock(tienda_id=t.id, dia_semana=MAR,
                          producto_id=pid, sabor_id=sid, cantidad=5))
    noche = _MARTES - timedelta(days=1)
    parte = ParteStock(fecha=noche, tienda_id=t.id, usuario_id=uid)
    db.add(parte); db.commit()
    db.add(LineaParteStock(parte_stock_id=parte.id, producto_id=pid, sabor_id=sid,
                           cantidad=5, raciones=0))
    db.commit()

    desc = descongelacion_congelado(db, t, noche)
    assert (pid, sid) not in desc
