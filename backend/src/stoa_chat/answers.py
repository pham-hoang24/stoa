"""The stable answer-service output boundary: scoped, finite, resolvable evidence."""
import json
import math


def abstain(explanation, error=None):
    answer = {'status': 'abstain', 'value': None, 'explanation': explanation, 'evidence': []}
    if error:
        answer['error'] = error
    return answer


def validate_answer(answer, drawings):
    """Return an independent JSON answer, or raise ValueError for unresolvable output.

    This checks source identity and coordinates; the injected analysis service remains
    responsible for semantic support, calculations, and truthful review status.
    """
    try:
        answer = json.loads(json.dumps(answer, allow_nan=False))
        if not isinstance(answer, dict) or answer.get('status') not in {'supported', 'proposal', 'estimate', 'clarification', 'abstain'}:
            raise ValueError('Invalid answer status')
        value = answer.get('value')
        if isinstance(value, bool) or value is not None and not isinstance(value, (int, float, str)):
            raise ValueError('Invalid answer value')
        evidence = answer.setdefault('evidence', [])
        if not isinstance(evidence, list):
            raise ValueError('Evidence must be a list')
        if answer['status'] in {'abstain', 'clarification'}:
            if value is not None:
                raise ValueError('Abstain/clarification cannot have a value')
            answer['value'] = None
        elif value is None or not evidence:
            raise ValueError('Substantive answers require a value and evidence')
        sources = {d['id']: d for d in drawings}
        for reference in evidence:
            drawing = sources.get(reference.get('drawing_id'))
            if drawing is None:
                raise ValueError('Evidence drawing outside selected scope')
            page = reference.get('page')
            entity = reference.get('entity_id')
            pages = {p['page']: p for p in drawing['pages']}
            if page is not None and (type(page) is not int or page not in pages):
                raise ValueError('Evidence page does not exist')
            if entity is not None and entity not in drawing['entity_ids']:
                raise ValueError('Evidence entity does not exist')
            if entity is None and page is None:
                raise ValueError('Evidence must identify a page or entity')
            box = reference.get('bbox')
            if box is not None:
                if page not in pages or not isinstance(box, list) or len(box) != 4:
                    raise ValueError('A box requires an existing page')
                if any(type(n) not in {int, float} or not math.isfinite(n) for n in box):
                    raise ValueError('Invalid box coordinates')
                p = pages[page]
                x, y = p.get('origin', [0, 0])
                if not (x <= box[0] < box[2] <= x + p['width'] and y <= box[1] < box[3] <= y + p['height']):
                    raise ValueError('Box is outside the original page')
            polygon = reference.get('polygon')
            if polygon is not None:
                if page not in pages or not isinstance(polygon,list) or not 2 <= len(polygon) <= 1000:
                    raise ValueError('Boundary requires an existing page and bounded vertices')
                p=pages[page]
                x,y=p.get('origin',[0,0])
                for vertex in polygon:
                    if not isinstance(vertex,list) or len(vertex)!=2 or any(type(n) not in {int,float} or not math.isfinite(n) for n in vertex):
                        raise ValueError('Invalid boundary vertex')
                    if not (x <= vertex[0] <= x+p['width'] and y <= vertex[1] <= y+p['height']):
                        raise ValueError('Boundary outside original source')
                    if box and not (box[0] <= vertex[0] <= box[2] and box[1] <= vertex[1] <= box[3]):
                        raise ValueError('Boundary outside cited region')
        return answer
    except (TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise ValueError('Malformed analysis output') from exc
