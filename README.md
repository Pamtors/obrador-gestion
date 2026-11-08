# Obrador Demo — Sistema de gestión para obrador de pastelería

Aplicación web interna para gestionar pedidos, producción, stock y reparto de un obrador de tartas con varias tiendas. Sustituye a un Excel de unas 90 hojas.

> **Proyecto real, datos ficticios.** Nació como encargo para una pastelería. La marca, los clientes, las tiendas y los datos fiscales se han sustituido por datos de ejemplo para poder publicarlo.

## Qué hace

- **Catálogo:** productos (tartas grandes, pequeñas, minis, cookies, tarrinas), sabores y su disponibilidad por producto (producción, encargo, agotado), con tres tarifas: PVP, B2B y franquicia.
- **Pedidos:** particulares, clientes B2B y pedidos de tienda. La fecha de horneado se calcula automáticamente a partir de la de entrega.
- **Producción:** lista de horneado diaria (pedidos del día más reposición de tiendas) y control de tartas congeladas.
- **Stock por tienda:** parte de cierre diario, mermas, previsión por día de la semana, necesidades y fichas de envío.
- **Reparto:** días de reparto por tienda y planificador de rutas.
- **Impresión:** pegatinas con código y fecha de caducidad, listados de pedidos y albaranes de franquicia.
- **Facturación:** creación de albaranes y facturas en Holded (API v1 y v2) a partir de los pedidos B2B.
- **Usuarios y permisos:** 9 roles con una matriz de permisos por sección (nada / ver / editar), y restricción por tienda para los usuarios de tienda.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- **Frontend:** plantillas Jinja2 renderizadas en servidor, CSS propio, sin frameworks JS
- **Base de datos:** SQLite en desarrollo, preparada para PostgreSQL
- **Autenticación:** cookie de sesión firmada (itsdangerous, 8 h) y contraseñas con bcrypt
- **Tests:** pytest y httpx, 139 casos

## Decisiones de diseño

- **Un módulo por sección.** Cada sección es un trío con el mismo nombre: endpoints en `app/api/`, tabla en `app/models/` y HTML en `app/templates/`.
- **Permisos en servidor.** La matriz `PERMISOS` (`app/auth/permisos.py`) es la única fuente de verdad y se aplica con decoradores en cada endpoint. Ocultar botones en la plantilla es solo cosmético.
- **Catálogo sin combinatoria.** El tamaño se fusiona en el producto y los precios son columnas del producto. Cambiar el precio de una tarta es editar un registro, no unos 120.
- **Migraciones compatibles con dos motores.** Todas funcionan en SQLite y PostgreSQL (`batch_alter_table`, sin `UPDATE ... FROM`).
- **Integración aislada.** Todo lo de Holded vive en `app/services/holded.py` y detecta la versión de la API por el prefijo de la clave.

## Puesta en marcha

```bash
git clone <URL-del-repositorio>
cd obrador-gestion
python -m venv venv
source venv/bin/activate        # en Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # en Windows: copy .env.example .env
# Edita .env: SECRET_KEY, ADMIN_PASSWORD (y opcionalmente INVITADO_PASSWORD)
alembic upgrade head
python scripts/seed.py          # usuario admin y tiendas base
python scripts/seed_catalogo.py # productos y sabores
python scripts/seed_simulacro.py  # (opcional) clientes, pedidos y stock de ejemplo
uvicorn app.main:app --reload
```

Abre http://localhost:8000 e inicia sesión con el email de `ADMIN_EMAIL` y la contraseña de `ADMIN_PASSWORD`.

Para pasar los tests: `pytest`.

La clave de la API de Holded se guarda desde la propia aplicación (tabla `config`), no en el repositorio. Backup manual de la base de datos: `python scripts/backup.py`.

## Estructura

```
app/
├── main.py         # arranque y registro de routers
├── config.py       # variables de entorno
├── api/            # endpoints y lógica de negocio, uno por sección
├── models/         # tablas SQLAlchemy
├── auth/           # bcrypt, sesiones y matriz de permisos
├── services/       # cliente de la API de Holded
├── templates/      # HTML Jinja2, espejo de api/
└── static/css/
alembic/versions/   # migraciones
scripts/            # seeds, datos de ejemplo y backup
tests/              # pytest
docs/               # guía del código, auditoría, manual de permisos y planes por fase
```

## Documentación

- [`docs/GUIA_CODIGO.md`](docs/GUIA_CODIGO.md): cómo está organizado el código y dónde tocar para cada cambio.
- [`docs/AUDITORIA.md`](docs/AUDITORIA.md): auditoría de código con problemas priorizados y su arreglo.
- [`docs/PERMISOS_MANUAL.md`](docs/PERMISOS_MANUAL.md) y [`docs/PERMISOS_SPEC.md`](docs/PERMISOS_SPEC.md): diseño y recetas del sistema de permisos.
- `docs/FASE*_PLAN.md` y `docs/mejoras/`: planes históricos y backlog, útiles para ver cómo se fue construyendo.

## Autores

- **Pol Moyano** — [@Pamtors](https://github.com/Pamtors)
- **Hugo** — [@hugomm21](https://github.com/hugomm21)

## Licencia

[MIT](LICENSE)
