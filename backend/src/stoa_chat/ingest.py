"""Validate original contents without benchmark metadata or external fetching."""
import io
import math
import re
import tempfile
import xml.etree.ElementTree as ET

import cv2
import ezdxf
import ifcopenshell
import numpy as np
import pymupdf


def inspect_upload(filename, content):
    extension = filename.rsplit('.', 1)[-1].lower()
    format = {'jpg': 'jpeg', 'jpeg': 'jpeg'}.get(extension, extension)
    media = {'png': 'image/png', 'jpeg': 'image/jpeg', 'pdf': 'application/pdf',
             'ifc': 'application/x-step', 'dxf': 'application/dxf', 'svg': 'image/svg+xml'}
    if format not in media:
        raise ValueError('Supported drawings: PNG, JPEG, PDF, IFC, DXF and SVG')
    try:
        pages, entities = [], []
        if format in {'png', 'jpeg'}:
            signature = b'\x89PNG\r\n\x1a\n' if format == 'png' else b'\xff\xd8\xff'
            if not content.startswith(signature):
                raise ValueError('Image contents do not match the filename extension')
            image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ValueError('Cannot decode image')
            height, width = image.shape[:2]
            if width * height > 80_000_000:
                raise ValueError('Image exceeds 80 million pixels')
            pages = [{'page': 1, 'width': width, 'height': height, 'units': 'pixel'}]
        elif format == 'pdf':
            if not content.startswith(b'%PDF-'):
                raise ValueError('Expected PDF contents')
            with pymupdf.open(stream=content, filetype='pdf') as document:
                if document.needs_pass or not document.page_count or document.page_count > 1000:
                    raise ValueError('PDF must have 1–1000 accessible pages without a password')
                pages = [{'page': i + 1, 'width': p.rect.width, 'height': p.rect.height, 'units': 'point'} for i, p in enumerate(document)]
        elif format == 'ifc':
            text = content.decode('utf-8-sig')
            if not text.lstrip().startswith('ISO-10303-21;') or 'END-ISO-10303-21;' not in text:
                raise ValueError('Expected complete IFC STEP contents')
            model = ifcopenshell.file.from_string(text)
            if not list(model):
                raise ValueError('IFC has no entities')
            entities = [e.GlobalId for e in model.by_type('IfcRoot') if e.GlobalId]
        elif format == 'dxf':
            if content.startswith(b'AutoCAD Binary DXF\r\n\x1a\x00'):
                with tempfile.NamedTemporaryFile(suffix='.dxf') as temporary:
                    temporary.write(content)
                    temporary.flush()
                    document = ezdxf.readfile(temporary.name)
            else:
                text = content.decode('utf-8-sig')
                if not re.search(r'\bEOF\s*$', text):
                    raise ValueError('Expected complete DXF contents')
                document = ezdxf.read(io.StringIO(text))
            entities = [e.dxf.handle for e in document.modelspace()]
        elif format == 'svg':
            if re.search(br'<!\s*(DOCTYPE|ENTITY)', content, re.I):
                raise ValueError('SVG declarations and entities are not permitted')
            root = ET.fromstring(content)
            if root.tag != '{http://www.w3.org/2000/svg}svg':
                raise ValueError('Expected an SVG root in the SVG namespace')
            allowed = {'svg', 'g', 'defs', 'title', 'desc', 'path', 'rect', 'circle', 'ellipse', 'line',
                       'polyline', 'polygon', 'text', 'tspan', 'use', 'symbol', 'clipPath', 'mask',
                       'linearGradient', 'radialGradient', 'stop', 'pattern'}
            for node in root.iter():
                if node.tag.split('}')[-1] not in allowed:
                    raise ValueError('Unsupported or active SVG element')
                for key, value in node.attrib.items():
                    attr = key.split('}')[-1].lower()
                    if attr.startswith('on') or attr in {'base', 'style'}:
                        raise ValueError('SVG scripts, style and event attributes are not permitted')
                    if attr == 'href' and not value.startswith('#'):
                        raise ValueError('SVG external resources are not permitted')
                    for target in re.findall(r'url\s*\((.*?)\)', value, re.I):
                        if not target.strip(' \t\"\'').startswith('#'):
                            raise ValueError('SVG external resources are not permitted')
                if 'id' in node.attrib:
                    entities.append(node.attrib['id'])
            box = root.get('viewBox')
            if box:
                x, y, width, height = map(float, box.replace(',', ' ').split())
                if not all(math.isfinite(n) for n in (x, y, width, height)) or width <= 0 or height <= 0:
                    raise ValueError('Invalid SVG viewBox')
                pages = [{'page': 1, 'width': width, 'height': height, 'origin': [x, y], 'units': 'svg'}]
        return {'format': format, 'media_type': media[format], 'pages': pages, 'entity_ids': entities}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Invalid {format.upper()} drawing') from exc
