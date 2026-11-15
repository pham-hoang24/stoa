"""Bounded detail requests and conservative count reconciliation in source pixels."""
from .answers import abstain
from .render import raster_views, TILE_SIDE, TILE_OVERLAP, MAX_UPSCALE, COUNT_TILED_SIDE


DETAILS_PER_BATCH = 3
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


def merged_ocr(answers):
    """Per-view OCR outcomes from every batch; each detail view is read in exactly one batch."""
    views={}
    for a in answers:
        for v in a.get('ocr',{}).get('views',[]):views.setdefault(v['view_id'],v)
    return {'ocr':{'engine':'tesseract','review_status':'unreviewed','views':list(views.values())}} if views else {}


def same_object(a,b):
    """Two source boxes cite one object when each centre lies within the other box grown by half its size."""
    def inside(box,other):
        cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
        w,h=other[2]-other[0],other[3]-other[1]
        return other[0]-w/2<=cx<=other[2]+w/2 and other[1]-h/2<=cy<=other[3]+h/2
    return inside(a,b) and inside(b,a)


def out_of_scale(boxes):
    """Indices of boxes far larger than the typical counted object (a room or coloured area
    boxed as a window); judged only when there are enough boxes to know what typical is."""
    if len(boxes)<SCALE_MIN_BOXES:
        return set()
    areas=[(b[2]-b[0])*(b[3]-b[1]) for b in boxes]
    median=sorted(areas)[len(areas)//2]
    return {i for i,a in enumerate(areas) if a>MAX_AREA_RATIO*median}


SCALE_MIN_BOXES=5
MAX_AREA_RATIO=20


def extract_small_count(context,catalogs,kind,extractor,region=None):
    """Count on a small raster from independent readings of overlapping enlarged tiles.

    Asked about the whole small sheet, the model guesses positions from the room layout; asked
    about one enlarged tile at a time it boxes the drawn symbols. Each tile is a plain one-view
    request, so the model never handles ownership rules: Python keeps a detection only in the
    tile whose core holds its centre and removes cross-tile duplicates. Any tile that cannot be
    read makes the whole count abstain."""
    from concurrent.futures import ThreadPoolExecutor
    drawing=context['drawings'][0]
    if region is not None:
        # A vector page: region = (tiles of the enlarged drawn region, zoom, region box in page points).
        tiles,scale,box=region
        method={'method':'enlarged_vector_region','region_bbox':[round(v,2) for v in box]}
    else:
        side=max(drawing['pages'][0]['width'],drawing['pages'][0]['height'])
        scale=min(MAX_UPSCALE,COUNT_TILED_SIDE/side)
        try:
            views=raster_views(drawing,scale=scale)
        except (ValueError,RuntimeError) as exc:
            return abstain(str(exc),'image_detail_scope')
        tiles=views[1:] or views
        method={'method':'enlarged_tiles'}
    hidden={'role','core_bbox','source_bbox'}
    plain=[(png,{**{k:v for k,v in d.items() if k not in hidden},'role':'page'}) for png,d in tiles]
    processing={**method,'version':1,'scale':round(scale,3),'tile_side':TILE_SIDE,'overlap':TILE_OVERLAP,
                'required_views':[d['id'] for _,d in plain],'completed_views':[],
                'regions':[{'id':d['id'],'source_bbox':d.get('source_bbox',[0,0,d['source_width'],d['source_height']])} for _,d in tiles]}

    # Region readings of a vector page see only their enlarged crop, as raster regions do: given the
    # page's text facts (legend, title block, labels elsewhere) the model copies them back unboxed.
    local=[{**c,'facts':[]} for c in catalogs] if region is not None else catalogs

    def read(view):
        answer=extractor(context,local,kind,_views=[view],_region=True)
        if answer.get('error')=='invalid_extraction':
            processing.setdefault('retried_views',[]).append(view[1]['id'])
            answer=extractor(context,local,kind,_views=[view],_region=True)
        return answer
    with ThreadPoolExecutor(min(4,len(plain))) as pool:
        answers=list(pool.map(read,plain))
    # One reading keeps its exact provenance (including any provider fallback); several are aggregated per view.
    extra=lambda:{'image_processing':processing,**merged_ocr(answers),
                  'model_provenance':answers[0].get('model_provenance',{}) if len(answers)==1 else provenance(answers)}
    for (_,d),answer in zip(plain,answers):
        if answer['status'] in {'abstain','clarification'}:
            return {**answer,'explanation':'Could not read every enlarged image region. '+answer['explanation'],**extra()}
        processing['completed_views'].append(d['id'])
    bases={a['calculation']['count_basis'] for a in answers if a['calculation']['facts']}
    if len(bases)>1:
        return {**abstain('Image regions mixed object counts and text-marker counts; the counting basis needs review.','image_reconciliation_failed'),**extra()}
    facts,evidence,owners,duplicates=[],[],[],0
    for tile,((_,d),answer) in enumerate(zip(tiles,answers)):
        sx,_,_,sy,ox,oy=d['transform']
        core=d.get('core_bbox',[0,0,d['width'],d['height']])
        for fact,ev in zip(answer['calculation']['facts'],answer['evidence']):
            b=ev['bbox'];cx,cy=((b[0]+b[2])/2-ox)/sx,((b[1]+b[3])/2-oy)/sy
            if not (core[0]<=cx<core[2] and core[1]<=cy<core[3]):
                continue   # its owning neighbour reports it
            if any(owner!=tile and same_object(b,prior['bbox']) for owner,prior in zip(owners,evidence)):
                duplicates+=1;continue
            facts.append(fact);evidence.append(ev);owners.append(tile)
    oversized=out_of_scale([e['bbox'] for e in evidence])
    if oversized:
        facts=[f for i,f in enumerate(facts) if i not in oversized]
        evidence=[e for i,e in enumerate(evidence) if i not in oversized]
    processing.update(duplicates_removed=duplicates,oversized_removed=len(oversized),
                      readings=[a['value'] for a in answers])
    basis=next(iter(bases)) if bases else 'objects'
    explanation=(f'Counted from cited detections in {len(tiles)} overlapping enlarged region(s) of the image, each read separately; '
                 'every object is counted in the one region that owns its centre. Visual interpretation remains unreviewed.')
    if duplicates:explanation+=f' {duplicates} detection(s) seen in two regions were counted once.'
    if oversized:explanation+=(f' {len(oversized)} region(s) far larger than the other counted objects were left out as not being one of them; '
                               'check them before relying on the total.')
    if basis=='text_markers':explanation+=' The label count assumes one marker per object; verify that assumption.'
    if not facts:
        from .extraction import NO_DETECTIONS
        explanation=NO_DETECTIONS+f' {len(tiles)} enlarged region(s) were read separately.'
    if not evidence:
        evidence=[e for a in answers for e in a['evidence'] if 'coverage' in e]
    return {**answers[0],'status':'estimate' if any(a['status']=='estimate' for a in answers) else 'proposal',
            'value':len(facts),'evidence':evidence,'explanation':explanation,
            'calculation':{'operation':'count','facts':facts,'count_basis':basis,'duplicates_removed':duplicates,
                           **({'oversized_removed':len(oversized)} if oversized else {})},
            'contributions':[{'drawing_id':drawing['id'],'evidence_count':len(evidence)}],**extra()}


def extract_details(context,catalogs,kind,extractor,scale=1):
    try:
        views=raster_views(context['drawings'][0],scale=scale)
    except (ValueError,RuntimeError) as exc:
        return abstain(str(exc),'image_detail_scope')
    overview,details=views[0],views[1:]
    required=[v['id'] for _,v in details]
    processing={'method':'overview_and_tiles','version':1,'tile_side':TILE_SIDE,'overlap':TILE_OVERLAP,
                'required_views':required,'completed_views':[],
                'regions':[{'id':v['id'],'source_bbox':v['source_bbox']} for _,v in details]}
    if kind!='count':
        # Normally unreachable: extract() answers non-count raster questions from one full view.
        answer=extractor(context,catalogs,kind)
        if answer['status'] not in {'abstain','clarification'}:processing['completed_views']=required[:]
        answer['image_processing']=processing
        return answer
    answers=[]
    for start in range(0,len(details),DETAILS_PER_BATCH):
        batch=details[start:start+DETAILS_PER_BATCH]
        answer=extractor(context,catalogs,kind,_views=[overview]+batch)
        if answer.get('error')=='invalid_extraction':
            # One fresh retry of only this batch; completed batches are kept, never re-asked.
            processing.setdefault('retried_batches',[]).append(start//DETAILS_PER_BATCH+1)
            answer=extractor(context,catalogs,kind,_views=[overview]+batch)
        answers.append(answer)
        if answer['status'] in {'abstain','clarification'}:
            answer={**answer,'explanation':'Could not complete all required image regions. '+answer['explanation'],
                    'image_processing':processing,'model_provenance':provenance(answers),**merged_ocr(answers)}
            return answer
        processing['completed_views'].extend(v['id'] for _,v in batch)
    try:
        facts,evidence,duplicates,basis=merge_counts(answers)
    except ValueError as exc:
        return {**abstain(str(exc),'image_reconciliation_failed'),'image_processing':processing,
                'model_provenance':provenance(answers),**merged_ocr(answers)}
    processing['duplicates_removed']=duplicates
    explanation=f'Calculated from cited detections after processing all {len(details)} required image regions. The overview supplied context; visual interpretation remains unreviewed.'
    if basis=='text_markers':explanation+=' The label count assumes one marker per object; verify that assumption.'
    if not facts:
        from .extraction import NO_DETECTIONS
        explanation=NO_DETECTIONS+f' All {len(details)} required image regions were read.'
    return {**answers[0],'status':'estimate' if any(a['status']=='estimate' for a in answers) else 'proposal',
            'value':len(facts),'evidence':evidence,'explanation':explanation,
            'calculation':{'operation':'count','facts':facts,'count_basis':basis,'duplicates_removed':duplicates},
            'image_processing':processing,'model_provenance':provenance(answers),**merged_ocr(answers)}
