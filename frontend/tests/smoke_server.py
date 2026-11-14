"""Local browser fixture: substitute only the external extraction transport."""
import json
from pathlib import Path
from stoa.lanes import llm
from stoa_chat import create_server

def provider(messages, **kwargs):
    payload = json.loads(messages[-1]['content'][0]['text'])
    question = payload['question'].lower()
    if 'volume' in question:
        return json.dumps({'operation':'abstain','missing':'No source height is available for volume.'})
    page = payload['pages'][0]
    return json.dumps({'operation':'count','complete':True,'coverage':payload['required_coverage'],
        'target':'saunas','estimate':'estimate' in question,
        'facts':[{'page_ref':page['id'],'bbox':[20,20,120,100],'kind':'object','label':'sauna'}]})

llm.chat = provider
if __name__ == '__main__':
    create_server(Path('/private/tmp/stoa42-browser-data'),port=8093,static_dir=Path(__file__).resolve().parents[1]).serve_forever()
