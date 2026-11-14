"""Local browser fixture: substitute only the external extraction transport."""
import json
import os
from pathlib import Path
from stoa.lanes import llm
from stoa_chat import create_server

def provider(messages, **kwargs):
    payload = json.loads(messages[-1]['content'][0]['text'])
    question = payload['question'].lower()
    if 'volume' in question:
        return json.dumps({'operation':'abstain','missing':'No source height is available for volume.'})
    page = next((p for p in payload['pages'] if p.get('role')=='detail'),payload['pages'][0])
    box=[40,40,240,200] if page.get('role')=='detail' else [20,20,120,100]
    return json.dumps({'operation':'count','complete':True,'coverage':payload['required_coverage'],
        'target':'saunas','estimate':'estimate' in question,
        'facts':[{'page_ref':page['id'],'bbox':box,'kind':'object','label':'sauna'}]})

llm.chat = provider
if __name__ == '__main__':
    create_server(Path(os.environ.get('STOA_SMOKE_STORAGE','/private/tmp/stoa42-browser-data')),port=int(os.environ.get('STOA_SMOKE_PORT','8093')),static_dir=Path(__file__).resolve().parents[1]).serve_forever()
