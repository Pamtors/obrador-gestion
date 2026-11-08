"""Simulacro de un día normal para testear la aplicación.

1. Crea sabores de ejemplo y sus
   asignaciones producto/sabor.
2. Carga las previsiones de stock (galletas, tarrinas, minis, pequeñas y
   tartas grandes) por tienda y día de la semana. REEMPLAZA la previsión
   existente de los productos cargados.
3. Crea 20 clientes B2B, 15 pedidos de particulares y 20 pedidos B2B.
4. Crea el parte de stock de hoy en cada tienda.

Uso: venv/Scripts/python scripts/seed_simulacro.py
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
import app.models.usuario  # noqa: F401  (registra el modelo Usuario en el mapper)
import app.models.plan_ruta  # noqa: F401
import app.models.config  # noqa: F401
from app.models.catalogo import SaborProducto
from app.models.cliente_b2b import ClienteB2B
from app.models.pedido import LineaPedido, Pedido
from app.models.producto import Producto
from app.models.sabor import Sabor
from app.models.stock import LineaParteStock, LineaParteStockOtros, ParteStock, PrevisionStock, SobranteParte
from app.models.tienda import Tienda

random.seed(42)

HOY = date.today()
MANANA = HOY + timedelta(days=1)

# Nombres de producto en BD
P_GRANDE, P_COOKIE, P_TARRINA, P_PEQUENA, P_MINI = "TARTA GRANDE", "COOKIE", "TARRINA", "TARTA PEQUEÑA", "TARTA MINI"

# Alias PDF -> sabor real
ALIAS = {"CHOCOBOM": "COCO BOOM", "GALLETA LIMON": "LIMON", "FILIPINOS - SOBRANTE": "FILIPINOS"}

SABORES_NUEVOS = [
    "DOS CHOCOLATES", "NEGRA CHOCOLATE BLANCO", "TWIX", "FILIPINOS BLANCOS", "DUBAI",
    "SOBRANTE", "ZANAHORIA", "RED VELVET", "CHOCOLATE BLANCO", "EAGLE", "TORRIJA",
    "FILIPINOS", "IDIAZABAL", "LA VIÑA", "MILKA CON OREO", "TURRON", "DULCE DE LECHE",
]

ASIGNACIONES = {
    P_COOKIE: ["DOS CHOCOLATES", "NEGRA CHOCOLATE BLANCO", "LOTUS", "PISTACHO", "KINDER", "OREO",
               "TWIX", "FILIPINOS BLANCOS", "DUBAI", "HAPPY HIPPO", "SOBRANTE", "ZANAHORIA",
               "RED VELVET", "COCO BOOM"],
    P_TARRINA: ["PISTACHO", "KINDER", "CHOCOLATE BLANCO", "EAGLE"],
    P_MINI: ["TORRIJA"],
    P_PEQUENA: ["PISTACHO", "PAYOYO", "TRADICIONAL", "FILIPINOS", "COCO BOOM", "TORRIJA"],
    P_GRANDE: ["TRADICIONAL", "PAYOYO", "IDIAZABAL", "LA VIÑA", "PISTACHO", "KINDER", "FILIPINOS",
               "LOTUS", "MILKA CON OREO", "SOBRANTE", "LIMON", "TURRON", "MANGO", "HAPPY HIPPO",
               "DULCE DE LECHE"],
}

# ------------------------------------------------------------------ PREVISIONES
# Cada bloque: {tienda: {dia(0=Lun..6=Dom): [cantidades en el orden de FILAS]}}

FILAS_COOKIE = ["DOS CHOCOLATES", "NEGRA CHOCOLATE BLANCO", "LOTUS", "PISTACHO", "KINDER", "OREO",
                "TWIX", "FILIPINOS BLANCOS", "DUBAI", "HAPPY HIPPO", "SOBRANTE", "ZANAHORIA",
                "RED VELVET", "CHOCOBOM"]
PREV_COOKIE = {
    "CENTRO": {
        0: [3, 2, 2, 3, 3, 3, 1, 2, 1, 0, 1, 1, 1, 3],
        1: [3, 2, 2, 3, 3, 3, 1, 2, 1, 0, 1, 1, 1, 3],
        2: [3, 2, 2, 3, 3, 3, 1, 2, 1, 0, 1, 1, 1, 3],
        3: [4, 2, 2, 4, 4, 4, 1, 2, 1, 0, 1, 1, 1, 3],
        4: [4, 2, 2, 4, 4, 4, 1, 2, 1, 0, 1, 1, 1, 3],
        5: [2, 3, 3, 5, 2, 3, 2, 3, 2, 0, 0, 4, 4, 4],
        6: [4, 2, 2, 4, 3, 3, 1, 2, 1, 0, 1, 1, 1, 4],
    },
    "PUERTO": {d: [17, 14, 17, 28, 16, 19, 12, 12, 12, 0, 6, 11, 11, 8] for d in range(7)},
    "PLAYA": {
        **{d: [3, 1, 2, 3, 2, 2, 2, 2, 2, 0, 2, 2, 2, 2] for d in range(4)},
        **{d: [3, 3, 3, 6, 3, 3, 3, 3, 2, 0, 3, 5, 2, 2] for d in (4, 5, 6)},
    },
    "UNIVERSIDAD": {
        **{d: [9, 5, 7, 10, 5, 8, 5, 5, 4, 0, 0, 3, 3, 3] for d in range(4)},
        **{d: [8, 7, 8, 16, 6, 9, 6, 7, 7, 0, 6, 4, 4, 4] for d in (4, 5, 6)},
    },
    "NORTE": {
        1: [10, 8, 12, 20, 10, 12, 6, 10, 10, 0, 6, 8, 8, 10],
        3: [12, 12, 15, 20, 14, 14, 9, 12, 12, 0, 7, 9, 9, 8],
        5: [15, 12, 14, 30, 16, 16, 12, 12, 11, 0, 8, 12, 12, 10],
        6: [18, 15, 18, 39, 20, 20, 15, 15, 15, 0, 8, 12, 12, 10],
    },
    "PLAZA": {
        **{d: [15, 10, 8, 15, 8, 10, 6, 8, 8, 0, 4, 8, 8, 7] for d in (0, 1, 2, 3, 6)},
        4: [13, 10, 15, 24, 13, 15, 8, 12, 12, 0, 8, 9, 9, 8],
        5: [15, 15, 15, 30, 16, 18, 12, 15, 15, 0, 8, 14, 14, 9],
    },
    "ESTACION": {
        0: [6, 8, 8, 12, 8, 7, 6, 8, 6, 0, 4, 6, 8, 6],
        1: [6, 8, 8, 12, 8, 7, 6, 8, 6, 0, 4, 6, 8, 6],
        **{d: [10, 8, 12, 20, 10, 12, 6, 10, 10, 0, 6, 8, 8, 6] for d in (2, 3, 4)},
        5: [12, 9, 13, 22, 11, 13, 7, 10, 10, 0, 6, 8, 8, 8],
        6: [9, 8, 12, 18, 10, 11, 6, 10, 10, 0, 6, 7, 7, 8],
    },
    "COSTA": {
        **{d: [3, 4, 5, 6, 5, 4, 3, 4, 3, 0, 0, 2, 3, 3] for d in range(5)},
        5: [8, 6, 8, 12, 6, 6, 6, 6, 5, 0, 0, 3, 3, 3],
        6: [9, 9, 9, 15, 8, 8, 7, 8, 8, 0, 0, 8, 8, 3],
    },
}

FILAS_TARRINA = ["PISTACHO", "KINDER", "CHOCOLATE BLANCO", "EAGLE"]
PREV_TARRINA = {t: {d: [5, 3, 3, 0] for d in range(7)} for t in PREV_COOKIE}

FILAS_MINI = ["TORRIJA"]
PREV_MINI = {
    "CENTRO": {0: [20], 1: [20], 2: [23], 3: [23], 4: [28], 5: [28], 6: [28]},
    "PUERTO": {0: [70], **{d: [85] for d in range(1, 7)}},
    "PLAYA": {d: [28] for d in range(7)},
    "UNIVERSIDAD": {d: [50] for d in range(7)},
    "NORTE": {1: [60], 3: [50], 5: [35], 6: [35]},
    "PLAZA": {d: [45] for d in range(7)},
    "ESTACION": {**{d: [50] for d in range(5)}, 5: [60], 6: [60]},
    "COSTA": {**{d: [25] for d in range(5)}, 5: [30], 6: [30]},
}

FILAS_PEQUENA = ["PISTACHO", "PAYOYO", "TRADICIONAL", "FILIPINOS - SOBRANTE", "CHOCOBOM", "TORRIJA"]
PREV_PEQUENA = {
    "CENTRO": {
        0: [0, 0, 0, 0, 0, 18], 1: [0, 0, 0, 0, 0, 18], 2: [0, 0, 0, 0, 0, 18],
        3: [0, 0, 0, 0, 0, 28],
        **{d: [3, 1, 1, 1, 0, 25] for d in (4, 5, 6)},
    },
    "PUERTO": {
        0: [2, 1, 1, 1, 0, 45], 1: [2, 1, 1, 1, 0, 45],
        2: [2, 1, 1, 1, 0, 55], 3: [2, 1, 1, 1, 0, 55],
        4: [3, 2, 1, 3, 0, 55], 5: [3, 2, 1, 3, 0, 55], 6: [3, 2, 1, 3, 0, 50],
    },
    "PLAYA": {
        **{d: [0, 0, 0, 0, 0, 25] for d in range(4)},
        **{d: [2, 1, 1, 1, 0, 25] for d in (4, 5, 6)},
    },
    "UNIVERSIDAD": {
        **{d: [3, 2, 2, 2, 0, 40] for d in range(4)},
        **{d: [4, 2, 2, 2, 0, 50] for d in (4, 5, 6)},
    },
    "NORTE": {1: [6, 6, 6, 6, 0, 40], 3: [7, 7, 7, 7, 0, 40],
                5: [12, 2, 12, 12, 0, 20], 6: [12, 2, 12, 12, 0, 15]},
    "PLAZA": {
        **{d: [3, 2, 3, 3, 0, 35] for d in range(4)},
        4: [2, 2, 2, 2, 0, 35], 5: [4, 3, 3, 3, 0, 30], 6: [2, 2, 2, 2, 0, 30],
    },
    "ESTACION": {
        **{d: [5, 3, 5, 5, 0, 57] for d in range(4)},
        4: [5, 5, 5, 5, 0, 57], 5: [5, 5, 5, 5, 0, 40], 6: [3, 3, 3, 3, 0, 40],
    },
    "COSTA": {
        0: [0, 0, 0, 0, 0, 14],
        **{d: [0, 0, 0, 0, 0, 18] for d in (1, 2, 3)},
        **{d: [3, 2, 2, 2, 0, 18] for d in (4, 5, 6)},
    },
}

FILAS_GRANDE = ["TRADICIONAL", "PAYOYO", "IDIAZABAL", "LA VIÑA", "PISTACHO", "KINDER", "FILIPINOS",
                "LOTUS", "MILKA CON OREO", "SOBRANTE", "GALLETA LIMON", "TURRON", "MANGO",
                "HAPPY HIPPO", "DULCE DE LECHE"]
PREV_GRANDE = {
    "CENTRO": {
        0: [3, 2, 0, 1, 2, 1, 2, 1, 1, 0, 0, 0, 1, 0, 0],
        1: [3, 2, 0, 1, 2, 1, 2, 1, 1, 0, 0, 0, 0, 1, 0],
        2: [3, 2, 0, 1, 2, 1, 2, 1, 1, 0, 0, 0, 1, 0, 0],
        3: [3, 2, 0, 1, 2, 1, 2, 1, 1, 0, 0, 0, 0, 1, 0],
        4: [4, 2, 0, 1, 4, 2, 3, 1, 1, 0, 0, 0, 1, 0, 0],
        5: [5, 3, 1, 1, 4, 3, 3, 1, 1, 0, 0, 0, 1, 0, 0],
        6: [5, 3, 1, 1, 4, 3, 3, 1, 1, 0, 0, 0, 0, 1, 0],
    },
    "PUERTO": {d: [16, 7, 2, 3, 16, 7, 11, 4, 3, 1, 1, 0, 1, 1, 0] for d in range(7)},
    "PLAYA": {
        **{d: [3, 1, 0, 1, 2, 1, 2, 1, 1, 1, 0, 0, 0, 1, 0] for d in range(5)},
        **{d: [4, 1, 0, 1, 4, 1, 3, 1, 1, 1, 0, 0, 0, 1, 0] for d in (5, 6)},
    },
    "UNIVERSIDAD": {
        **{d: [5, 2, 1, 1, 5, 2, 5, 1, 2, 1, 1, 0, 1, 1, 0] for d in range(4)},
        4: [6, 2, 1, 1, 6, 3, 5, 1, 3, 1, 1, 0, 1, 1, 0],
        5: [8, 3, 1, 1, 8, 3, 6, 1, 3, 2, 1, 0, 1, 1, 0],
        6: [7, 2, 1, 1, 7, 3, 5, 1, 3, 1, 1, 0, 1, 1, 0],
    },
    "NORTE": {
        1: [9, 3, 2, 1, 9, 5, 6, 2, 2, 1, 0, 0, 0, 0, 0],
        3: [14, 7, 3, 2, 14, 7, 9, 2, 2, 4, 0, 0, 2, 3, 0],
        5: [12, 5, 2, 1, 12, 7, 9, 4, 2, 1, 0, 0, 2, 2, 0],
        6: [12, 5, 2, 1, 12, 7, 9, 4, 2, 1, 0, 0, 2, 2, 0],
    },
    "PLAZA": {
        **{d: [5, 2, 1, 0, 5, 3, 4, 1, 1, 1, 0, 0, 1, 1, 0] for d in (0, 1, 2, 3, 4, 6)},
        5: [7, 2, 1, 1, 5, 3, 3, 1, 1, 1, 0, 0, 1, 1, 0],
    },
    "ESTACION": {
        **{d: [7, 2, 1, 1, 7, 5, 5, 2, 1, 1, 1, 0, 1, 1, 0] for d in range(6)},
        6: [7, 4, 2, 1, 5, 3, 4, 2, 2, 2, 0, 0, 1, 2, 0],
    },
    "COSTA": {
        **{d: [3, 1, 0, 1, 2, 2, 2, 1, 1, 0, 1, 0, 1, 0, 1] for d in range(4)},
        **{d: [4, 2, 1, 1, 4, 2, 3, 2, 1, 0, 1, 0, 0, 1, 1] for d in (4, 5, 6)},
    },
}

BLOQUES = [
    (P_COOKIE, FILAS_COOKIE, PREV_COOKIE),
    (P_TARRINA, FILAS_TARRINA, PREV_TARRINA),
    (P_MINI, FILAS_MINI, PREV_MINI),
    (P_PEQUENA, FILAS_PEQUENA, PREV_PEQUENA),
    (P_GRANDE, FILAS_GRANDE, PREV_GRANDE),
]

# ------------------------------------------------------------------ CLIENTES B2B
CLIENTES = [
    # (nombre_comercial, razon_social, cif, zona, direccion, desde, hasta, doc, envio, pago)
    ("Café del Centro", "Café del Centro SL", "B00000001", "Centro", "Calle Mayor 11, Ciudad Demo", "08:00", "09:30", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Restaurante La Plaza", "Hostelería La Plaza SL", "B00000002", "Centro", "Calle Real 62, Ciudad Demo", "09:00", "10:30", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Cafetería El Faro", "El Faro Hostelería SL", "B00000003", "Este", "Paseo Marítimo 3, Ciudad Demo", "08:30", "10:00", "ALBARAN", "WHATSAPP", "EFECTIVO"),
    ("Chiringuito Las Olas", "Las Olas Playa SL", "B00000004", "Este", "Calle Mar 26, Ciudad Demo", "10:00", "11:30", "ALBARAN", "WHATSAPP", "EFECTIVO"),
    ("Hotel Gran Vista", "Hoteles Vista SA", "A00000005", "Centro", "Calle Catedral 20, Ciudad Demo", "07:30", "09:00", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Brunch & Coffee Norte", "Brunch Norte SL", "B00000006", "Norte", "Calle del Sol 9, Ciudad Demo", "08:00", "09:00", "FACTURA", "EMAIL", "TARJETA"),
    ("Restaurante La Despensa", "La Despensa Universitaria SL", "B00000007", "Universidad", "Avenida del Campus 5, Ciudad Demo", "11:00", "12:30", "ALBARAN", "EMAIL", "TRANSFERENCIA"),
    ("Cafetería Campus", "Cafeterías Campus SL", "B00000008", "Universidad", "Calle Estudiantes 4, Ciudad Demo", "07:30", "08:30", "ALBARAN", "NA", "TRANSFERENCIA"),
    ("Bar La Esquina", "La Esquina CB", "E00000009", "Centro", "Calle Larga 92, Ciudad Demo", "10:30", "12:00", "ALBARAN", "WHATSAPP", "EFECTIVO"),
    ("Pastelería Azúcar y Canela", "Azúcar y Canela SL", "B00000010", "Ribera", "Calle Puerto 44, Ciudad Demo", "08:00", "09:30", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Restaurante Brisa Marina", "Brisa Marina SL", "B00000011", "Playa", "Paseo de la Playa 51, Ciudad Demo", "10:00", "11:00", "ALBARAN", "WHATSAPP", "EFECTIVO"),
    ("Café Alameda", "Alameda Hostelería SL", "B00000012", "Centro", "Calle Alameda 21, Ciudad Demo", "08:00", "09:00", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Hotel Costa Sol", "Costa Sol Hoteles SA", "A00000013", "Este", "Avenida del Mar 16, Ciudad Demo", "07:00", "08:30", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Gastrobar El Rincón", "El Rincón Gastro SL", "B00000014", "Norte", "Calle Nueva 29, Ciudad Demo", "11:00", "12:00", "ALBARAN", "WHATSAPP", "EFECTIVO"),
    ("Cafetería Mediodía", "Mediodía CB", "E00000015", "Costa", "Paseo Marítimo 87, Villa Costa", "09:00", "10:30", "ALBARAN", "WHATSAPP", "EFECTIVO"),
    ("Restaurante El Olivo", "El Olivo Playa SL", "B00000016", "Costa", "Calle de la Cruz 15, Villa Costa", "10:00", "11:30", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Café Mirador", "Mirador Hostelería SL", "B00000017", "Sierra", "Calle Reyes 30, Villa Sierra", "08:30", "10:00", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Tetería El Jardín", "El Jardín CB", "E00000018", "Sierra", "Carrera del Río 41, Villa Sierra", "10:00", "11:30", "ALBARAN", "WHATSAPP", "EFECTIVO"),
    ("Catering Eventos Demo", "Eventos Demo Catering SL", "B00000019", "Polígono", "Calle Industria 17, Ciudad Demo", "07:00", "08:00", "FACTURA", "EMAIL", "TRANSFERENCIA"),
    ("Supermercado Gourmet Demo", "Gourmet Demo SL", "B00000020", "Centro", "Calle Comercio 5, Ciudad Demo", "08:00", "09:00", "FACTURA", "EMAIL", "TRANSFERENCIA"),
]

PARTICULARES = [
    ("María López García", "612345001"), ("Antonio Ruiz Fernández", "612345002"),
    ("Carmen Jiménez Torres", "612345003"), ("Javier Moreno Díaz", "612345004"),
    ("Lucía Sánchez Romero", "612345005"), ("Pablo García Navas", "612345006"),
    ("Elena Martín Vega", "612345007"), ("Sergio Castillo Ramos", "612345008"),
    ("Isabel Ortega Molina", "612345009"), ("David Herrera Campos", "612345010"),
    ("Ana Belén Cortés", "612345011"), ("Francisco Gálvez Rueda", "612345012"),
    ("Rocío Aguilar Santos", "612345013"), ("Miguel Ángel Pardo", "612345014"),
    ("Natalia Reyes Luque", "612345015"),
]

COMENTARIOS_PART = [
    "Cumpleaños, poner vela", "Escribir 'Felicidades Mamá'", None, "Sin frutos secos si es posible",
    None, "Recoge por la tarde", None, None, "Es para una comunión", None,
    "Llamar cuando esté lista", None, None, "Aniversario", None,
]


def get_maps(db):
    productos = {p.nombre: p for p in db.query(Producto).all()}
    sabores = {s.nombre: s for s in db.query(Sabor).all()}
    tiendas = {t.nombre: t for t in db.query(Tienda).all()}
    return productos, sabores, tiendas


def paso1_catalogo(db):
    productos, sabores, _ = get_maps(db)
    max_orden = max(s.orden or 0 for s in sabores.values())
    for i, nombre in enumerate(SABORES_NUEVOS, start=1):
        if nombre not in sabores:
            s = Sabor(nombre=nombre, orden=max_orden + i)
            db.add(s)
            sabores[nombre] = s
    db.flush()

    existentes = {(sp.producto_id, sp.sabor_id): sp for sp in db.query(SaborProducto).all()}
    for prod_nombre, lista in ASIGNACIONES.items():
        p = productos[prod_nombre]
        for sab_nombre in lista:
            s = sabores[ALIAS.get(sab_nombre, sab_nombre)]
            sp = existentes.get((p.id, s.id))
            if sp is None:
                db.add(SaborProducto(producto_id=p.id, sabor_id=s.id, produccion=True))
            elif sp.out:
                sp.out, sp.produccion = False, True
    db.flush()
    print(f"[1] Catálogo: sabores totales {db.query(Sabor).count()}, asignaciones {db.query(SaborProducto).count()}")


def paso2_previsiones(db):
    productos, sabores, tiendas = get_maps(db)
    prod_ids = [productos[b[0]].id for b in BLOQUES]
    borradas = db.query(PrevisionStock).filter(PrevisionStock.producto_id.in_(prod_ids)).delete(synchronize_session=False)
    n = 0
    for prod_nombre, filas, data in BLOQUES:
        p = productos[prod_nombre]
        for tienda_nombre, dias in data.items():
            t = tiendas[tienda_nombre]
            for dia, cantidades in dias.items():
                for fila, cant in zip(filas, cantidades):
                    if cant <= 0:
                        continue
                    s = sabores[ALIAS.get(fila, fila)]
                    db.add(PrevisionStock(tienda_id=t.id, dia_semana=dia,
                                          producto_id=p.id, sabor_id=s.id, cantidad=cant))
                    n += 1
    db.flush()
    print(f"[2] Previsiones: {borradas} filas antiguas reemplazadas, {n} filas cargadas")


def paso3_clientes(db):
    existentes = {c.nombre_comercial for c in db.query(ClienteB2B).all()}
    nuevos = []
    for i, (nombre, razon, cif, zona, direccion, desde, hasta, doc, envio, pago) in enumerate(CLIENTES, start=1):
        if nombre in existentes:
            continue
        email = nombre.lower().replace(" ", "").replace("&", "") \
            .translate(str.maketrans("áéíóúñ", "aeioun")) + "@ejemplo.com"
        c = ClienteB2B(
            codigo=f"B2B{i:03d}", nombre_comercial=nombre, razon_social=razon, cif=cif,
            direccion_social=direccion, direccion_entrega=direccion, zona_ruta=zona,
            ventana_entrega_desde=desde, ventana_entrega_hasta=hasta,
            telefono=f"95210{i:04d}", email=email, tipo_cliente="B2B",
            tipo_documento=doc, metodo_envio_factura=envio, via_pago=pago, activo=True,
        )
        db.add(c)
        nuevos.append(c)
    db.flush()
    print(f"[3] Clientes B2B creados: {len(nuevos)}")
    return nuevos


def combos_validos(db, solo_productos=None):
    """(producto, sabor) no deshabilitados (out), solo productos activos."""
    productos, sabores, _ = get_maps(db)
    prod_by_id = {p.id: p for p in productos.values()}
    sab_by_id = {s.id: s for s in sabores.values()}
    combos = []
    for sp in db.query(SaborProducto).filter(SaborProducto.out == False).all():
        p = prod_by_id.get(sp.producto_id)
        s = sab_by_id.get(sp.sabor_id)
        if p and s and p.activo and (solo_productos is None or p.nombre in solo_productos):
            combos.append((p, s))
    return combos


def paso4_pedidos_particulares(db):
    productos, _, tiendas = get_maps(db)
    combos = combos_validos(db, {P_GRANDE, P_PEQUENA, P_MINI})
    tiendas_lista = list(tiendas.values())
    n = 0
    for i, (nombre, telefono) in enumerate(PARTICULARES):
        recogida = MANANA + timedelta(days=random.choice([0, 0, 0, 1, 1, 2]))
        pedido = Pedido(
            referencia=f"SIM-P{i+1:02d}",
            fecha_pedido=HOY, fecha_recogida=recogida,
            fecha_horneado=recogida - timedelta(days=1),
            tipo="PARTICULAR", ubicacion_entrega="TIENDA",
            tienda_id=random.choice(tiendas_lista).id,
            nombre_cliente=nombre, telefono_cliente=telefono,
            comentario=COMENTARIOS_PART[i],
        )
        db.add(pedido)
        db.flush()
        for p, s in random.sample(combos, random.choice([1, 1, 2])):
            db.add(LineaPedido(pedido_id=pedido.id, producto_id=p.id, sabor_id=s.id,
                               cantidad=random.choice([1, 1, 1, 2])))
        n += 1
    db.flush()
    print(f"[4] Pedidos PARTICULAR creados: {n}")


def paso5_pedidos_b2b(db, clientes):
    if not clientes:
        clientes = db.query(ClienteB2B).filter(ClienteB2B.activo == True).all()
    combos_g = combos_validos(db, {P_GRANDE})
    combos_c = combos_validos(db, {P_COOKIE})
    combos_m = combos_validos(db, {P_MINI, P_PEQUENA})
    n = 0
    for i, cliente in enumerate(clientes[:20]):
        recogida = MANANA + timedelta(days=random.choice([0, 0, 0, 0, 1]))
        pedido = Pedido(
            referencia=f"SIM-B{i+1:02d}",
            fecha_pedido=HOY, fecha_recogida=recogida,
            fecha_horneado=recogida - timedelta(days=1),
            tipo="B2B",
            ubicacion_entrega=random.choice(["RESTAURANTE", "RESTAURANTE", "RESTAURANTE", "PUERTO"]),
            cliente_b2b_id=cliente.id,
            comentario=None,
        )
        db.add(pedido)
        db.flush()
        # 2-4 líneas: tartas grandes + cookies + alguna mini/pequeña
        usados = set()
        for grupo, cant_rango in [(combos_g, (1, 4)), (combos_c, (6, 24)),
                                  (random.choice([combos_g, combos_m]), (1, 6))]:
            p, s = random.choice(grupo)
            if (p.id, s.id) in usados:
                continue
            usados.add((p.id, s.id))
            db.add(LineaPedido(pedido_id=pedido.id, producto_id=p.id, sabor_id=s.id,
                               cantidad=random.randint(*cant_rango)))
        n += 1
    db.flush()
    print(f"[5] Pedidos B2B creados: {n}")


def paso6_partes_stock(db):
    productos, sabores, tiendas = get_maps(db)
    dia = HOY.weekday()
    n = 0
    for t in tiendas.values():
        if not t.activa:
            continue
        existe = db.query(ParteStock).filter(ParteStock.tienda_id == t.id, ParteStock.fecha == HOY).first()
        if existe:
            print(f"    - {t.nombre}: ya tiene parte hoy, se omite")
            continue
        parte = ParteStock(fecha=HOY, tienda_id=t.id, usuario_id=1, cerrado=True)
        db.add(parte)
        db.flush()
        # Sobrantes por producto (tabla sobrantes_parte)
        for nombre_p in random.sample([P_GRANDE, P_PEQUENA, P_MINI, P_COOKIE, P_TARRINA], 3):
            cant = random.randint(0, 4)
            if cant > 0:
                db.add(SobranteParte(parte_stock_id=parte.id,
                                     producto_id=productos[nombre_p].id, cantidad=cant))
        prevs = db.query(PrevisionStock).filter(
            PrevisionStock.tienda_id == t.id, PrevisionStock.dia_semana == dia
        ).all()
        prod_by_id = {p.id: p for p in productos.values()}
        for pv in prevs:
            # recuento al cierre: entre 0 y la previsión (lo no vendido)
            restante = max(0, pv.cantidad - random.randint(0, pv.cantidad + 1))
            p = prod_by_id[pv.producto_id]
            raciones = random.randint(0, 7) if p.permite_porciones else 0
            db.add(LineaParteStock(parte_stock_id=parte.id, producto_id=pv.producto_id,
                                   sabor_id=pv.sabor_id, cantidad=restante, raciones=raciones))
        if random.random() < 0.5:
            db.add(LineaParteStockOtros(parte_stock_id=parte.id,
                                        descripcion="Pedido no recogido",
                                        tartas_enteras=1, raciones=0))
        n += 1
    db.flush()
    print(f"[6] Partes de stock creados para hoy ({HOY}): {n}")


def main():
    db = SessionLocal()
    try:
        paso1_catalogo(db)
        paso2_previsiones(db)
        clientes = paso3_clientes(db)
        paso4_pedidos_particulares(db)
        paso5_pedidos_b2b(db, clientes)
        paso6_partes_stock(db)
        db.commit()
        print("\nOK - simulacro cargado")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
