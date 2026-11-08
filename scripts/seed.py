"""
Crea el usuario ADMIN inicial y las tiendas base.
Ejecutar UNA SOLA VEZ tras la primera migración:
  python scripts/seed.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.auth.contrasena import hashear
from app.config import config
from app.database import SessionLocal, engine
from app.models.tienda import Tienda
from app.models.cliente_b2b import ClienteB2B
from app.models.usuario import Rol, Usuario

TIENDAS_INICIALES = [
    "CENTRO", "PUERTO", "PLAYA", "UNIVERSIDAD",
    "NORTE", "PLAZA", "ESTACION", "COSTA",
]

def seed():
    db = SessionLocal()
    try:
        # Tiendas
        for nombre in TIENDAS_INICIALES:
            if not db.query(Tienda).filter(Tienda.nombre == nombre).first():
                db.add(Tienda(nombre=nombre))
        db.commit()
        print(f"Tiendas creadas: {len(TIENDAS_INICIALES)}")

        # Usuario ADMIN
        if not db.query(Usuario).filter(Usuario.email == config.admin_email).first():
            admin = Usuario(
                nombre=config.admin_nombre,
                email=config.admin_email,
                hash_contrasena=hashear(config.admin_password),
                rol=Rol.JEFES,
            )
            db.add(admin)
            db.commit()
            print(f"Usuario ADMIN creado: {config.admin_email}")
        else:
            print(f"El usuario ADMIN ya existe: {config.admin_email}")

        # ==========================
        # Usuario INVITADO
        # ==========================
        invitado_email = "invitado@obrador-demo.example"

        if not config.invitado_password:
            print("INVITADO_PASSWORD no definida en .env: no se crea el usuario invitado.")
        elif not db.query(Usuario).filter(Usuario.email == invitado_email).first():
            invitado = Usuario(
                nombre="Invitado",
                email=invitado_email,
                hash_contrasena=hashear(config.invitado_password),
                rol=Rol.VISUALIZADOR,
            )
            db.add(invitado)
            db.commit()
            print(f"Usuario INVITADO creado: {invitado_email}")
        else:
            print(f"El usuario INVITADO ya existe: {invitado_email}")

    finally:
        db.close()


if __name__ == "__main__":
    if not config.admin_password:
        print("ERROR: ADMIN_PASSWORD no está definida en el .env")
        sys.exit(1)

    seed()
    print("Seed completado.")
