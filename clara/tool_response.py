"""Normalize the MCP and SDK response shapes without discarding error evidence."""
import json


def response_blocks(value):
    blocks=[];failed=False
    def visit(item):
        nonlocal failed
        if hasattr(item,'model_dump'): item=item.model_dump()
        if isinstance(item,str):
            try: decoded=json.loads(item)
            except (ValueError,TypeError): decoded=None
            if isinstance(decoded,(dict,list)): visit(decoded)
            else: blocks.append({'type':'text','text':item})
        elif isinstance(item,list):
            for child in item: visit(child)
        elif isinstance(item,dict):
            failed |= item.get('isError') is True or item.get('is_error') is True or item.get('clara_tool_error') is True
            failed |= bool(item.get('clara_observation') and item.get('verified') is False)
            failed |= isinstance(item.get('exit_code'),int) and item['exit_code']!=0
            if item.get('type')=='image':
                source=item.get('source') if isinstance(item.get('source'),dict) else {}
                blocks.append({'type':'image','data':item.get('data',source.get('data','')),
                    'mimeType':item.get('mimeType',source.get('media_type',''))})
            elif item.get('type')=='audio': pass
            elif item.get('type')=='text': visit(item.get('text',''))
            elif isinstance(item.get('content'),list): visit(item['content'])
            else: blocks.append({'type':'text','text':json.dumps(item,ensure_ascii=False,default=str)})
        elif item is not None: blocks.append({'type':'text','text':str(item)})
    visit(value)
    return blocks,failed
