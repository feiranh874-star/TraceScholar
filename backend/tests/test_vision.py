"""Vision transport/structure failures must not corrupt evidence or cause silent retries."""
import copy
import io
import json
import threading
import time
import urllib.error
from dataclasses import replace

import pymupdf
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import jobs, papers, vision
from app.config import Settings
from app.main import create_app

SETTINGS = Settings(vision_api_key='test-only-vision-key')


def record():
    return {'tables':[{'label':'Table 3', 'bbox':[50, 50, 950, 500],
                      'rows':[['group', 'h', 'BLEU'], ['base', '8', '25.8'], ['(A)', '1', '24.9'], [None, '4', None], ['=SUM(1,2)', None, None]],
                      'merges':[{'row':2, 'column':0, 'rowspan':2, 'colspan':1}], 'notes':'空白保留。'}],
            'equations':[{'label':'(1)', 'bbox':[100, 600, 900, 650], 'latex':r'x_{i}^{2}', 'notes':''}],
            'figures':[], 'warnings':[]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, 'DATA_DIR', tmp_path / 'data')
    with TestClient(create_app(SETTINGS)) as c:
        yield c
    assert not jobs._ACTIVE


def upload(client, scanned=False):
    with pymupdf.open() as doc:
        page = doc.new_page()
        if not scanned:
            page.insert_text((50, 50), 'A paper with native text and trustworthy experimental evidence.')
        data = doc.tobytes()
    result = client.post('/api/papers', files={'file':('sample.pdf', data, 'application/pdf')})
    assert result.status_code == 201, result.text
    return result.json()['paper_id']


def wait(client, identifier):
    for _ in range(200):
        job = client.get('/api/jobs/' + identifier).json()
        if job['status'] not in ('queued', 'running'):
            return job
        time.sleep(.01)
    pytest.fail('Vision job did not finish')


@pytest.mark.parametrize('scanned', [False, True])
def test_saved_rows_blanks_merges_sources_and_csv_are_shared(client, monkeypatch, scanned):
    pid = upload(client, scanned); calls = []
    original = client.get(f'/api/papers/{pid}/pages/1').json()
    def recognize(image, settings):
        assert image.startswith(b'\x89PNG')
        calls.append(1)
        return vision.Recognition.model_validate(record()).model_dump(), {'input_tokens':123}
    monkeypatch.setattr(vision, 'recognize', recognize)
    assert client.get(f'/api/papers/{pid}/vision/1').json()['result'] is None
    start = client.post(f'/api/papers/{pid}/vision/1', json={})
    assert start.status_code == 202, start.text
    job = wait(client, start.json()['id']); assert job['status'] == 'done', job
    data = client.get(f'/api/papers/{pid}/vision/1').json()['result']
    assert data['tables'][0]['rows'] == record()['tables'][0]['rows']
    assert data['tables'][0]['source']['paper_id'] == pid
    assert data['tables'][0]['source']['page_start'] == 1
    assert data['tables'][0]['merges'][0]['rowspan'] == 2
    assert data['tables'][0]['bbox'][2] == pytest.approx(data['width'] * .95)
    assert data['equations'][0]['latex'] == r'x_{i}^{2}'
    response = client.get(f'/api/papers/{pid}/vision/1/tables/vision-table-1.csv')
    assert response.status_code == 200 and "'=SUM(1,2)" in response.text
    assert '未识别' not in response.text and ',4,' in response.text
    for _ in range(2):
        assert client.post(f'/api/papers/{pid}/vision/1', json={}).json()['cached']
    assert len(calls) == 1
    assert client.get(f'/api/papers/{pid}/pages/1').json() == original
    assert SETTINGS.vision_api_key not in json.dumps(data)
    assert client.delete('/api/papers/' + pid).status_code == 204
    assert client.get(f'/api/papers/{pid}/vision/1').status_code == 404


def test_busy_delete_force_failure_and_recovery_preserve_success(client, monkeypatch):
    pid = upload(client)
    monkeypatch.setattr(vision, 'recognize', lambda *a:(record(), {}))
    first = wait(client, client.post(f'/api/papers/{pid}/vision/1', json={}).json()['id'])
    assert first['status'] == 'done'
    old = client.get(f'/api/papers/{pid}/vision/1').json()
    entered = threading.Event(); release = threading.Event()
    def fail(*a):
        entered.set(); release.wait(3)
        raise RuntimeError('视觉接口密钥无效，请检查 VISION_API_KEY。')
    monkeypatch.setattr(vision, 'recognize', fail)
    start = client.post(f'/api/papers/{pid}/vision/1', json={'force':True}).json()
    assert entered.wait(2)
    try:
        assert client.delete('/api/papers/' + pid).status_code == 409
        assert client.post(f'/api/papers/{pid}/vision/1', json={'force':True}).status_code == 409
    finally:
        release.set()
    assert wait(client, start['id'])['status'] == 'failed'
    assert client.get(f'/api/papers/{pid}/vision/1').json() == old
    monkeypatch.setattr(vision, 'recognize', lambda *a:(record(), {}))
    assert client.post('/api/jobs/' + start['id'] + '/resume').status_code == 202
    assert wait(client, start['id'])['status'] == 'done'


def test_missing_config_invalid_pages_and_no_auto_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, 'DATA_DIR', tmp_path)
    with TestClient(create_app(Settings())) as c:
        pid = upload(c)
        assert c.get('/api/vision/status').json()['configured'] is False
        assert c.post(f'/api/papers/{pid}/vision/1', json={}).status_code == 503
        assert not list((tmp_path / 'jobs').glob('*.json'))
    with TestClient(create_app(SETTINGS)) as c:
        assert c.post(f'/api/papers/{pid}/vision/2', json={}).status_code == 404
        assert c.get(f'/api/papers/{pid}/vision/1/tables/missing.csv').status_code == 404


@pytest.mark.parametrize('change', ['uneven', 'hidden', 'overlap', 'bbox', 'numbers'])
def test_invalid_model_structure_is_rejected(change):
    data = record(); table = data['tables'][0]
    if change == 'uneven': table['rows'][1].pop()
    if change == 'hidden': table['rows'][3][0] = 'must not hide this'
    if change == 'overlap': table['merges'].append(copy.deepcopy(table['merges'][0]))
    if change == 'bbox': table['bbox'][2] = 1001
    if change == 'numbers': table['rows'][1][1] = 8
    with pytest.raises(ValidationError): vision.Recognition.model_validate(data)


def test_responses_payload_and_completed_output_only(monkeypatch):
    observed = []
    response = {'status':'completed', 'output':[{'type':'reasoning', 'summary':[]},
                 {'type':'message','content':[{'type':'output_text','text':json.dumps(record())}]}],
                'usage':{'input_tokens':100, 'output_tokens':500, 'irrelevant':'discard'}}
    def open_request(request, **kwargs):
        observed.append(json.loads(request.data))
        assert request.full_url == 'https://ark.cn-beijing.volces.com/api/v3/responses'
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(vision.urllib.request, 'urlopen', open_request)
    data, usage = vision.recognize(b'png-bytes', SETTINGS)
    assert data['tables'][0]['rows'][3] == [None, '4', None]
    assert usage == {'input_tokens':100,'output_tokens':500}
    assert observed[0]['thinking'] == {'type':'disabled'}
    assert observed[0]['input'][0]['content'][0]['type'] == 'input_image'
    response['status'] = 'incomplete'
    with pytest.raises(RuntimeError, match='不完整'): vision.recognize(b'png', SETTINGS)


@pytest.mark.parametrize('code', [400, 401, 402, 403, 429, 500])
def test_transport_errors_are_redacted_and_not_retried(monkeypatch, code):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError('https://example.invalid', code, SETTINGS.vision_api_key, {}, io.BytesIO(b'secret'))
    monkeypatch.setattr(vision.urllib.request, 'urlopen', fail)
    with pytest.raises(RuntimeError) as error: vision.recognize(b'png', SETTINGS)
    assert SETTINGS.vision_api_key not in str(error.value)
    assert 'secret' not in str(error.value)
    assert len(calls) == 1


def test_vision_env_loads_separately_from_text_provider(monkeypatch):
    monkeypatch.setenv('VISION_API_KEY', 'test-vision')
    monkeypatch.setenv('LLM_API_KEY', 'test-text')
    settings = Settings.from_env()
    assert settings.vision_api_key == 'test-vision' and settings.llm_api_key == 'test-text'
    with pytest.raises(ValueError): replace(settings, vision_timeout_seconds=0).validate()


def test_model_merge_conflict_keeps_every_raw_cell_and_warns():
    data = record()
    data['tables'][0]['rows'][2][0] = None
    data['tables'][0]['rows'][3][0] = '(A)'
    response = {'status':'completed', 'output':[{'type':'message', 'content':[
        {'type':'output_text', 'text':json.dumps(data)}]}]}
    parsed, _ = vision.parse_response(response)
    assert parsed['tables'][0]['rows'] == data['tables'][0]['rows']
    assert parsed['tables'][0]['merges'] == []
    assert '1 组合并范围' in parsed['tables'][0]['notes']
    assert '未移动或补值' in parsed['tables'][0]['notes']
    data['tables'][0]['rows'][1].pop()
    response['output'][0]['content'][0]['text'] = json.dumps(data)
    with pytest.raises(RuntimeError, match='结构不合法'): vision.parse_response(response)


def test_old_cached_results_get_display_fixes_without_network_or_rewriting_cache(client, monkeypatch):
    pid = upload(client)
    monkeypatch.setattr(vision, 'recognize', lambda *a:(record(), {}))
    assert wait(client, client.post(f'/api/papers/{pid}/vision/1', json={}).json()['id'])['status'] == 'done'
    path = vision.cache_path(pid, 1)
    raw = json.loads(path.read_text())
    raw['tables'][0]['rows'] = [['', 'metric'], ['(A)', '1'], ['', '2'], ['(B)', '3'], ['', '4']]
    raw['tables'][0]['merges'] = []
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    def no_network(*args): pytest.fail('Reading old cache must never call the model')
    monkeypatch.setattr(vision, 'recognize', no_network)
    result = client.get(f'/api/papers/{pid}/vision/1').json()['result']
    assert result['tables'][0]['rows'] == raw['tables'][0]['rows']
    assert len(result['tables'][0]['display_merges']) == 2
    assert result['layout_version'] == 1
    assert client.post(f'/api/papers/{pid}/vision/1', json={}).json()['cached']
    assert path.read_bytes() == before
