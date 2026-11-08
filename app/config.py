"""Configuración de la aplicación leída desde variables de entorno / .env.

`database_url` determina el motor: SQLite en local, PostgreSQL en servidor
(cambiar la URL basta; database.py ajusta connect_args según el prefijo)."""
from pydantic_settings import BaseSettings


class Configuracion(BaseSettings):
    secret_key: str  # firma de tokens JWT de sesión
    database_url: str = "sqlite:///./obrador.db"
    entorno: str = "development"
    # Credenciales del usuario JEFES inicial (se crea si no existe)
    admin_nombre: str = "Admin"
    admin_email: str = "admin@obrador-demo.example"
    admin_password: str = ""
    invitado_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


config = Configuracion()
