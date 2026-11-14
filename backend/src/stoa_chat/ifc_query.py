"""Plan typed IFC selections before reading properties or asking a model for facts."""
from dataclasses import dataclass, asdict
from pathlib import Path
import re
from .answers import abstain


@dataclass(frozen=True)
class IFCQuery:
    entity_type: str
    operation: str
    model_name: str | None = None
    matched_entities: int = 0
    scope: str = 'uploaded_file'


def identity(value):
    return ' '.join(re.findall(r'\w+', str(value).casefold()))


def prepare(question, drawing, prior_target=None):
    """Return answer or a bounded type-selected catalog for semantic interpretation.

    Unknown modifiers remain in the question. Only a validated model title and
    harmless request grammar can be removed from a deterministic query.
    """
    import ifcopenshell
    from .analysis import TARGETS, question_kind, result, clarify
    from .native import ifc_facts
    model = ifcopenshell.open(str(drawing['path']))
    names = {drawing.get('filename',''),Path(drawing.get('filename','')).stem,
             str(model.header.file_name.name)}
    projects = model.by_type('IfcProject')
    buildings = model.by_type('IfcBuilding')
    # Multiple projects/buildings require explicit submodel selection; a title
    # must never silently turn into a whole-file count.
    if len(projects)==1:names.add(projects[0].Name or '')
    if len(projects)<=1 and len(buildings)==1:names.add(buildings[0].Name or '')
    names = {n for n in names if n.strip()}
    scope = re.search(r'\bmodel\s+(?:(?:named|called|titled)\s+)?[\'"‘“]([^\'"’”]+)[\'"’”]',question,re.I)
    if scope is None:
        scope = re.search(r'\bmodel\s+(?:(?:named|called|titled)\s+)?([^?\n]+?)[?.]?$',question,re.I)
    requested = scope.group(1).strip() if scope else None
    if requested and identity(requested) not in {identity(n) for n in names}:
        return clarify(f'The requested model {requested!r} does not match the selected upload ({drawing.get("filename","IFC file")}). Select that model, or confirm a question about this uploaded file.'),None,question,None
    scoped = question[:scope.start()]+ 'model' + question[scope.end():] if scope else question
    words = set(re.findall(r'[\wäöå]+',scoped.casefold()))
    targets = [t for t,aliases in TARGETS.items() if words.intersection(aliases) and t in {'wall','door','window','space','buildingstorey','slab'}]
    if not targets and re.search(r'\b(its|their|them|those|niiden|niitä)\b',scoped,re.I) and prior_target in TARGETS:
        targets = [prior_target]
    kind = question_kind(scoped)
    if re.search(r'\bnumber\s+of\b',scoped,re.I):kind='count'
    if len(targets)>1:
        return clarify('Choose one IFC element type for a quantity, or ask separate questions for each type.'),None,scoped,None
    if not targets:
        count=len(model.by_type('IfcObject'))
        if count>2500:
            return clarify('Specify the IFC element type and quantity to query (for example, count doors or total wall area). This model is too large for an unfiltered fact extraction.'),None,scoped,None
        return None,ifc_facts(drawing,model=model),scoped,None
    target = targets[0]
    entity_type = {'buildingstorey':'IfcBuildingStorey'}.get(target,'Ifc'+target.title())
    entities = model.by_type(entity_type)
    query = asdict(IFCQuery(entity_type,kind,requested,len(entities)))
    if any(not e.GlobalId for e in entities):
        return abstain(f'The {entity_type} selection includes entities without inspectable GlobalIds; no complete quantity can be supported.', 'ifc_missing_identifiers'),None,scoped,query
    allowed = {'how','many','what','is','the','total','of','their','its','are','there','in','this','that','model',
               'count','area','volume','length','kuinka','monta','montako','on','mikä','niiden','pinta','ala',
               'tilavuus','yhteensä','pituus','could','can','you','please','tell','me','give','number','all',
               'uploaded','file','provided','selected'} | set(TARGETS[target])
    plain = not (words - allowed)
    if kind=='count' and not entities:
        answer=abstain(f'No {entity_type} occurrences are explicitly classified in this upload. This does not establish that the building contains no physical {target}s; verify the export or provide the intended model.', 'ifc_type_absent')
        return answer,None,scoped,query
    # A count needs only occurrence handles, never every property in the file.
    data = ifc_facts(drawing,model=model,entities=entities,include_properties=not (plain and kind=='count'))
    if plain and kind=='count':
        answer=result(len(entities),'count',[o['evidence'] for o in data['objects']],'count',[],target)
        answer['explanation']=f'Counted {len(entities)} {entity_type} occurrences (including subtypes) in the selected uploaded IFC; type definitions and unrelated entities are excluded.'
        return answer,data,scoped,query
    if plain and kind in {'length','area','volume'}:
        # Reuse the strict source-quantity rules, with a canonical local query.
        from .analysis import native_answer
        answer=native_answer(f'{kind} of {TARGETS[target][0]}',drawing,data,target)
        return answer,data,scoped,query
    # Properties remain scoped to this type even when a model must interpret a
    # semantic modifier; never drop the modifier or infer it from the class.
    if len(data['objects'])+len(data['facts'])>2500:
        answer=abstain(f'The {entity_type} selection still exceeds the bounded fact limit. Narrow the IFC selection or ask an unfiltered native count/quantity; this model has no page selection for this query.', 'ifc_query_scope')
        return answer,None,scoped,query
    return None,data,scoped,query
