"""Source facts for application drawings; no benchmark or export-specific rules."""
import math


def ifc_facts(drawing):
    import ifcopenshell
    import ifcopenshell.util.element as element
    import ifcopenshell.util.unit as units
    model = ifcopenshell.open(str(drawing['path']))
    # IFC defaults to SI when no unit assignment is supplied.
    scale = units.calculate_unit_scale(model)
    facts, objects = [], []
    for entity in model.by_type('IfcObject'):
        if not entity.GlobalId:
            continue
        evidence = {'drawing_id': drawing['id'], 'entity_id': entity.GlobalId,
                    'global_id': entity.GlobalId, 'native_type': entity.is_a(),
                    'details': {'Name': entity.Name, 'Description': entity.Description}}
        obj = {'id': entity.GlobalId, 'type': entity.is_a(), 'label': entity.Name or '', 'evidence': evidence, 'quantities': {}}
        objects.append(obj)
        for group, properties in element.get_psets(entity).items():
            for name, value in properties.items():
                if name == 'id' or not isinstance(value, (str, int, float)) or isinstance(value, bool):
                    continue
                quantity = ('area' if 'area' in name.lower() else 'volume' if 'volume' in name.lower()
                            else 'length' if any(s in name.lower() for s in ('length', 'height', 'width', 'perimeter')) else 'text')
                power = {'area': 2, 'volume': 3, 'length': 1}.get(quantity, 0)
                if power and isinstance(value, (int, float)):
                    value *= scale ** power
                    if not math.isfinite(value):
                        continue
                else:
                    quantity = 'text'
                ref = entity.GlobalId + ':' + group + '.' + name
                fact = {'id': ref, 'label': f'{obj["label"]} {group}.{name}', 'kind': quantity,
                        'value': value, 'unit': {'area': 'm²', 'volume': 'm³', 'length': 'm'}.get(quantity),
                        'evidence': {**evidence, 'property': group + '.' + name, 'source_value': properties[name]}}
                facts.append(fact)
                obj['quantities'].setdefault(quantity, []).append(fact)
    return {'objects': objects, 'facts': facts, 'complete': True}


def inventory(drawing):
    if drawing['format'] == 'ifc':
        return ifc_facts(drawing)
    return {'objects': [], 'facts': [], 'complete': False}
