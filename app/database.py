"""Conexión a la base de datos: engine, fábrica de sesiones y Base declarativa.

Todos los modelos de app/models/ heredan de `Base`; `get_db` es la dependencia
de FastAPI que abre/cierra una sesión por petición."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import config

# connect_args solo necesario para SQLite (no usar con PostgreSQL)
_es_sqlite = config.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 15} if _es_sqlite else {}

engine = create_engine(config.database_url, connect_args=connect_args)

if _es_sqlite:
    # SQLite ignora las FKs salvo que se active por conexión; WAL permite
    # lecturas simultáneas con una escritura (varias tiendas a la vez).
    @event.listens_for(engine, "connect")
    def _configurar_sqlite(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
