"""Discover MCP tools without model inference, browser clicks or desktop actions."""
import argparse
import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from clara.config import Config, default_data
from clara.connectors import mcp_connectors


async def main():
    config = Config(default_data())
    config.initialize()
    results = []
    for name, spec in mcp_connectors(config).items():
        async with asyncio.timeout(45):
            async with stdio_client(StdioServerParameters(command=spec['command'], args=spec['args'], env=spec.get('env'))) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    results.append({'connector':name,'tools':[tool.name for tool in tools.tools],
                                    'note':'Discovery only. No model or computer action was executed.'})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
