# Plan de implementación: Sistema de permisos por puesto

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir los 5 roles + `@requiere_rol` por 8 puestos con matriz central de permisos (NADA/VER/EDITAR por servicio y subapartado) y ámbito por tienda, según `docs/PERMISOS_SPEC.md`.

**Architecture:** Matriz `PERMISOS` única en `app/auth/permisos.py`, decorador `@requiere_permiso("clave", editar=bool)` que sustituye a `@requiere_rol` endpoint a endpoint, helpers `puede()`/`puede_editar()` en `UsuarioSesion` para plantillas, migración Alembic de datos del enum.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + SQLite + Jinja2. Tests: pytest + fastapi TestClient (httpx).

**Working dir:** `obrador-gestion`. Ejecutar pytest con el venv del proyecto: `venv\Scripts\python -m pytest`.

---

## Mapa de claves de permiso

| Clave | Endpoints (router prefix) |
|---|---|
| `clientes` | `/clientes/*` |
| `pedidos` (= bandeja) | `/pedidos/`, `/pedidos/{id}`, `/pedidos/crear`, `/pedidos/{id}/editar`, `/pedidos/{id}/eliminar` |
| `pedidos.rutas` | `/pedidos/rutas` |
| `impresion` | `/imprimir/*` |
| `stock.partes` | `/stock/`, `/stock/nuevo`, `/stock/{parte_id}`, `/stock/{parte_id}/editar`, `/stock/{parte_id}/cerrar` |
| `stock.envios` | `/stock/envios/` |
| `stock.mermas` | `/stock/mermas/*` |
| `stock.prevision` | `/stock/prevision/*`, `/stock/necesidades/` |
| `stock.dias_reparto` | `/stock/reparto/*` |
| `produccion` | `/produccion/*` |
| `holded` | `/holded/*` |
| `catalogo` | `/catalogo/*` |
| `admin` | `/usuarios/*`, `/tiendas/*` |

Regla de resolución: se busca la clave exacta; si no existe, la clave del servicio (parte antes del punto); si tampoco, `NADA`.

---

### Task 1: Infraestructura de tests

**Files:**
- Create: `tests/__init__.py` (vacío)
- Create: `tests/conftest.py`
- Create: `tests/test_infra.py`
- Modify: `requirements.txt` (añadir pytest y httpx si faltan)

- [ ] **Step 1: Instalar dependencias de test**

```bash
venv\Scripts\pip install pytest httpx
```

Añadir a `requirements.txt` (si no están): `pytest` y `httpx`.

- [ ] **Step 2: Escribir conftest.py**

El config es un singleton que lee `.env` al importar, así que fijamos las variables de entorno ANTES de importar la app, y apuntamos la BD a un fichero temporal.

```python
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
```

Nota: si `Tienda` tiene campos obligatorios adicionales (mirar `app/models/tienda.py`), añadirlos en las fixtures con valores dummy.

- [ ] **Step 3: Test de humo**

`tests/test_infra.py`:

```python
from app.models.usuario import Rol


def test_sin_sesion_redirige_a_login(anonimo):
    r = anonimo.get("/")
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_con_sesion_inicio_carga(como):
    r = como(Rol.ADMIN).get("/")
    assert r.status_code == 200
```

- [ ] **Step 4: Ejecutar**

Run: `venv\Scripts\python -m pytest tests/test_infra.py -v` (desde `obrador-gestion`)
Expected: 2 PASS. (Este test usa `Rol.ADMIN`, que aún existe; en la Task 2 se actualizará a `Rol.JEFES`.)

- [ ] **Step 5: Commit**

```bash
git add tests/ requirements.txt
git commit -m "test: infraestructura de tests con BD temporal y clientes por rol"
```

---

### Task 2: Enum de 8 puestos + migración de datos

**Files:**
- Modify: `app/models/usuario.py:13-19` (enum)
- Modify: todas las referencias `Rol.ADMIN/OFICINA/TIENDA/OBRADOR/REPARTO` en `app/api/*.py`, `app/auth/permisos.py`, `scripts/*.py`
- Modify: plantillas que comparan `usuario.rol` con strings (se dejan funcionando con los nombres nuevos; la conversión a `puede()` llega en Task 8)
- Create: `alembic/versions/<hash>_ocho_puestos.py`
- Test: `tests/test_infra.py` (actualizar) 

Mapeo: `ADMIN→JEFES`, `OFICINA→ADMINISTRACION`, `TIENDA→TIENDAS`, `OBRADOR→PASTELERAS`, `REPARTO→REPARTIDORES`. Nuevos: `JEFE_PASTELEROS`, `AREA_MANAGER`, `COMERCIAL`.

- [ ] **Step 1: Nuevo enum en `app/models/usuario.py`**

```python
class Rol(str, enum.Enum):
    """Puesto que determina los permisos del usuario (ver app/auth/permisos.py)."""
    REPARTIDORES = "REPARTIDORES"
    JEFES = "JEFES"
    ADMINISTRACION = "ADMINISTRACION"
    PASTELERAS = "PASTELERAS"
    JEFE_PASTELEROS = "JEFE_PASTELEROS"
    TIENDAS = "TIENDAS"
    AREA_MANAGER = "AREA_MANAGER"
    COMERCIAL = "COMERCIAL"


# Nombres legibles para desplegables y listados
ROL_NOMBRES = {
    Rol.REPARTIDORES: "Repartidores",
    Rol.JEFES: "Jefes",
    Rol.ADMINISTRACION: "Administración",
    Rol.PASTELERAS: "Pasteleras",
    Rol.JEFE_PASTELEROS: "Jefe pasteleros",
    Rol.TIENDAS: "Tiendas",
    Rol.AREA_MANAGER: "Area Manager",
    Rol.COMERCIAL: "Comercial",
}
```

Actualizar también el comentario de `tienda_id` («Solo relevante para rol TIENDAS»).

- [ ] **Step 2: Renombrar referencias en Python**

Buscar con `grep -rn "Rol\.\(ADMIN\|OFICINA\|TIENDA\|OBRADOR\|REPARTO\)\b" app/ scripts/` y sustituir según el mapeo (¡cuidado: `Rol.TIENDA` → `Rol.TIENDAS`, no confundir con `Rol.TIENDAS` ya sustituido!). Afecta como mínimo a: `app/api/*.py` (decoradores y filtros internos de stock.py/imprimir.py), `app/auth/permisos.py` (docstring), `scripts/seed.py`, `scripts/seed_simulacro.py`, y donde se cree el admin inicial (buscar `admin_email`).

- [ ] **Step 3: Renombrar strings de rol en plantillas**

En `app/templates/base.html`, `inicio.html`, `stock/index.html`, `stock/mermas.html` (y cualquier otra que salga con `grep -rn '"ADMIN"\|"OFICINA"\|"TIENDA"\|"OBRADOR"' app/templates/`): sustituir `"ADMIN"→"JEFES"`, `"OFICINA"→"ADMINISTRACION"`, `"TIENDA"→"TIENDAS"`, `"OBRADOR"→"PASTELERAS"`. (Temporal: en Task 8 estas comparaciones desaparecen en favor de `puede()`.)

- [ ] **Step 4: Migración Alembic**

`alembic revision -m "ocho_puestos"`. El enum en SQLite es VARCHAR con CHECK, así que hay que recrear la columna con batch mode además de actualizar los datos:

```python
import sqlalchemy as sa
from alembic import op

MAPEO = {"ADMIN": "JEFES", "OFICINA": "ADMINISTRACION", "TIENDA": "TIENDAS",
         "OBRADOR": "PASTELERAS", "REPARTO": "REPARTIDORES"}
NUEVOS = ["REPARTIDORES", "JEFES", "ADMINISTRACION", "PASTELERAS",
          "JEFE_PASTELEROS", "TIENDAS", "AREA_MANAGER", "COMERCIAL"]


def upgrade():
    # 1) Quitar la restricción vieja recreando la columna como String plano
    with op.batch_alter_table("usuarios") as b:
        b.alter_column("rol", type_=sa.String(20), existing_nullable=False)
    # 2) Migrar los datos
    for viejo, nuevo in MAPEO.items():
        op.execute(f"UPDATE usuarios SET rol = '{nuevo}' WHERE rol = '{viejo}'")
    # 3) Volver a poner el enum con los 8 valores
    with op.batch_alter_table("usuarios") as b:
        b.alter_column("rol", type_=sa.Enum(*NUEVOS, name="rol"), existing_nullable=False)


def downgrade():
    with op.batch_alter_table("usuarios") as b:
        b.alter_column("rol", type_=sa.String(20), existing_nullable=False)
    for viejo, nuevo in MAPEO.items():
        op.execute(f"UPDATE usuarios SET rol = '{viejo}' WHERE rol = '{nuevo}'")
    # Los puestos nuevos no existen en el enum viejo: degradar a OFICINA
    op.execute("UPDATE usuarios SET rol = 'OFICINA' WHERE rol IN "
               "('JEFE_PASTELEROS', 'AREA_MANAGER', 'COMERCIAL')")
    viejos = ["ADMIN", "OFICINA", "TIENDA", "OBRADOR", "REPARTO"]
    with op.batch_alter_table("usuarios") as b:
        b.alter_column("rol", type_=sa.Enum(*viejos, name="rol"), existing_nullable=False)
```

- [ ] **Step 5: Actualizar tests/test_infra.py** (`Rol.ADMIN` → `Rol.JEFES`) y ejecutar

Run: `venv\Scripts\python -m pytest -v` → PASS.
Run: `venv\Scripts\alembic upgrade head` (con backup previo de `obrador.db` en `backups/`).
Verificar: `SELECT DISTINCT rol FROM usuarios;` solo devuelve valores nuevos.
Arrancar `iniciar.bat` y hacer login con un usuario existente → la app funciona igual que antes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: enum de 8 puestos con migracion de datos"
```

---

### Task 3: Matriz PERMISOS y resolución de niveles

**Files:**
- Modify: `app/auth/permisos.py` (añadir `Nivel`, `PERMISOS`, `nivel_permiso`)
- Test: `tests/test_matriz.py`

- [ ] **Step 1: Test de la matriz (escribirlo primero)**

`tests/test_matriz.py`:

```python
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
```

Run: `venv\Scripts\python -m pytest tests/test_matriz.py -v` → FAIL (Nivel no existe).

- [ ] **Step 2: Implementar en `app/auth/permisos.py`**

```python
class Nivel(enum.IntEnum):
    """Nivel de acceso a un servicio/subapartado."""
    NADA = 0
    VER = 1      # consulta: GET sí, POST no, sin botones de edición
    EDITAR = 2


_TODO_JEFES = {"clientes": Nivel.EDITAR, "pedidos": Nivel.EDITAR, "pedidos.rutas": Nivel.EDITAR,
               "impresion": Nivel.EDITAR, "stock": Nivel.EDITAR, "produccion": Nivel.EDITAR,
               "holded": Nivel.EDITAR, "catalogo": Nivel.EDITAR, "admin": Nivel.EDITAR}

# Matriz de permisos (docs/PERMISOS_SPEC.md). Clave = "servicio" o "servicio.subapartado".
# Resolución: clave exacta > clave del servicio > NADA.
PERMISOS: dict[Rol, dict[str, Nivel]] = {
    Rol.JEFES: _TODO_JEFES,
    Rol.ADMINISTRACION: {**_TODO_JEFES, "admin": Nivel.NADA},
    Rol.REPARTIDORES: {
        "pedidos.rutas": Nivel.EDITAR,
        "impresion": Nivel.EDITAR,
        "stock.envios": Nivel.EDITAR,
    },
    Rol.PASTELERAS: {
        "pedidos": Nivel.VER,
        "pedidos.rutas": Nivel.NADA,
        "impresion": Nivel.EDITAR,
        "stock.partes": Nivel.EDITAR,
        "stock.envios": Nivel.EDITAR,
        "stock.dias_reparto": Nivel.VER,
        "produccion": Nivel.EDITAR,
    },
    Rol.JEFE_PASTELEROS: {
        "pedidos": Nivel.EDITAR, "pedidos.rutas": Nivel.EDITAR,
        "impresion": Nivel.EDITAR, "stock": Nivel.EDITAR,
        "produccion": Nivel.EDITAR, "catalogo": Nivel.EDITAR,
    },
    Rol.TIENDAS: {  # además, todo limitado a su tienda_id (se aplica en los endpoints)
        "pedidos": Nivel.VER,
        "pedidos.rutas": Nivel.NADA,
        "stock.partes": Nivel.EDITAR,
        "stock.envios": Nivel.EDITAR,
        "stock.mermas": Nivel.EDITAR,
        "stock.dias_reparto": Nivel.VER,
    },
    Rol.AREA_MANAGER: {"pedidos": Nivel.EDITAR, "pedidos.rutas": Nivel.EDITAR,
                       "stock": Nivel.EDITAR},
    Rol.COMERCIAL: {"clientes": Nivel.EDITAR, "pedidos": Nivel.EDITAR,
                    "pedidos.rutas": Nivel.NADA},
}


def nivel_permiso(rol: Rol, clave: str) -> Nivel:
    """Nivel de un rol para una clave: exacta > servicio > NADA."""
    permisos = PERMISOS.get(rol, {})
    if clave in permisos:
        return permisos[clave]
    servicio = clave.split(".")[0]
    return permisos.get(servicio, Nivel.NADA)
```

Añadir `import enum` arriba si falta.

- [ ] **Step 3: Ejecutar y commit**

Run: `venv\Scripts\python -m pytest tests/test_matriz.py -v` → PASS.

```bash
git add app/auth/permisos.py tests/test_matriz.py
git commit -m "feat: matriz central de permisos con niveles NADA/VER/EDITAR"
```

---

### Task 4: Decorador `requiere_permiso` y helpers de plantilla

**Files:**
- Modify: `app/auth/permisos.py`
- Test: `tests/test_decorador.py`

- [ ] **Step 1: Test primero**

`tests/test_decorador.py` (app FastAPI mínima para probar el decorador aislado):

```python
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth.permisos import requiere_permiso
from app.auth.sesion import crear_token_sesion
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
    # PASTELERAS tiene stock.dias_reparto VER: GET sí, POST no. Probamos con
    # una clave VER real usando el decorador de /editar sobre mermas (NADA para
    # PASTELERAS) y el GET de dias_reparto en la Task 7. Aquí: NADA en POST.
    c = _cliente(como, Rol.PASTELERAS)               # stock.mermas NADA
    assert c.post("/editar").status_code == 403
```

Run: `venv\Scripts\python -m pytest tests/test_decorador.py -v` → FAIL (`requiere_permiso` no existe).

- [ ] **Step 2: Implementar decorador y helpers en `app/auth/permisos.py`**

```python
def requiere_permiso(clave: str, editar: bool = False) -> Callable:
    """Exige nivel VER (o EDITAR si editar=True) para la clave de permiso.
    Sin sesión → redirect a /login; nivel insuficiente → 403.
    Deja el usuario en request.state.usuario."""
    minimo = Nivel.EDITAR if editar else Nivel.VER

    def decorador(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            usuario = obtener_usuario_actual(request)
            if not usuario:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url="/login", status_code=302)
            if nivel_permiso(usuario.rol, clave) < minimo:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes permiso para acceder a esta sección.",
                )
            request.state.usuario = usuario
            return await func(request, *args, **kwargs)
        return wrapper
    return decorador
```

Y en `UsuarioSesion` (misma dataclass, añadir métodos):

```python
    def puede(self, clave: str) -> bool:
        return nivel_permiso(self.rol, clave) >= Nivel.VER

    def puede_editar(self, clave: str) -> bool:
        return nivel_permiso(self.rol, clave) >= Nivel.EDITAR

    def puede_servicio(self, servicio: str) -> bool:
        """True si tiene acceso al servicio o a ALGÚN subapartado (para el menú)."""
        permisos = PERMISOS.get(self.rol, {})
        if permisos.get(servicio, Nivel.NADA) >= Nivel.VER:
            return True
        return any(k.startswith(servicio + ".") and n >= Nivel.VER
                   for k, n in permisos.items())
```

- [ ] **Step 3: Ejecutar y commit**

Run: `venv\Scripts\python -m pytest -v` → PASS (toda la suite).

```bash
git add app/auth/permisos.py tests/test_decorador.py
git commit -m "feat: decorador requiere_permiso y helpers puede/puede_editar"
```

---

### Task 5: Migrar routers simples (clientes, catálogo, tiendas, usuarios, holded, producción, impresión)

**Files:**
- Modify: `app/api/clientes.py`, `catalogo.py`, `tiendas.py`, `usuarios.py`, `holded.py`, `produccion.py`, `imprimir.py`, `inicio.py`
- Test: `tests/test_acceso_servicios.py`

Sustituir cada `@requiere_rol(...)` por `@requiere_permiso(...)` según esta tabla (GET de consulta → sin `editar`; POST y GET de formularios de alta/edición → `editar=True`):

| Fichero | Endpoints | Decorador nuevo |
|---|---|---|
| `inicio.py:14` | `GET /` | `@requiere_sesion` (nuevo decorador que solo exige estar autenticado, ver Step 1) |
| `clientes.py` (5) | GET `/`, GET `/{id}` | `@requiere_permiso("clientes")` |
| | POST `/crear`, POST `/{id}/editar`, POST `/{id}/toggle` | `@requiere_permiso("clientes", editar=True)` |
| `catalogo.py` (15) | GET `/sabores`, GET `/productos` | `@requiere_permiso("catalogo")` |
| | los 13 POST | `@requiere_permiso("catalogo", editar=True)` |
| `tiendas.py` (6) | GET `/` | `@requiere_permiso("admin")` |
| | los 5 POST | `@requiere_permiso("admin", editar=True)` |
| `usuarios.py` (3) | GET `/` | `@requiere_permiso("admin")` |
| | POST `/crear`, POST `/{usuario_id}/toggleactivo` | `@requiere_permiso("admin", editar=True)` |
| `holded.py` (8) | GET `/`, GET `/config`, GET `/sync`, GET `/albaran/{id}` | `@requiere_permiso("holded")` |
| | POST `/config`, `/sync`, `/crear-todos`, `/albaran/{id}` | `@requiere_permiso("holded", editar=True)` |
| `produccion.py` (2) | GET `/` | `@requiere_permiso("produccion")` |
| | POST `/` | `@requiere_permiso("produccion", editar=True)` |
| `imprimir.py` (9) | GET `/`, `/pegatinas/config`, `/pegatinas/dia`, `/pegatinas/{id}`, `/rutas`, `/pedidos`, `/pedidos-tiendas` | `@requiere_permiso("impresion")` |
| | POST `/pegatinas/config`, `/rutas/guardar` | `@requiere_permiso("impresion", editar=True)` |

- [ ] **Step 1: Añadir `requiere_sesion` a `app/auth/permisos.py`**

```python
def requiere_sesion(func: Callable) -> Callable:
    """Solo exige estar autenticado (para la página de inicio)."""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        usuario = obtener_usuario_actual(request)
        if not usuario:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=302)
        request.state.usuario = usuario
        return await func(request, *args, **kwargs)
    return wrapper
```

En `inicio.py`: `@requiere_rol()` → `@requiere_sesion` (sin paréntesis) y actualizar el import.

- [ ] **Step 2: Test primero** — `tests/test_acceso_servicios.py`:

```python
import pytest
from app.models.usuario import Rol

# (rol, ruta GET, status esperado)
CASOS = [
    (Rol.JEFES, "/usuarios/", 200),
    (Rol.ADMINISTRACION, "/usuarios/", 403),      # admin solo Jefes
    (Rol.ADMINISTRACION, "/holded/", 200),
    (Rol.JEFE_PASTELEROS, "/catalogo/productos", 200),
    (Rol.PASTELERAS, "/catalogo/productos", 403),
    (Rol.PASTELERAS, "/holded/", 403),
    (Rol.PASTELERAS, "/produccion/", 200),
    (Rol.PASTELERAS, "/imprimir/", 200),
    (Rol.TIENDAS, "/imprimir/", 403),             # Tiendas sin Impresión (PDF)
    (Rol.COMERCIAL, "/clientes/", 200),
    (Rol.COMERCIAL, "/produccion/", 403),
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
```

Run → FAIL (los endpoints aún usan `requiere_rol` con roles viejos, p.ej. ADMINISTRACION no entra a `/holded/`... según el caso fallarán unos u otros).

- [ ] **Step 3: Aplicar la tabla de decoradores** en los 8 ficheros. En cada fichero cambiar el import: `from app.auth.permisos import requiere_permiso` (y quitar `requiere_rol`, `Rol` si ya no se usa en ese fichero — en `imprimir.py` y `stock.py` `Rol` se sigue usando para el ámbito tienda).

- [ ] **Step 4: Ejecutar y commit**

Run: `venv\Scripts\python -m pytest -v` → PASS.

```bash
git add app/ tests/test_acceso_servicios.py
git commit -m "feat: requiere_permiso en clientes, catalogo, admin, holded, produccion e impresion"
```

---

### Task 6: Pedidos — permisos + ámbito por tienda en bandeja

**Files:**
- Modify: `app/api/pedidos.py`
- Test: `tests/test_pedidos_permisos.py`

Decoradores:

| Endpoint | Decorador |
|---|---|
| `GET /pedidos/rutas` (`pedidos.py:86`) | `@requiere_permiso("pedidos.rutas")` |
| `GET /pedidos/` (bandeja), `GET /pedidos/{id}` | `@requiere_permiso("pedidos")` |
| `GET /pedidos/crear`, `POST /pedidos/crear`, `GET/POST /pedidos/{id}/editar`, `POST /pedidos/{id}/eliminar` | `@requiere_permiso("pedidos", editar=True)` |

- [ ] **Step 1: Test primero** — `tests/test_pedidos_permisos.py`:

```python
from datetime import date

from app.database import SessionLocal
from app.models.usuario import Rol
from app.models.pedido import Pedido


def _crear_pedido(tienda_id):
    """Pedido mínimo para tests; ajustar campos obligatorios según el modelo."""
    s = SessionLocal()
    try:
        p = Pedido(fecha_recogida=date.today(), tienda_id=tienda_id,
                   nombre_cliente="Test", telefono="600000000")
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id
    finally:
        s.close()


def test_pasteleras_ve_bandeja_pero_no_crea(como):
    c = como(Rol.PASTELERAS)
    assert c.get("/pedidos/").status_code == 200
    assert c.get("/pedidos/crear").status_code == 403
    assert c.post("/pedidos/crear", data={}).status_code == 403


def test_repartidores_rutas_si_bandeja_no(como):
    c = como(Rol.REPARTIDORES)
    assert c.get("/pedidos/rutas").status_code == 200
    assert c.get("/pedidos/").status_code == 403


def test_tienda_solo_ve_pedidos_de_su_tienda(como, tienda, tienda2):
    pid_mia = _crear_pedido(tienda.id)
    pid_ajena = _crear_pedido(tienda2.id)
    c = como(Rol.TIENDAS, tienda_id=tienda.id)
    assert c.get(f"/pedidos/{pid_mia}").status_code == 200
    assert c.get(f"/pedidos/{pid_ajena}").status_code == 404
    html = c.get("/pedidos/").text
    assert f"/pedidos/{pid_mia}" in html
    assert f"/pedidos/{pid_ajena}" not in html
```

Nota: revisar `app/models/pedido.py` y `app/templates/pedidos/bandeja.html` para ajustar los campos obligatorios de `_crear_pedido` y el assert del HTML (usar algo estable, p. ej. el enlace al detalle).

Run → FAIL.

- [ ] **Step 2: Implementar.** Cambiar decoradores según la tabla. En `bandeja()` (`pedidos.py:143`), tras construir `query`, añadir el ámbito:

```python
        usuario = request.state.usuario
        if usuario.rol == Rol.TIENDAS and usuario.tienda_id:
            query = query.filter(Pedido.tienda_id == usuario.tienda_id)
        elif tienda_id:
            ...  # filtro manual existente (solo para el resto de puestos)
```

(El `if tienda_id:` existente pasa a `elif`.) En el detalle `GET /pedidos/{id}` (`pedidos.py:287`), tras cargar el pedido:

```python
        if usuario.rol == Rol.TIENDAS and pedido.tienda_id != usuario.tienda_id:
            raise HTTPException(status_code=404)
```

Regla TIENDAS sin tienda_id: si `usuario.tienda_id` es None, filtrar por `Pedido.tienda_id == -1` (lista vacía, nunca acceso global):

```python
        if usuario.rol == Rol.TIENDAS:
            query = query.filter(Pedido.tienda_id == (usuario.tienda_id or -1))
```

- [ ] **Step 3: Ejecutar y commit**

Run: `venv\Scripts\python -m pytest -v` → PASS.

```bash
git add app/api/pedidos.py tests/test_pedidos_permisos.py
git commit -m "feat: permisos y ambito por tienda en pedidos"
```

---

### Task 7: Stock — subapartados + auditoría de ámbito por tienda

**Files:**
- Modify: `app/api/stock.py` (borrar `ROLES_STOCK`/`ROLES_GESTION` de las líneas 31-32)
- Test: `tests/test_stock_permisos.py`

Decoradores (línea actual → nuevo):

| Endpoint | Decorador |
|---|---|
| `GET /stock/reparto/` (275) | `@requiere_permiso("stock.dias_reparto")` |
| `POST /stock/reparto/toggle` (295) | `@requiere_permiso("stock.dias_reparto", editar=True)` |
| `GET /stock/prevision/` (327), `GET /stock/prevision/{tienda_id}` (352), `GET /stock/necesidades/` (415) | `@requiere_permiso("stock.prevision")` |
| `POST /stock/prevision/{tienda_id}` (381) | `@requiere_permiso("stock.prevision", editar=True)` |
| `GET /stock/envios/` (458) | `@requiere_permiso("stock.envios")` |
| `GET /stock/mermas/` (610) | `@requiere_permiso("stock.mermas")` |
| `GET /stock/mermas/nuevo` (661), `POST /stock/mermas/nuevo` (679) | `@requiere_permiso("stock.mermas", editar=True)` |
| `GET /stock/` (716), `GET /stock/{parte_id}` (1052) | `@requiere_permiso("stock.partes")` |
| `GET /stock/nuevo` (839), `POST /stock/nuevo` (879), `GET/POST /stock/{parte_id}/editar` (949/989), `POST /{parte_id}/cerrar` (1035) | `@requiere_permiso("stock.partes", editar=True)` |

Ámbito tienda — auditoría (los checks `Rol.TIENDA` ya renombrados a `Rol.TIENDAS` en Task 2):
1. Ya cubiertos: mermas lista (618), mermas POST fuerza `usuario.tienda_id` (695), index (738), parte nuevo (849/893), editar (958/999), cerrar (1043), detalle (1061). Verificar uno a uno que siguen tras el renombrado.
2. **Añadir**: en `GET /stock/envios/` (función en 458), restringir la lista de tiendas si el usuario es TIENDAS: donde se recorren las tiendas con reparto (bucle sobre `db.query(Tienda)`), añadir antes:

```python
        usuario = request.state.usuario
        if usuario.rol == Rol.TIENDAS:
            reparto_tienda_ids &= {usuario.tienda_id or -1}
```

(ajustar al nombre real de la variable de ids con reparto en esa función).

- [ ] **Step 1: Test primero** — `tests/test_stock_permisos.py`:

```python
from app.models.usuario import Rol


def test_dias_reparto_ver_pero_no_tocar(como):
    for rol in (Rol.PASTELERAS, Rol.TIENDAS):
        c = como(rol)
        assert c.get("/stock/reparto/").status_code == 200
        assert c.post("/stock/reparto/toggle", data={"tienda_id": 1, "dia": 1}).status_code == 403


def test_prevision_oculta_para_tiendas_y_pasteleras(como):
    assert como(Rol.TIENDAS).get("/stock/prevision/").status_code == 403
    assert como(Rol.PASTELERAS).get("/stock/necesidades/").status_code == 403
    assert como(Rol.AREA_MANAGER).get("/stock/prevision/").status_code == 200


def test_mermas_tiendas_si_pasteleras_no(como):
    assert como(Rol.TIENDAS).get("/stock/mermas/").status_code == 200
    assert como(Rol.PASTELERAS).get("/stock/mermas/").status_code == 403


def test_repartidores_envios_si_partes_no(como):
    c = como(Rol.REPARTIDORES)
    assert c.get("/stock/envios/").status_code == 200
    assert c.get("/stock/").status_code == 403


def test_merma_de_tienda_se_guarda_con_su_tienda(como, tienda, tienda2):
    """Aunque el form traiga otra tienda_id, se guarda con la del usuario."""
    c = como(Rol.TIENDAS, tienda_id=tienda.id)
    r = c.post("/stock/mermas/nuevo", data={
        "fecha": "2026-07-14", "tienda_id": tienda2.id, "producto_id": 1,
        "sabor_id": 1, "cantidad": 2, "motivo": "caducado", "comentario": "",
    })
    assert r.status_code == 302
    from app.database import SessionLocal
    from app.models.stock import Merma  # ajustar import si Merma vive en otro módulo (grep "class Merma")
    s = SessionLocal()
    try:
        m = s.query(Merma).order_by(Merma.id.desc()).first()
        assert m.tienda_id == tienda.id
    finally:
        s.close()
```

Run → FAIL.

- [ ] **Step 2: Aplicar decoradores + filtro de envíos.** Borrar `ROLES_STOCK` y `ROLES_GESTION`.

- [ ] **Step 3: Ejecutar y commit**

Run: `venv\Scripts\python -m pytest -v` → PASS.

```bash
git add app/api/stock.py tests/test_stock_permisos.py
git commit -m "feat: permisos por subapartado y ambito de tienda en stock"
```

---

### Task 8: Menú y plantillas con `puede()` / `puede_editar()`

**Files:**
- Modify: `app/templates/base.html:18-56`, `inicio.html:16-43`, `pedidos/bandeja.html`, `stock/index.html:124-142`, `stock/mermas.html:15`, plantilla de días de reparto (`stock/reparto*.html`), `usuarios/lista.html`
- Modify: `app/api/usuarios.py` (pasar `ROL_NOMBRES` a la plantilla)

- [ ] **Step 1: Menú lateral (`base.html`).** Sustituir cada condición por servicio:

```jinja
{% if usuario.puede_servicio("pedidos") %} ... enlace Pedidos ... {% endif %}
{% if usuario.puede_servicio("stock") %} ... {% endif %}
{% if usuario.puede_servicio("impresion") %} ... {% endif %}
{% if usuario.puede_servicio("produccion") %} ... {% endif %}
{% if usuario.puede_servicio("holded") %} ... {% endif %}
{% if usuario.puede_servicio("catalogo") %} ... {% endif %}
{% if usuario.puede_servicio("clientes") %} ... {% endif %}
{% if usuario.puede_servicio("admin") %} ... enlaces Usuarios y Tiendas ... {% endif %}
```

Mapear cada `{% if usuario.rol in [...] %}` existente (líneas 18, 29, 34, 40, 45, 49, 54) al servicio del enlace que envuelve. Mismo cambio en las tarjetas de `inicio.html`.

- [ ] **Step 2: Botones de edición.**
- `pedidos/bandeja.html`: envolver el botón "Nuevo pedido" (y acciones de editar/eliminar si las hay) en `{% if usuario.puede_editar("pedidos") %}`.
- Plantilla de días de reparto: envolver los toggles/botones en `{% if usuario.puede_editar("stock.dias_reparto") %}` (buscar la plantilla que renderiza `/stock/reparto/`).
- `stock/index.html:124-142` y `stock/mermas.html:15`: cambiar las comparaciones `usuario.rol in [...]` por `usuario.puede_editar("stock.partes")` / `usuario.puede("stock.mermas")` según lo que condicione cada bloque (leer el bloque antes de tocar).
- Repasar el resto con `grep -rn "usuario.rol" app/templates/` — al acabar este paso no debe quedar ninguna comparación de rol por string en plantillas (el `<small>{{ usuario.rol }}</small>` informativo de base.html:64 puede quedarse, mostrando el nombre legible: ver Step 3).

- [ ] **Step 3: Nombres legibles.** En `app/api/usuarios.py` importar `ROL_NOMBRES` y pasarlo al contexto de `usuarios/lista.html`; en la plantilla, el desplegable (`lista.html:78-83`) muestra `{{ nombres[r] }}` y el badge usa también el nombre legible. Cambiar la etiqueta "Tienda (solo para rol TIENDA)" → "Tienda (solo para el puesto Tiendas)". En `base.html:64` mostrar el nombre legible: pasar `ROL_NOMBRES` vía contexto o añadir una property `rol_nombre` a `UsuarioSesion`:

```python
    @property
    def rol_nombre(self) -> str:
        from app.models.usuario import ROL_NOMBRES
        return ROL_NOMBRES.get(self.rol, self.rol.value)
```

y en plantillas `{{ usuario.rol_nombre }}`.

- [ ] **Step 4: Verificación manual.** Arrancar la app (`iniciar.bat`) y entrar con un usuario de cada puesto clave (crear usuarios de prueba TIENDAS y PASTELERAS desde /usuarios/ con un JEFES): el menú solo muestra sus servicios; la bandeja de Pasteleras no tiene botón de crear; Tiendas solo ve su tienda en stock y pedidos.

- [ ] **Step 5: Commit**

```bash
git add app/
git commit -m "feat: menu y plantillas condicionados por puede()/puede_editar()"
```

---

### Task 9: Eliminar `requiere_rol` y cierre

**Files:**
- Modify: `app/auth/permisos.py` (borrar `requiere_rol`)
- Modify: `docs/GUIA_CODIGO.md` si documenta el sistema de roles

- [ ] **Step 1: Confirmar que no queda ningún uso**

Run: `grep -rn "requiere_rol" app/ scripts/ tests/`
Expected: solo la definición en `permisos.py`. Borrarla y actualizar el docstring del módulo (línea 1-2) con los 8 puestos y el nuevo sistema.

- [ ] **Step 2: Suite completa + arranque**

Run: `venv\Scripts\python -m pytest -v` → todo PASS.
Run: arrancar `iniciar.bat`, login como JEFES, click por todos los servicios → sin errores 500.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: eliminar requiere_rol, sistema de permisos completo"
```

---

## Notas para el ejecutor

- **Backup antes de migrar**: copiar `obrador.db` a `backups/` antes de `alembic upgrade head` (Task 2).
- **NO hacer `git push`** en ningún momento (regla del proyecto: el push lo autoriza el usuario).
- Cambios de comportamiento intencionados (vienen del PDF, no son bugs): Tiendas pierde acceso a Impresión; Repartidores pierde la bandeja de pedidos pero gana rutas y envíos; Pasteleras gana bandeja en consulta y días de reparto en consulta; aparecen 3 puestos nuevos sin usuarios todavía.
- Si algún test de plantilla es frágil (asserts sobre HTML), preferir comprobar enlaces (`href`) o códigos de estado, no textos visibles.
