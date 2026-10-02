"""Immutable public HTML artifacts; Postgres retains the source and fallback HTML."""

import os

from vercel.blob import delete_async, iter_objects_async, put_async

from render import isolated_html


def enabled():
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN"))


async def upload(id: str, html: str):
    if not enabled():
        return None
    result = await put_async(
        f"notebooks/{id}/published.html",
        isolated_html(html).encode(),
        access="public",
        content_type="text/html; charset=utf-8",
        add_random_suffix=True,
        cache_control_max_age=31536000,
    )
    return result.url


async def remove(id: str):
    if not enabled():
        return
    async for item in iter_objects_async(prefix=f"notebooks/{id}/"):
        await delete_async(item.url)
