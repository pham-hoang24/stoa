"""Bounded raster previews and explicit preview-pixel → source transforms."""
import cv2
import numpy as np
import pymupdf


MAX_SIDE = 1600
MAX_PAGES = 12
# One full view for raster questions. The model downsamples internally (about 3.4k prompt
# tokens for both 2480- and 3000-pixel sheets), so sending more pixels buys nothing.
SINGLE_VIEW_MAX_SIDE = 3000


def raster_image(drawing):
    image = cv2.imdecode(np.frombuffer(drawing['path'].read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    # UNCHANGED preserves the uploaded source frame (including JPEG EXIF),
    # alpha and bit depth. Normalize before compositing on a white sheet.
    if image is not None:
        if image.dtype == np.uint16:
            image = (image / 257).round().astype(np.uint8)
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            alpha = image[:, :, 3:4].astype(np.float32) / 255
            image = (image[:, :, :3] * alpha + 255 * (1 - alpha)).round().astype(np.uint8)
    if image is None:
        raise ValueError('Cannot decode preview')
    return image


def preview(drawing, page=1, max_side=MAX_SIDE):
    metadata = next((p for p in drawing['pages'] if p['page'] == page), None)
    if metadata is None:
        raise ValueError('Source page does not exist')
    format = drawing['format']
    if format in {'png', 'jpeg'}:
        image = raster_image(drawing)
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
    factor = min(1, max_side / max(width, height))
    if factor < 1:
        image = cv2.resize(image, (max(1, round(width * factor)), max(1, round(height * factor))))
    height, width = image.shape[:2]
    origin = metadata.get('origin', [0, 0])
    descriptor = {'id': drawing['id'] + ':' + str(page), 'drawing_id': drawing['id'], 'page': page,
                  'width': width, 'height': height, 'source_width': metadata['width'], 'source_height': metadata['height'],
                  'source_origin': origin, 'source_units': metadata['units'],
                  'transform': [metadata['width'] / width, 0, 0, metadata['height'] / height, *origin],
                  'original_url': drawing['asset_url'], 'preview_url': drawing['asset_url'].replace('/assets/', '/previews/') + '/' + str(page)}
    if format == 'jpeg' and max_side > MAX_SIDE:
        # A large photographic scan re-encoded as PNG can exceed provider request limits.
        return cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes(), descriptor
    return cv2.imencode('.png', image)[1].tobytes(), descriptor


TILE_SIDE = 1400
TILE_OVERLAP = .2
MAX_DETAIL_VIEWS = 64


def tile_axes(length):
    """Partial edge tiles retain fixed overlap instead of shrinking the source."""
    import math
    stride=round(TILE_SIDE*(1-TILE_OVERLAP))
    return [i*stride for i in range(max(1,math.ceil((length-TILE_SIDE)/stride)+1))]


def raster_views(drawing, page=1):
    """Overview plus lossless source-pixel crops with nonoverlapping ownership cores."""
    if drawing['format'] not in {'png','jpeg'}:
        raise ValueError('Detailed raster views require a PNG or JPEG upload')
    metadata=next(p for p in drawing['pages'] if p['page']==page)
    image=raster_image(drawing)
    height,width=image.shape[:2]
    tiled=max(width,height)>MAX_SIDE
    xs,ys=tile_axes(width),tile_axes(height)
    if tiled and len(xs)*len(ys)>MAX_DETAIL_VIEWS:
        raise ValueError(f'Image requires {len(xs)*len(ys)} detail regions; maximum is {MAX_DETAIL_VIEWS}. Select a smaller image scope.')
    factor=min(1,MAX_SIDE/max(width,height))
    overview=cv2.resize(image,(max(1,round(width*factor)),max(1,round(height*factor)))) if factor<1 else image
    oh,ow=overview.shape[:2]
    ox,oy=metadata.get('origin',[0,0])
    base={'drawing_id':drawing['id'],'page':page,'source_width':metadata['width'],'source_height':metadata['height'],
          'source_origin':[ox,oy],'source_units':metadata['units'],'original_url':drawing['asset_url'],
          'preview_url':drawing['asset_url'].replace('/assets/','/previews/')+'/'+str(page)}
    overview_descriptor={**base,'id':drawing['id']+':'+str(page),'width':ow,'height':oh,
                         'transform':[metadata['width']/ow,0,0,metadata['height']/oh,ox,oy],
                         'role':'overview' if tiled else 'page'}
    views=[(cv2.imencode('.png',overview)[1].tobytes(),overview_descriptor)]
    if not tiled:return views
    sx,sy=metadata['width']/width,metadata['height']/height
    for row,y in enumerate(ys):
        for col,x in enumerate(xs):
            x1,y1=min(x+TILE_SIDE,width),min(y+TILE_SIDE,height)
            left=0 if col==0 else (min(xs[col-1]+TILE_SIDE,width)+x)/2-x
            right=x1-x if col==len(xs)-1 else (x1+xs[col+1])/2-x
            top=0 if row==0 else (min(ys[row-1]+TILE_SIDE,height)+y)/2-y
            bottom=y1-y if row==len(ys)-1 else (y1+ys[row+1])/2-y
            descriptor={**base,'id':f'{drawing["id"]}:{page}:tile:{row}:{col}','width':x1-x,'height':y1-y,
                        'transform':[sx,0,0,sy,ox+x*sx,oy+y*sy],'role':'detail',
                        'source_bbox':[ox+x*sx,oy+y*sy,ox+x1*sx,oy+y1*sy],
                        'core_bbox':[left,top,right,bottom]}
            views.append((cv2.imencode('.png',image[y:y1,x:x1])[1].tobytes(),descriptor))
    return views
