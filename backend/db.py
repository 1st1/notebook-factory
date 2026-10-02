import time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    inspect,
    select,
    text,
)
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
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("github_id", BigInteger, unique=True),
    Column("login", String, nullable=False, unique=True),
    Column("avatar_url", Text),
    Column("sandbox_name", String, nullable=False, unique=True),
    Column("created_at", Integer, nullable=False),
    CheckConstraint("id >= 1 AND id <= 500", name="users_max_500_slots"),
)

notebooks = Table(
    "notebooks",
    metadata,
    Column("id", String, primary_key=True),
    Column("owner_id", Integer, ForeignKey("users.id"), nullable=False, server_default="1"),
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
        # Reserve the original workspace for its verified GitHub account.
        if await conn.scalar(select(users.c.id).where(users.c.id == 1)) is None:
            from accounts import sandbox_name
            await conn.execute(users.insert().values(
                id=1, login="1st1", sandbox_name=sandbox_name("1st1", 1), created_at=timestamp(),
            ))

        columns = await conn.run_sync(
            lambda sync: {column["name"] for column in inspect(sync).get_columns("notebooks")}
        )
        if "owner_id" not in columns:
            await conn.execute(text(
                "ALTER TABLE notebooks ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"
            ))
        for column in ("published_html", "render_url", "chat_history"):
            if column not in columns:
                await conn.execute(text(f"ALTER TABLE notebooks ADD COLUMN {column} TEXT"))

        await conn.execute(text("CREATE INDEX IF NOT EXISTS notebooks_owner_id_idx ON notebooks(owner_id)"))

        if "chat_revision" not in columns:
            await conn.execute(
                text("ALTER TABLE notebooks ADD COLUMN chat_revision INTEGER NOT NULL DEFAULT 0")
            )


def timestamp():
    return int(time.time())
