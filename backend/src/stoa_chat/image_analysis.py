"""Bounded detail requests and conservative count reconciliation in source pixels."""
from .answers import abstain
from .render import raster_views, TILE_SIDE, TILE_OVERLAP


DETAILS_PER_BATCH = 3
MAX_JOINT_DETAILS = 12
MAX_COUNT_FACTS = 3000


def provenance(answers):
    producers=[{'batch':i+1,'status':a['status'],**a.get('model_provenance',{})} for i,a in enumerate(answers)]
    identities={(p['provider'],p.get('model')) for p in producers if p.get('provider')}
    provider,model=next(iter(identities)) if len(identities)==1 else ('mixed' if identities else None,None)
    return {'transport':'stoa.lanes.llm.chat','provider':provider,'model':model,
            'review_status':'unreviewed','per_batch':producers,
            'extraction_attempts':sum(p['extraction_attempts'] for p in producers) if all('extraction_attempts' in p for p in producers) else None}


def overlap(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    intersection=x*y
    return intersection/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


def merge_counts(answers):
    facts,evidence=[],[]
    if sum(len(a['calculation']['facts']) for a in answers)>MAX_COUNT_FACTS:
        raise ValueError(f'Detail detections exceed the {MAX_COUNT_FACTS}-fact reconciliation budget. Narrow the image scope; no partial total was calculated.')
    duplicates=0
    bases={a['calculation']['count_basis'] for a in answers if a['calculation']['facts']}
    if len(bases)>1:
        raise ValueError('Detail batches mixed object counts and text-marker counts; the counting basis needs review.')
    for answer in answers:
        for fact,ev in zip(answer['calculation']['facts'],answer['evidence']):
            duplicate=False
            for prior,previous in zip(facts,evidence):
                if (ev['drawing_id'],ev['page'])!=(previous['drawing_id'],previous['page']):continue
                if ev.get('view_id')==previous.get('view_id'):continue
                iou=overlap(ev['bbox'],previous['bbox'])
                if iou<.35:continue
                key='printed_text' if fact['kind']=='text' else 'label'
                same=fact['kind']==prior['kind'] and str(fact.get(key,fact.get('value',''))).strip().casefold()==str(prior.get(key,prior.get('value',''))).strip().casefold()
                if iou>=.85 and same:
                    duplicate=True;duplicates+=1;break
                raise ValueError('Overlapping detections from different detail views disagree; review their regions before using a total.')
            if not duplicate:
                facts.append(fact);evidence.append(ev)
    if not evidence:evidence=[e for a in answers for e in a['evidence']]
    basis=next(iter(bases)) if bases else 'objects'
    return facts,evidence,duplicates,basis


def extract_details(context,catalogs,kind,extractor):
    try:
        views=raster_views(context['drawings'][0])
    except (ValueError,RuntimeError) as exc:
        return abstain(str(exc),'image_detail_scope')
    overview,details=views[0],views[1:]
    required=[v['id'] for _,v in details]
    processing={'method':'overview_and_tiles','version':1,'tile_side':TILE_SIDE,'overlap':TILE_OVERLAP,
                'required_views':required,'completed_views':[],
                'regions':[{'id':v['id'],'source_bbox':v['source_bbox']} for _,v in details]}
    if kind!='count':
        if len(details)>MAX_JOINT_DETAILS:
            return {**abstain(f'This question requires {len(details)} detail regions together; the current measurement/text limit is {MAX_JOINT_DETAILS}. Select a smaller image scope. No detail regions were silently omitted.','image_detail_scope'),
                    'image_processing':processing}
        answer=extractor(context,catalogs,kind,_views=views)
        if answer['status'] not in {'abstain','clarification'}:processing['completed_views']=required[:]
        answer['image_processing']=processing
        return answer
    answers=[]
    for start in range(0,len(details),DETAILS_PER_BATCH):
        batch=details[start:start+DETAILS_PER_BATCH]
        answer=extractor(context,catalogs,kind,_views=[overview]+batch)
        answers.append(answer)
        if answer['status'] in {'abstain','clarification'}:
            answer={**answer,'explanation':'Could not complete all required image regions. '+answer['explanation'],
                    'image_processing':processing,'model_provenance':provenance(answers)}
            return answer
        processing['completed_views'].extend(v['id'] for _,v in batch)
    try:
        facts,evidence,duplicates,basis=merge_counts(answers)
    except ValueError as exc:
        return {**abstain(str(exc),'image_reconciliation_failed'),'image_processing':processing,
                'model_provenance':provenance(answers)}
    processing['duplicates_removed']=duplicates
    explanation=f'Calculated from cited detections after processing all {len(details)} required image regions. The overview supplied context; visual interpretation remains unreviewed.'
    if basis=='text_markers':explanation+=' The label count assumes one marker per object; verify that assumption.'
    return {**answers[0],'status':'estimate' if any(a['status']=='estimate' for a in answers) else 'proposal',
            'value':len(facts),'evidence':evidence,'explanation':explanation,
            'calculation':{'operation':'count','facts':facts,'count_basis':basis,'duplicates_removed':duplicates},
            'image_processing':processing,'model_provenance':provenance(answers)}
