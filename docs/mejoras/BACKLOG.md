# Backlog de mejoras — Obrador Demo

> **Regla de oro:** ahora NO se implementa nada nuevo. Cogemos lo que ya hay y lo
> hacemos más fácil de usar, más intuitivo y más bonito. Cualquier idea nueva que
> surja va al **Buzón de ideas** (final del archivo) y se queda ahí hasta que
> terminemos todo lo de abajo.

## Cómo usarlo
1. Abre el localhost y ve pantalla por pantalla, en el mismo orden que aparecen aquí.
2. En cada pantalla, escribe debajo TODO lo que quieras cambiar (un punto por línea).
3. Si tienes un boceto, guárdalo en `bocetos/` y enlázalo: `![boceto](bocetos/nombre.png)`.
4. No te cortes: apunta hasta lo más pequeño. Filtramos después.

**Leyenda de estado:** `[ ]` pendiente · `[~]` en curso · `[x]` hecho
**Etiquetas:** `(H)` Hugo · `(C)` el otro · `(?)` por decidir quién

---

## Inicio / Dashboard
*Qué es: la pantalla de aterrizaje tras login.*

- [ ]

**Boceto:** _(enlazar aquí)_

## Login
- [ ]

---

## Catálogo

> ⭐ **PRIORITARIO / PILAR.** Es la pieza central: casi todo lo demás está vinculado
> al catálogo. Ahora mismo **no es nada intuitivo y es muy aparatoso**. Todas sus
> funciones son esenciales (no se quita nada), pero hay que **rediseñarlo entero**
> para que sea mucho más friendly y se entienda todo mejor. Pendiente: definir cómo
> reorganizarlo (productos/sabores/tamaños/combinaciones/precios juntos vs separados).

- [ ] Replantear la navegación/estructura completa del catálogo (más intuitiva).

### Productos
- [ ]

### Sabores
- [ ]

### Tamaños
- [ ]

### Combinaciones
- [ ]

### Precios
- [ ]

---

## Clientes

### Lista
- [ ]

### Detalle de cliente / Alta de cliente
- [ ] **Autocompletado tipo Holded al dar de alta cliente/contacto:** al buscar el
  nombre de la sociedad, que el resto de campos se rellenen automáticamente.
  → INVESTIGAR cómo lo hace Holded y cómo replicarlo aquí.

---

## Pedidos

### Bandeja (lista de pedidos)
- [ ] Las **pegatinas (etiquetas)** solo deben aparecer para clientes **B2B**.
- [ ] Añadir **botón rápido "pedidos para mañana"** en vez de tener que seleccionar
  la fecha manualmente.

### Crear pedido
- [ ]

### Detalle de pedido
- [ ]

---

## Producción

### Horneado
- [ ] **Vincular directamente con la Lista de necesidades** (mismos datos).
- [ ] Única diferencia: **Horneado = para imprimir**; Necesidades = registro de los
  distintos días. Ref: el boceto de la ficha de horneado (no incluido).

---

## Stock

### Resumen (index)
- [ ]

### Previsión
- [ ]

### Necesidades → **RENOMBRAR** (el nombre "Necesidades" queda mal y poco intuitivo)
- [ ] **Rehacer por completo** a algo **mucho más compacto**, tipo la
  el boceto de la ficha de horneado (no incluido) adjunta.
- [ ] Esa misma hoja debe incluir, juntos: **pedidos de stock del día siguiente**
  + **pedidos de particulares** + **pedidos B2B**.
- [ ] **Filtros** para buscar rápido: por **tienda**, **días concretos**,
  **sabores concretos**, **productos**, **pedidos particulares** y **pedidos B2B**.
- [ ] Buscar un **nombre nuevo** para la pantalla.
- [ ] Debe quedar **vinculada con la Lista de horneado** (ver Producción › Horneado):
  misma información; Necesidades = registro de los distintos días.

### Reparto (Días de reparto)
- [ ] Que los **cuadrados queden marcados/guardados** y solo los modifiques y guardes,
  en vez de tener que seleccionar todos los cuadraditos cada vez. (Persistir estado.)

### Mermas
- [ ]

### Partes de stock
- [ ] **Segmentar las tartas por tamaños.**
- [ ] **Solo las tartas grandes** pueden seleccionar **porciones y enteras (grandes)**.
- [ ] Las **tartas medianas NO son parte del stock** (van por encargo) → quitarlas.
- [ ] Referencia de cómo debería quedar (o algo similar): el boceto de la ficha de stock (no incluido).

---

## Tiendas
- [ ] Añadir un campo **"Otros"**: muchas veces las tiendas piden cosas especiales
  al obrador y hay que poder anotarlo.
- [ ] **Quitar que se puedan apuntar tartas a las tiendas.** Las tartas se asignan
  automáticamente por stock y previsión; si un día necesitan más, se les aumenta la
  previsión y listo. Una tienda nunca hace un "pedido" como tal.

## Usuarios
- [ ] Poder **editar los usuarios ya creados**.
- [ ] El **Admin pueda ver toda la información**, incluidas las contraseñas.
  ⚠️ OJO: hoy las contraseñas se guardan **hasheadas** (no se pueden "ver" tal cual).
  Hay que decidir: ¿mostrar/forzar reseteo de contraseña por el admin? ¿guardarlas
  en claro (mala idea de seguridad)? → DECISIÓN PENDIENTE.

---

## Holded

### Sincronización
- [ ]

### Configuración
- [ ]

### Albaranes
- [ ]

### Hacer Facturas y Albaranes (pestaña NUEVA)
- [ ] Crear pestaña cuya función principal sea: que salgan **todos los restaurantes
  que han pedido para el día siguiente** y, con **un botón**, se generen las
  **facturas y los albaranes**.

---

## Imprimir (Centro de impresión)

> Rehacer el centro de impresión: las funciones actuales están bien, pero hay que
> añadir cosas y cambiar el aspecto. Botones **más vistosos e intuitivos**.

- [ ] Poder imprimir **solo pedidos por tienda**.
- [ ] Las **pegatinas solo de las tartas B2B**.
- [ ] **Unificar el formato de las pegatinas** (usar el mismo para todas).
- [ ] Rehacer los botones, que sean claros y vistosos. Botones objetivo:
  - [ ] **Pegatinas restaurantes**
  - [ ] **Listas de tiendas**
  - [ ] **Listas restaurantes**
  - [ ] **Ruta de repartidores** (las rutas hay que poder imprimirlas)

---

## Transversal (afecta a todas las pantallas)
*Cosas de aspecto/UX que se repiten: colores, tipografía, botones, menú, mensajes
de error, móvil vs escritorio, etc.*

- [ ]

---

## Fuera de la aplicación (infraestructura e integraciones)
*Tareas que no son pantallas de la app, sino trabajo alrededor.*

### Web WordPress ↔ base de datos
- [ ] Aprender a **vincular una web hecha con WordPress con nuestra base de datos**
  para que los **pedidos entren directamente**.
- [ ] Dejar el **camino ya hecho** para poder vincularla de forma sencilla.

### Chatbots de Obrador Demo (2)
> Ya hay trabajo previo en `un prototipo previo de chatbot (n8n + Claude)` (n8n + Claude). Reaprovechar.

**1) Telegram — uso interno**
- [ ] Que tenga toda la **información de las tiendas** y **cómo se hacen los procesos**.
- [ ] Que cualquier empleado pueda **preguntarle dudas fáciles** sin tener que
  preguntar a los jefes.

**2) WhatsApp — clientes**
- [ ] **Recoger pedidos de particulares**.
- [ ] Resolver dudas de: **horarios**, **ubicación de tiendas**, **alérgenos**,
  **si los productos están pasteurizados**, **sabores**, **tamaños**, **precios**.
- [ ] **Preguntar a los WhatsApp de las tiendas** si tienen stock de una tarta;
  si lo tienen, **hacer reservas para el mismo día**.
- [ ] **Crear tickets** de las preguntas que no sepa responder con **>95% de
  seguridad**.
- [ ] Enviar **recordatorios de pedidos a los clientes B2B**.
- [ ] **Apuntar pedidos de los clientes B2B**.

### Servidor y seguridad
- [ ] **Crear el servidor** para el funcionamiento de la web.
- [ ] Revisar **toda la seguridad del servidor** para que no lo puedan **tumbar ni
  hackear**.

---

## Buzón de ideas nuevas (NO tocar hasta acabar lo de arriba)
*Aquí va todo lo que se te ocurra que sea funcionalidad nueva. Aparcado a propósito.*

- [ ] (H) **Editar envíos por las pasteleras**: opción para modificar las fichas de
  envío cuando cambia la producción del día, para que no queden desajustadas.
  Relacionado con Albarán franquicias (el albarán se genera tras confirmar producción).
-
