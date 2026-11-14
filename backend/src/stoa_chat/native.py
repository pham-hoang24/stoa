"""Source facts for application drawings; no benchmark or export-specific rules."""
import math


def ifc_unit_scale(unit, kind):
    """Resolve dimensional source units, including quantity overrides, to SI."""
    import ifcopenshell.util.unit as units
    expected = {'length':'LENGTHUNIT','area':'AREAUNIT','volume':'VOLUMEUNIT'}[kind]
    if unit is None or getattr(unit,'UnitType',None) != expected:
        return None
    if unit.is_a('IfcSIUnit'):
        names = {'length':'METRE','area':'SQUARE_METRE','volume':'CUBIC_METRE'}
        if unit.Name != names[kind]:
            return None
        return units.get_prefix_multiplier(unit.Prefix) ** {'length':1,'area':2,'volume':3}[kind]
    if unit.is_a('IfcConversionBasedUnit') and not unit.is_a('IfcConversionBasedUnitWithOffset'):
        factor=ifc_unit_scale(unit.ConversionFactor.UnitComponent,kind)
        if factor is not None:
            return unit.ConversionFactor.ValueComponent.wrappedValue*factor
    return None


def ifc_facts(drawing):
    import ifcopenshell
    import ifcopenshell.util.element as element
    model = ifcopenshell.open(str(drawing['path']))
    assignments = [p.UnitsInContext for p in model.by_type('IfcProject') if p.UnitsInContext]
    assigned = {u.UnitType:u for a in assignments for u in a.Units if hasattr(u,'UnitType')}
    dimensional = {'IfcQuantityLength':'length','IfcQuantityArea':'area','IfcQuantityVolume':'volume',
                   'IfcLengthMeasure':'length','IfcPositiveLengthMeasure':'length','IfcAreaMeasure':'area','IfcVolumeMeasure':'volume'}
    families = ['IfcWall','IfcDoor','IfcWindow','IfcSpace','IfcBuildingStorey','IfcSlab']
    facts, objects = [], []
    for entity in model.by_type('IfcObject'):
        if not entity.GlobalId:
            continue
        evidence = {'drawing_id':drawing['id'],'entity_id':entity.GlobalId,'global_id':entity.GlobalId,
                    'native_type':entity.is_a(),'details':{'Name':entity.Name,'Description':entity.Description}}
        obj = {'id':entity.GlobalId,'type':entity.is_a(),'families':[t.lower() for t in families if entity.is_a(t)],
               'label':entity.Name or '', 'evidence':evidence,'quantities':{}}
        objects.append(obj)
        for attribute in ('Name','Description','ObjectType'):
            value=getattr(entity,attribute,None)
            if value:
                facts.append({'id':entity.GlobalId+':'+attribute,'label':entity.is_a()+' '+attribute,'kind':'text','value':value,'unit':None,'evidence':{**evidence,'property':attribute,'source_value':value}})
        for group, properties in element.get_psets(entity,verbose=True).items():
            for name, info in properties.items():
                if name=='id' or not isinstance(info,dict) or not info.get('id'):
                    continue
                source=model.by_id(info['id'])
                value=info.get('value')
                if not isinstance(value,(str,int,float)) or isinstance(value,bool):
                    continue
                measure=getattr(source,'NominalValue',None)
                quantity=dimensional.get(measure.is_a() if measure is not None else source.is_a(),'text')
                if quantity!='text':
                    assigned_type={'length':'LENGTHUNIT','area':'AREAUNIT','volume':'VOLUMEUNIT'}[quantity]
                    unit=getattr(source,'Unit',None) or assigned.get(assigned_type)
                    scale=ifc_unit_scale(unit,quantity)
                    if scale is None or type(value) not in {int,float}:
                        continue
                    value *= scale
                    if not math.isfinite(value) or value<0:
                        continue
                ref=entity.GlobalId+':'+group+'.'+name
                fact={'id':ref,'label':f'{obj["label"]} {group}.{name}','kind':quantity,'role':name.lower(),
                      'value':value,'unit':{'area':'m²','volume':'m³','length':'m'}.get(quantity),
                      'evidence':{**evidence,'property':group+'.'+name,'source_value':info['value'],'source_entity_id':source.id()}}
                facts.append(fact)
                obj['quantities'].setdefault(quantity,[]).append(fact)
    return {'objects':objects,'facts':facts,'complete':True}


def inventory(drawing):
    if drawing['format'] == 'ifc':
        return ifc_facts(drawing)
    if drawing['format'] == 'dxf':
        return dxf_facts(drawing)
    if drawing['format'] == 'pdf':
        return pdf_facts(drawing)
    if drawing['format'] == 'svg':
        return svg_facts(drawing)
    return {'objects': [], 'facts': [], 'complete': False}


def dxf_facts(drawing):
    import ezdxf
    from ezdxf import units
    document = ezdxf.readfile(drawing['path'])
    code = document.header.get('$INSUNITS', 0)
    try:
        scale = units.conversion_factor(code, units.M) if code else None
    except (ValueError, TypeError):
        scale = None
    objects, facts = [], []
    for entity in document.modelspace():
        kind = entity.dxftype()
        evidence = {'drawing_id':drawing['id'], 'entity_id':entity.dxf.handle, 'entity_handle':entity.dxf.handle,
                    'native_type':kind, 'details':{'layer':entity.dxf.layer, 'insunits':code}}
        obj = {'id':entity.dxf.handle,'type':kind,'label':entity.dxf.layer,'evidence':evidence,'quantities':{}}
        objects.append(obj)
        values = {}
        if kind == 'LINE':
            values['length'] = (entity.dxf.end - entity.dxf.start).magnitude
            evidence['details'].update(start=list(entity.dxf.start), end=list(entity.dxf.end))
        elif kind == 'CIRCLE':
            values = {'length':2*math.pi*entity.dxf.radius, 'area':math.pi*entity.dxf.radius**2}
            evidence['details'].update(center=list(entity.dxf.center), radius=entity.dxf.radius)
        elif kind == 'LWPOLYLINE' and not any(p[4] for p in entity.get_points()):
            points = [(p[0],p[1]) for p in entity.get_points()]
            if len(points) >= 2:
                from shapely.geometry import Polygon, LineString
                boundary = points + [points[0]] if entity.closed else points
                values['length'] = LineString(boundary).length
                if entity.closed and Polygon(points).is_valid:
                    values['area'] = Polygon(points).area
                evidence['details']['points'] = points
        elif kind == 'INSERT':
            evidence['details'].update(block_name=entity.dxf.name, insertion=list(entity.dxf.insert))
            obj['label']=entity.dxf.name+' '+entity.dxf.layer
        elif kind in {'TEXT','MTEXT'}:
            text = entity.dxf.text if kind == 'TEXT' else entity.plain_text()
            facts.append({'id':obj['id']+':text','label':obj['label'],'kind':'text','value':text,'unit':None,'evidence':evidence})
        for quantity,value in values.items():
            if scale is None:
                continue
            value *= scale ** (2 if quantity == 'area' else 1)
            fact = {'id':obj['id']+':'+quantity,'label':f'{kind} {entity.dxf.layer}', 'kind':quantity,'value':value,
                    'unit':'m²' if quantity == 'area' else 'm', 'evidence':{**evidence,'property':quantity,'source_value':value / scale ** (2 if quantity=='area' else 1)}}
            facts.append(fact)
            obj['quantities'][quantity] = [fact]
    return {'objects':objects,'facts':facts,'complete':True}


def page_evidence(drawing, page, box=None):
    p = next(p for p in drawing['pages'] if p['page'] == page)
    evidence = {'drawing_id':drawing['id'],'page':page,'source_width':p['width'],'source_height':p['height'],
                'source_origin':p.get('origin',[0,0]), 'source_units':p['units'], 'original_url':drawing['asset_url'],
                'preview_url':drawing['asset_url'].replace('/assets/','/previews/')+'/'+str(page)}
    if box:
        evidence['bbox'] = list(box)
    return evidence


def pdf_facts(drawing):
    import pymupdf
    import re
    facts = []
    with pymupdf.open(drawing['path']) as doc:
        for number, page in enumerate(doc):
            for index, block in enumerate(page.get_text('blocks')):
                text = block[4].strip()
                if not text:
                    continue
                # Text layer regions can extend slightly beyond the crop box.
                box = [max(0,block[0]),max(0,block[1]),min(page.rect.width,block[2]),min(page.rect.height,block[3])]
                if box[0] >= box[2] or box[1] >= box[3]:
                    continue
                ev = page_evidence(drawing,number+1,box)
                ref = f'page:{number+1}:block:{index}'
                facts.append({'id':ref,'label':text,'kind':'text','value':text,'unit':None,'evidence':ev})
                for match in re.finditer(r'(\d+(?:[.,]\d+)?)\s*(m²|m2|m³|m3|mm|cm|m)\b',text):
                    value,unit = match.groups()
                    kind = 'area' if unit in {'m²','m2'} else 'volume' if unit in {'m³','m3'} else 'length'
                    facts.append({'id':ref+':quantity:'+str(match.start()),'label':text,'kind':kind,'value':float(value.replace(',','.')),
                                  'unit':{'m2':'m²','m3':'m³'}.get(unit,unit),'evidence':{**ev,'property':'printed_text','source_value':match.group()}})
    return {'objects':[],'facts':facts,'complete':True}


def svg_facts(drawing):
    import re
    import xml.etree.ElementTree as ET
    root = ET.fromstring(drawing['path'].read_bytes())
    facts, objects = [], []
    scale = None
    # Physical root sizes describe the printed sheet, not building calibration.
    # An explicit source model calibration is metres per viewBox/user unit.
    try:
        supplied=float(root.get('data-metres-per-unit','nan'))
        if math.isfinite(supplied) and supplied>0:
            scale=supplied
    except ValueError:
        pass
    # Transform hierarchies, use references and styled text are left to rendering.
    geometry_safe = not any(n.get('transform') or n.tag.split('}')[-1] == 'use' for n in root.iter())
    for index,node in enumerate(root.iter()):
        tag = node.tag.split('}')[-1]
        entity = node.get('id')
        if tag in {'text','tspan'} and drawing['pages']:
            text = ''.join(node.itertext()).strip()
            if text:
                ev = page_evidence(drawing,1)
                if entity:
                    ev['entity_id'] = entity
                facts.append({'id':f'svg:{index}:text','label':text,'kind':'text','value':text,'unit':None,'evidence':ev})
        if not entity or tag not in {'rect','line','circle','polygon','polyline'}:
            continue
        ev = {'drawing_id':drawing['id'],'entity_id':entity,'native_type':tag,'details':dict(node.attrib)}
        if drawing['pages']:
            ev.update(page_evidence(drawing,1))
        obj = {'id':entity,'type':tag,'label':entity,'evidence':ev,'quantities':{}}
        objects.append(obj)
        values = {}
        try:
            if tag == 'rect':
                w,h = float(node.get('width')),float(node.get('height'))
                values = {'area':w*h,'length':2*(w+h)}
            elif tag == 'circle':
                radius = float(node.get('r'))
                values = {'area':math.pi*radius**2,'length':2*math.pi*radius}
            elif tag == 'line':
                values['length'] = math.hypot(float(node.get('x2','0'))-float(node.get('x1','0')),float(node.get('y2','0'))-float(node.get('y1','0')))
            elif tag in {'polygon','polyline'}:
                from shapely.geometry import Polygon, LineString
                coords = list(map(float,re.split(r'[ ,\s]+',node.get('points','').strip())))
                points = list(zip(coords[::2],coords[1::2]))
                if tag == 'polygon' and Polygon(points).is_valid:
                    values['area'] = Polygon(points).area
                    points += [points[0]]
                values['length'] = LineString(points).length
        except (ValueError,TypeError):
            pass
        for kind,value in values.items():
            if not geometry_safe or scale is None or not math.isfinite(value) or value < 0:
                continue
            fact = {'id':entity+':'+kind,'label':entity,'kind':kind,'value':value*scale**(2 if kind=='area' else 1),
                    'unit':'m²' if kind=='area' else 'm','evidence':{**ev,'property':kind,'source_value':value,'metres_per_source_unit':scale}}
            facts.append(fact)
            obj['quantities'][kind] = [fact]
    return {'objects':objects,'facts':facts,'complete':geometry_safe and all(n.get('id') for n in root.iter() if n.tag.split('}')[-1] in {'rect','line','circle','polygon','polyline'})}
