import time

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
metadata = MetaData()
notebooks = Table(
    "notebooks",
    metadata,
    Column("id", String, primary_key=True),
    Column("title", String, nullable=False),
    Column("source", Text, nullable=False),
    Column("published", Text, nullable=False),
    Column("published_html", Text),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    Column("revision", Integer, nullable=False, default=1),
    Column("editor", Text),
    Column("claim", String),
    Column("claim_until", Integer, default=0),
)


async def initialize():
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(734823109)"))
        await conn.run_sync(metadata.create_all)
        columns = await conn.run_sync(
            lambda sync: {column["name"] for column in inspect(sync).get_columns("notebooks")}
        )
        if "published_html" not in columns:
            await conn.execute(text("ALTER TABLE notebooks ADD COLUMN published_html TEXT"))


def timestamp():
    return int(time.time())
