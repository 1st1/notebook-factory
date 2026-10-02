"""Indexed public notebook search; drafts, outputs and chats are not indexed."""
from sqlalchemy import select, text

from db import notebooks

# PostgreSQL maintains the stored vector on title/publication changes, including forks.
SEARCH_SCHEMA = """
ALTER TABLE notebooks ADD COLUMN IF NOT EXISTS search_vector tsvector
GENERATED ALWAYS AS (
    setweight(to_tsvector('english'::regconfig, title), 'A') ||
    setweight(jsonb_to_tsvector('english'::regconfig,
        jsonb_path_query_array(published::jsonb, '$.cells[*].source'::jsonpath),
        '["string"]'::jsonb), 'B')
) STORED
"""
SEARCH_QUERY = text("""
SELECT id, owner_id, title, updated_at, revision, render_url
FROM notebooks
WHERE search_vector @@ websearch_to_tsquery('english', :query)
ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', :query)) DESC,
         updated_at DESC, id
LIMIT 100
""")


async def search_notebooks(conn, query):
    if conn.dialect.name == 'postgresql':
        rows = await conn.execute(SEARCH_QUERY, {'query': query})
    else:
        # Local SQLite development only; production always uses indexed Postgres FTS.
        rows = await conn.execute(select(
            notebooks.c.id, notebooks.c.owner_id, notebooks.c.title,
            notebooks.c.updated_at, notebooks.c.revision, notebooks.c.render_url,
        ).where(notebooks.c.title.icontains(query, autoescape=True))
            .order_by(notebooks.c.updated_at.desc(), notebooks.c.id).limit(100))
    return [dict(row) for row in rows.mappings()]
