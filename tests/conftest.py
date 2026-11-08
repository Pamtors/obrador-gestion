"""Fixtures de test: app con BD SQLite temporal y clientes autenticados por rol."""
import os
import tempfile

os.environ["SECRET_KEY"] = "clave-test"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["ADMIN_PASSWORD"] = "x"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app.main import app
from app.auth.contrasena import hashear
from app.auth.sesion import crear_token_sesion
from app.models.usuario import Rol, Usuario
from app.models.tienda import Tienda


@pytest.fixture(scope="session", autouse=True)
def _crear_tablas():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def tienda(db):
    t = db.query(Tienda).filter(Tienda.nombre == "Test Carretería").first()
    if not t:
        t = Tienda(nombre="Test Carretería")
        db.add(t)
        db.commit()
        db.refresh(t)
    return t


@pytest.fixture()
def tienda2(db):
    t = db.query(Tienda).filter(Tienda.nombre == "Test Larios").first()
    if not t:
        t = Tienda(nombre="Test Larios")
        db.add(t)
        db.commit()
        db.refresh(t)
    return t


def _crear_usuario(db, rol: Rol, tienda_id: int | None = None) -> Usuario:
    email = f"{rol.value.lower()}_{tienda_id or 0}@test.com"
    u = db.query(Usuario).filter(Usuario.email == email).first()
    if not u:
        u = Usuario(nombre=f"Test {rol.value}", email=email,
                    hash_contrasena=hashear("1234"), rol=rol, tienda_id=tienda_id)
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


@pytest.fixture()
def como():
    """Devuelve una factoría: como(rol, tienda_id=None) → TestClient autenticado."""
    def _factory(rol: Rol, tienda_id: int | None = None) -> TestClient:
        s = SessionLocal()
        try:
            u = _crear_usuario(s, rol, tienda_id)
            token = crear_token_sesion(u.id)
        finally:
            s.close()
        c = TestClient(app, follow_redirects=False)
        c.cookies.set("sesion", token)
        return c
    return _factory


@pytest.fixture()
def anonimo():
    return TestClient(app, follow_redirects=False)
