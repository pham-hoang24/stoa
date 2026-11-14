import math
from types import SimpleNamespace
import cv2,numpy as np,pytest
from stoa_chat import ocr

HEADER='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
ROW='5\t1\t1\t1\t1\t1\t2\t3\t10\t8\t91.5\t12,5\n'

@pytest.fixture
def image():return cv2.imencode('.png',np.full((20,40,3),255,np.uint8))[1].tobytes()

@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(ocr.shutil,'which',lambda *a:'/controlled/tesseract')
    state=SimpleNamespace(fail=None,mode=None,tsv=HEADER+ROW,calls=[])
    def run(args,**kwargs):
        state.calls.append((args,kwargs))
        phase='version' if '--version' in args else 'languages' if '--list-langs' in args else 'ocr'
        if phase==state.fail:
            if state.mode=='timeout':raise ocr.subprocess.TimeoutExpired(args,1)
            if state.mode=='oserror':raise OSError('engine unavailable')
            return SimpleNamespace(returncode=1,stdout='' if kwargs.get('text') else b'',stderr='engine failed' if kwargs.get('text') else b'engine failed')
        out='tesseract 5.5.3\n' if phase=='version' else 'List of available languages (2):\neng\nfin\n' if phase=='languages' else state.tsv
        return SimpleNamespace(returncode=0,stdout=out if kwargs.get('text') or isinstance(out,bytes) else out.encode(),stderr='' if kwargs.get('text') else b'')
    monkeypatch.setattr(ocr.subprocess,'run',run)
    return state

@pytest.mark.parametrize('phase',['version','languages','ocr'])
@pytest.mark.parametrize('mode',['timeout','oserror','exit'])
def test_engine_failures_are_explicit_unavailability(image,engine,phase,mode):
    engine.fail=phase;engine.mode=mode
    with pytest.raises(ocr.OcrUnavailable):ocr.extract_text(image)

def test_all_process_calls_have_finite_timeout(image,engine):
    assert ocr.extract_text(image)[0]['text']=='12,5'
    assert len(engine.calls)==3
    assert all(isinstance(k.get('timeout'),(int,float)) and 0<k['timeout']<math.inf for a,k in engine.calls)

@pytest.mark.parametrize('bad',[b'',b'not an image'])
def test_invalid_input_is_valueerror_even_without_engine(bad,monkeypatch):
    monkeypatch.setattr(ocr.shutil,'which',lambda *a:None)
    with pytest.raises(ValueError,match='image'):ocr.extract_text(bad)

@pytest.mark.parametrize('tsv',['',HEADER+ROW.replace('\t2\t3\t10\t8\t','\t-1\t3\t10\t8\t'),
    HEADER+ROW.replace('\t2\t3\t10\t8\t','\t35\t3\t10\t8\t'),
    HEADER+ROW.replace('\t10\t8\t','\t0\t8\t'),HEADER+ROW.replace('91.5','nan'),HEADER+ROW.replace('91.5','101'),(HEADER+ROW).encode().replace(b'12,5',b'\xff')])
def test_engine_output_must_be_json_ready_and_in_input_frame(image,engine,tsv):
    engine.tsv=tsv
    with pytest.raises(ocr.OcrUnavailable):ocr.extract_text(image)

def test_valid_blank_and_unknown_confidence_stay_distinct(image,engine):
    engine.tsv=HEADER
    assert ocr.extract_text(image)==[]
    engine.tsv=HEADER+ROW.replace('91.5','-1')
    token=ocr.extract_text(image)[0]
    assert token['confidence'] is None and token['text']=='12,5' and token['bbox']==[2,3,12,11]


def test_actual_hung_process_is_terminated(image,monkeypatch,tmp_path):
    import sys,time
    exe=tmp_path/'tesseract'
    exe.write_text(f'#!{sys.executable}\nimport time\ntime.sleep(10)\n')
    exe.chmod(0o755)
    monkeypatch.setattr(ocr.shutil,'which',lambda *a:str(exe))
    monkeypatch.setattr(ocr,'PROBE_TIMEOUT_SECONDS',.05)
    start=time.monotonic()
    with pytest.raises(ocr.OcrUnavailable,match='timed out'):ocr.extract_text(image)
    assert time.monotonic()-start<2


@pytest.mark.parametrize('languages',[[], 'eng', [None], ['']])
def test_invalid_language_arguments_are_valueerror(image,languages):
    with pytest.raises(ValueError,match='languages'):ocr.extract_text(image,languages)


def test_jpeg_orientation_does_not_change_engine_coordinate_frame(engine):
    import struct
    jpeg=cv2.imencode('.jpg',np.full((20,40,3),255,np.uint8))[1].tobytes()
    exif=(b'Exif\0\0II'+struct.pack('<HIH',42,8,1)+struct.pack('<HHI',274,3,1)
          +struct.pack('<H',6)+b'\0\0'+struct.pack('<I',0))
    encoded=jpeg[:2]+b'\xff\xe1'+struct.pack('>H',len(exif)+2)+exif+jpeg[2:]
    ocr.extract_text(encoded)
    payload=next(kwargs['input'] for _,kwargs in engine.calls if kwargs.get('input') is not None)
    decoded=cv2.imdecode(np.frombuffer(payload,np.uint8),cv2.IMREAD_UNCHANGED)
    assert payload.startswith(b'\x89PNG') and decoded.shape[:2]==(20,40)
