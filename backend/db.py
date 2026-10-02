import time

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    **(
        {"pool_size": 2, "max_overflow": 3, "pool_pre_ping": True, "pool_recycle": 300}
        if DATABASE_URL.startswith("postgresql+")
        else {"poolclass": NullPool}
    ),
)
metadata = MetaData()
notebooks = Table(
    "notebooks",
    metadata,
    Column("id", String, primary_key=True),
    Column("title", String, nullable=False),
    Column("source", Text, nullable=False),
    Column("published", Text, nullable=False),
    Column("published_html", Text),
    Column("render_url", Text),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    Column("revision", Integer, nullable=False, default=1),
    Column("editor", Text),
    Column("chat_history", Text),
    Column("chat_revision", Integer, nullable=False, default=0),
    Column("claim", String),
    Column("claim_until", Integer, default=0),
)


runtimes = Table(
    "shared_runtimes", metadata,
    Column("id", String, primary_key=True),
    Column("state", Text),
    Column("claim", String),
    Column("claim_until", Integer, nullable=False, default=0),
)


async def initialize():
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(734823109)"))
        await conn.run_sync(metadata.create_all)
        columns = await conn.run_sync(
            lambda sync: {column["name"] for column in inspect(sync).get_columns("notebooks")}
        )
        for column in ("published_html", "render_url", "chat_history"):
            if column not in columns:
                await conn.execute(text(f"ALTER TABLE notebooks ADD COLUMN {column} TEXT"))

        if "chat_revision" not in columns:
            await conn.execute(
                text("ALTER TABLE notebooks ADD COLUMN chat_revision INTEGER NOT NULL DEFAULT 0")
            )


def timestamp():
    return int(time.time())
