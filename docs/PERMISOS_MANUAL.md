# Manual de modificación del sistema de permisos

> Guía operativa para cambiar permisos de forma rápida y segura. Pensada para que
> cualquier IA o desarrollador haga el cambio sin tener que redescubrir el sistema.
> Contexto de diseño en `PERMISOS_SPEC.md`; historia de implementación en `PERMISOS_PLAN.md`.

## Mapa del sistema (30 segundos)

| Pieza | Dónde | Qué hace |
|---|---|---|
| Matriz `PERMISOS` | `app/auth/permisos.py` | **Única fuente de verdad**: qué nivel (NADA/VER/EDITAR) tiene cada puesto en cada clave |
| Enum `Rol` + `ROL_NOMBRES` | `app/models/usuario.py` | Los 8 puestos y sus nombres legibles |
| `@requiere_permiso("clave")` / `("clave", editar=True)` | decoradores en `app/api/*.py` | Bloqueo real en servidor: VER permite GET, EDITAR exige el flag |
| `usuario.puede()` / `puede_editar()` / `puede_servicio()` | plantillas Jinja | Ocultación cosmética (menú, botones); la seguridad es el decorador |
| Tests de la matriz | `tests/test_matriz.py` y resto de `tests/` | Fijan la matriz; si cambias permisos, cámbialos también |

**Claves existentes:** `clientes`, `pedidos` (bandeja+detalle), `pedidos.rutas`, `impresion`,
`stock.partes`, `stock.envios`, `stock.mermas`, `stock.prevision`, `stock.dias_reparto`,
`produccion`, `holded`, `catalogo`, `admin` (usuarios+tiendas).

**Resolución:** clave exacta > clave del servicio (antes del punto) > NADA. Ejemplo:
AREA_MANAGER tiene `"stock": EDITAR` y ninguna subclave → todo stock EDITAR.
PASTELERAS no tiene `"stock"` ni `"stock.mermas"` → mermas NADA por fallback.

**Gotchas conocidas:**
- Producción está montada en **`/horneado`**, no `/produccion` (la clave sí es `"produccion"`).
- Los GET de formularios de alta/edición llevan `editar=True` (un rol VER no debe ni ver el form).
- El puesto TIENDAS además está limitado a su `tienda_id` por código en `app/api/pedidos.py`
  y `app/api/stock.py` (patrón fail-closed `usuario.tienda_id or -1`); eso NO se controla
  desde la matriz.
- En `usuarios/lista.html` el `<option value>` debe seguir siendo `r.value` (el POST espera
  el nombre del enum); solo la etiqueta visible usa `ROL_NOMBRES`.

---

## Receta 1 — Cambiar lo que puede hacer un puesto

*Ej.: "que Pasteleras pueda registrar mermas" o "que Comercial solo consulte pedidos".*

1. Edita el dict del puesto en `PERMISOS` (`app/auth/permisos.py`): añade/cambia la clave
   al nivel deseado (`Nivel.NADA` / `Nivel.VER` / `Nivel.EDITAR`). Recuerda el fallback:
   para QUITAR un subapartado a quien tiene el servicio entero, añade la subclave en NADA.
2. Actualiza los asserts de ese puesto en `tests/test_matriz.py` (y en
   `tests/test_acceso_servicios.py` / `test_stock_permisos.py` / `test_pedidos_permisos.py`
   si el caso aparece ahí).
3. `venv\Scripts\python -m pytest -q` → todo verde.
4. No hay que tocar routers ni plantillas: decoradores y menú leen la matriz.
   Excepción: si el cambio da acceso a TIENDAS a datos de otras tiendas, revisa el
   ámbito (Receta 5).

## Receta 2 — Añadir un subapartado nuevo a un servicio existente

*Ej.: nueva pantalla "Inventario" dentro de Stock.*

1. Decide la clave: `"stock.inventario"`.
2. Decoradores en los endpoints nuevos: `@requiere_permiso("stock.inventario")` en GETs de
   consulta, `@requiere_permiso("stock.inventario", editar=True)` en POSTs y GETs de formulario.
3. Matriz: los puestos con `"stock"` a nivel servicio (JEFES, ADMINISTRACION,
   JEFE_PASTELEROS, AREA_MANAGER) lo heredan solos. Para el resto, añade la subclave
   explícita al nivel que toque (o nada = NADA).
4. Menú: en `app/templates/base.html`, el enlace nuevo va con
   `{% if usuario.puede("stock.inventario") %}`.
5. Tests: añade asserts en `test_matriz.py` + un caso de acceso (rol permitido 200, rol
   denegado 403) en `test_stock_permisos.py`.

## Receta 3 — Añadir un puesto nuevo

1. `app/models/usuario.py`: añade el valor al enum `Rol` y su etiqueta en `ROL_NOMBRES`.
2. `app/auth/permisos.py`: añade su entrada en `PERMISOS` (si no la añades, ese puesto no
   verá NADA — el sistema es fail-closed).
3. **No hace falta migración Alembic** para añadir un valor: la columna `rol` es VARCHAR sin
   CHECK en SQLite. (Sí haría falta migración de datos si RENOMBRAS o eliminas un valor
   existente — mira `alembic/versions/51c378d8905c_ocho_puestos.py` como plantilla.)
4. El desplegable de Admin → Usuarios se alimenta del enum: aparece solo.
5. Tests: bloque nuevo en `test_matriz.py` con las claves clave del puesto + 1-2 casos en
   `test_acceso_servicios.py`.

## Receta 4 — Añadir un servicio nuevo (router nuevo)

1. Clave nueva de servicio, p. ej. `"informes"`.
2. Router en `app/api/informes.py` con `@requiere_permiso("informes"[, editar=True])` en
   cada endpoint (ninguno sin decorador; solo login/logout son públicos). Registrarlo en
   `app/main.py`.
3. Matriz: añade `"informes": Nivel.X` a cada puesto que deba verlo (los demás, NADA
   automático).
4. Menú: bloque en `base.html` con `{% if usuario.puede_servicio("informes") %}` (y
   tarjeta en `inicio.html` si aplica).
5. Tests como en la Receta 2.

## Receta 5 — Ámbito por tienda (datos limitados a la tienda del usuario)

El patrón usado en pedidos y stock, si hay que aplicarlo a algo nuevo:

```python
usuario = request.state.usuario
if usuario.rol == Rol.TIENDAS:
    query = query.filter(Modelo.tienda_id == (usuario.tienda_id or -1))  # fail-closed
```

- En POSTs con `tienda_id` en el form: ignorar el valor del form y forzar
  `usuario.tienda_id` (ver `merma_form_post` en `app/api/stock.py`).
- En detalles/ediciones de un recurso ajeno: 404 (no 403) para no revelar que existe
  (ver `detalle()` en `app/api/pedidos.py`).
- Test correspondiente: usuario TIENDAS de tienda A no ve/edita recurso de tienda B
  (ejemplos en `tests/test_pedidos_permisos.py` y `test_stock_permisos.py`).

## Checklist final de cualquier cambio de permisos

- [ ] `venv\Scripts\python -m pytest -q` → todo verde (46+ tests)
- [ ] Si cambió la matriz: `tests/test_matriz.py` refleja el estado nuevo (los tests SON
      la documentación ejecutable de la matriz)
- [ ] Ningún endpoint nuevo sin `@requiere_permiso`/`@requiere_sesion`
- [ ] Probar en local con un usuario del puesto afectado (crear uno de prueba desde
      Admin → Usuarios con un JEFES)
- [ ] Actualizar la tabla de `PERMISOS_SPEC.md` si el cambio altera la matriz acordada
