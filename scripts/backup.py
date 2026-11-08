"""
Copia la base de datos a la carpeta /backups/ con fecha y hora en el nombre.
Para SQLite: copia el archivo .db directamente.
Para PostgreSQL: usa pg_dump (requiere tenerlo instalado).

Ejecutar manualmente o programar con el Programador de tareas de Windows.
  python scripts/backup.py
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import config

DIRECTORIO_BACKUPS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups")


def backup_sqlite(db_url: str):
    ruta_db = db_url.replace("sqlite:///", "").replace("sqlite://", "")
    if not os.path.isabs(ruta_db):
        ruta_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), ruta_db.lstrip("./"))
    if not os.path.exists(ruta_db):
        print(f"ERROR: No se encuentra la base de datos en {ruta_db}")
        sys.exit(1)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(DIRECTORIO_BACKUPS, f"obrador_{timestamp}.db")
    shutil.copy2(ruta_db, destino)
    print(f"Backup SQLite guardado: {destino}")


def backup_postgres(db_url: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(DIRECTORIO_BACKUPS, f"obrador_{timestamp}.sql")
    resultado = subprocess.run(
        ["pg_dump", db_url, "-f", destino],
        capture_output=True, text=True
    )
    if resultado.returncode != 0:
        print(f"ERROR en pg_dump: {resultado.stderr}")
        sys.exit(1)
    print(f"Backup PostgreSQL guardado: {destino}")


if __name__ == "__main__":
    os.makedirs(DIRECTORIO_BACKUPS, exist_ok=True)
    url = config.database_url
    if url.startswith("sqlite"):
        backup_sqlite(url)
    elif url.startswith("postgresql"):
        backup_postgres(url)
    else:
        print(f"Tipo de base de datos no reconocido: {url}")
        sys.exit(1)
