"""Hybrid application answering. Models select facts; Python calculates values."""
import re
from .answers import abstain
from .native import inventory


TARGETS = {'wall': ('wall', 'walls', 'seinä', 'seinää', 'seinien'),
           'door': ('door', 'doors', 'ovi', 'ovea', 'ovien'),
           'window': ('window', 'windows', 'ikkuna', 'ikkunaa', 'ikkunoiden'),
           'space': ('room', 'rooms', 'huone', 'huonetta'),
           'buildingstorey': ('storey', 'storeys', 'floor', 'floors', 'kerros', 'kerrosta'),
           'slab': ('slab', 'slabs')}


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
    if not target and re.search(r'\b(their|them|those|niiden|niitä)\b', question.casefold()):
        target = prior_target
    kind = question_kind(question)
    if target and drawing['format'] == 'ifc':
        # Only answer unfiltered inventories: semantic modifiers require interpretation.
        allowed = {'how','many','what','is','the','total','of','their','are','there','in','this','model',
                   'count','area','volume','length','kuinka','monta','montako','on','mikä','niiden','pinta','ala',
                   'tilavuus','yhteensä','pituus'} | set(TARGETS[target])
        if words - allowed:
            return None
        objects = [o for o in data['objects'] if o['type'].lower() == 'ifc' + target]
        if kind == 'count':
            evidence = [o['evidence'] for o in objects]
            if not evidence:
                # Retain an inspectable model entity for a complete zero inventory.
                evidence = [{'drawing_id': drawing['id'], 'entity_id': drawing['entity_ids'][0], 'coverage': 'Complete IFC type inventory'}]
            return result(len(objects), 'count', evidence, 'count', [], target)
        if kind in {'area', 'volume', 'length'}:
            selected = [o['quantities'].get(kind, []) for o in objects]
            if not objects or any(len(q) != 1 for q in selected):
                return abstain('Each selected element needs one unambiguous source quantity; none may be omitted.')
            facts = [q[0] for q in selected]
            return result(sum(f['value'] for f in facts), facts[0]['unit'], [f['evidence'] for f in facts], 'sum', facts, target)
    return None


def result(value, unit, evidence, operation, facts, target=None):
    return {'status': 'supported', 'value': value, 'unit': unit, 'evidence': evidence,
            'explanation': 'Calculated from native source facts.', 'review_status': 'native', 'target': target,
            'calculation': {'operation': operation, 'facts': [{k: v for k, v in f.items() if k != 'evidence'} for f in facts]}}


class HybridAnswerer:
    def __call__(self, context):
        if len(context['drawings']) != 1:
            return {'status': 'clarification', 'value': None, 'evidence': [], 'explanation': 'Confirm that these drawings are independent views before combining them.'}
        prior = next((m['answer'].get('target') for m in reversed(context['messages'])
                      if m['role'] == 'assistant' and m.get('drawing_ids') == context['drawing_ids']), None)
        drawing = context['drawings'][0]
        data = inventory(drawing)
        answer = native_answer(context['question'], drawing, data, prior)
        if answer is not None:
            return answer
        from .extraction import extract
        return extract(context, [data], question_kind(context['question']))
