"""Verify the real SDK/CLI/MCP protocol without sending a model prompt."""
import asyncio
import json
import tempfile
from pathlib import Path
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from clara.auth import cli_path, sanitize_process_environment
from clara.config import Config
from clara.store import Store
from clara.tools import tool_server


async def main():
    sanitize_process_environment()
    with tempfile.TemporaryDirectory(prefix='clara-sdk-probe-') as directory:
        config = Config(Path(directory));config.initialize()
        store=Store(config.data/'probe.sqlite')
        conversation=store.create_conversation()
        job=store.create_job(conversation['id'],'SDK protocol probe only','ask',[])
        async def no_action(*args):
            raise RuntimeError('No tool execution is allowed in this connection-only probe.')
        options=ClaudeAgentOptions(cli_path=cli_path(),cwd=str(config.workspace),
            tools=['Read','Skill','ToolSearch'],setting_sources=['project'],skills='all',
            strict_mcp_config=True,mcp_servers={'clara':tool_server(config,store,job,no_action)},
            stderr=lambda line:None)
        async with asyncio.timeout(45):
            async with ClaudeSDKClient(options=options) as client:
                result=await client.get_mcp_status()
                servers=result['mcpServers']
                report={'sdk_transport_connected':True,
                        'servers':[{'name':s['name'],'status':s['status']} for s in servers],
                        'model_prompt_sent':False,'model_inference_verified':False,
                        'note':'This CLI can defer MCP startup until a task is submitted. An empty list does not prove tool readiness.'}
                print(json.dumps(report,indent=2))
                assert isinstance(servers,list)


if __name__ == '__main__':
    asyncio.run(main())
