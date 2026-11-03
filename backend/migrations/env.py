from alembic import context
from sqlalchemy import engine_from_config, pool
from app.core.config import settings
from app.db.session import Base
from app.models import models

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
