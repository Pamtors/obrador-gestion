# Plan Fase 4 — Stock (Parte Diario + Mermas)

## Contexto del proyecto

- **Ruta:** `obrador-gestion`
- **Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Jinja2, SQLite
- **Venv:** `.\venv\Scripts\` — arrancar con `.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`
- **Admin:** admin@obrador-demo.example / (la que definas en .env)
- **Migración head actual:** `76bb22d7031a`

---

## Estado actual del sistema

Ya existe en `base.html` el enlace `/stock/` (muerto) visible para ADMIN, OFICINA y TIENDA.

No hay modelos, rutas ni templates de stock. Se crean desde cero.

---

## Qué construye esta fase

### Flujo de negocio

Cada día, cada tienda hace un **parte de stock**: cuenta cuántas tartas tiene al cerrar. El sistema registra esas cantidades. Si hay unidades caducadas o rotas, se registran como **mermas** por separado.

ADMIN y OFICINA pueden ver partes de todas las tiendas. TIENDA solo ve los suyos.

---

## Modelos nuevos — `app/models/stock.py`

```python
class ParteStock(Base):
    __tablename__ = "partes_stock"
    id: int (PK)
    fecha: Date (nullable=False)
    tienda_id: FK → tiendas (nullable=False)
    usuario_id: FK → usuarios (nullable=False)   # quien lo registró
    cerrado: bool (default=False)                # True = no se puede editar
    creado_en: DateTime (server_default=now)
    lineas: List[LineaParteStock]

class LineaParteStock(Base):
    __tablename__ = "lineas_parte_stock"
    id: int (PK)
    parte_stock_id: FK → partes_stock (ondelete=CASCADE)
    producto_id: FK → productos
    sabor_id: FK → sabores
    tamano_id: FK → tamanios
    cantidad: int (nullable=False, default=0)

class Merma(Base):
    __tablename__ = "mermas"
    id: int (PK)
    fecha: Date (nullable=False)
    tienda_id: FK → tiendas (nullable=False)
    usuario_id: FK → usuarios (nullable=False)
    producto_id: FK → productos (nullable=False)
    sabor_id: FK → sabores (nullable=False)
    tamano_id: FK → tamanios (nullable=False)
    cantidad: int (nullable=False)
    motivo: String(20)   # CADUCIDAD | ROTURA | DEVOLUCION | OTRO
    comentario: Text (nullable=True)
    creado_en: DateTime (server_default=now)
```

---

## Migración Alembic

Un único archivo. Solo CREATE TABLE (sin alterar tablas existentes).

1. `CREATE TABLE partes_stock`
2. `CREATE TABLE lineas_parte_stock`
3. `CREATE TABLE mermas`

Importar `app.models.stock` en `alembic/env.py`.

---

## API — `app/api/stock.py` (prefix="/stock")

### Parte de stock

```
GET  /stock/                  → índice: ADMIN/OFICINA ven todos; TIENDA ve el suyo
GET  /stock/nuevo             → formulario nuevo parte (ADMIN, OFICINA, TIENDA)
POST /stock/nuevo             → guardar parte y sus lineas
GET  /stock/{parte_id}        → ver parte (cerrado=True → solo lectura)
POST /stock/{parte_id}/cerrar → marcar como cerrado (solo ADMIN/OFICINA, o la tienda propietaria)
```

**Lógica de `/stock/nuevo`:**
- Carga todas las combinaciones activas del catálogo:
  - `SaborProducto` con estado != "OUT"
  - Para cada una, los `PrecioProductoTamano` con activo=True
- Agrupa en `{producto: {sabor: [tamanios]}}` ordenado por nombre
- El template muestra una tabla editable con esas combinaciones
- Si ya existe un `ParteStock` abierto de hoy para la tienda del usuario → redirigir a editar ese parte

**Control de acceso:**
- TIENDA: solo ve/crea partes de su propia tienda (`usuario.tienda_id`)
- ADMIN/OFICINA: ven todos, pueden crear para cualquier tienda (selector de tienda en el form)

### Mermas

```
GET  /stock/mermas/           → lista de mermas (filtro: tienda, fecha)
GET  /stock/mermas/nuevo      → formulario nueva merma
POST /stock/mermas/nuevo      → guardar merma
```

**Control de acceso:** igual que partes (TIENDA solo ve las suyas, ADMIN/OFICINA ven todas).

---

## Templates — `app/templates/stock/`

### `index.html`
- Para ADMIN/OFICINA: tabla con columnas Fecha | Tienda | Estado (Abierto/Cerrado) | Total unidades | Acciones
- Para TIENDA: solo sus partes; botón grande "Hacer parte de hoy" si no existe el de hoy
- Enlace a `/stock/mermas/` en la cabecera

### `parte_form.html`
- Cabecera: Fecha (date input), Tienda (selector si ADMIN/OFICINA, readonly si TIENDA)
- Tabla de combinaciones activas: una fila por producto×sabor×tamaño con input numérico de cantidad
- Las filas están agrupadas visualmente por producto (fila de cabecera con nombre del producto)
- Botón "Guardar parte"

### `parte_detalle.html`
- Muestra el parte en solo lectura (tabla igual que el formulario pero sin inputs)
- Si no está cerrado: botón "Cerrar parte"
- Cabecera con fecha, tienda, usuario, estado

### `mermas.html`
- Tabla: Fecha | Tienda | Producto | Sabor | Tamaño | Cant | Motivo | Comentario
- Filtros arriba: tienda (ADMIN/OFICINA), fecha desde/hasta
- Botón "Registrar merma"

### `merma_form.html`
- Campos: Fecha (default hoy), Tienda (selector o readonly), Producto, Sabor, Tamaño, Cantidad, Motivo (select), Comentario (opcional)
- Sabor y Tamaño se cargan dinámicamente según el producto elegido (igual que en pedidos)

---

## Sidebar — cambios en `base.html`

La sección Stock ya existe. Añadir sub-enlace de mermas:

```
ADMIN/OFICINA/TIENDA:
  Stock
    ├── Parte de stock    (/stock/)
    └── Mermas            (/stock/mermas/)
```

El enlace actual `/stock/` ya está. Solo hay que activar la clase activo y añadir el enlace de mermas.

---

## Notas técnicas

- **SQLite batch:** NO hay `ALTER TABLE` en esta fase, solo `CREATE TABLE`. No se necesita `batch_alter_table`.
- **DetachedInstanceError:** convertir objetos ORM a dicts antes de `db.close()`.
- **Tienda de la TIENDA:** `request.state.usuario.tienda_id` — asegurarse de que el modelo Usuario tenga este campo (ya existe desde Fase 0).
- **Combinaciones activas:** consultar `SaborProducto` (estado != "OUT") + `PrecioProductoTamano` (activo=True) para poblar el formulario de parte.
- **Unicidad de parte:** un solo `ParteStock` por (fecha, tienda_id). Si ya existe abierto, redirigir; si está cerrado, mostrar error.
- **Cantidades a 0:** guardar todas las líneas aunque la cantidad sea 0 (no omitir filas vacías), para dejar constancia de que se revisó ese producto.

---

## Orden de ejecución

1. Crear `app/models/stock.py` con los tres modelos
2. Añadir `import app.models.stock` en `alembic/env.py`
3. Generar migración: `.\venv\Scripts\alembic.exe revision --autogenerate -m "fase4_stock"`
4. Aplicar migración: `.\venv\Scripts\alembic.exe upgrade head`
5. Crear `app/api/stock.py` con todas las rutas
6. Crear templates: `stock/index.html`, `stock/parte_form.html`, `stock/parte_detalle.html`, `stock/mermas.html`, `stock/merma_form.html`
7. Actualizar `app/main.py` → incluir `stock.router`
8. Actualizar `base.html` → activar clase activo en `/stock/` y añadir enlace mermas
9. Verificar arranque y rutas manualmente
