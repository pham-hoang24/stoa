"""Hybrid application answering. Models select facts; Python calculates values."""
import re
from .answers import abstain
from .native import inventory


TARGETS = {'wall': ('wall', 'walls', 'seinä', 'seinää', 'seinien'),
           'door': ('door', 'doors', 'ovi', 'ovea', 'ovien'),
           'window': ('window', 'windows', 'ikkuna', 'ikkunaa', 'ikkunoiden'),
           'space': ('room', 'rooms', 'huone', 'huonetta'),
           'buildingstorey': ('storey', 'storeys', 'floor', 'floors', 'kerros', 'kerrosta'),
           'slab': ('slab', 'slabs'), 'line':('line','lines','viiva','viivaa'),
           'circle':('circle','circles'), 'lwpolyline':('polyline','polylines'),
           'rect':('rectangle','rectangles'), 'polygon':('polygon','polygons')}


def question_kind(question):
    q = question.casefold()
    for kind, pattern in [('volume', r'volume|tilavuu|m³'), ('area', r'area|pinta.ala|m²'),
                          ('length', r'length|long|pitu|perimeter|ympärys'),
                          ('count', r'how many|count|kuinka monta|montako|lukumäärä')]:
        if re.search(pattern, q):
            return kind
    return 'text'


def native_answer(question, drawing, data, prior_target=None):
    words = set(re.findall(r'[\wäöå]+', question.casefold()))
    target = next((t for t, aliases in TARGETS.items() if words.intersection(aliases)), None)
    if not target and re.search(r'\b(its|their|them|those|niiden|niitä)\b', question.casefold()):
        target = prior_target
    kind = question_kind(question)
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
        negated = bool(re.search(r'\b(not|no|never|ei|eivät|don.t)\b',question.casefold()))
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
            data = inventory(drawing)
            answer = native_answer(question,drawing,data,prior)
            if answer is None:
                scoped = {**context,'question':question,'drawing_ids':[drawing['id']],'drawings':[drawing],
                          'messages':[m for m in context['messages'] if m.get('drawing_ids')==selection]}
                answer = extract(scoped,[data],question_kind(question))
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
                      'review_status':'unreviewed' if any(a.get('review_status')=='unreviewed' for a in answers) else 'native',
                      'evidence':[e for a in answers for e in a['evidence']],
                      'calculation':{'operation':'sum_contributions','calculations':[a.get('calculation') for a in answers]}}
        answer['independent_scope'] = confirmed
        answer['contributions'] = [{'drawing_id':d['id'],'value':a['value'],'unit':a.get('unit')} for d,a in zip(drawings,answers)]
        sources = {d['id']:d for d in drawings}
        for ev in answer['evidence']:
            source = sources[ev['drawing_id']]
            ev.update(source_sha256=source['sha256'], original_url=source['asset_url'])
        return answer
