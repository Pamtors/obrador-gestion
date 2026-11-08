# Guía del código — Obrador Demo

Guía para entender el proyecto sin haberlo visto antes y saber dónde tocar
para hacer cualquier modificación (incluida la migración de base de datos a servidor).

## Qué es

Sistema web interno que sustituye al Excel de gestión de Obrador Demo:
catálogo de tartas, pedidos, producción (horneado), stock de tiendas, reparto,
pegatinas/listados de impresión y facturación vía Holded.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 · Alembic · Jinja2 (server-side, sin frontend JS aparte) · SQLite en local (preparado para PostgreSQL).

## Cómo arrancar en local

```bash
cd obrador-gestion
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

(o `iniciar.bat`). Necesita un `.env` con al menos `SECRET_KEY`; `DATABASE_URL` es opcional
(por defecto `sqlite:///./obrador.db`). Ver variables en `app/config.py`.

## Estructura de carpetas

```
app/
  main.py          ← punto de entrada: registra los 11 routers
  config.py        ← variables de entorno (.env): SECRET_KEY, DATABASE_URL...
  database.py      ← engine SQLAlchemy, SessionLocal, Base, get_db()
  models/          ← 1 archivo por entidad = definición de las tablas (19 tablas)
  api/             ← 1 archivo por sección de la app = endpoints + lógica de negocio
  auth/            ← contraseñas (bcrypt), sesiones (cookie firmada), permisos (roles)
  services/        ← holded.py: cliente HTTP de la API de Holded (v1 y v2)
  templates/       ← HTML Jinja2, una carpeta por sección (espejo de api/)
  static/          ← css/ y js/
alembic/           ← migraciones de BD versionadas (alembic/versions/)
scripts/           ← seed.py, seed_catalogo.py (datos iniciales), backup.py
docs/              ← planes de fase y esta guía
```

**Regla de oro para orientarse:** cada sección de la app es un trío con el mismo nombre:
`app/api/pedidos.py` (endpoints y lógica) + `app/templates/pedidos/` (HTML) +
`app/models/pedido.py` (tabla). Si buscas dónde está algo, empieza por `app/api/`.

## Las tablas (esquema de BD)

Definidas en `app/models/` (cada archivo tiene docstrings con el detalle). 5 bloques:

### Catálogo — qué se vende
| Tabla | Qué es |
|---|---|
| `productos` | Tipo de tarta. `dias_caducidad` y `dias_hasta_entrega` controlan fechas de pegatinas y horneado |
| `sabores` | Sabor de cheesecake. `base_id` (FK a sí misma): sabores que comparten base en horneado |
| `tamanios` | Formato de venta. `permite_porciones`: se puede vender/contar por raciones |
| `sabor_producto` | Qué sabores tiene cada producto y en qué estado: PRODUCCION / ENCARGO / OUT |
| `precios_producto_tamanio` | Precio por producto+tamaño con 3 tarifas: PVP, B2B y franquicia |

### Organización — quién
| Tabla | Qué es |
|---|---|
| `tiendas` | Punto de venta. `es_franquicia` decide tarifa y facturación |
| `usuarios` | Empleados. Puestos: JEFES, ADMINISTRACION, TIENDAS, PASTELERAS, JEFE_PASTELEROS, AREA_MANAGER, COMERCIAL, REPARTIDORES. Puesto TIENDAS solo ve su `tienda_id` |
| `clientes_b2b` | Clientes de facturación (restaurantes, hoteles, franquicias). `id_holded` los vincula con Holded |

### Pedidos
| Tabla | Qué es |
|---|---|
| `pedidos` | Encargo PARTICULAR / B2B / TIENDA. `fecha_horneado = fecha_recogida − 1 día`. `holded_doc_id` = factura/albarán ya creado en Holded |
| `lineas_pedido` | Líneas de catálogo (producto+sabor+tamaño+cantidad) |
| `lineas_pedido_otros` | Líneas de texto libre fuera de catálogo |

### Producción y reparto
| Tabla | Qué es |
|---|---|
| `produccion_dia` | Cantidades confirmadas por el obrador por día. **Fuente de verdad de los envíos** |
| `planes_ruta` | Plan de reparto del día (PK = fecha), detalle guardado como JSON |

### Stock de tiendas
| Tabla | Qué es |
|---|---|
| `partes_stock` + `lineas_parte_stock` (+ `_otros`) | Recuento diario al cierre por tienda. 6 raciones = 1 tarta equivalente. Flag `cerrado` bloquea edición |
| `prevision_stock` | Objetivo de stock por tienda + día de semana (0=lunes) + combinación |
| `dias_reparto` | Qué días de la semana recibe mercancía cada tienda |
| `mermas` | Producto desechado (caducidad, rotura, devolución) |

Y `config`: pares clave/valor editables en runtime (API key de Holded, ajustes de pegatinas `pegatinas.*`).

## El flujo de negocio (cómo encaja todo)

1. **Oficina crea pedidos** (`/pedidos`) → se calcula la fecha de horneado.
2. **La tienda cuenta su stock** al cierre (`/stock/nuevo`) → parte de stock.
3. **Necesidades** (`/stock/necesidades/`): previsión del día − último stock contado = lo que falta en cada tienda.
4. **Lista de horneado** (`/horneado`): pedidos del día + reposición de tiendas. El obrador confirma cantidades → `produccion_dia`.
5. **Envíos** (`/stock/envios/`): fichas por tienda = faltante limitado por lo realmente horneado + pedidos a entregar allí.
6. **Impresión** (`/imprimir`): pegatinas (código = cliente + abreviatura sabor + fecha; caducidad = horneado + días del producto), listados y planificador de rutas.
7. **Facturación** (`/holded`): crea albarán o factura en Holded por cada pedido B2B según `tipo_documento` del cliente.

## Autenticación y permisos

- Login con email+contraseña (bcrypt) → cookie `sesion` httponly con el id de usuario
  firmado con `itsdangerous` (SECRET_KEY), caducidad 8 h. **No hay tabla de sesiones.**
- Cada endpoint se protege con el decorador `@requiere_permiso(clave, editar=...)` o
  `@requiere_sesion` (`app/auth/permisos.py`), que deja el usuario en `request.state.usuario`.
  El nivel requerido (NADA/VER/EDITAR) se resuelve contra la matriz `PERMISOS` por puesto.
- Para añadir un endpoint nuevo: copia el patrón de cualquier función de `app/api/` —
  decorador de permiso + `db: Session = Depends(get_db)` + render de template o redirect.
- **Para modificar permisos** (cambiar qué puede un puesto, añadir puestos, subapartados
  o servicios, ámbito por tienda): recetas paso a paso en `docs/PERMISOS_MANUAL.md`.

## Cómo tocar la base de datos (recetas)

### Añadir un campo o tabla
1. Edita/crea el modelo en `app/models/`.
2. Si es tabla nueva, **impórtala en `alembic/env.py`** (si no, autogenerate no la ve — ya pasó con `planes_ruta`).
3. `venv\Scripts\alembic revision --autogenerate -m "descripcion"` → revisa el archivo generado en `alembic/versions/` (autogenerate se equivoca a veces, sobre todo con SQLite).
4. `venv\Scripts\alembic upgrade head`.

### Consultar el estado de migraciones
`alembic current` (dónde está la BD) · `alembic history` (todas las migraciones, hay 19).

### Migrar a PostgreSQL (servidor)
No hay que rediseñar nada: el esquema completo vive en las migraciones.
1. Crear el PostgreSQL (managed: Railway/Supabase/Neon).
2. En el `.env` del servidor: `DATABASE_URL=postgresql://usuario:pass@host:5432/obrador`
   (`database.py` detecta el motor por el prefijo de la URL; nada más que cambiar).
3. `alembic upgrade head` → crea las 19 tablas.
4. `scripts/seed.py` crea el usuario ADMIN inicial (credenciales del `.env`) y las 8 tiendas base — ejecutar una sola vez; `seed_catalogo.py` carga el catálogo base.
5. **Probar antes las migraciones contra un Postgres local/de prueba**: SQLite es permisivo con tipos y es el punto típico de fallo en este salto.

Los datos existentes de `obrador.db` NO se migran con Alembic; si hacen falta, se vuelcan con un script aparte.

## Trampas conocidas

- **`alembic/env.py` debe importar todos los modelos.** Si añades un modelo y no lo importas ahí, `--autogenerate` propondrá *borrar* su tabla.
- **`check_same_thread` solo aplica a SQLite** — `database.py` ya lo condiciona, no lo copies a otros sitios.
- **Holded tiene dos APIs** (v1 y v2) con auth, formato de fechas y endpoints distintos; `app/services/holded.py` auto-detecta por el prefijo de la clave (`pat_`/`sk_` = v2). No mezclar formatos: leer los docstrings de ese archivo antes de tocar nada.
- Las ediciones de pedidos y previsiones funcionan **por reemplazo total** de líneas (borra y reinserta), no por diff.
- `/docs` y `/redoc` de FastAPI están desactivados a propósito (app interna, no API pública).

## Documentación complementaria

- Docstrings en el propio código (todo `app/` está comentado en español).
- `docs/FASE*_PLAN.md`: planes históricos de cada fase, útiles para el "por qué" de las decisiones.
- `README.md`: instrucciones básicas de instalación.
