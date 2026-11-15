"""Bounded raster previews and explicit preview-pixel → source transforms."""
import cv2
import numpy as np
import pymupdf


MAX_SIDE = 1600
MAX_PAGES = 12
# One full view for raster questions. The model downsamples internally (about 3.4k prompt
# tokens for both 2480- and 3000-pixel sheets), so sending more pixels buys nothing.
SINGLE_VIEW_MAX_SIDE = 3000
# Count questions on rasters smaller than COUNT_MIN_SIDE: windows and doors in a 500-pixel plan
# are a few pixels thick, and asked about the whole sheet the model guesses positions from the
# layout. The sheet is enlarged (cubic, at most MAX_UPSCALE times) to about COUNT_TILED_SIDE and
# read as overlapping TILE_SIDE crops (up to 3x3; 2600 measured better than 2400 or 3000 on
# small CubiCasa plans); transforms still map to source pixels.
COUNT_MIN_SIDE = 1600
COUNT_TILED_SIDE = 2600
MAX_UPSCALE = 6


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


def raster_views(drawing, page=1, scale=1):
    """Overview plus lossless source-pixel crops with nonoverlapping ownership cores.

    scale > 1 first enlarges a small raster (cubic) so its symbols span enough pixels; crops
    are then cut from the enlargement and the transforms still map to source pixels."""
    if drawing['format'] not in {'png','jpeg'}:
        raise ValueError('Detailed raster views require a PNG or JPEG upload')
    metadata=next(p for p in drawing['pages'] if p['page']==page)
    image=raster_image(drawing)
    if scale>1:
        image=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale)),interpolation=cv2.INTER_CUBIC)
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
    return views+_detail_tiles(image,base,drawing,page,metadata['width']/width,metadata['height']/height,ox,oy)


def _detail_tiles(image,base,drawing,page,sx,sy,ox,oy):
    """Overlapping crops of an image whose pixel (x, y) is source point (ox + x*sx, oy + y*sy)."""
    height,width=image.shape[:2]
    xs,ys=tile_axes(width),tile_axes(height)
    views=[]
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


def vector_count_views(drawing, page=1):
    """Enlarged crops of the drawn region of a vector PDF page, for count questions.

    A whole A3 sheet at 1600 pixels leaves the plan under half the frame and door swings a few
    pixels wide. The region holding the plan (the main block of vector paths, see
    vector_counts.content_region) is rendered at about COUNT_TILED_SIDE pixels and cut into the
    same overlapping tiles as small rasters; transforms map tile pixels to page points.
    Returns None when the page has no compact vector region worth enlarging."""
    from .vector_counts import content_region
    if drawing['format'] != 'pdf':
        return None
    metadata = next(p for p in drawing['pages'] if p['page'] == page)
    with pymupdf.open(drawing['path']) as document:
        source = document[page - 1]
        if source.rotation:
            return None
        region = content_region(source)
        if region is None:
            return None
        zoom = min(MAX_UPSCALE * 2, COUNT_TILED_SIDE / max(region.width, region.height))
        if zoom < 1.5 * min(2, MAX_SIDE / max(source.rect.width, source.rect.height)):
            return None   # the normal preview already shows the region nearly this large
        pixmap = source.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=region, alpha=False)
        image = cv2.imdecode(np.frombuffer(pixmap.tobytes('png'), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    sx, sy = region.width / width, region.height / height
    base = {'drawing_id': drawing['id'], 'page': page, 'source_width': metadata['width'], 'source_height': metadata['height'],
            'source_origin': [0, 0], 'source_units': metadata['units'], 'original_url': drawing['asset_url'],
            'preview_url': drawing['asset_url'].replace('/assets/', '/previews/') + '/' + str(page)}
    if max(width, height) <= MAX_SIDE:
        descriptor = {**base, 'id': f'{drawing["id"]}:{page}:region', 'width': width, 'height': height,
                      'transform': [sx, 0, 0, sy, region.x0, region.y0], 'role': 'page',
                      'source_bbox': [region.x0, region.y0, region.x1, region.y1]}
        return [(cv2.imencode('.png', image)[1].tobytes(), descriptor)], zoom, [region.x0, region.y0, region.x1, region.y1]
    tiles = _detail_tiles(image, base, drawing, page, sx, sy, region.x0, region.y0)
    return tiles, zoom, [region.x0, region.y0, region.x1, region.y1]
