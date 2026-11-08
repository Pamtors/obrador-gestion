"""
Carga el catálogo base: productos y sabores, con la disponibilidad de cada
sabor en cada producto (sabor_producto).

Cada producto vendible ya lleva el tamaño fusionado en el nombre ("TARTA GRANDE",
"TARTA MINI", ...): no existe un catálogo de tamaños aparte, y los precios
(PVP / B2B / franquicia) son columnas del propio producto.

Re-ejecutable sin duplicar: get-or-create por nombre en todos los pasos.

Uso: venv/Scripts/python scripts/seed_catalogo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models.usuario  # noqa: F401  (registra Usuario para las relaciones de Tienda)
import app.models.plan_ruta  # noqa: F401
import app.models.config  # noqa: F401
import app.models.cliente_b2b  # noqa: F401  (registra ClienteB2B para la FK de Tienda)
import app.models.tienda  # noqa: F401  (registra Tienda para las relaciones de Usuario)
from app.database import SessionLocal
from app.models.catalogo import SaborProducto
from app.models.producto import Producto
from app.models.sabor import Sabor

# ── Nombres de producto (misma convención que seed_simulacro.py) ───────
P_GRANDE, P_COOKIE, P_TARRINA, P_PEQUENA, P_MINI = (
    "TARTA GRANDE", "COOKIE", "TARRINA", "TARTA PEQUEÑA", "TARTA MINI",
)

# (nombre, orden, permite_porciones, precio_pvp, precio_b2b, precio_franquicia)
# Los precios son orientativos de arranque; se ajustan desde /catalogo/productos.
PRODUCTOS = [
    (P_GRANDE,  1, True,  None, None, None),
    (P_COOKIE,  2, False, None, None, None),
    (P_TARRINA, 3, False, None, None, None),
    (P_PEQUENA, 4, False, None, None, None),
    (P_MINI,    5, False, None, None, None),
]

# Sabores disponibles por producto. El orden de cada lista es el orden con el que
# se numera el sabor dentro de ESE producto (sabor_producto.orden).
ASIGNACIONES = {
    P_GRANDE: [
        "TRADICIONAL", "PAYOYO", "IDIAZABAL", "LA VIÑA", "PISTACHO", "KINDER", "FILIPINOS",
        "LOTUS", "MILKA CON OREO", "SOBRANTE", "LIMON", "TURRON", "MANGO", "HAPPY HIPPO",
        "DULCE DE LECHE",
    ],
    P_COOKIE: [
        "DOS CHOCOLATES", "NEGRA CHOCOLATE BLANCO", "LOTUS", "PISTACHO", "KINDER", "OREO",
        "TWIX", "FILIPINOS BLANCOS", "DUBAI", "KIT KAT", "SOBRANTE", "ZANAHORIA",
        "RED VELVET", "COCO BOOM",
    ],
    P_TARRINA: ["PISTACHO", "KINDER", "CHOCOLATE BLANCO", "EAGLE"],
    P_PEQUENA: ["PISTACHO", "PAYOYO", "TRADICIONAL", "FILIPINOS", "COCO BOOM", "LACASITOS"],
    P_MINI: ["PISTACHO", "PAYOYO", "TRADICIONAL", "FILIPINOS", "COCO BOOM", "LACASITOS"],
}


def seed_productos(db):
    existentes = {p.nombre: p for p in db.query(Producto).all()}
    creados = 0
    for nombre, orden, porciones, pvp, b2b, franquicia in PRODUCTOS:
        if nombre not in existentes:
            p = Producto(
                nombre=nombre,
                orden=orden,
                permite_porciones=porciones,
                precio_pvp=pvp,
                precio_b2b=b2b,
                precio_franquicia=franquicia,
            )
            db.add(p)
            existentes[nombre] = p
            creados += 1
    db.flush()
    print(f"Productos: {creados} creados, {len(existentes)} en total")
    return existentes


def seed_sabores(db):
    """Crea los sabores que aparecen en ASIGNACIONES, respetando el orden global
    en que se mencionan por primera vez."""
    existentes = {s.nombre: s for s in db.query(Sabor).all()}
    orden_actual = max([s.orden or 0 for s in existentes.values()], default=0)

    nombres = []
    for lista in ASIGNACIONES.values():
        for nombre in lista:
            if nombre not in nombres:
                nombres.append(nombre)

    creados = 0
    for nombre in nombres:
        if nombre not in existentes:
            orden_actual += 1
            s = Sabor(nombre=nombre, orden=orden_actual)
            db.add(s)
            existentes[nombre] = s
            creados += 1
    db.flush()
    print(f"Sabores: {creados} creados, {len(existentes)} en total")
    return existentes


def seed_asignaciones(db, productos, sabores):
    existentes = {(sp.producto_id, sp.sabor_id): sp for sp in db.query(SaborProducto).all()}
    creadas = 0
    for prod_nombre, lista in ASIGNACIONES.items():
        p = productos[prod_nombre]
        for orden, sab_nombre in enumerate(lista, start=1):
            s = sabores[sab_nombre]
            sp = existentes.get((p.id, s.id))
            if sp is None:
                db.add(SaborProducto(
                    producto_id=p.id, sabor_id=s.id, produccion=True, orden=orden,
                ))
                creadas += 1
            elif not sp.produccion or sp.out:
                # Reactiva lo que estuviera dado de baja, sin tocar su orden actual
                # (puede haberlo reordenado alguien a propósito).
                sp.produccion, sp.out = True, False
    db.flush()
    print(f"Asignaciones sabor_producto: {creadas} creadas, {len(existentes) + creadas} en total")


def seed():
    db = SessionLocal()
    try:
        productos = seed_productos(db)
        sabores = seed_sabores(db)
        seed_asignaciones(db, productos, sabores)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Catálogo base cargado.")
