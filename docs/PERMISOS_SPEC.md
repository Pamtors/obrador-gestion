# Spec: Sistema de permisos por puesto (2026-07-14)

## Objetivo

Sustituir el control de acceso actual (5 roles + `@requiere_rol` por endpoint) por una
matriz de permisos central con 8 puestos, niveles VER/EDITAR por subapartado, y ámbito
por tienda para el puesto Tiendas. La matriz vive **fija en código**: cambiarla es una
tarea de desarrollo, no una pantalla de la app.

## Decisiones tomadas

1. **Roles fijos en código.** Nada de editor de permisos en la app. Al crear un usuario
   solo se elige su puesto (y su tienda si es puesto Tiendas).
2. **8 puestos** según el documento de permisos original (no incluido en este repositorio).
3. **Solo Jefes accede a Admin** (gestión de usuarios). Administración no.
4. **Migración de roles existentes:** ADMIN→JEFES, OFICINA→ADMINISTRACION,
   TIENDA→TIENDAS, OBRADOR→PASTELERAS, REPARTO→REPARTIDORES.
5. **Ámbito por tienda:** los usuarios del puesto Tiendas solo ven y editan datos de su
   `tienda_id` en TODO: partes de stock, envíos, mermas y también la bandeja de pedidos
   (solo pedidos cuya recogida es en su tienda).

## Enum de puestos

```python
class Rol(str, enum.Enum):
    REPARTIDORES = "REPARTIDORES"
    JEFES = "JEFES"
    ADMINISTRACION = "ADMINISTRACION"
    PASTELERAS = "PASTELERAS"
    JEFE_PASTELEROS = "JEFE_PASTELEROS"
    TIENDAS = "TIENDAS"
    AREA_MANAGER = "AREA_MANAGER"
    COMERCIAL = "COMERCIAL"
```

## Matriz de servicios (página 1 del PDF)

| Puesto          | Clientes | Pedidos | Impresión | Stock | Producción | Holded | Catálogo | Admin |
|-----------------|:--------:|:-------:|:---------:|:-----:|:----------:|:------:|:--------:|:-----:|
| Repartidores    |    –     |    ✔    |     ✔     |   ✔   |     –      |   –    |    –     |   –   |
| Jefes           |    ✔     |    ✔    |     ✔     |   ✔   |     ✔      |   ✔    |    ✔     |   ✔   |
| Administración  |    ✔     |    ✔    |     ✔     |   ✔   |     ✔      |   ✔    |    ✔     |   –   |
| Pasteleras      |    –     |    ✔    |     ✔     |   ✔   |     ✔      |   –    |    –     |   –   |
| Jefe pasteleros |    –     |    ✔    |     ✔     |   ✔   |     ✔      |   –    |    ✔     |   –   |
| Tiendas         |    –     |    ✔    |     –     |   ✔   |     –      |   –    |    –     |   –   |
| Area Manager    |    –     |    ✔    |     –     |   ✔   |     –      |   –    |    –     |   –   |
| Comercial       |    ✔     |    ✔    |     –     |   –   |     –      |   –    |    –     |   –   |

## Subpermisos (página 2 del PDF)

Niveles: `NADA` (ni aparece), `VER` (consulta, sin botones de crear/editar, POST
bloqueado en servidor), `EDITAR` (todo).

**Repartidores**
- Pedidos: bandeja NADA · rutas de reparto EDITAR
- Stock: envíos EDITAR · partes/mermas/previsión/días reparto NADA

**Pasteleras** (y se asume igual para Jefe pasteleros salvo que éste tiene además
Producción completa como jefe — el PDF no lo detalla, Jefe pasteleros hereda acceso
completo a los subapartados de sus servicios)
- Pedidos: bandeja VER · rutas NADA
- Stock: partes EDITAR · envíos EDITAR · días reparto VER · mermas/previsión NADA

**Tiendas** (todo limitado a su `tienda_id`)
- Pedidos: bandeja VER (solo pedidos de su tienda) · rutas NADA
- Stock: partes EDITAR · envíos EDITAR · mermas EDITAR · días reparto VER · previsión NADA

**Resto de puestos** (Jefes, Administración, Jefe pasteleros, Area Manager, Comercial):
acceso EDITAR a todos los subapartados de los servicios que tienen marcados.
Excepción: Comercial no tiene Rutas de reparto (solo bandeja de pedidos).

## Arquitectura (Opción A: matriz central)

### 1. Matriz en `app/auth/permisos.py`

```python
class Nivel(enum.IntEnum):
    NADA = 0
    VER = 1
    EDITAR = 2

# Clave = "servicio" o "servicio.subapartado".
# Si una clave "servicio.sub" no está, hereda el nivel del servicio.
PERMISOS: dict[Rol, dict[str, Nivel]] = {
    Rol.TIENDAS: {
        "pedidos": Nivel.VER,          # bandeja solo consulta
        "pedidos.rutas": Nivel.NADA,
        "stock": Nivel.EDITAR,         # partes, envíos, mermas
        "stock.dias_reparto": Nivel.VER,
        "stock.prevision": Nivel.NADA,
    },
    # ... resto de puestos
}
```

### 2. Decorador `@requiere_permiso`

Sustituye a `@requiere_rol` endpoint a endpoint:

```python
@requiere_permiso("stock.mermas")                 # exige nivel >= VER
@requiere_permiso("stock.mermas", editar=True)    # exige EDITAR (para los POST)
```

Comportamiento idéntico al actual: sin sesión → redirect a `/login`; sin nivel
suficiente → 403. Deja el usuario en `request.state.usuario`.

### 3. Helpers para plantillas

`UsuarioSesion.puede(clave)` y `UsuarioSesion.puede_editar(clave)`:
- El menú lateral oculta los servicios con nivel NADA.
- Las pantallas ocultan botones de crear/guardar cuando el nivel es VER
  (p. ej. Pasteleras ve la bandeja sin botón "Nuevo pedido").

La ocultación en plantilla es cosmética; la garantía real es el decorador en el POST.

### 4. Ámbito por tienda (puesto TIENDAS)

Ya existe parcialmente en `app/api/stock.py` (filtros por `usuario.tienda_id`).
Trabajo pendiente:
- Auditar TODOS los endpoints de stock (GET y POST) para confirmar que el filtro se
  aplica siempre; los checks actuales `rol == Rol.TIENDA` pasan a `rol == Rol.TIENDAS`.
- Añadir el filtro a la bandeja de pedidos: `Pedido.tienda_id == usuario.tienda_id`.
- En formularios donde la tienda va en el form (p. ej. mermas), el servidor ignora el
  valor del form y usa siempre `usuario.tienda_id` (ya se hace en mermas, replicar).

### 5. Migración Alembic

- Renombrar valores del enum en la tabla `usuarios` según el mapeo de la decisión 4.
- SQLite guarda el enum como texto: `UPDATE usuarios SET rol = ...` por cada valor.

### 6. Pantalla Admin → Usuarios

- Restringida a JEFES (antes ADMIN).
- Desplegable de puesto con los 8 valores y nombres legibles ("Jefe pasteleros"…).
- Campo tienda obligatorio solo si puesto = Tiendas (como ahora con TIENDA).

## Errores

- POST sin nivel EDITAR → 403 con el mensaje actual de "No tienes permiso".
- Usuario TIENDAS sin `tienda_id` asignada → tratar como sin datos (listas vacías),
  nunca como acceso global.

## Tests

- Por cada puesto: acceso permitido/denegado a una ruta representativa de cada servicio.
- Nivel VER: GET 200 y POST 403 (bandeja para Pasteleras/Tiendas, días reparto).
- Ámbito tienda: usuario TIENDAS no ve ni edita partes/mermas/pedidos de otra tienda
  (GET de detalle ajeno → 403 o 404, POST con tienda_id ajeno en el form → se guarda
  con la suya).
- Migración: usuarios existentes conservan acceso equivalente.

## Fuera de alcance

- Editor de permisos en la app.
- Permisos por usuario individual (excepciones).
- Cambios en Producción, Holded, Catálogo, Impresión más allá de cambiar el decorador.
