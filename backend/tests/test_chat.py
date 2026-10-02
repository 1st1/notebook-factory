from contextlib import asynccontextmanager

import ai

import chat


# @lat: [[chat#Streaming protocol tests]]
async def test_client_tool_is_dispatched_without_execution(monkeypatch):
    message = ai.types.messages.Message(
        role="assistant",
        parts=[
            ai.types.messages.ToolCallPart(
                tool_call_id="call-1", tool_name="read_notebook", tool_args="{}"
            )
        ],
    )

    @asynccontextmanager
    async def stream(*args, **kwargs):
        async def events():
            yield ai.events.StreamStart(message=message)
            yield ai.events.StreamEnd(message=message, finish_reason="tool_call")

        yield events()

    monkeypatch.setattr(ai, "stream", stream)
    chunks = "".join([chunk async for chunk in chat.stream([], "existing-assistant")])
    assert '"type": "tool-input-available"' in chunks
    assert '"toolName": "read_notebook"' in chunks
    assert "tool-output-available" not in chunks
    assert "data: [DONE]" in chunks


# @lat: [[chat#Tool argument streaming]]
async def test_partial_tool_arguments_stream_before_dispatch(monkeypatch):
    call = ai.types.messages.ToolCallPart(
        tool_call_id="write-1",
        tool_name="insert_cell",
        tool_args='{"source":"print(42)","cell_type":"code","after_id":""}',
    )
    message = ai.types.messages.Message(role="assistant", parts=[call])
    finished = False

    @asynccontextmanager
    async def stream(*args, **kwargs):
        async def events():
            nonlocal finished
            yield ai.events.StreamStart(message=message)
            yield ai.events.ToolStart(tool_call_id="write-1", tool_name="insert_cell")
            yield ai.events.ToolDelta(tool_call_id="write-1", chunk='{"source":"print(')
            yield ai.events.ToolDelta(
                tool_call_id="write-1", chunk='42)","cell_type":"code","after_id":""}'
            )
            finished = True
            yield ai.events.ToolEnd(tool_call_id="write-1", tool_call=call)
            yield ai.events.StreamEnd(message=message, finish_reason="tool_call")

        yield events()

    monkeypatch.setattr(ai, "stream", stream)
    chunks = []
    async for chunk in chat.stream([]):
        chunks.append(chunk)
        if '"type": "tool-input-delta"' in chunk:
            assert not finished
    text = "".join(chunks)
    assert text.count('"type": "tool-input-delta"') == 2
    assert text.index('"tool-input-delta"') < text.index('"tool-input-available"')
