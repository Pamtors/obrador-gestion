# Plan Fase 4b — Rediseño Stock (Ficha PDF + Previsión + Días Reparto)

## Respuestas de diseño confirmadas
- **2 columnas** = Tartas enteras / Raciones (porciones)
- **Días de reparto** = fijos semanales pero editables (override puntual posible)
- **Previsión** = varía por día de semana (más stock el fin de semana)

---

## Qué cambia respecto a la Fase 4

Fase 4 construyó la estructura base. Esta fase la redesña completamente:
- El formulario de parte pasa a tener 2 columnas (enteras/raciones) + sección "Otros"
- El índice pasa a vista horizontal multi-tienda
- Se añaden previsión, días de reparto y necesidades → integración en horneado

---

## Cambios en modelos

### 1. Alterar `lineas_parte_stock` — añadir `raciones`

```python
# Añadir a LineaParteStock:
raciones: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
```

### 2. Nueva tabla `lineas_parte_stock_otros`

Para items que no están en el catálogo (rellenos, pedidos no recogidos, sobrantes).

```python
class LineaParteStockOtros(Base):
    __tablename__ = "lineas_parte_stock_otros"
    id: int (PK)
    parte_stock_id: FK → partes_stock (CASCADE)
    descripcion: String(200)         # "Pistacho pequeña sobrante", etc.
    tartas_enteras: int (default=0)
    raciones: int (default=0)
```

### 3. Nueva tabla `prevision_stock`

Target de stock por tienda × día de semana × combinación de producto.

```python
class PrevisionStock(Base):
    __tablename__ = "prevision_stock"
    id: int (PK)
    tienda_id: FK → tiendas
    dia_semana: int  # 0=Lunes … 6=Domingo
    producto_id: FK → productos
    sabor_id: FK → sabores
    tamano_id: FK → tamanios
    cantidad: int (default=0)   # tartas enteras objetivo
    # UniqueConstraint(tienda_id, dia_semana, producto_id, sabor_id, tamano_id)
```

### 4. Nueva tabla `dias_reparto`

Días en que cada tienda recibe mercancía. Puede editarse.

```python
class DiasReparto(Base):
    __tablename__ = "dias_reparto"
    id: int (PK)
    tienda_id: FK → tiendas
    dia_semana: int  # 0=Lunes … 6=Domingo
    # UniqueConstraint(tienda_id, dia_semana)
```

---

## Migración

Un único archivo Alembic:
1. `lineas_parte_stock` (batch): add `raciones` Integer default 0
2. `CREATE TABLE lineas_parte_stock_otros`
3. `CREATE TABLE prevision_stock`
4. `CREATE TABLE dias_reparto`

---

## API — reescritura completa de `app/api/stock.py`

### Rutas (orden: literales primero)

```
GET  /stock/                          → vista horizontal multi-tienda (hoy por defecto)
GET  /stock/necesidades/              → qué hay que hornear/enviar hoy por tienda
GET  /stock/reparto/                  → config días reparto (ADMIN)
POST /stock/reparto/                  → guardar días reparto (ADMIN)
GET  /stock/prevision/{tienda_id}     → editar previsión de una tienda (ADMIN)
POST /stock/prevision/{tienda_id}     → guardar previsión
GET  /stock/mermas/                   → (sin cambios)
GET  /stock/mermas/nuevo              → (sin cambios)
POST /stock/mermas/nuevo              → (sin cambios)
GET  /stock/nuevo                     → formulario nuevo parte (rediseñado)
POST /stock/nuevo                     → guardar parte (acepta enteras+raciones+otros)
POST /stock/{parte_id}/cerrar         → (sin cambios)
GET  /stock/{parte_id}                → detalle parte (rediseñado)
```

### Lógica `GET /stock/` — vista multi-tienda horizontal

- Parámetros: `?fecha=YYYY-MM-DD&tienda_id=N`
- Si se pasa `tienda_id` → solo esa tienda (vista vertical normal)
- Sin tienda_id → columnas = todas las tiendas activas, filtradas a las que tienen parte ese día
- Filas = todas las combinaciones activas del catálogo
- Celdas = `(tartas_enteras, raciones)` del ParteStock de esa tienda en esa fecha; `(—, —)` si no existe
- Muestra también "Otros" al final de cada tienda

### Lógica `GET /stock/necesidades/`

- Parámetros: `?fecha=YYYY-MM-DD`
- Día de semana de la fecha → obtener tiendas con entrega ese día (DiasReparto)
- Para cada tienda con entrega: obtener PrevisionStock para ese dia_semana
- Buscar ParteStock del día anterior de esa tienda (el último stock conocido)
- Necesidad por item = max(0, prevision.cantidad - stock_ayer.tartas_enteras)
- Mostrar tabla: tienda × producto/sabor/tamaño → prevision | stock_ayer | necesidad
- Totales por producto/sabor/tamaño (para dar a obrador el total a hornear)

### Lógica `GET/POST /stock/reparto/`

- Muestra grid: filas = tiendas activas, columnas = L M X J V S D
- Checkboxes marcados según `DiasReparto` existentes
- POST: borra todos los DiasReparto de las tiendas activas y reinserta los marcados

### Lógica `GET/POST /stock/prevision/{tienda_id}`

- Selector de día de semana (tabs: L M X J V S D)
- Tabla = combinaciones activas del catálogo con input de cantidad objetivo
- POST: upsert de PrevisionStock para tienda × dia_semana

---

## Templates — `app/templates/stock/`

### `index.html` — REDISEÑADO

Vista horizontal multi-tienda:
```
[Filtros: fecha | tienda (opcional)] [Botón: + Nuevo parte]

       TIENDA A          TIENDA B          TIENDA C
       Ent  | Rac        Ent  | Rac        Ent  | Rac
TARTA DE QUESO
  Pistacho    2      5     1      3     —      —
  Lotus       1      2     0      1     —      —
TARRINA
  Pistacho    0      —     2      —     3      —
...
OTROS (por tienda)  (descripción libre)
```

CSS: `table-layout: fixed`, scroll horizontal, primera columna sticky.

Si se filtra por tienda → muestra solo esa columna (vista vertical).

### `parte_form.html` — REDISEÑADO

Cabecera: Fecha, Tienda, encabezados de columna (TARTAS ENTERAS | RACIONES)

Cuerpo: igual que la ficha PDF — secciones por producto, filas por sabor/tamaño.
Inputs: `ent_{prod}_{sabor}_{tam}` y `rac_{prod}_{sabor}_{tam}`

Sección OTROS al final: 5 filas vacías con:
- `otros_desc_{n}` (text)
- `otros_ent_{n}` (number)
- `otros_rac_{n}` (number)

### `parte_detalle.html` — REDISEÑADO

Igual que el formulario pero en solo lectura. Muestra ambas columnas.

### `necesidades.html` — NUEVO

Tabla con tiendas como columnas o en filas agrupadas.
Totales a hornear resaltados en azul.
Enlace a `/horneado/?fecha=...`.

### `reparto.html` — NUEVO

Grid de checkboxes tienda × día de la semana.

### `prevision.html` — NUEVO

Tabs por día de semana. Tabla de combinaciones activas con inputs de cantidad.

---

## Integración con horneado

Modificar `app/api/produccion.py` → `GET /horneado/`:
- Calcular necesidades del día igual que `/stock/necesidades/`
- Añadir `necesidades` al contexto de la plantilla

Modificar `app/templates/produccion/horneado.html`:
- Añadir sección "REPOSICIÓN TIENDAS" debajo de la lista de horneado existente
- Misma estructura visual (producto → sabor → tamaño → cantidad total a reponer)

---

## Sidebar — cambios en `base.html`

Bajo Stock (ADMIN/OFICINA/TIENDA), añadir:
- Necesidades → `/stock/necesidades/`
- ADMIN only: Previsión → `/stock/prevision/` (como página de selección de tienda)
- ADMIN only: Días reparto → `/stock/reparto/`

---

## Notas técnicas

- **batch_alter_table**: OBLIGATORIO para añadir `raciones` a `lineas_parte_stock` (SQLite).
- **UniqueConstraint prevision_stock**: (tienda_id, dia_semana, producto_id, sabor_id, tamano_id).
- **UniqueConstraint dias_reparto**: (tienda_id, dia_semana).
- **Stock "ayer"**: buscar el ParteStock más reciente anterior a `fecha` para esa tienda (no necesariamente el día anterior exacto, ya que puede no haber parte todos los días).
- **Vista horizontal**: usar `<thead>` con colspan para tiendas; sticky primera columna con `position: sticky; left: 0`.
- **tojson en templates**: disponible (ya se usa en pedidos/crear.html).

---

## Orden de ejecución

1. Modificar `app/models/stock.py` → añadir `LineaParteStockOtros`, `PrevisionStock`, `DiasReparto`; añadir campo `raciones` a `LineaParteStock`
2. Actualizar `alembic/env.py` (no necesita cambios si stock ya está importado)
3. Generar migración: `alembic revision --autogenerate -m "fase4b_stock_redesign"`
4. Aplicar migración: `alembic upgrade head`
5. Reescribir `app/api/stock.py` completamente
6. Modificar `app/api/produccion.py` → añadir necesidades al contexto horneado
7. Rediseñar `stock/index.html` (vista multi-tienda)
8. Rediseñar `stock/parte_form.html` (ficha PDF con 2 cols)
9. Rediseñar `stock/parte_detalle.html`
10. Crear `stock/necesidades.html`
11. Crear `stock/reparto.html`
12. Crear `stock/prevision.html`
13. Modificar `produccion/horneado.html` → añadir sección REPOSICIÓN
14. Actualizar `base.html` → nuevos enlaces sidebar
15. Verificar arranque y rutas
