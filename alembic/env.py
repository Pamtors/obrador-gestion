"""Configuración de Alembic: importa todos los modelos, toma la URL de BD de
app.config y ejecuta las migraciones (modo online contra la BD u offline a SQL)."""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Importar todos los modelos para que Alembic los detecte en autogenerate
from app.database import Base
import app.models.tienda  # noqa: F401
import app.models.usuario  # noqa: F401
import app.models.sabor  # noqa: F401
import app.models.producto  # noqa: F401
import app.models.catalogo  # noqa: F401
import app.models.cliente_b2b  # noqa: F401
import app.models.pedido  # noqa: F401
import app.models.config  # noqa: F401
import app.models.stock  # noqa: F401
import app.models.produccion  # noqa: F401
import app.models.plan_ruta  # noqa: F401
import app.models.albaran_franquicia  # noqa: F401
import app.models.envio  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    from app.config import config as app_config
    return app_config.database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
