# Plan — Albarán Franquicias

Estado: **cerrado, listo para programar** · Fecha: 2026-07-15

## 1. Objetivo

Nuevo apartado **"Albarán franquicias"** que, para cada tienda marcada como
franquicia (`Tienda.es_franquicia`), genere:

1. Un **albarán imprimible en la appweb** con:
   - Los productos y **cantidades exactas que se le envían** ese día (solo lo que
     sale del almacén). **Sin importes** — solo cantidades (ej. "2 · Café").
   - **Datos fiscales del emisor** (Obrador Demo).
   - **Datos fiscales del receptor** (la franquicia).
2. Una **copia del albarán en Holded** (waybill) para la contabilidad. La copia de
   Holded **sí lleva importes** (`precio_franquicia` + IVA 10%): es donde se llevan
   las cuentas. El precio se guarda en el snapshot pero NO se muestra en el impreso.
3. Acceso desde el **Centro de impresión** → tarjeta "Albarán franquicias",
   desde donde se imprime el de cada franquicia.

## 2. Decisiones tomadas (respuestas del 2026-07-15)

| Tema | Decisión |
|------|----------|
| Vínculo tienda ↔ datos fiscales | **FK `cliente_b2b_id` en `Tienda`** apuntando al `ClienteB2B` tipo FRANQUICIA. Reutiliza CIF, razón social, dirección e `id_holded`. |
| Contenido del albarán | **Solo lo que sale del almacén** = columna `envío` (`envio_map`). Los encargos ya van incluidos ahí; no se desglosan (ver §3). |
| Importes en el impreso | **Solo cantidades, sin precios.** El albarán valorado ("todo lo que mandamos con precio") será un apartado aparte más adelante. |
| Anti-doble-facturación | Los pedidos B2B **recogidos en una franquicia** se facturan a través de la franquicia (van en su albarán) y **se excluyen del flujo Holded B2B actual**. Los pedidos entregados en el local del cliente siguen con su factura/albarán propio. |
| Datos del emisor | **Config editable** (tabla `config`, prefijo `empresa.`), con pantalla de edición. |
| Documento Holded | **Albarán (waybill)**, `precio_franquicia` + IVA 10%. |
| Numeración | `AF{código franquicia}-{YYYY}-{DDMM}`. Ej. Fuengirola hoy → `AFF-2026-1507`. Mismo número en Holded. Determinista → idempotente. |
| Roles | Generan e imprimen: **PASTELERAS, JEFES, ADMINISTRACIÓN** (a las 21:00 solo hay pasteleras; el repartidor sale a las 6:00 sin administración). |

## 3. Contenido de las líneas (CONFIRMADO)

Leyendo el cálculo de envíos ([app/api/stock.py:534-551](../../app/api/stock.py#L534)):

```python
necesidad = max(0, prevision − stock) + pedido      # pedidos YA sumados aquí
envio = min(necesidad, cantidad_prod) if cantidad_prod is not None else necesidad
```

**La columna `envío` YA incluye las unidades de los pedidos.** El bloque `pedidos`
que se ve aparte en la ficha es solo informativo (para saber cuántas de las que se
envían van reservadas a encargos).

**Consecuencia:** las líneas del albarán de franquicia = **`envio_map`** (lo que
físicamente sale hacia la tienda). NO se debe hacer `envio + pedidos` o se
duplicaría. "Reposición + pedidos" queda cubierto por esa única cifra.

La regla anti-doble-facturación es **independiente** del cálculo de líneas: se
trata de excluir esos pedidos del *flujo Holded B2B*, no de sumarlos otra vez aquí.

> **CONFIRMADO:** el albarán refleja exactamente la columna `envío` = lo que sale
> del almacén (encargos ya incluidos). Sin desglose reposición/encargos.

## 4. Regla anti-doble-facturación (detalle)

Discriminador de un pedido:
- `pedido.tienda_id` → tienda donde se recoge (se rellena en recogida en tienda).
- `pedido.ubicacion_entrega` = TIENDA | CARRETERIA | RESTAURANTE.

Reglas:
- **B2B recogido en tienda FRANQUICIA** (`tienda_id` → tienda con `es_franquicia`)
  → facturado a la franquicia (entra en su envío/albarán). **Excluir** del flujo
  Holded B2B (`_preview_data`, `index`, `crear_todos`, `albaran_crear`).
- **B2B entregado en su local / carretería** (sin tienda franquicia)
  → flujo Holded B2B actual, **sin cambios**.
- **B2B recogido en tienda PROPIA** (no franquicia)
  → flujo Holded B2B actual (la tienda propia no es entidad de facturación).
- **Particulares recogidos en franquicia** → van en el envío físico igualmente;
  no se facturan al particular por la central (nunca lo han hecho).

Cambio concreto: en el flujo Holded B2B, filtrar fuera los pedidos cuyo
`tienda_id` sea de una tienda con `es_franquicia == True`.

> **I1 (repaso) — discriminador:** el envío incluye un pedido por
> `tienda_id == tienda.id` ([stock.py:503-507](../../app/api/stock.py#L503)),
> **sin mirar `ubicacion_entrega`**. Para que "lo que se factura vía franquicia" y
> "lo que se excluye del flujo B2B" sean el MISMO conjunto, el discriminador de
> exclusión debe ser el mismo criterio: **`tienda_id ∈ franquicias`** (no mezclar
> con `ubicacion_entrega`, o se desincronizan inclusión y exclusión).
> ⚠️ **Verificar §Q2 antes de programar:** que el alta de pedido B2B recogido en
> tienda escribe de verdad `tienda_id` (el modelo lo permite NULL). Si algún B2B
> recogido en franquicia se guarda con `tienda_id = NULL`, se colará en el flujo
> B2B y se facturaría dos veces.

> **M6 (repaso):** `pedidos_map` no filtra por `tipo`, así que en el envío (y en la
> copia Holded) entran también encargos de particulares y B2B recogidos en la
> franquicia, **todos a `precio_franquicia` + IVA 10%**. Coherente con el modelo
> (la central factura a la franquicia lo que le manda). Confirmado implícitamente
> por la decisión "solo lo que sale del almacén".

## 5. Modelo de datos (migraciones Alembic)

### 5.1 `tiendas` — nuevas columnas
- `cliente_b2b_id` (FK `clientes_b2b.id`, nullable). Solo se usa si `es_franquicia`.
- `codigo_albaran` (String corto, nullable). Código para el nº de albarán (ej. "F"
  de Fuengirola). Default = 1ª letra del nombre, editable en la ficha. **Debe ser
  único entre franquicias** para no colisionar en `AF{codigo}-YYYY-DDMM` (dos
  franquicias con la misma inicial). Validar unicidad al guardar.

### 5.2 Nuevas tablas (snapshot inmutable del albarán)
El envío se calcula al vuelo; para evitar duplicados en Holded y que el impreso no
cambie si la previsión/stock se recalcula, se guarda una foto al generar.

`albaranes_franquicia`
- `id` PK
- `tienda_id` FK tiendas
- `cliente_b2b_id` FK clientes_b2b (receptor, copiado al generar)
- `fecha` (fecha del envío)
- `numero` (nº de albarán, ver §7)
- `holded_doc_id` (nullable hasta que se cree en Holded)
- `total_sin_iva`, `total_iva`, `total` (snapshot)
- `creado_en`, `creado_por` (usuario_id)
- UNIQUE(`tienda_id`, `fecha`) → un albarán por franquicia y día (idempotencia)

`lineas_albaran_franquicia`
- `id` PK
- `albaran_id` FK (cascade)
- `producto_id`, `sabor_id`
- `producto_nombre`, `sabor_nombre` (congelados por separado — ver C1)
- `descripcion` (texto congelado para el impreso: "SABOR PRODUCTO")
- `cantidad`
- `precio_unit` (precio_franquicia congelado, para Holded)

> **C1 (repaso):** guardar `producto_nombre`/`sabor_nombre` por separado y **NO
> reutilizar `construir_items`** para la copia Holded. Esa función espera claves
> `sabor_nombre`/`tamano_nombre` y re-mira el catálogo; tras congelar, el waybill
> se construye directo del snapshot: `{name: descripcion, units: cantidad,
> subtotal: precio_unit, tax: 10}` (mismo formato interno que consume
> `crear_documento`). Evita re-lookup y desincronización.

### 5.3 Config emisor (tabla `config`, prefijo `empresa.`)
`empresa.razon_social`, `empresa.cif`, `empresa.direccion`, `empresa.cp`,
`empresa.poblacion`, `empresa.provincia`, `empresa.telefono`, `empresa.email`,
`empresa.registro_sanitario` (opcional).

## 6. Backend (nuevo módulo `app/api/franquicias.py`)

Prefijo `/franquicias`. Permiso nuevo `franquicias` en la matriz
([app/auth/permisos.py](../../app/auth/permisos.py)): **PASTELERAS, JEFE_PASTELEROS,
JEFES y ADMINISTRACIÓN = EDITAR** (a las 21:00 solo hay pasteleras y el repartidor
sale a las 6:00 sin administración; deben poder generar e imprimir).

> **C2 (repaso):** `franquicias` NO se resuelve solo. `_TODO_JEFES`
> (permisos.py:27-29) no la incluye → JEFES y ADMINISTRACIÓN darían **403**. Hay que
> añadir `"franquicias": Nivel.EDITAR` explícitamente en **3 sitios**: `_TODO_JEFES`
> (cubre JEFES+ADMINISTRACIÓN), el dict de `Rol.PASTELERAS` y el de
> `Rol.JEFE_PASTELEROS`. Ámbito TIENDAS no aplica (no se les da el permiso).

Endpoints:
- `GET /franquicias/albaranes?fecha=` → lista de franquicias con reparto ese día
  (por defecto mañana), estado de su albarán (generado / en Holded / pendiente).
- `GET /franquicias/albaranes/{tienda_id}?fecha=` → **preview** del albarán:
  líneas (desde `envio_map`), importes, datos emisor+receptor, avisos
  (sin `cliente_b2b_id`, sin `precio_franquicia`, sin `id_holded`...).
- `POST /franquicias/albaranes/{tienda_id}` (fecha) → **genera** el snapshot local
  (`albaranes_franquicia` + líneas). Idempotente por UNIQUE(tienda, fecha):
  si existe, `recrear=1` para regenerar.
- `POST /franquicias/albaranes/{tienda_id}/holded` → crea el **waybill en Holded**
  reutilizando `crear_documento(...)` y guarda `holded_doc_id`. Exige `recrear`
  si ya tiene doc.
- `GET /franquicias/albaranes/{albaran_id}/imprimir` → vista imprimible A4.
- Config emisor: `GET/POST /franquicias/config-empresa`.

Lógica de líneas: **refactor de `stock.envios_get`** para extraer un helper
puro `calcular_envio(db, tienda, fecha) -> envio_map` reutilizable, y así no
duplicar el cálculo. Solo tiendas con `es_franquicia == True`.

> **I3 (repaso):** el helper NO depende de `usuario.rol` (el filtro TIENDAS solo
> decide qué tiendas se listan), pero debe englobar TODO el bloque
> [stock.py:489-550](../../app/api/stock.py#L489): parte del día anterior con
> `_tartas_equiv`, `pedidos_map`, `prevision_map` por `dia_semana` y
> `prod_confirmada`. Ojo timing: `envio` solo se capa a lo horneado **si existe**
> `ProduccionDia` de esa fecha; si las pasteleras generan el albarán a las 21:00
> **antes** de confirmar producción, se congela la necesidad teórica, no lo real
> horneado. → **Verificar §Q1**.

Servicio Holded: construir el waybill **directo del snapshot** (ver C1) y llamar a
`crear_documento` ([app/services/holded.py](../../app/services/holded.py)).
`contact_id` = `cliente_b2b.id_holded` del receptor. Ya soporta v1/v2.

> **I2 (repaso):** `crear_documento` manda `docNumber`/`document_number` tal cual,
> sin control de duplicados. Como el número es determinista, un 2º push a Holded
> con `recrear` reintenta el MISMO número → Holded puede rechazarlo o duplicar,
> dejando el `holded_doc_id` viejo huérfano. Semántica adoptada: **si ya hay
> `holded_doc_id`, bloquear el re-push salvo confirmación explícita**; al recrear NO
> se borra el doc anterior automáticamente (se avisa de borrarlo a mano en Holded).
> El UNIQUE(tienda,fecha) resuelve la idempotencia LOCAL, no la de Holded.

## 7. Numeración (CONFIRMADO)

Formato: **`AF{codigo_albaran}-{YYYY}-{DDMM}`**
- Ej. Fuengirola, 15/07/2026 → `AFF-2026-1507`.
- `codigo_albaran` = campo de la tienda (§5.1), default 1ª letra del nombre.
- **Mismo número en Holded** (se pasa como `docNumber`/`document_number`).
- Determinista → idempotente: recalcular el mismo día da el mismo número, encaja
  con el UNIQUE(tienda, fecha).

Helper: `numero_albaran(tienda, fecha) -> f"AF{tienda.codigo_albaran}-{fecha:%Y-%d%m}"`.

## 8. Frontend / plantillas

- `app/templates/franquicias/albaranes.html` — lista por día (como `holded/index`).
- `app/templates/franquicias/albaran_preview.html` — preview + botones generar/Holded.
- `app/templates/franquicias/albaran_print.html` — A4 imprimible (emisor, receptor,
  nº albarán, fecha, tabla de líneas **solo cantidad + descripción, sin importes**).
  Reutilizar tokens de `estilos.css`.
- `app/templates/franquicias/config_empresa.html` — form datos emisor.
- **Centro de impresión** ([app/templates/imprimir/index.html](../../app/templates/imprimir/index.html)):
  nueva tarjeta "🧾 Albarán franquicias" → `/franquicias/albaranes`.
- Ficha de tienda: selector de `cliente_b2b_id` cuando `es_franquicia`
  (en [app/templates/tiendas/](../../app/templates/tiendas/)).
- Registrar el router en [app/main.py](../../app/main.py) y añadir al menú
  [app/templates/base.html](../../app/templates/base.html).

## 9. Cambios en el flujo Holded B2B existente (anti-doble-facturación)

En [app/api/holded.py](../../app/api/holded.py): en `index`, `crear_todos` y
`_preview_data`, excluir los pedidos B2B cuyo `tienda_id` sea de una tienda con
`es_franquicia == True`. Un helper `_es_pedido_de_franquicia(pedido, tiendas_map)`.
Test de regresión: un B2B recogido en franquicia NO aparece como pendiente en
`/holded`.

## 10. Tests (TDD)

- `calcular_envio` helper: coincide con lo que muestra la ficha de envíos.
- Preview albarán franquicia: líneas = `envio_map`, importes = cantidad×precio_franquicia, IVA 10%.
- Avisos: franquicia sin `cliente_b2b_id`, cliente sin `id_holded`, producto sin `precio_franquicia`.
- Idempotencia: 2º POST no duplica; `recrear` regenera.
- Exclusión B2B: pedido B2B recogido en franquicia excluido del flujo Holded B2B;
  el entregado en local sí aparece.
- Permisos: rol sin `franquicias` recibe 403.

## 11. Orden de implementación (mañana)

0. **Verificaciones previas** (§14) antes de tocar código: `alembic heads`, y
   confirmar que el alta de pedido B2B con recogida en tienda escribe `tienda_id`.
1. Migración `tiendas.cliente_b2b_id` **+ `codigo_albaran`** (único entre
   franquicias, default 1ª letra) + selector/edición en la ficha de tienda + validación de unicidad. Encadenar `down_revision` al head real.
2. Config emisor (`empresa.*`) + pantalla. **Sin migración** (tabla `config` es
   key/value genérica, ya usada para `holded_api_key`).
3. Refactor `calcular_envio(db, tienda, fecha)` helper en stock (englobar bloque
   [489-550](../../app/api/stock.py#L489)); no debe cambiar el comportamiento de
   `/stock/envios/`.
4. Migración `albaranes_franquicia` + `lineas_albaran_franquicia` (con
   `producto_nombre`/`sabor_nombre` por separado, C1). UNIQUE(tienda, fecha).
5. Módulo `app/api/franquicias.py` (preview → generar snapshot → push Holded
   directo del snapshot → imprimir). **Registrar router en
   [app/main.py](../../app/main.py)** (M7).
6. Plantillas + tarjeta en centro de impresión + menú + **permiso `franquicias` en
   los 3 sitios de la matriz** (C2).
7. Exclusión anti-doble-facturación en flujo Holded B2B (`index`, `crear_todos`,
   `_preview_data`): filtrar B2B con `tienda_id ∈ franquicias` (I1).
8. Tests (§10).

## 12. Decisiones cerradas (resumen)

1. **Líneas** = columna `envío` (lo que sale del almacén, encargos incluidos). ✅
2. **Numeración** = `AF{codigo}-{YYYY}-{DDMM}`, mismo número en Holded. ✅
3. **Impreso** = solo cantidades, sin importes (el valorado será apartado futuro). ✅
4. **Roles** = PASTELERAS, JEFE_PASTELEROS, JEFES, ADMINISTRACIÓN. ✅
5. **Un albarán por franquicia y día** (UNIQUE tienda+fecha). Asunción conservadora;
   avisar si una franquicia puede tener varios envíos el mismo día.

## 13. Idea futura (no ahora)

Apartado "albarán valorado / listado completo con precios" — todo lo que se manda
con importes. Se hará más adelante, fuera de este alcance.

## 14. Verificaciones y decisiones del repaso (planner, 2026-07-15)

Correcciones ya integradas arriba: **C1** (snapshot con nombres separados + waybill
directo, no `construir_items`), **C2** (permiso en 3 sitios de la matriz), **I2**
(recreación Holded: bloquear re-push sin confirmación, no auto-borrar), **I3**
(timing producción), **M3** (`codigo_albaran` en paso 1), **M4** (config sin
migración), **M5** (encadenar `alembic heads`), **M6** (encargos a precio_franquicia),
**M7** (registrar router). Roles unificados a 4: PASTELERAS, JEFE_PASTELEROS, JEFES,
ADMINISTRACIÓN.

**Resueltas (Hugo, 2026-07-15):**
- **Q2 / I1 — RESUELTO:** los pedidos B2B recogidos en tienda deben llevar
  `tienda_id` para NO generarles factura/albarán propio. Confirmado como criterio
  correcto. Tarea en el paso 0: revisar el alta de pedidos B2B y **garantizar que la
  recogida en tienda escribe `tienda_id`** (añadirlo si no lo hace ya).
- **Q1 / I3 — RESUELTO:** el albarán se genera **DESPUÉS** de confirmar la
  producción del día. Así el snapshot refleja lo realmente horneado. (No recalcular
  al imprimir; se congela al generar tras producción.)

**Decisiones menores pendientes (no bloquean, se pueden cerrar mañana al empezar):**
- **M2:** ¿REPARTIDORES necesita reimprimir el albarán a las 6:00 desde la app, o
  basta con el papel generado la noche anterior? Si lo necesita, darle `franquicias`
  = VER. (Asunción actual: papel listo la noche anterior, no se le da permiso.)

**Tarea futura relacionada (aparcada, en BACKLOG "Buzón de ideas"):**
- Opción para que las pasteleras **editen los envíos** cuando cambia la producción
  del día, para que las fichas no queden desajustadas. Fuera del alcance de esta
  feature; se hará como task aparte.
