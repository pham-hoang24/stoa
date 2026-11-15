"""Hybrid application answering. Models select facts; Python calculates values."""
import re
from .answers import abstain
from .native import inventory


TARGETS = {'wall': ('wall', 'walls', 'seinä', 'seinää', 'seinien'),
           'door': ('door', 'doors', 'ovi', 'ovea', 'ovien', 'ovet', 'tür', 'türe', 'türen', 'tuer', 'tuere', 'tueren',
                    'porte', 'portes', 'porta'),
           'window': ('window', 'windows', 'ikkuna', 'ikkunaa', 'ikkunoiden', 'ikkunat', 'fenster', 'fenêtre', 'fenêtres',
                      'fenetre', 'fenetres', 'finestra', 'finestre'),
           'space': ('room', 'rooms', 'huone', 'huonetta'),
           'buildingstorey': ('storey', 'storeys', 'floor', 'floors', 'kerros', 'kerrosta'),
           'slab': ('slab', 'slabs'), 'line':('line','lines','viiva','viivaa'),
           'circle':('circle','circles'), 'lwpolyline':('polyline','polylines'),
           'rect':('rectangle','rectangles'), 'polygon':('polygon','polygons')}


def question_kind(question):
    q = question.casefold()
    # Physical units outrank counts; counts outrank dimensional adjectives. The kind guides the
    # extraction (and decides which quantities Python may compute); a well-cited direct reading
    # of printed text is still accepted for length/area/volume questions.
    for kind, pattern in [
        ('volume', r'volume|tilavuu|m³|cubic\s+met(?:re|er)s?'),
        ('area', r'area|pinta.ala|m²|square\s+met(?:re|er)s?|neliömet'),
        ('count', r'\bhow many\b|\bcount(?:s|ing)?\b(?!\s+as\b)|\bnumber\s+of\b|kuinka monta|montako|lukumäärä'
                  r'|\bwie viele\b|\banzahl\b|\bcombien\b|\bnombre de\b|\bquant[ie]\b|\bnumero di\b'),
        ('length', r'\b(?:length|long|width|wide|height|high|tall|distance|depth|deep|perimeter)\b|pitu|ympärys|levey|korkeu|etäisyy|syvyy')]:
        if re.search(pattern, q):
            return kind
    return 'text'


# Words that do not narrow an unfiltered "how many doors/windows" question, in the five
# question languages. Any other word (a room, a storey, "interior") needs interpretation.
OPENING_COUNT_WORDS = {
    'how', 'many', 'what', 'is', 'the', 'total', 'number', 'of', 'are', 'there', 'in', 'on', 'this', 'drawing', 'plan',
    'sheet', 'floor', 'count', 'shown', 'drawn', 'do', 'you', 'see', 'can', 'all', 'here',
    'wie', 'viele', 'gibt', 'es', 'sind', 'hat', 'der', 'die', 'das', 'dem', 'den', 'diesem', 'dieser', 'im', 'auf',
    'plan', 'grundriss', 'insgesamt', 'anzahl', 'zeichnung',
    'combien', 'de', 'y', 'a', 't', 'il', 'sur', 'ce', 'cette', 'le', 'la', 'les', 'dans', 'nombre', 'des', 'au', 'total',
    'quante', 'quanti', 'ci', 'sono', 'nel', 'nella', 'questo', 'questa', 'pianta', 'disegno', 'numero', 'di', 'delle', 'dei',
    'kuinka', 'monta', 'montako', 'on', 'tässä', 'piirustuksessa', 'kuvassa', 'pohjassa', 'yhteensä', 'lukumäärä'}


def opening_answer(question, drawing, target, kind):
    """Rule-based door/window counts from vector geometry; None when the rule cannot answer."""
    if kind != 'count' or target not in {'door', 'window'} or drawing['format'] not in {'pdf', 'dxf'}:
        return None
    words = set(re.findall(r'[\w]+', question.casefold()))
    if words - OPENING_COUNT_WORDS - set(TARGETS[target]):
        return None
    from .vector_counts import opening_count
    try:
        return opening_count(drawing, target)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RuntimeError, OSError):
        return None


def native_answer(question, drawing, data, prior_target=None):
    words = set(re.findall(r'[\w]+', question.casefold()))
    target = next((t for t, aliases in TARGETS.items() if words.intersection(aliases)), None)
    if not target and re.search(r'\b(its|their|them|those|niiden|niitä)\b', question.casefold()):
        target = prior_target
    kind = question_kind(question)
    answer = opening_answer(question, drawing, target, kind)
    if answer is not None:
        return answer
    if kind == 'text' and re.fullmatch(r'(what (text|labels) (is|are) on this drawing|show (all )?(text|labels)|näytä teksti)\??', question.casefold().strip()):
        facts = [f for f in data['facts'] if f['kind'] == 'text']
        if facts:
            return result('\n'.join(str(f['value']) for f in facts), None, [f['evidence'] for f in facts], 'text', facts)
    domain = {'ifc': {'wall','door','window','space','buildingstorey','slab'}, 'dxf': {'line','circle','lwpolyline'}, 'svg': {'rect','circle','line','polygon','polyline'}}
    if target in domain.get(drawing['format'], set()) and data['complete']:
        # Only answer unfiltered inventories: semantic modifiers require interpretation.
        allowed = {'how','many','what','is','the','total','of','their','are','there','in','this','model',
                   'count','area','volume','length','kuinka','monta','montako','on','mikä','niiden','pinta','ala',
                   'tilavuus','yhteensä','pituus'} | set(TARGETS[target])
        if words - allowed:
            return None
        expected = 'ifc' + target if drawing['format'] == 'ifc' else target
        objects = [o for o in data['objects'] if o['type'].lower()==expected or expected in o.get('families',[])]
        if kind == 'count':
            evidence = [o['evidence'] for o in objects]
            if not evidence:
                # Retain an inspectable model entity for a complete zero inventory.
                if drawing['pages']:
                    from .native import page_evidence
                    evidence=[page_evidence(drawing,p['page']) | {'coverage':'Complete native shape inventory'} for p in drawing['pages']]
                elif drawing['entity_ids']:
                    evidence=[{'drawing_id':drawing['id'],'entity_id':drawing['entity_ids'][0],'coverage':'Complete native type inventory'}]
                else:
                    return abstain('No inspectable source entity or page can support this zero inventory.')
            return result(len(objects), 'count', evidence, 'count', [], target)
        if kind in {'area', 'volume', 'length'}:
            selected = [o['quantities'].get(kind, []) for o in objects]
            if kind=='length' and drawing['format']=='ifc':
                selected=[[f for f in quantities if f.get('role','') in {'length','netlength','grosslength'}] for quantities in selected]
            if not objects or any(len(q) != 1 for q in selected):
                return abstain('Each selected element needs one unambiguous source quantity; none may be omitted.')
            facts = [q[0] for q in selected]
            return result(sum(f['value'] for f in facts), facts[0]['unit'], [f['evidence'] for f in facts], 'sum', facts, target)
    return None


def result(value, unit, evidence, operation, facts, target=None):
    return {'status': 'supported', 'value': value, 'unit': unit, 'evidence': evidence,
            'explanation': 'Calculated from native source facts.', 'review_status': 'native', 'target': target,
            'calculation': {'operation': operation, 'facts': [{k: v for k, v in f.items() if k != 'evidence'} for f in facts]}}


def clarify(message):
    return {'status':'clarification','value':None,'evidence':[],'explanation':message}


class HybridAnswerer:
    def __call__(self, context):
        drawings = context['drawings']
        selection = context['drawing_ids']
        question = context['question']
        previous = next((m for m in reversed(context['messages']) if m['role']=='assistant'), None)
        prior = previous['answer'].get('target') if previous and previous.get('drawing_ids')==selection else None
        if re.search(r'\b(its|their|them|those|niiden|niitä)\b',question.casefold()) and not prior:
            return clarify('Which objects do you mean? State the target for this selected drawing scope.')
        negated = bool(re.search(r'\b(not|no|never|ei|eivät|don.t|aren.t|isn.t|weren.t|wasn.t|cannot|can.t)\b',question.casefold()))
        independent = not negated and bool(re.search(r'\b(are (?:all )?independent|are non.overlapping|confirm independent|erillisiä)\b',question.casefold()))
        confirmed = independent or bool(previous and previous.get('drawing_ids')==selection and previous['answer'].get('independent_scope'))
        if len(drawings)>1:
            if re.search(r'compare|difference|ratio|average|versus|vertaa|ero|suhde|keskiarvo',question,re.I):
                return clarify('This comparison needs a defined operation and target per drawing. Ask each drawing separately, or request an additive total for independent views.')
            if negated and re.search(r'independent|overlap|erillisiä',question,re.I):
                return clarify('Overlapping views cannot be summed. Select one view or specify a per-drawing text question.')
            if len({d['sha256'] for d in drawings})!=len(drawings):
                return clarify('Identical source content is selected more than once. Select one copy before combining quantities.')
            if not confirmed and question_kind(question)!='text':
                return clarify('These drawings may overlap. Confirm that they are independent views before combining quantities.')
            if len(drawings)>12:
                return abstain('Select at most twelve independent drawings for one question.')
            if independent:
                question = re.sub(
                    r"\b(?:(?:yes|kyllä)[,\s]+)?(?:these(?: drawings| views)?|they|the drawings|all drawings)\s+are\s+(?:all\s+)?(?:independent|non.overlapping)\b|\b(?:I\s+)?confirm independent\b|\b(?:nämä ovat\s+)?erillisiä\b",
                    '', question, flags=re.I).strip(' ,.!;:')
                if not question or question.casefold() in {'yes','kyllä'}:
                    question = next((m['question'] for m in reversed(context['messages']) if m['role']=='user' and m.get('drawing_ids')==selection), '')
        answers = []
        from .extraction import extract
        for drawing in drawings:
            scoped_question, query = question, None
            if drawing['format']=='ifc':
                from .ifc_query import prepare
                answer,data,scoped_question,query = prepare(question,drawing,prior)
            else:
                data = inventory(drawing)
                answer = native_answer(question,drawing,data,prior)
            if answer is None:
                scoped = {**context,'question':scoped_question,'drawing_ids':[drawing['id']],'drawings':[drawing],
                          'messages':[m for m in context['messages'] if m.get('drawing_ids')==selection]}
                answer = extract(scoped,[data],question_kind(question))
            if query:
                answer['native_query'] = query
            answers.append(answer)
        if any(a['status'] in {'abstain','clarification'} for a in answers):
            if len(answers)==1:
                return answers[0]
            return abstain('A total requires every selected drawing: ' + '; '.join(a['explanation'] for a in answers if a['status'] in {'abstain','clarification'}))
        answer = answers[0]
        if len(answers)>1:
            if len({a.get('unit') for a in answers})!=1 or any(isinstance(a['value'],str)!=isinstance(answer['value'],str) for a in answers):
                return abstain('Selected drawing contributions have incompatible quantities or units.')
            answer = {**answer,'value':'\n'.join(a['value'] for a in answers) if isinstance(answer['value'],str) else sum(a['value'] for a in answers),
                      'status':'estimate' if any(a['status']=='estimate' for a in answers) else 'proposal' if any(a['status']=='proposal' for a in answers) else 'supported',
                      'review_status':'unreviewed' if any(a.get('review_status')=='unreviewed' for a in answers)
                                       else 'rule_based' if any(a.get('review_status')=='rule_based' for a in answers) else 'native',
                      'evidence':[e for a in answers for e in a['evidence']],
                      'calculation':{'operation':'sum_contributions','calculations':[a.get('calculation') for a in answers]}}
            producers = [{'drawing_id':d['id'], **a['model_provenance']}
                         for d,a in zip(drawings,answers) if a.get('model_provenance')]
            if producers:
                identities = {(p['provider'],p['model']) for p in producers}
                provider,model = next(iter(identities)) if len(identities)==1 else ('mixed',None)
                answer['model_provenance'] = {'transport':'stoa.lanes.llm.chat',
                                              'provider':provider,'model':model,
                                              'review_status':'unreviewed','per_drawing':producers}
        answer['independent_scope'] = confirmed
        answer['contributions'] = [{'drawing_id':d['id'],'value':a['value'],'unit':a.get('unit'),
                                    'target':a.get('target'),'status':a['status'],'review_status':a.get('review_status'),
                                    **({'model_provenance':a['model_provenance']} if a.get('model_provenance') else {}),
                                    **({'native_query':a['native_query']} if a.get('native_query') else {}),
                                    **({'image_processing':a['image_processing']} if a.get('image_processing') else {}),
                                    **({'ocr':{k:v for k,v in a['ocr'].items() if k!='views'}|{'views':[{k:v for k,v in view.items() if k!='tokens'} for view in a['ocr']['views']]}} if a.get('ocr') else {})}
                                   for d,a in zip(drawings,answers)]
        if len(answers)>1 and any(a.get('native_query') for a in answers):
            answer['native_query'] = {'scope':'independent_drawings','per_drawing':[
                {'drawing_id':d['id'],**a['native_query']} for d,a in zip(drawings,answers) if a.get('native_query')]}
        if len(answers)>1 and any(a.get('image_processing') for a in answers):
            processing=[{'drawing_id':d['id'],**a['image_processing']} for d,a in zip(drawings,answers) if a.get('image_processing')]
            answer['image_processing']={'method':'multiple_drawings','per_drawing':processing,
                'required_views':[v for p in processing for v in p['required_views']],
                'completed_views':[v for p in processing for v in p['completed_views']]}
        if len(answers)>1 and any(a.get('ocr') for a in answers):
            answer['ocr']={'engine':'tesseract','review_status':'unreviewed','per_drawing':[
                {'drawing_id':d['id'],**a['ocr']} for d,a in zip(drawings,answers) if a.get('ocr')]}
        sources = {d['id']:d for d in drawings}
        for ev in answer['evidence']:
            source = sources[ev['drawing_id']]
            ev.update(source_sha256=source['sha256'], original_url=source['asset_url'])
        return answer
