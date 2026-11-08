# Auditoría de código — Obrador Demo

**Fecha:** 2026-07-06 · **Alcance:** `app/` completo (~4.600 líneas), `requirements.txt`, arranque y configuración.

> **Estado (2026-07-06):** C1–C6, I1, I2 e I4 **aplicados y verificados** en la rama `auditoria-fixes` (backup previo de la BD en `backups/obrador_pre_auditoria_20260706.db`). Quedan pendientes a futuro: I3 (solo aplica si se pasa a HTTPS), I5 (tests) y las optimizaciones O1–O3 (solo si se nota lentitud).

Cada punto lleva: qué pasa, por qué es un problema, y **cómo arreglarlo sin romper nada**. Los puntos están ordenados por prioridad. Recomendación general: arreglar de uno en uno, probar la pantalla afectada tras cada cambio, y hacer un commit por punto.

---

## 🔴 CRÍTICO — arreglar cuanto antes

### C1. `requests` no está en `requirements.txt`

- **Dónde:** `requirements.txt` + `app/services/holded.py:7`
- **Problema:** `services/holded.py` hace `import requests`, pero `requests` no aparece en `requirements.txt` (está instalado en el venv actual de casualidad, seguramente como resto de otra instalación).
- **Riesgo:** el día que reinstales el venv, despliegues en un servidor o clones el repo en otro PC, la app **no arranca** (`ModuleNotFoundError` al importar `app.main`).
- **Arreglo (sin riesgo, no toca código):** añadir esta línea a `requirements.txt`:
  ```
  requests==2.34.2
  ```
  (es la versión que ya tienes en el venv: no cambia nada del comportamiento actual).

### C2. SQLite no tiene las foreign keys activadas

- **Dónde:** `app/database.py:11-13`
- **Problema:** SQLite ignora las `ForeignKey` (y los `ondelete="CASCADE"`) salvo que se active `PRAGMA foreign_keys=ON` en cada conexión. Ahora mismo la BD acepta filas huérfanas sin quejarse.
- **Riesgo real ya presente:** en `app/api/stock.py:935`, si un ADMIN envía el formulario de parte nuevo sin tienda, se guarda un `ParteStock` con `tienda_id=0` (una tienda que no existe) y la BD lo acepta. Datos corruptos silenciosos que luego rompen listados ("—" por todas partes) y cálculos de necesidades.
- **Arreglo:** en `app/database.py`, después de crear el `engine`, añadir:
  ```python
  from sqlalchemy import event

  if config.database_url.startswith("sqlite"):
      @event.listens_for(engine, "connect")
      def _fk_on(dbapi_conn, _):
          dbapi_conn.execute("PRAGMA foreign_keys=ON")
  ```
- **⚠️ Precaución antes de activarlo:** si ya hay filas huérfanas en la BD, las FKs no fallan al leer, solo al insertar/borrar, así que activarlo es seguro. Pero conviene **comprobar primero si existe basura** con:
  ```sql
  SELECT * FROM partes_stock WHERE tienda_id NOT IN (SELECT id FROM tiendas);
  ```
  y limpiarla a mano si aparece algo. Además, arreglar la causa: en `stock.py` `parte_nuevo_post` (línea ~935), tras calcular `tienda_id`, añadir:
  ```python
  if not tienda_id:
      return RedirectResponse(url="/stock/nuevo", status_code=302)
  ```

### C3. Los endpoints `async` con llamadas HTTP a Holded congelan toda la aplicación

- **Dónde:** `app/api/holded.py` — `sync_preview` (159), `sync_ejecutar` (189) y sobre todo `crear_todos` (249).
- **Problema:** los endpoints son `async def`, así que FastAPI los ejecuta en el event loop (un solo hilo). Dentro usan `requests` (bloqueante). `crear_todos` puede hacer decenas de llamadas HTTP en serie, y `obtener_contactos_holded` pagina todos los contactos.
- **Riesgo:** mientras se crean los albaranes o se sincronizan contactos, **ninguna otra persona puede usar el sistema** (ni las tiendas metiendo su parte de stock). Con Holded lento (o un 429), la app entera parece caída durante minutos.
- **Arreglo quirúrgico (solo estos 3 endpoints, no tocar el resto):** envolver las llamadas de red con `run_in_threadpool`:
  ```python
  from starlette.concurrency import run_in_threadpool

  # en sync_preview y sync_ejecutar:
  contactos = await run_in_threadpool(obtener_contactos_holded, api_key)

  # en crear_todos y albaran_crear:
  holded_doc_id = await run_in_threadpool(
      crear_documento,
      api_key=api_key, contact_id=..., fecha=..., numero=..., items=..., doc_tipo=...,
  )
  ```
  No cambia la lógica ni el resultado; solo mueve la espera de red fuera del hilo principal.
- **⚠️ No hacer:** no convertir los endpoints a `def` síncrono ni migrar a `httpx` async — funciona, pero es un cambio mucho más invasivo con más riesgo de romper.

### C4. Crear un usuario con email duplicado tumba la petición con un 500

- **Dónde:** `app/api/usuarios.py:33-57` (`crear_usuario`)
- **Problema:** no captura `IntegrityError` (a diferencia de `catalogo.py`, que sí lo hace). Si el email ya existe, el usuario del sistema ve una pantalla de error 500 sin explicación.
- **Arreglo (copiar el patrón que ya usas en `catalogo.py:55-74`):**
  ```python
  from sqlalchemy.exc import IntegrityError
  ...
      try:
          db.add(nuevo)
          db.commit()
      except IntegrityError:
          db.rollback()
          return RedirectResponse(url="/usuarios/?error=email_duplicado", status_code=302)
      finally:
          db.close()
  ```
  (Y en `usuarios/lista.html`, mostrar el error si viene en la query string, como ya haces en sabores.)

### C5. Formularios de pedidos: datos malformados producen error 500

- **Dónde:** `app/api/pedidos.py` — `guardar_crear` (211) y `guardar_editar` (352)
- **Problemas concretos:
  1. `date.fromisoformat(form.get("fecha_recogida"))` — si el campo falta o viene vacío → `TypeError` → 500. Todos los demás sitios del código ya protegen esto con try/except; aquí no.
  2. `int(sabores_ids[i])`, `int(tamanios_ids[i])` — si una fila del formulario llega con producto pero sin sabor/tamaño → `ValueError` → 500. Además, en `guardar_editar` el 500 llega **después de haber borrado las líneas** (líneas 370-371)... aunque no se hace commit, así que no se pierden datos (el rollback implícito al cerrar la sesión lo salva). Aun así el usuario ve un 500 y no sabe si su pedido se guardó.
  3. `bandeja` (línea 158): `int(tienda_id)` con un valor no numérico en la URL → 500.
- **Arreglo mínimo (mismo patrón que ya usas en `stock.py:746-755`):**
  - Envolver el parseo de fecha:
    ```python
    try:
        fecha_recogida = date.fromisoformat(form.get("fecha_recogida", ""))
    except (ValueError, TypeError):
        return RedirectResponse(url="/pedidos/crear", status_code=302)
    ```
  - En el bucle de líneas, saltar la fila si sabor o tamaño vienen vacíos:
    ```python
    if not productos_ids[i] or not sabores_ids[i] or not tamanios_ids[i]:
        continue
    ```
  - En `bandeja`, replicar el try/except de `stock_index` para `tienda_id`.
- **⚠️ Precaución:** en `guardar_editar` aplicar la validación de fecha **antes** de los `.delete()` de líneas.

### C6. Falta un unique constraint en partes de stock (un parte por tienda y día)

- **Dónde:** `app/models/stock.py:11-32` (`ParteStock`)
- **Problema:** la regla "un parte por tienda y día" solo se comprueba en Python (`stock.py:937`), con una ventana de carrera: dos envíos casi simultáneos (doble click, dos dependientas) crean dos partes duplicados. Después, `_calc_necesidades` y la matriz de stock cogen uno u otro arbitrariamente.
- **Arreglo:** añadir al modelo:
  ```python
  __table_args__ = (
      UniqueConstraint("tienda_id", "fecha", name="uq_parte_tienda_fecha"),
  )
  ```
  y generar migración: `alembic revision --autogenerate -m "unique parte tienda fecha"` + `alembic upgrade head`.
- **⚠️ Precaución obligatoria antes de migrar:** comprobar que no hay duplicados existentes, o la migración fallará:
  ```sql
  SELECT tienda_id, fecha, COUNT(*) FROM partes_stock
  GROUP BY tienda_id, fecha HAVING COUNT(*) > 1;
  ```
  Si hay duplicados, decidir a mano cuál conservar y borrar el otro (con sus líneas). Hacer copia de `obrador.db` antes (`scripts/backup.py`).

---

## 🟡 IMPORTANTE — no urge, pero conviene planificarlo

### I1. SQLite sin timeout: riesgo de "database is locked" con varios usuarios

- **Dónde:** `app/database.py:11`
- **Problema:** con varias tiendas escribiendo a la vez (partes de stock a la hora del cierre), SQLite puede devolver `database is locked` porque el timeout por defecto es bajo y no está activado el modo WAL.
- **Arreglo (2 líneas, mismo sitio que C2):**
  ```python
  connect_args = {"check_same_thread": False, "timeout": 15} if ... else {}
  ```
  y en el mismo listener de C2, añadir `dbapi_conn.execute("PRAGMA journal_mode=WAL")`. WAL permite lecturas simultáneas con una escritura. Es persistente y reversible (`PRAGMA journal_mode=DELETE`).

### I2. `crear_todos` de Holded puede superar el timeout del navegador

- **Dónde:** `app/api/holded.py:249`
- **Problema:** con N pedidos pendientes hace N tandas de consultas + N llamadas HTTP en serie dentro de una sola petición POST. Con 30-40 pendientes y Holded lento, el navegador corta la conexión y el usuario no ve el resultado (aunque los documentos SÍ se crean, porque cada uno se guarda al momento — eso está bien hecho).
- **Mitigación barata (sin rediseñar):** limitar el lote, p. ej. procesar máximo 20 por click añadiendo `.limit(20)` a la query de `pendientes_ids` y mostrando "quedan X pendientes" en el resultado. El usuario pulsa el botón varias veces si hace falta.

### I3. Sesión no revocable y sin renovación

- **Dónde:** `app/auth/sesion.py`
- **Estado:** el diseño actual es correcto para el tamaño del sistema (el token solo lleva el `usuario_id`, y `obtener_usuario_actual` re-consulta la BD en cada petición, así que desactivar un usuario le corta el acceso al instante — bien). Dos cosas a saber:
  1. Si la `SECRET_KEY` se filtra, cualquiera puede forjar sesiones. Está bien guardada en `.env` (y `.env` está en `.gitignore` ✓). No hay acción; solo no moverla nunca al código.
  2. La cookie no lleva `secure=True`. **Si algún día se sirve por HTTPS** (servidor público), añadir `secure=True` en `auth.py:43`. En local por HTTP no lo añadas aún (la cookie dejaría de funcionar).

### I4. La cantidad de mermas y líneas admite valores negativos

- **Dónde:** `app/api/stock.py:707-736` (mermas), `pedidos.py` (líneas)
- **Problema:** `cantidad: int = Form(...)` acepta `-5`. Una merma negativa o una línea de pedido negativa descuadra los totales de necesidades y producción sin que nadie lo note.
- **Arreglo:** en `merma_form_post`, tras leer `cantidad`: `if cantidad < 1: return RedirectResponse(url="/stock/mermas/nuevo", status_code=302)`. En pedidos, al construir la línea: `cantidad=max(1, int(cantidades[i]) if cantidades[i] else 1)`.

### I5. No hay tests

- **Dónde:** `tests/` está vacío.
- **Riesgo:** la lógica más delicada del negocio (`_calc_necesidades`, `_tartas_equiv`, `_build_catalogo_parte`, el cálculo de envíos) solo se verifica usando la app a mano. Cualquier refactor futuro (incluidos los de este documento) va a ciegas.
- **Sugerencia mínima viable:** un solo archivo `tests/test_stock_calculos.py` con 4-5 tests de `_tartas_equiv` y `_calc_necesidades` usando una BD SQLite en memoria. Son funciones puras respecto a la BD y fáciles de testear. No hace falta más para empezar.

---

## 🟢 OPTIMIZACIONES — solo si se nota lentitud (con precaución)

El sistema es pequeño (decenas de productos, pocas tiendas), así que **nada de esto es urgente**. Lo apunto porque los patrones crecerán mal si el catálogo o el histórico crecen.

### O1. Consultas dentro de bucles (patrón N+1)

- `app/api/holded.py:412-420` — `_preview_data` consulta `PrecioProductoTamano` una vez **por línea de pedido**. En `crear_todos` esto se multiplica: pedidos × líneas consultas. Arreglo seguro: cargar todos los precios en un dict antes del bucle (mismo patrón que ya usas con `sabores_map`):
  ```python
  precios_map = {(pp.producto_id, pp.tamano_id): pp
                 for pp in db.query(PrecioProductoTamano).all()}
  # y en el bucle: precio_obj = precios_map.get((l.producto_id, l.tamano_id))
  ```
- `app/api/stock.py:771-777` (`stock_index`) y `539-544` (`envios_get`) — una query de `ParteStock` por tienda. Con 3-5 tiendas da igual; si algún día hay 20, cargar los partes de todas las tiendas en una query con `ParteStock.tienda_id.in_([...])`.

### O2. Producto cartesiano en `_build_catalogo*`

- **Dónde:** `app/api/stock.py:69-88`, `232-260`, `294-314` — las tres funciones hacen `for precio in precios: for (pid, sid) in sp_set: if pid != precio.producto_id: continue`, es decir, precios × asignaciones iteraciones descartando casi todas.
- **Arreglo seguro (misma salida, menos trabajo):** indexar las asignaciones por producto una vez:
  ```python
  sabores_por_producto: dict[int, list[int]] = {}
  for sp in db.query(SaborProducto).filter(SaborProducto.estado != "OUT").all():
      sabores_por_producto.setdefault(sp.producto_id, []).append(sp.sabor_id)
  # y en el bucle:
  for sid in sabores_por_producto.get(precio.producto_id, []):
  ```
- **⚠️ Precaución:** son las funciones que alimentan partes, previsiones y necesidades — el corazón del módulo de stock. Si lo cambias, verificar a mano que la pantalla de parte nuevo, la previsión-grid y necesidades muestran exactamente lo mismo antes/después (misma cantidad de filas y mismos sabores). Hazlo en una rama.

### O3. Código duplicado en `holded.py` (mantenimiento, no rendimiento)

- El bloque que construye la lista `pedidos` para el índice está copiado dos veces (`index` líneas 44-57 y `crear_todos` líneas 334-347). Si un día cambias un campo, hay que acordarse de los dos sitios. Extraer a un helper `_listar_pedidos_b2b(db)` cuando toque tocar ese código — no antes.

### O4. `obtener_usuario_actual` consulta la BD en cada petición

- **Dónde:** `app/auth/permisos.py:35-61`
- Es **correcto y deseable** (permite revocar acceso al instante, ver I3). No lo caches salvo que haya un problema de rendimiento medible, que con SQLite local no va a haber. Lo anoto solo para que nadie lo "optimice" quitando la consulta.

---

## Cosas que están BIEN (no tocar)

Para que el que lea esto no "arregle" lo que no está roto:

- **`.gitignore`** cubre `.env`, `*.db`, backups y logs ✓
- **Contraseñas con bcrypt** y verificación correcta ✓
- **Cookie httponly + samesite=lax** ✓
- **Cascadas ORM** (`cascade="all, delete-orphan"`) en pedidos y partes: borrar un pedido borra sus líneas aunque SQLite no aplique el CASCADE (lo hace SQLAlchemy) ✓
- **`crear_todos` guarda cada `holded_doc_id` justo tras crear el documento** (si el proceso se corta a medias, no se duplican documentos al reintentar) ✓
- **Serializar a dicts antes de cerrar la sesión** (`_pedido_a_dict` etc.) evita los clásicos `DetachedInstanceError` ✓
- **El error de "clave v1 vs v2" de Holded** está bien manejado con mensajes accionables ✓

---

## Orden sugerido de ejecución

| # | Punto | Esfuerzo | Riesgo del cambio |
|---|-------|----------|-------------------|
| 1 | C1 requirements.txt | 1 min | Ninguno |
| 2 | C4 email duplicado | 10 min | Muy bajo |
| 3 | C5 validación pedidos | 30 min | Bajo |
| 4 | C2 PRAGMA foreign_keys (+ limpieza previa) | 30 min | Bajo con la comprobación previa |
| 5 | I1 WAL + timeout | 5 min | Bajo |
| 6 | C6 unique constraint (+ backup + comprobación) | 30 min | Medio — hacer backup antes |
| 7 | C3 run_in_threadpool en Holded | 30 min | Medio — probar sync y crear-todos después |
| 8 | I2, I4 | 30 min | Bajo |
| 9 | I5 tests, O1-O3 | cuando toque | — |
