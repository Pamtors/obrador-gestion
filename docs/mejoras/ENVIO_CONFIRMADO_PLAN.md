# Plan — Envío confirmado (Editar / Confirmar en la ficha de envío)

Estado: **cerrado, listo para programar** · Fecha: 2026-07-16

## 1. Problema

Hoy la **lista de horneado** (`/horneado/`) se confirma y se congela en
`ProduccionDia` (fuente de verdad). Pero la **ficha de envío** (`/stock/envios/`)
**no se guarda en ningún sitio**: se recalcula en vivo cada vez con
`calcular_envio()` (previsión − stock ayer + pedidos, capado a lo horneado).

Consecuencia: si mañana las pasteleras cambian el horneado (p.ej. se quedan sin
galletas de pistacho) **no tienen forma de ajustar a mano el envío a cada tienda**.
El reparto automático se distribuye solo, y lo que reciben las tiendas puede no
coincidir ni con lo que la pastelera decidió ni con el albarán. Además el albarán
de franquicia se genera desde ese mismo cálculo en vivo, así que puede imprimirse
un albarán que luego no cuadra.

## 2. Objetivo

Que el envío tenga la misma garantía que el horneado: **una cifra confirmada,
editable a mano y congelada**, que sea la única fuente de verdad para:

1. Lo que ve la tienda en su ficha de envío.
2. Lo que sale físicamente del almacén.
3. Las líneas del albarán de franquicia (que solo se podrá generar/imprimir
   **después** de confirmar el envío, nunca antes).

Mecánica pedida (igual que horneado, pero con doble botón para no editar sin
querer): en cada ficha de envío, dos botones **Editar** y **Confirmar envío**.

## 3. Decisiones tomadas (2026-07-16)

| Tema | Decisión |
|------|----------|
| Alcance de la confirmación | **Por tienda**: cada ficha tiene su Editar/Confirmar y su estado. Encaja 1:1 con el albarán (uno por tienda/fecha). |
| Quién edita/confirma | **Solo obrador**: PASTELERAS, JEFE_PASTELEROS, JEFES, ADMINISTRACION. REPARTIDORES y TIENDAS ven la ficha en **solo lectura** (aunque hoy tengan `stock.envios` EDITAR). |
| Albarán antes de confirmar | **Bloqueado.** `build_preview` añade bloqueante si el envío de esa tienda/fecha no está confirmado. El albarán se genera desde el envío confirmado, no desde `calcular_envio()`. |
| Qué se congela | Solo la **cantidad por (producto, sabor)**. No se añaden/quitan líneas fuera del roster de la previsión (mismo criterio que la ficha actual). |
| Reabrir tras confirmar | **Editar** vuelve a hacer editables las casillas (precargadas con lo confirmado) y **Confirmar** re-graba. Si el albarán ya se había generado, se avisa de que hay que regenerarlo (§7). |
| Punto de partida al editar | Las casillas se precargan con el **envío propuesto** (`calcular_envio()`) si aún no hay confirmación, o con lo ya confirmado si la hay. |

## 4. Modelo de datos (nuevo)

Cabecera + líneas, mismo patrón que `ParteStock`/`LineaParteStock`:

```python
# app/models/envio.py  (NUEVO)

class EnvioTienda(Base):
    """Envío confirmado a una tienda en una fecha. Congela lo que sale del
    almacén; fuente de verdad para la ficha de la tienda y el albarán."""
    __tablename__ = "envios_tienda"
    __table_args__ = (
        UniqueConstraint("tienda_id", "fecha", name="uq_envio_tienda_fecha"),
    )
    id            : int
    tienda_id     : FK tiendas.id      (not null)
    fecha         : Date               (not null)
    confirmado    : bool = False       (not null)
    confirmado_en : DateTime | None
    confirmado_por: FK usuarios.id | None
    lineas: relationship(cascade="all, delete-orphan")

class LineaEnvioTienda(Base):
    __tablename__ = "lineas_envio_tienda"
    id             : int
    envio_tienda_id: FK envios_tienda.id (ondelete CASCADE, not null)
    producto_id    : FK productos.id     (not null)
    sabor_id       : FK sabores.id       (not null)
    cantidad       : int = 0             (not null)
```

Nota: se guarda cabecera aparte (con `confirmado`) en vez de "existe fila =
confirmado" para tener sello temporal/autor y poder representar un envío
confirmado con ceros. Solo se guardan líneas con `cantidad > 0`.

**Migración Alembic** nueva (crear ambas tablas), siguiendo el estilo de
`alembic/versions/a1b2c3d4e5f6_t5_t6_t8_stock_envios_horneado.py`.

## 5. Backend

### 5.1 Helper de lectura — `app/api/stock.py`

```python
def envio_confirmado_map(db, tienda_id, fecha) -> dict | None:
    """{(prod_id, sabor_id): cantidad} si existe EnvioTienda.confirmado para
    esa tienda/fecha; None si no hay confirmación (→ usar propuesta en vivo)."""
```

`calcular_envio()` **se mantiene**: es la propuesta/punto de partida que se
muestra y precarga antes de confirmar. No se toca su lógica.

### 5.2 Ficha de envío — `envios_get` (`GET /stock/envios/`)

Por cada tienda:
- `conf = envio_confirmado_map(db, tienda.id, fecha_dt)`.
- Si `conf is not None` → los valores `envio` de las filas salen de `conf`;
  marcar `ficha["confirmado"] = True`.
- Si `conf is None` → `envio_map = calcular_envio(...)` (como hoy);
  `ficha["confirmado"] = False`.
- Añadir al contexto de cada ficha `puede_editar` = usuario es obrador
  (helper `_rol_obrador(usuario)`, ver §5.4) y **no** es TIENDAS.

El resto del armado de secciones/filas no cambia (las filas ya llevan
`key = "{pid}_{sid}"`, que reutilizamos como `name` de los inputs).

### 5.3 Confirmar envío — `POST /stock/envios/{tienda_id}/confirmar` (NUEVO)

```python
@router.post("/envios/{tienda_id}/confirmar")
@requiere_permiso("stock.envios", editar=True)
async def envio_confirmar(request, tienda_id):
    # 1. Guard de rol: solo obrador (§5.4). TIENDAS/REPARTIDORES → 403.
    # 2. fecha del form (por defecto mañana, como el resto de envíos).
    # 3. Upsert EnvioTienda(tienda_id, fecha): crear si no existe.
    # 4. Reemplazar líneas: borrar las actuales, reinsertar cant_<pid>_<sid> > 0.
    # 5. confirmado=True, confirmado_en=now, confirmado_por=usuario.id.
    # 6. Redirect a /stock/envios/?fecha=...
```

Formato de inputs: `cant_<producto_id>_<sabor_id>` (idéntico a horneado, parseo
por `split("_")`). Valores negativos → 0 (`max(0, int(val))`). Manejar
`IntegrityError` del UNIQUE por doble submit (patrón de `parte_nuevo_post`).

### 5.4 Guard de rol (obrador)

```python
def _rol_obrador(usuario) -> bool:
    return usuario.rol in (Rol.PASTELERAS, Rol.JEFE_PASTELEROS,
                           Rol.JEFES, Rol.ADMINISTRACION)
```

`stock.envios` da EDITAR también a REPARTIDORES y TIENDAS
([permisos.py:37-66](../../app/auth/permisos.py#L37)), por eso el decorador no
basta: el endpoint de confirmar comprueba además `_rol_obrador`.

### 5.5 Albarán franquicia — `app/api/franquicias.py`

`build_preview()` ([franquicias.py:145](../../app/api/franquicias.py#L145)):

- Sustituir `envio_map = calcular_envio(db, tienda, fecha)` por
  `envio_map = envio_confirmado_map(db, tienda.id, fecha)`.
- Si `envio_map is None` → **bloqueante**: *"El envío de esta franquicia no está
  confirmado. Confírmalo en Stock › Envíos antes de generar el albarán."*
- Si `envio_map == {}` (confirmado vacío) → el bloqueante existente
  *"No hay nada que enviar…"* sigue valiendo.

Con esto, el resto del flujo de albarán (snapshot congelado, Holded, edición
manual de cantidades por JEFES) **no cambia**: simplemente ahora parte de una
cifra ya confirmada por el obrador en vez de un cálculo en vivo.

## 6. Frontend — `app/templates/stock/envios.html`

La plantilla es hoy una hoja imprimible sin formulario. Cambios mínimos:

- **Estado por ficha**: chip en la cabecera —
  `✓ Envío confirmado` (verde) / `Sin confirmar` (ámbar)— según `ficha.confirmado`.
  Reutilizar estilos de chip de horneado (`.estado-chip`).
- **Envolver cada ficha en su `<form method="post"
  action="/stock/envios/{{ ficha.tienda_id }}/confirmar">`** con un
  `<input type="hidden" name="fecha" value="{{ fecha.isoformat() }}">`.
- **Botones (solo si `ficha.puede_editar`)**, en la zona de controles de la ficha:
  - `Editar` (tipo botón, JS): pasa la ficha a modo edición.
  - `Confirmar envío` (`type="submit"`, oculto hasta pulsar Editar): graba.
- **Casilla de envío editable**: la celda `td.num.env` que hoy pinta
  `fila.envio` pasa a contener, en modo edición, un
  `<input type="number" name="cant_{{ fila.key }}" value="{{ fila.envio }}">`
  (reutilizar `key = "{pid}_{sid}"` que ya viene en la fila). Fuera de modo
  edición se muestra el número tal cual (para no romper la impresión).
- **JS mínimo** (patrón de horneado): un `toggleEditar(fichaEl)` que muestra los
  inputs, oculta los números estáticos y revela el botón Confirmar. Sin edición
  activa, la hoja se ve e imprime igual que ahora.

TIENDAS y REPARTIDORES: `puede_editar = False` → ven la ficha en solo lectura,
sin botones ni inputs.

## 7. Interacción con el albarán ya generado (caso borde)

Si se re-confirma un envío cuya franquicia **ya tenía albarán generado**:
- El albarán es un snapshot independiente; no se toca automáticamente.
- Al re-generar (`recrear=1`) leerá el nuevo envío confirmado. El aviso de Holded
  existente (`aviso_holded_previo`) ya cubre el caso de un doc previo en Holded.
- **Suposición conservadora**: no se añade lógica de invalidación automática del
  albarán en esta fase. Basta con que, tras cambiar el envío, el obrador
  regenere el albarán (flujo ya existente). Documentar en la ayuda de la pantalla.

## 8. Validación opcional (aviso, no bloqueante)

Motivación directa del problema (falta de pistacho): al editar, si la **suma de
lo enviado a todas las tiendas** para un (producto, sabor) supera lo horneado
(`ProduccionDia`), mostrar un aviso ámbar por fila (patrón `.aviso-pedidos` de
horneado). No bloquea el guardado; solo advierte de que se está repartiendo más
de lo que se horneó. **Incluir si da tiempo; no es imprescindible para el MVP.**

## 9. Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `app/models/envio.py` | **NUEVO** — `EnvioTienda` + `LineaEnvioTienda`. |
| `app/models/__init__.py` | Registrar los modelos nuevos si allí se importan. |
| `alembic/versions/xxxx_envio_confirmado.py` | **NUEVO** — crear las dos tablas. |
| `app/api/stock.py` | `envio_confirmado_map()`, `_rol_obrador()`, usar confirmado en `envios_get`, endpoint `POST /envios/{tienda_id}/confirmar`. |
| `app/api/franquicias.py` | `build_preview` lee `envio_confirmado_map` + bloqueante si no confirmado. |
| `app/templates/stock/envios.html` | Chip de estado, form por ficha, botones Editar/Confirmar, inputs de cantidad, JS. |
| `tests/` | Ver §10. |

## 10. Tests

Reutilizar el estilo de `tests/test_calcular_envio.py` y
`tests/test_albaranes_franquicia.py`:

1. `envio_confirmado_map` devuelve `None` sin confirmación y el map correcto con ella.
2. `envios_get`: sin confirmar muestra la propuesta; con confirmado muestra lo congelado (aunque cambie el stock/previsión después).
3. `POST /envios/{id}/confirmar`: guarda líneas, marca `confirmado`, sello temporal/autor; re-confirmar reemplaza.
4. Guard de rol: TIENDAS y REPARTIDORES reciben 403 al confirmar; ven la ficha en solo lectura.
5. Albarán: `build_preview` bloquea si el envío no está confirmado; genera con las cantidades confirmadas cuando lo está.
6. Idempotencia del UNIQUE(tienda, fecha) ante doble submit.

## 11. Orden de implementación sugerido (para Sonnet)

1. Modelo `envio.py` + migración Alembic + registro. Migrar en local.
2. `envio_confirmado_map` + `_rol_obrador` + endpoint `confirmar` (con tests 1, 3, 4, 6).
3. `envios_get` usa el confirmado (test 2).
4. Plantilla `envios.html`: chip, form, botones, inputs, JS.
5. `build_preview` bloquea/usa confirmado (test 5).
6. (Opcional) Aviso de sobre-reparto §8.

Cada bloque es verificable por separado; 1–3 no rompen la pantalla actual
(mientras no haya confirmaciones, todo sigue mostrando la propuesta en vivo).
