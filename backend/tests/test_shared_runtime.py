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
    monkeypatch.setattr(editor, 'shared_runtime_name', lambda owner: key)
    monkeypatch.setattr(editor, 'session', api_session)
    instance = SimpleNamespace(fs=SimpleNamespace(write_text=AsyncMock()), current_session=None)
    monkeypatch.setattr(editor.sandbox, 'get_sandbox', AsyncMock(return_value=instance))
    monkeypatch.setattr(editor, '_destroy_runtime', AsyncMock())
    monkeypatch.setattr(editor, '_alive', AsyncMock(return_value=True))
    create = AsyncMock(return_value={'name': key, 'base_url': 'https://example.test/cap', 'generation': editor.generation()})
    monkeypatch.setattr(editor, '_start_runtime', create)
    a, b = await asyncio.gather(editor.start('source A', notebook_id='A', owner={'id': 2}), editor.start('source B', notebook_id='B', owner={'id': 2}))
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
    monkeypatch.setattr(editor, 'shared_runtime_name', lambda owner: key)
    monkeypatch.setattr(editor, 'session', api_session)
    monkeypatch.setattr(editor.sandbox, 'delete_drive', AsyncMock())
    await editor.delete_workspace('deleted', owner={'id': 2})
    pending = (await runtime_registry.load_runtime(key))['pending_deletions']
    assert len(pending) == 1
    instance = SimpleNamespace(fs=SimpleNamespace(remove=AsyncMock(), write_text=AsyncMock()), current_session=None)
    monkeypatch.setattr(editor.sandbox, 'get_sandbox', AsyncMock(return_value=instance))
    monkeypatch.setattr(editor, '_destroy_runtime', AsyncMock())
    monkeypatch.setattr(editor, '_start_runtime', AsyncMock(return_value={'name': key, 'base_url': 'https://example.test/cap', 'generation': editor.generation()}))
    await editor.start('source', notebook_id='new', owner={'id': 2})
    instance.fs.remove.assert_awaited_once_with(pending[0], recursive=True, missing_ok=True)
    assert (await runtime_registry.load_runtime(key))['pending_deletions'] == []


async def test_different_users_have_separate_runtime_leases_and_documents(monkeypatch):
    await db.initialize()
    monkeypatch.setattr(editor, 'session', api_session)
    monkeypatch.setattr(editor, '_destroy_runtime', AsyncMock())
    monkeypatch.setattr(editor, '_alive', AsyncMock(return_value=True))
    instances = {}
    async def get_sandbox(*, name):
        return instances.setdefault(name, SimpleNamespace(fs=SimpleNamespace(write_text=AsyncMock()), current_session=None))
    monkeypatch.setattr(editor.sandbox, 'get_sandbox', get_sandbox)
    async def create(owner, report):
        return {'name': owner['sandbox_name'], 'base_url': 'https://' + owner['sandbox_name'] + '.test/cap', 'generation': editor.generation()}
    create_mock = AsyncMock(side_effect=create)
    monkeypatch.setattr(editor, '_start_runtime', create_mock)
    alice = {'id': 20, 'sandbox_name': 'nf-alice-isolation'}
    bob = {'id': 21, 'sandbox_name': 'nf-bob-isolation'}
    a, b, a2 = await asyncio.gather(
        editor.start('A', notebook_id='a', owner=alice),
        editor.start('B', notebook_id='b', owner=bob),
        editor.start('A2', notebook_id='a2', owner=alice),
    )
    assert a['name'] == a2['name'] != b['name']
    assert create_mock.await_count == 2
    assert instances[a['name']].fs.write_text.await_count == 2
    assert instances[b['name']].fs.write_text.await_count == 1
