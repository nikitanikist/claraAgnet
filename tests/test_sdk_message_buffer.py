"""Screenshot-sized CLI messages must survive framing without an unbounded buffer."""
import asyncio
import json

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk._errors import CLIJSONDecodeError
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

from clara.agent import SDK_MESSAGE_BUFFER_BYTES


class FinishedProcess:
    async def wait(self):
        return 0


async def decode(messages, limit):
    transport = SubprocessCLITransport('test', ClaudeAgentOptions(max_buffer_size=limit))
    transport._process = FinishedProcess()
    wire = '\n'.join(json.dumps(message) for message in messages) + '\n'

    async def chunks():
        for start in range(0, len(wire), 65536):
            yield wire[start:start + 65536]

    transport._stdout_stream = chunks()
    return [message async for message in transport.read_messages()]


def test_screenshot_message_over_default_limit_and_following_message_are_preserved():
    messages = [
        {'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'screenshot', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                           'data': 'A' * (2 * 1024 * 1024)}}]}]}},
        {'type': 'result', 'subtype': 'success', 'result': 'Next action'},
    ]
    with pytest.raises(CLIJSONDecodeError, match='maximum buffer size'):
        asyncio.run(decode(messages, 1024 * 1024))
    assert asyncio.run(decode(messages, SDK_MESSAGE_BUFFER_BYTES)) == messages


def test_configured_limit_still_rejects_oversized_messages():
    with pytest.raises(CLIJSONDecodeError, match='maximum buffer size'):
        asyncio.run(decode([{'data': 'A' * SDK_MESSAGE_BUFFER_BYTES}], SDK_MESSAGE_BUFFER_BYTES))
