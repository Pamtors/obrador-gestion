# Tareas — desglose para trabajar por partes

> Este archivo trocea cada punto del [BACKLOG.md](BACKLOG.md) en subtareas concretas.
> El backlog es el **qué quiero**; esto es el **cómo lo partimos** para repartir y
> avanzar por trozos. Cada tarea tiene un ID (`T1`, `T1.1`...) para poder referirla.
>
> **Leyenda:** `[ ]` pendiente · `[~]` en curso · `[x]` hecho · `(H)`/`(C)` quién

---

## T1 · Clientes — Autocompletado tipo Holded al dar de alta
*Backlog: Clientes › Alta de cliente*

- [ ] **T1.1** Investigar cómo Holded resuelve el autocompletado: ¿usa su propia API
      de contactos/empresas?, ¿una fuente externa (registro mercantil, NIF)?
- [ ] **T1.2** Revisar si el adapter de Holded del proyecto ya expone búsqueda de
      sociedades reutilizable (`app/adapters`).
- [ ] **T1.3** Decidir qué campos se autocompletan (razón social, NIF/CIF, dirección,
      CP, ciudad, email, teléfono...).
- [ ] **T1.4** Endpoint backend de búsqueda por nombre de sociedad (devuelve candidatos).
- [ ] **T1.5** UI: input con typeahead/autocompletar en el formulario de alta.
- [ ] **T1.6** Al seleccionar un resultado, rellenar los campos del formulario.
- [ ] **T1.7** Casos límite: sociedad no encontrada y edición manual posterior.

## T2 · Bandeja de pedidos
*Backlog: Pedidos › Bandeja*

- [x] **T2.1** Mostrar la acción de **pegatinas/etiquetas solo si el cliente es B2B**
      (ocultarla para tiendas).
- [x] **T2.2** Añadir **botón rápido "Pedidos para mañana"** que aplique el filtro de
      fecha = mañana sin usar el selector.

## T3 · Tiendas
*Backlog: Tiendas*

- [x] **T3.1** Añadir campo **"Otros"** al modelo de tienda/pedido de tienda
      (migración Alembic + schema + formulario + mostrarlo).
- [x] **T3.2** Localizar dónde se apuntan tartas a las tiendas hoy.
- [x] **T3.3** Pedidos tipo TIENDA se mantienen (cajones, pegatinas, sesiones foto...);
      precio 0€ para tiendas propias, precio coste para franquicias. Las tartas
      van por previsión de stock; las tiendas NO hacen "pedidos" de tartas.
- [x] **T3.4** Verificar que el flujo de previsión cubre "necesitan más" (aumentar
      previsión) sin romper nada.
- [x] **T3.extra** Pedidos de tienda pueden incluir artículos libres ("Otros"):
      cajones de galletas, material, etc. — exclusivo para tipo TIENDA.

## T4.0 · Preparación para T4 — Ubicación B2B y base de rutas
*Prerequisito para T4 (rutas de repartidores)*

- [x] **T4.0a** En pedidos B2B, añadir selector de **punto de entrega**: Tienda / Restaurante.
      La tienda solo se muestra y requiere cuando el punto es "Tienda".
- [x] **T4.0b** Campo `ubicacion_entrega` en el modelo `Pedido` + migración Alembic.
      `tienda_id` pasa a nullable para B2B con entrega en carretería/restaurante.
- [x] **T4.0c** Nueva pantalla **Rutas de reparto** (`/pedidos/rutas`): lista pedidos B2B
      de un día agrupados por `zona_ruta` del cliente (campo ya existente en `ClienteB2B`).
      Enlace en el sidebar. Imprimible con CSS `@media print`.

## T4 · Centro de impresión
*Backlog: Imprimir*

- [x] **T4.1** Imprimir **solo pedidos por tienda** (filtro de selección por tienda).
- [x] **T4.2** Pegatinas **solo de tartas B2B**.
- [x] **T4.3** **Unificar el formato de pegatinas** (una sola plantilla para todas).
- [x] **T4.4** Rediseñar la pantalla con 4 botones claros y vistosos:
  - [x] **T4.4a** Pegatinas restaurantes
  - [x] **T4.4b** Listas de tiendas
  - [x] **T4.4c** Listas restaurantes
  - [x] **T4.4d** Ruta de repartidores
- [x] **T4.5** Hacer la **ruta de repartidores imprimible**.

## T5 · Stock — Partes de stock
*Backlog: Stock › Partes de stock. Ref: el boceto de la ficha de stock (no incluido)*

- [x] **T5.1** Segmentar las tartas por **tamaños** en el parte.
- [x] **T5.2** Que **solo las tartas grandes** permitan elegir **porciones y enteras**
      (`permite_porciones` activado en BD para GRANDE).
- [x] **T5.3** **Quitar las tartas medianas** del stock (van por encargo) — ya excluidas
      por `_build_catalogo_parte`/`_build_catalogo_grid`.
- [x] **T5.4** Ajustar el modelo/plantilla del parte a la estructura del PDF de ejemplo.
- [x] **T5.5** Sobrante agregado (no por sabor): un input "Sobrante" al final de
      "Tartas grandes" y otro al final de "Pequeñas & Mini" — reemplaza la sección
      libre de "Otros/rellenos". Campos `sobrante_grande`/`sobrante_pequena_mini` en
      `ParteStock` (migración `b7c8d9e0f1a2`). Se muestra como aviso informativo en
      `/stock/`, `/stock/{id}`, `/stock/necesidades/` y `/stock/envios/`.
- [x] **T5.6** 🐛 **BUG — categorización rota para Cookie y Tarrina.** `_cat_tamano()`
      clasifica por el **nombre del tamaño** (GRANDE/MEDIANO/PEQUEÑA/MINI/PORCIÓN/
      ÚNICO...), pero **COOKIE** y **TARRINA** son **productos** (tabla `productos`),
      no tamaños — su tamaño real es "ÚNICO" o similar, que no contiene "cookie"/
      "tarrin"/"galleta". Resultado: cada combinación sabor×Cookie y sabor×Tarrina cae
      en el cajón genérico "Otros tamaños" en vez de en su propia sección, generando
      un aluvión de filas sueltas en `/stock/nuevo`.
      **Fix pendiente**: cambiar `_cat_tamano(nombre)` por una función que reciba
      también el nombre del **producto** y decida la categoría mirando el producto
      primero (COOKIE→cookie, TARRINA→tarrina) y el tamaño después (GRANDE/PEQUEÑA/
      MINI) para el producto TARTA. Afecta a `_build_catalogo_parte` y
      `_build_catalogo_grid` en `app/api/stock.py`, y sus templates
      (`parte_form.html`, `prevision.html`).
- [x] **T5.7** 🐛 Revisar por qué **Necesidades** (`/stock/necesidades/`) no muestra
      nada tras los últimos cambios. Verificado con datos reales (tiendas CARRETERIA
      y FUENGIROLA, jueves 2026-07-02): `_calc_necesidades` y la plantilla ya manejan
      bien el formato `{"filas":..., "sobrante_grande":.., "sobrante_pequena_mini":..}}`
      — no era un bug, faltaban datos en las pruebas anteriores. De paso se arregló un
      bug real de navegación: `ayer_iso` no se pasaba al template (botón "◀" roto) y
      `manana_iso`/`hoy_iso` se calculaban sobre `date.today()` en vez de sobre la
      fecha mostrada, rompiendo el avance de fecha en fecha al navegar.
- [x] **T5.8** Que el orden del catálogo en Necesidades/Envíos coincida exactamente
      con el de Partes de stock (grande → pequeña → mini → tarrina → cookie → otro),
      una vez resuelto T5.6.

## T6 · Stock — Necesidades (renombrar + rehacer)
*Backlog: Stock › Necesidades. Ref: el boceto de la ficha de horneado (no incluido)*

- [x] **T6.1** Decidir el **nuevo nombre** de la pantalla.
- [x] **T6.2** Rediseñar a un formato **compacto** tipo el boceto de la ficha de horneado (no incluido).
- [x] **T6.3** Que la hoja agregue en uno: **stock del día siguiente** + **particulares**
      + **B2B**.
- [x] **T6.4** **Filtros**: tienda · días concretos · sabores · productos · particulares · B2B.
- [x] **T6.5** **Vincular con la Lista de horneado** (T8): misma fuente de datos.

## T7 · Stock — Días de reparto (persistencia)
*Backlog: Stock › Reparto*

- [x] **T7.1** Cargar los cuadrados con su **estado guardado** marcado.
- [x] **T7.2** Poder **modificar y guardar** sin reseleccionar todo cada vez.

## T8 · Producción — Lista de horneado
*Backlog: Producción › Horneado*

- [x] **T8.1** Vincular **horneado ↔ necesidades** (misma información, una sola fuente).
- [x] **T8.2** Horneado = vista/formato **para imprimir**; Necesidades = registro por días.

## T9 · Holded — Pestaña "Hacer Facturas y Albaranes"
*Backlog: Holded › pestaña nueva*

- [x] **T9.1** Listar **restaurantes que han pedido para el día siguiente**.
- [x] **T9.2** Botón que **genere facturas y albaranes** de ese listado (vía Holded).

## T10 · Catálogo — Rediseño (PILAR ⭐)
*Backlog: Catálogo. Mantener TODAS las funciones; solo hacerlo intuitivo.*

- [x] **T10.1** Mapear todas las funciones actuales del catálogo (no perder ninguna).
- [x] **T10.2** Diseñar la nueva navegación/estructura (boceto antes de tocar código).
- [x] **T10.3** Rehacer la UI de productos/sabores/tamaños/combinaciones/precios.

## T11 · Usuarios
*Backlog: Usuarios*

- [x] **T11.1** Poder **editar usuarios ya creados**.
- [x] **T11.2** Vista de admin con **toda la info** del usuario.
- [x] **T11.3** Decidir qué hacer con las contraseñas (están hasheadas, no se pueden
      mostrar): ¿reseteo por admin? ¿otra solución? — **resuelto**.

---

# Fuera de la aplicación (infraestructura e integraciones)

## T12 · Integración Web WordPress ↔ Base de datos
*Backlog: Fuera de la app › Web WordPress*

- [ ] **T12.1** Investigar cómo conectar WordPress (WooCommerce/plugin/API) con nuestra BD.
- [ ] **T12.2** Definir cómo entran los **pedidos** desde la web a la app (endpoint/webhook).
- [ ] **T12.3** Dejar el **camino preparado** para vincular la web de forma sencilla (doc + plantilla).

## T13 · Chatbot interno (Telegram)
*Backlog: Fuera de la app › Chatbots › Telegram. Reaprovechar `un prototipo previo de chatbot (n8n + Claude)`.*

- [ ] **T13.1** Reunir la **base de conocimiento**: info de tiendas + cómo se hacen los procesos.
- [ ] **T13.2** Bot de Telegram que responda **dudas internas** de empleados.

## T14 · Chatbot clientes (WhatsApp)
*Backlog: Fuera de la app › Chatbots › WhatsApp*

- [ ] **T14.1** Recoger **pedidos de particulares**.
- [ ] **T14.2** Responder info: horarios, ubicación, alérgenos, pasteurizado, sabores, tamaños, precios.
- [ ] **T14.3** **Consultar stock a los WhatsApp de las tiendas** y, si hay, **reservar mismo día**.
- [ ] **T14.4** **Tickets** para preguntas con confianza **<95%**.
- [ ] **T14.5** **Recordatorios** de pedidos a clientes B2B.
- [ ] **T14.6** **Apuntar pedidos** de clientes B2B.

## T15 · Servidor y seguridad
*Backlog: Fuera de la app › Servidor y seguridad*

- [ ] **T15.1** Montar el **servidor** para la web.
- [ ] **T15.2** **Hardening de seguridad**: protección anti-DDoS/caída y anti-intrusión.

## T16 · Diseñador de pegatinas
*Creador de diseños personalizados de pegatina, independiente del diseño base*

- [ ] **T16.1** Modelo `DisenioPegatina`: nombre, ancho/alto (mm), campos visibles,
      textos de campos, tamaños de fuente (nombre cliente, sabor), tipo de borde,
      logo (URL opcional). Migración Alembic.
- [ ] **T16.2** CRUD `/imprimir/disenios/`: lista, crear, editar, eliminar diseños.
- [ ] **T16.3** Formulario de diseño con **vista previa en tiempo real** (JS):
      muestra cómo queda la pegatina mientras se edita, con las dimensiones reales
      escaladas a pantalla.
- [ ] **T16.4** El template de pegatinas acepta un diseño custom (`?diseno_id=X`)
      y ajusta CSS dinámicamente (dimensiones, fuentes, borde, logo).
- [ ] **T16.5** Desde el Centro de impresión se puede elegir qué diseño usar
      al generar las pegatinas del día o de un pedido.

---

> A medida que sigamos recorriendo el localhost y crezca el backlog, se añaden aquí
> los nuevos bloques de tareas (T17, T18...).
