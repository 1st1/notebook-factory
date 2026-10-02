import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

import db
import editor
import runtime_registry


@asynccontextmanager
async def api_session():
    yield


# @lat: [[editing#Shared runtime tests]]
async def test_concurrent_notebooks_share_runtime_and_keep_distinct_documents(monkeypatch):
    await db.initialize()
    key = 'shared-concurrency-test'
    monkeypatch.setattr(editor, 'shared_runtime_name', lambda: key)
    monkeypatch.setattr(editor, 'session', api_session)
    instance = SimpleNamespace(fs=SimpleNamespace(write_text=AsyncMock()), current_session=None)
    monkeypatch.setattr(editor.sandbox, 'get_sandbox', AsyncMock(return_value=instance))
    monkeypatch.setattr(editor, '_destroy_runtime', AsyncMock())
    monkeypatch.setattr(editor, '_alive', AsyncMock(return_value=True))
    create = AsyncMock(return_value={'name': key, 'base_url': 'https://example.test/cap', 'generation': editor.generation()})
    monkeypatch.setattr(editor, '_start_runtime', create)
    a, b = await asyncio.gather(editor.start('source A', notebook_id='A'), editor.start('source B', notebook_id='B'))
    assert create.await_count == 1
    assert a['name'] == b['name']
    assert a['path'] != b['path'] and a['token'] != b['token']
    instance.fs.write_text.assert_any_await(a['path'], 'source A')
    instance.fs.write_text.assert_any_await(b['path'], 'source B')
    assert a['url'].endswith('?nf_editor_token=' + a['token'])


async def test_stop_only_deletes_matching_kernel_and_document(monkeypatch):
    deleted = []
    def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, json=[{'id': 'a', 'path': 'one.ipynb'}, {'id': 'b', 'path': 'two.ipynb'}])
        deleted.append(request.url.path)
        return httpx.Response(204)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(editor.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    destroy = AsyncMock()
    monkeypatch.setattr(editor, '_destroy_runtime', destroy)
    await editor.stop({'shared': True, 'base_url': 'https://example.test/cap', 'path': 'one.ipynb'})
    assert deleted == ['/cap/api/sessions/a', '/cap/api/contents/one.ipynb']
    destroy.assert_not_awaited()


async def test_heartbeat_extends_to_idle_horizon_not_per_tab(monkeypatch):
    monkeypatch.setattr(editor.time, 'time', lambda: 1000)
    current = SimpleNamespace(status=editor.sandbox.SandboxStatus.RUNNING, started_at=500,
                              execution_time_limit=timedelta(seconds=900), extend_execution_time_limit=AsyncMock())
    instance = SimpleNamespace(current_session=current)
    await editor._extend(instance)
    current.extend_execution_time_limit.assert_awaited_once_with(500)
    current.execution_time_limit = timedelta(seconds=1400)
    await editor._extend(instance)
    assert current.extend_execution_time_limit.await_count == 1


async def test_offline_deletion_is_applied_on_next_start(monkeypatch):
    await db.initialize()
    key = 'shared-deletion-test'
    monkeypatch.setattr(editor, 'shared_runtime_name', lambda: key)
    monkeypatch.setattr(editor, 'session', api_session)
    monkeypatch.setattr(editor.sandbox, 'delete_drive', AsyncMock())
    await editor.delete_workspace('deleted')
    pending = (await runtime_registry.load_runtime(key))['pending_deletions']
    assert len(pending) == 1
    instance = SimpleNamespace(fs=SimpleNamespace(remove=AsyncMock(), write_text=AsyncMock()), current_session=None)
    monkeypatch.setattr(editor.sandbox, 'get_sandbox', AsyncMock(return_value=instance))
    monkeypatch.setattr(editor, '_destroy_runtime', AsyncMock())
    monkeypatch.setattr(editor, '_start_runtime', AsyncMock(return_value={'name': key, 'base_url': 'https://example.test/cap', 'generation': editor.generation()}))
    await editor.start('source', notebook_id='new')
    instance.fs.remove.assert_awaited_once_with(pending[0], recursive=True, missing_ok=True)
    assert (await runtime_registry.load_runtime(key))['pending_deletions'] == []
