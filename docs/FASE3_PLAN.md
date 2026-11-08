# Plan Fase 3 — Lista de Horneado + Integración Holded

## Contexto del proyecto

- **Ruta:** `obrador-gestion`
- **Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Jinja2, SQLite
- **Venv:** `.\venv\Scripts\` — arrancar con `.\venv\Scripts\uvicorn.exe app.main:app --reload`
- **Admin:** admin@obrador-demo.example / (la que definas en .env)
- **Migración head al empezar:** `154c0c658da9`

---

## Estado actual del sistema (lo que ya existe)

```
app/
├── models/
│   ├── usuario.py       — Usuario, Rol (ADMIN, OFICINA, TIENDA, OBRADOR)
│   ├── tienda.py        — Tienda (id, nombre, direccion, activa, registro_sanitario)
│   ├── sabor.py         — Sabor (id, nombre, orden, abreviatura)
│   ├── tamano.py        — Tamano (id, nombre, descripcion, orden, activo)
│   ├── producto.py      — Producto (id, nombre, dias_caducidad, dias_hasta_entrega, activo)
│   ├── catalogo.py      — SaborProducto, PrecioProductoTamano (precio_pvp, precio_franquicia)
│   ├── cliente_b2b.py   — ClienteB2B (id, codigo, id_holded, nombre_comercial, ...)
│   └── pedido.py        — Pedido, LineaPedido
├── api/
│   ├── auth.py, inicio.py, usuarios.py, tiendas.py, clientes.py, catalogo.py
│   ├── pedidos.py       — CRUD completo de pedidos con líneas
│   └── imprimir.py      — etiquetas (por pedido y por día), lista imprimible agrupada por día
└── templates/
    ├── pedidos/         — bandeja, crear/editar, detalle
    └── imprimir/        — index (accesos rápidos mañana), etiquetas (A4 2×4), pedidos (por día)
```

**Sidebar actual** (base.html):
- ADMIN/OFICINA: Clientes B2B, Bandeja de pedidos
- Todos: Centro de impresión
- ADMIN/OFICINA/TIENDA: **Stock** → `/stock/` (enlace muerto)
- ADMIN/OBRADOR: **Producción** → `/horneado/` (enlace muerto)
- ADMIN: Catálogo, Administración

---

## Parte 1 — Lista de Horneado (Producción)

### Descripción
El obrador necesita saber qué hornear cada día. La lista se genera a partir de los pedidos con `fecha_horneado = X`, agrupando las líneas por producto → sabor → tamaño con totales de unidades.

### Reglas de negocio
- Acceso: ADMIN y OBRADOR
- Filtro por `fecha_horneado` (default = hoy)
- Acceso rápido "hornear hoy" y "hornear mañana"
- Agrupación: Producto → Sabor → Tamaño → suma de cantidades
- Vista imprimible sin sidebar (igual que etiquetas y lista pedidos)
- No hay modelo nuevo — todo se saca de `Pedido` + `LineaPedido`

### API — `app/api/produccion.py`

```
GET  /horneado/    → lista de horneado (filtro ?fecha=YYYY-MM-DD)
```

### Template

```
app/templates/produccion/
└── horneado.html   — tabla agrupada, accesos rápidos hoy/mañana, CSS @media print
```

### Estructura de la tabla en pantalla

```
HORNEADO — Martes 17/06/2026
════════════════════════════════════════════════════════
TARTA DE QUESO
  PISTACHO
    GRANDE (1,5 kg) ............... 4
    MEDIANO (1 kg)  ............... 2
  LOTUS
    GRANDE (1,5 kg) ............... 3
────────────────────────────────────────────────────────
TOTAL UNIDADES: 9
```

---

## Parte 2 — Integración Holded (Albaranes B2B)

### Descripción
Desde el detalle de un pedido B2B, poder crear el albarán correspondiente en Holded con un clic. Usa la API REST de Holded (`https://api.holded.com/api/invoicing/v1`).

El app `un script previo de facturación` ya tiene toda la lógica de la API de Holded; hay que portarla al servidor FastAPI.

### Reglas de negocio
- Solo pedidos tipo B2B con `cliente_b2b.id_holded` relleno
- Solo ADMIN y OFICINA pueden crear albaranes
- La API key de Holded se guarda en la tabla `Config` de la BD (cifrada en base64 mínimo)
- El albarán se crea con fecha = `fecha_recogida` del pedido
- Cada `LineaPedido` se convierte en un item de Holded:
  - `name`: `"{sabor.nombre} {tamano.nombre}"` (ej: "PISTACHO GRANDE")
  - `desc`: `""` (vacío)
  - `units`: `linea.cantidad`
  - `subtotal`: `precio_franquicia` de `PrecioProductoTamano` (precio unitario)
  - `tax`: `10` (IVA alimentación, fijo por ahora)
- Si no hay `precio_franquicia` configurado, mostrar error y no crear el albarán
- Guardar el ID del documento creado en Holded → campo nuevo `holded_doc_id` en `Pedido`
- Si el pedido ya tiene `holded_doc_id`, mostrar el ID y opción de "recrear" (con confirmación)

### Cambios en modelos existentes

#### `app/models/pedido.py`
```python
# Añadir a Pedido:
holded_doc_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
```

### Modelo nuevo — `app/models/config.py`

```python
class Config(Base):
    __tablename__ = "config"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Claves usadas:
- `"holded_api_key"` — API key de Holded (32 chars hex)

### Migración (un solo archivo)

1. `config` (CREATE TABLE)
2. `pedidos` (batch): add `holded_doc_id`

### API — `app/api/holded.py`

```
GET  /holded/config              → página de configuración (solo ADMIN)
POST /holded/config              → guardar API key
POST /holded/albaran/{pedido_id} → crear albarán en Holded y guardar holded_doc_id
```

### Servicio interno — `app/services/holded.py`

Funciones puras (sin FastAPI, sin DB):

```python
HOLDED_BASE = "https://api.holded.com/api/invoicing/v1"

def crear_albaran(api_key: str, contact_id: str, fecha: date, numero: str, items: list[dict]) -> str:
    """Llama a POST /documents/waybill y devuelve el holded_doc_id."""

def construir_items(lineas: list[dict], precios: dict) -> list[dict]:
    """
    lineas: [{sabor_nombre, tamano_nombre, cantidad, precio_franquicia}]
    Devuelve [{name, desc, units, subtotal, tax}]
    """
```

### Templates

```
app/templates/holded/
├── config.html    — formulario para guardar la API key (solo ADMIN)
└── albaran.html   — preview del albarán antes de crearlo + resultado tras crearlo
```

### Sidebar (base.html) — cambios

Añadir bajo "Pedidos" para ADMIN/OFICINA:
```
Holded
  └── Configuración   (/holded/config)   [solo ADMIN]
```

En el detalle de pedido B2B (`pedidos/detalle.html`):
- Si `holded_doc_id` es null: botón "Crear albarán en Holded"
- Si `holded_doc_id` existe: mostrar ID + botón "Ver en Holded" (link externo) + botón "Recrear" (con confirm)

---

## Migración

Un solo archivo Alembic:
1. `CREATE TABLE config`
2. `pedidos` (batch): add `holded_doc_id` String(24)

Recordar: `import app.models.config` en `alembic/env.py`

---

## Orden de ejecución en el nuevo chat

1. Leer modelos existentes: `pedido.py`, `catalogo.py`, `alembic/env.py`
2. Modificar `pedido.py` → añadir `holded_doc_id`
3. Crear `app/models/config.py`
4. Actualizar `alembic/env.py` → importar `config`
5. Generar migración (autogenerate) + corregir batch_alter_table en `pedidos`
6. Aplicar migración (`alembic upgrade head`)
7. Crear `app/api/produccion.py`
8. Crear `app/services/holded.py` (lógica pura sin DB ni FastAPI)
9. Crear `app/api/holded.py`
10. Crear templates: `produccion/horneado.html`, `holded/config.html`, `holded/albaran.html`
11. Actualizar `pedidos/detalle.html` → añadir bloque Holded
12. Actualizar `main.py` → incluir routers de produccion y holded
13. Actualizar `base.html` → añadir entradas al sidebar
14. Verificar arranque y rutas

---

## Notas técnicas del proyecto

- **SQLite + Alembic:** SIEMPRE usar `batch_alter_table` para alterar tablas existentes
- **DetachedInstanceError:** Convertir objetos ORM a dicts ANTES de `db.close()`
- **bcrypt:** Directo, sin passlib
- **`requiere_rol`:** Decorador en `app/auth/permisos.py`
- **Pattern de sesión DB:** `db = SessionLocal()` + `try/finally: db.close()`
- **Tamaños en catálogo JS:** cargar todos los activos, NO filtrar por `precios_producto_tamanio`
- **Rutas con prefijo literal vs parámetro:** definir literales ANTES de `/{id}`
- **Holded API key:** guardar en `Config` table con key `"holded_api_key"`. El campo `value` guarda el string de 32 chars hex directamente. En producción futura se cifraría, de momento texto plano en SQLite local.
- **Holded items:** `subtotal` = precio UNITARIO (Holded calcula total como `units × subtotal`)
- **Holded contact_id** = `cliente_b2b.id_holded` (string 24 chars hex)
- **`PrecioProductoTamano.precio_franquicia`**: puede ser null — validar antes de crear albarán y mostrar error si falta
