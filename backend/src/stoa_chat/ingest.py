"""Validate original contents without benchmark metadata or external fetching."""
import math
import re
import struct
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
            width, height = raster_size(format, content)
            if width * height > 80_000_000:
                raise ValueError('Image exceeds 80 million pixels')
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
            binary = content.startswith(b'AutoCAD Binary DXF\r\n\x1a\x00')
            if not binary and not re.search(br'\bEOF\s*$', content):
                raise ValueError('Expected complete DXF contents')
            # ezdxf detects the declared legacy code page (and modern UTF-8).
            # Parse a temporary copy; the original uploaded bytes stay immutable.
            with tempfile.NamedTemporaryFile(suffix='.dxf') as temporary:
                temporary.write(content)
                temporary.flush()
                document = ezdxf.readfile(temporary.name)
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
                    if attr.startswith('on') or attr == 'base':
                        raise ValueError('SVG scripts and event attributes are not permitted')
                    if attr == 'style':
                        validate_svg_style(value)
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
            else:
                width, height = svg_length(root.get('width', '')), svg_length(root.get('height', ''))
                if width is not None and height is not None:
                    pages = [{'page': 1, 'width': width, 'height': height, 'origin': [0, 0], 'units': 'svg'}]
        return {'format': format, 'media_type': media[format], 'pages': pages, 'entity_ids': entities}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Invalid {format.upper()} drawing') from exc


def validate_svg_style(value):
    """Permit static presentation declarations without executable/resource CSS."""
    value = re.sub(r'/\*.*?\*/', '', value, flags=re.S)
    if re.search(r'[\\@<>]|expression|javascript|vbscript|behavior|binding', value, re.I):
        raise ValueError('Active SVG CSS is not permitted')
    allowed = {'fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width', 'stroke-opacity',
               'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit', 'stroke-dasharray',
               'stroke-dashoffset', 'opacity', 'color', 'font', 'font-family', 'font-size',
               'font-style', 'font-weight', 'font-variant', 'letter-spacing', 'word-spacing',
               'text-anchor', 'text-decoration', 'dominant-baseline', 'alignment-baseline',
               'display', 'visibility', 'vector-effect', 'paint-order', 'shape-rendering',
               'text-rendering', 'color-rendering', 'image-rendering', 'clip-path',
               'clip-rule', 'mask', 'filter', 'stop-color', 'stop-opacity', 'overflow'}
    for declaration in value.split(';'):
        if not declaration.strip():
            continue
        name, separator, contents = declaration.partition(':')
        if not separator or name.strip().lower() not in allowed:
            raise ValueError('Unsupported SVG CSS property')
        for target in re.findall(r'url\s*\((.*?)\)', contents, re.I):
            if not target.strip(' \t\"\'').startswith('#'):
                raise ValueError('SVG external CSS resources are not permitted')


def svg_length(value):
    match = re.fullmatch(r'\s*([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(px|pt|pc|in|cm|mm|q)?\s*', value)
    if not match:
        return None
    factors = {'px': 1, 'pt': 96 / 72, 'pc': 16, 'in': 96, 'cm': 96 / 2.54, 'mm': 96 / 25.4, 'q': 96 / 101.6}
    result = float(match[1]) * factors.get(match[2], 1)
    return result if math.isfinite(result) and result > 0 else None


def raster_size(format, content):
    """Read allocation dimensions from PNG IHDR / JPEG SOF before decoding pixels."""
    if format == 'png':
        if len(content) < 33 or content[12:16] != b'IHDR':
            raise ValueError('Missing PNG image header')
        width, height = struct.unpack('>II', content[16:24])
        if not width or not height:
            raise ValueError('Invalid image dimensions')
        return width, height
    position = 2
    frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while position < len(content):
        if content[position] != 0xFF:
            break
        while position < len(content) and content[position] == 0xFF:
            position += 1
        if position >= len(content):
            break
        marker = content[position]
        position += 1
        if marker in {0xD9, 0xDA}:
            break
        if marker in {0x01, 0xD8} or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(content):
            break
        length = int.from_bytes(content[position:position + 2], 'big')
        if length < 2 or position + length > len(content):
            break
        if marker in frame_markers and length >= 8:
            height, width = struct.unpack('>HH', content[position + 3:position + 7])
            if not width or not height:
                raise ValueError('Invalid image dimensions')
            return width, height
        position += length
    raise ValueError('Missing JPEG image frame header')
