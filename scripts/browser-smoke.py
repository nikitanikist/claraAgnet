"""Real Chrome MCP smoke test against an ephemeral local page; no model or external tenant."""
import asyncio
import functools
import json
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from clara.config import Config
from clara.connectors import mcp_connectors


async def main():
    with tempfile.TemporaryDirectory(prefix='clara-browser-test-') as tmp:
        folder=Path(tmp);cfg=Config(folder/'data');cfg.initialize()
        cfg.save_settings({**cfg.settings(),'browser_enabled':True})
        (folder/'input.txt').write_text('Synthetic Clara upload')
        (cfg.workspace/'input.txt').write_text('Synthetic Clara upload')
        (folder/'index.html').write_text('<!doctype html><title>Clara browser test</title><label>Name<input id="name"></label><label>File<input id="file" type="file"></label><button onclick="document.getElementById(\'result\').textContent=\'Hello \'+document.getElementById(\'name\').value">Prepare</button><p id="result"></p><a href="input.txt" download>Download test file</a>')
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(folder)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            spec=mcp_connectors(cfg).get('chrome')
            if not spec: raise RuntimeError('Run Setup-Browser / install-browser first; Chrome must be installed.')
            spec['args'].append('--headless')
            async with asyncio.timeout(60):
                async with stdio_client(StdioServerParameters(command=spec['command'],args=spec['args'],env=spec.get('env'))) as streams:
                    async with ClientSession(*streams) as client:
                        await client.initialize()
                        page_id=None
                        async def call(name,args):
                            if page_id is not None and name not in {'new_page','list_pages'}: args={'pageId':page_id,**args}
                            result=await client.call_tool(name,args)
                            if result.is_error: raise RuntimeError(str(result.content))
                            return '\n'.join(b.text for b in result.content if hasattr(b,'text'))
                        import re
                        opened=await call('new_page',{'url':f'http://127.0.0.1:{server.server_port}/index.html'})
                        match=re.search(r'(\d+): .*127\.0\.0\.1:',opened)
                        if not match: raise RuntimeError('Cannot identify test page: '+opened[:2000])
                        page_id=int(match.group(1))
                        snapshot=await call('take_snapshot',{})
                        def uid(label):
                            match=re.search(r'uid=([^ ]+).*'+re.escape(label),snapshot)
                            if not match: raise RuntimeError('Missing control '+label+' in '+snapshot[:3000])
                            return match.group(1)
                        await call('fill',{'uid':uid('textbox "Name"'),'value':'Clara'})
                        await call('upload_file',{'uid':uid('button "File"'),'filePaths':[str(cfg.workspace/'input.txt')]})
                        await call('click',{'uid':uid('button "Prepare"')})
                        result=await call('take_snapshot',{})
                        if 'Hello Clara' not in result: raise RuntimeError('Browser action was not reflected in the page.')
                        snapshot=result
                        await call('click',{'uid':uid('link "Download test file"')})
                        print(json.dumps({'passed':['Chrome launch','DOM snapshot','form fill','file upload','click','postcondition readback','download link click'],
                            'note':'Actual download persistence is covered by the browser UI test. No model or client website was used.'}))
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)


if __name__=='__main__': asyncio.run(main())
