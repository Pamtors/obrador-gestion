# Plan Fase 2 — Pedidos + Etiquetas + Centro de Impresión

## ✅ COMPLETADA — 16/06/2026

**Migración head al finalizar:** `154c0c658da9`

---

## Contexto del proyecto

- **Ruta:** `obrador-gestion`
- **Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Jinja2, SQLite
- **Venv:** `.\venv\Scripts\` — arrancar con `.\venv\Scripts\uvicorn.exe app.main:app --reload`
- **Admin:** admin@obrador-demo.example / (la que definas en .env)
- **Migraciones aplicadas hasta ahora:** `a38f5b8d3307` (al inicio de la fase)

---

## Reglas de negocio acordadas

- **Solo Oficina/Admin** crea pedidos (de momento)
- **Sin estado** en Pedido — no hay ciclo de vida, son solo registros
- **Tipos de pedido:** PARTICULAR (cliente con nombre+teléfono), B2B (ClienteB2B), TIENDA (pedido interno)
- **Etiquetas:** 2 columnas × 4 filas en A4 (105mm × 74.25mm c/u), HTML con CSS de impresión — el navegador hace el PDF con Ctrl+P
- El **código** en la etiqueta = `{codigo_cliente}{abrev_sabor}{fecha_entrega_label}`
  - Para B2B: `codigo` del ClienteB2B (campo nuevo)
  - Para particular: `referencia` del Pedido
  - `fecha_entrega_label` = "MAÑANA" si recogida = horneado+1día, si no la fecha en DD/MM
- **Fecha horneado** = siempre `fecha_recogida - 1 día`, calculada automáticamente — no editable por el usuario
- **Fecha caducidad** = `fecha_horneado + producto.dias_caducidad` (calculada, no almacenada)
- **Registro sanitario** viene de `Tienda.registro_sanitario` (campo nuevo)
- Cantidad en línea = unidades; cada unidad genera UNA etiqueta (si cantidad=3 → 3 etiquetas idénticas)

---

## Formato de etiqueta (del PDF de referencia)

```
┌─────────────────────────────┬───────────────────┐
│ CÓDIGO      │ 277PISMAÑANA  │ REGISTRO          │
│ FECHA ENT.  │ 17/06/2026    │ SANITARIO         │
│ FECHA HORN. │ 16/06/2026    │ Nº ASIGNADO:      │
│ FECHA CAD.  │ 20/06/2026    │ 29013-00234       │
│ FORMATO     │ GRANDE(1,5KG) │                   │
├─────────────────────────────┴───────────────────┤
│                                                  │
│          CLIENTE EJEMPLO SL                      │
│                PISTACHO                          │
│                                                  │
└──────────────────────────────────────────────────┘
```

Papel físico: A4 con 1 corte vertical (2 cols) + 4 cortes horizontales = 8 etiquetas por hoja.
Dimensiones reales: **105mm × 74.25mm** por etiqueta. Sin gaps entre etiquetas.

---

## Lo implementado

### Cambios en modelos existentes

| Modelo | Campo añadido | Tipo |
|--------|--------------|------|
| `sabores` | `abreviatura` | String(10) nullable |
| `tiendas` | `registro_sanitario` | String(50) nullable |
| `clientes_b2b` | `codigo` | String(20) nullable |
| `clientes_b2b` | `id_holded` | String(24) nullable — ID del contacto en Holded para crear albaranes/facturas |

### Modelos nuevos

#### `app/models/pedido.py`
```python
class Pedido(Base):
    __tablename__ = "pedidos"
    id, referencia, fecha_pedido, fecha_recogida, fecha_horneado,
    tipo ("PARTICULAR"|"B2B"|"TIENDA"), tienda_id (FK),
    cliente_b2b_id (FK nullable), nombre_cliente, telefono_cliente,
    comentario, creado_en

class LineaPedido(Base):
    __tablename__ = "lineas_pedido"
    id, pedido_id (FK cascade delete), producto_id (FK),
    sabor_id (FK), tamano_id (FK), cantidad (default 1), comentario
```

### Migraciones aplicadas
1. `a52eed1a916b` — tablas pedidos/lineas_pedido + campos abreviatura, registro_sanitario, codigo (con batch_alter_table)
2. `154c0c658da9` — campo id_holded en clientes_b2b

### API implementada

**`app/api/pedidos.py`**
```
GET  /pedidos/              → bandeja (filtros fecha_recogida, tienda)
GET  /pedidos/crear         → formulario nuevo pedido
POST /pedidos/crear         → guardar pedido + líneas
GET  /pedidos/{id}          → detalle + link etiquetas
GET  /pedidos/{id}/editar   → formulario editar
POST /pedidos/{id}/editar   → guardar cambios
POST /pedidos/{id}/eliminar → eliminar pedido
```

**`app/api/imprimir.py`**
```
GET  /imprimir/                          → centro de impresión
GET  /imprimir/etiquetas/dia             → etiquetas de todos los pedidos de un día (?fecha=&tipo=B2B)
GET  /imprimir/etiquetas/{pedido_id}     → etiquetas de un pedido concreto
GET  /imprimir/pedidos                   → lista imprimible agrupada por día (?manana=1 para acceso rápido)
```

### Templates creados
```
app/templates/
├── pedidos/
│   ├── bandeja.html    — lista con filtros, badge por tipo
│   ├── crear.html      — form reutilizado para crear/editar, JS vanilla para líneas dinámicas
│   └── detalle.html    — vista completa + botones editar/eliminar/etiquetas
└── imprimir/
    ├── index.html      — centro con accesos rápidos "mañana" (todos + solo B2B)
    ├── etiquetas.html  — A4 exacto 2×4, @page margin:0, float layout, guía de corte punteada
    └── pedidos.html    — agrupado por día, badge "MAÑANA", botón acceso rápido
```

---

## Notas técnicas del proyecto (acumuladas)

- **SQLite + Alembic:** SIEMPRE usar `batch_alter_table` para alterar tablas existentes
- **DetachedInstanceError:** Convertir objetos ORM a dicts ANTES de `db.close()` — no pasar ORM objects a templates si usan relaciones
- **bcrypt:** Directo, sin passlib
- **`requiere_rol`:** Decorador en `app/auth/permisos.py` — usar en todos los endpoints
- **Pattern de sesión DB:** `db = SessionLocal()` + `try/finally: db.close()` — no usar dependency injection
- Los templates Jinja2 renderizan DESPUÉS de que `db.close()` es llamado, por eso los dicts
- **Tamaños en el form de pedido:** Se cargan TODOS los tamaños activos para todos los productos (tabla `precios_producto_tamanio` puede estar vacía; no filtrar por ella)
- **Rutas con prefijo literal vs parámetro:** En FastAPI, definir `/etiquetas/dia` ANTES de `/etiquetas/{pedido_id}` para evitar colisiones
- **Catálogo JS:** `{prod_id: {sabores:[{id,nombre,abreviatura}], tamanios:[{id,nombre}]}}` pre-cargado en el template como JSON
