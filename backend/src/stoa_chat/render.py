"""Bounded raster previews and explicit preview-pixel → source transforms."""
import cv2
import numpy as np
import pymupdf


MAX_SIDE = 1600
MAX_PAGES = 12


def preview(drawing, page=1):
    metadata = next((p for p in drawing['pages'] if p['page'] == page), None)
    if metadata is None:
        raise ValueError('Source page does not exist')
    format = drawing['format']
    if format in {'png', 'jpeg'}:
        image = cv2.imdecode(np.frombuffer(drawing['path'].read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    elif format in {'pdf', 'svg'}:
        # SVG was validated during ingest. MuPDF rasterizes without browser scripts
        # or network resource resolution; uploaded SVG never enters the DOM.
        content=drawing['path'].read_bytes()
        if format=='svg':
            import xml.etree.ElementTree as ET
            root=ET.fromstring(content)
            # Canonical viewport removes root sheet aspect-ratio letterboxing;
            # all evidence stays in the original viewBox/user coordinate frame.
            root.set('width',str(metadata['width']))
            root.set('height',str(metadata['height']))
            content=ET.tostring(root)
        document = pymupdf.open(stream=content, filetype=format)
        if format == 'svg':
            converted = pymupdf.open('pdf', document.convert_to_pdf())
            document.close()
            document = converted
        with document:
            source = document[page - 1]
            factor = min(2, MAX_SIDE / max(source.rect.width, source.rect.height))
            pixmap = source.get_pixmap(matrix=pymupdf.Matrix(factor, factor), alpha=False)
            image = cv2.imdecode(np.frombuffer(pixmap.tobytes('png'), dtype=np.uint8), cv2.IMREAD_COLOR)
    else:
        raise ValueError('No spatial preview available; inspect original native entities')
    if image is None:
        raise ValueError('Cannot decode preview')
    height, width = image.shape[:2]
    factor = min(1, MAX_SIDE / max(width, height))
    if factor < 1:
        image = cv2.resize(image, (max(1, round(width * factor)), max(1, round(height * factor))))
    height, width = image.shape[:2]
    origin = metadata.get('origin', [0, 0])
    descriptor = {'id': drawing['id'] + ':' + str(page), 'drawing_id': drawing['id'], 'page': page,
                  'width': width, 'height': height, 'source_width': metadata['width'], 'source_height': metadata['height'],
                  'source_origin': origin, 'source_units': metadata['units'],
                  'transform': [metadata['width'] / width, 0, 0, metadata['height'] / height, *origin],
                  'original_url': drawing['asset_url'], 'preview_url': drawing['asset_url'].replace('/assets/', '/previews/') + '/' + str(page)}
    return cv2.imencode('.png', image)[1].tobytes(), descriptor
