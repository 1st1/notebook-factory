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
