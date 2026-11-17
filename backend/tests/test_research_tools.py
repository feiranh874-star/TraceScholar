import io
import json
import socket
import ssl
import subprocess
import time
import urllib.error
import uuid
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app import papers, ocr, reading, discovery
from app.config import Settings
from app.main import create_app
from app.llm import LLMServiceError

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(papers,'DATA_DIR',tmp_path/'data')
    return TestClient(create_app(Settings(llm_api_key='test',llm_model='test',llm_base_url='https://example.invalid')))

def pdf(title, texts, scanned=False):
    d=pymupdf.open()
    for text in texts:
        p=d.new_page();p.insert_textbox((40,40,550,780),text,fontsize=11)
    d.set_metadata({'title':title,'author':'Alice Example'})
    if scanned:
        scan=pymupdf.open()
        for p in d:
            page=scan.new_page();page.insert_image(page.rect,stream=p.get_pixmap().tobytes('png'))
        data=scan.tobytes();scan.close()
    else: data=d.tobytes()
    d.close();return data

def upload(client,title,texts,scanned=False):
    r=client.post('/api/papers',files={'file':('paper.pdf',pdf(title,texts,scanned),'application/pdf')})
    assert r.status_code==201,r.text
    return r.json()

def test_ocr_persists_text_index_and_skips_completed_on_retry(client,monkeypatch):
    paper=upload(client,'Scan',['Scanned attention text','Second scan'],scanned=True)
    monkeypatch.setattr(ocr,'engine_command',lambda:['test'])
    calls=[]
    def recognize(page,command,on_rendered=None):
        calls.append(page.number)
        if page.number==1: raise RuntimeError('Temporary page failure')
        return 'Scaled dot product attention computes query key value representation for transformers.'
    monkeypatch.setattr(ocr,'recognize',recognize)
    pid=paper['paper_id']
    assert client.post(f'/api/papers/{pid}/ocr').status_code==202
    job=client.get(f'/api/papers/{pid}/ocr').json()
    assert job['status']=='partial'
    assert job['processed']==2 and job['completed_pages']==[1]
    assert client.get(f'/api/papers/{pid}').json()['needs_ocr_pages']==[2]
    monkeypatch.setattr(ocr,'recognize',lambda page,command,**kwargs:'A second recovered page contains enough text for indexed academic attention retrieval.')
    client.post(f'/api/papers/{pid}/ocr')
    assert client.get(f'/api/papers/{pid}/ocr').json()['requested_pages']==[2]
    assert client.get(f'/api/papers/{pid}').json()['parse_status']=='ready'
    evidence=client.post('/api/research/retrieve',json={'question':'scaled dot product attention','paper_ids':[pid]}).json()['items']
    assert evidence and evidence[0]['source']['page_start']==1
    assert client.get(f'/api/papers/{pid}/pages/1').json()['text_origin']=='ocr'

def test_missing_ocr_engine_and_restart_status_are_explicit(client,monkeypatch):
    p=upload(client,'Scan',['not text'],scanned=True);pid=p['paper_id']
    def missing(): raise RuntimeError('未找到 OCR 引擎')
    monkeypatch.setattr(ocr,'engine_command',missing)
    client.post(f'/api/papers/{pid}/ocr')
    assert client.get(f'/api/papers/{pid}/ocr').json()['status']=='failed'
    path=papers._papers_dir()/pid/'ocr-job.json'
    papers._write_json(path,{'status':'running'})
    assert client.get(f'/api/papers/{pid}/ocr').json()['status']=='interrupted'

def test_ocr_reports_live_page_phase_and_stall(client,monkeypatch):
    p=upload(client,'Scan',['not text'],scanned=True);pid=p['paper_id']
    monkeypatch.setattr(ocr,'engine_command',lambda:['test'])
    def recognize(page,command,on_rendered=None):
        status=client.get(f'/api/papers/{pid}/ocr').json()
        assert status['phase']=='rendering' and status['current_page']==1
        assert status['processed']==0 and status['status']=='running'
        on_rendered()
        path=papers._papers_dir()/pid/'ocr-job.json'
        job=papers._read_metadata(path)
        assert job['phase']=='recognizing'
        job['updated_at']=time.time()-60
        papers._write_json(path,job)
        assert client.get(f'/api/papers/{pid}/ocr').json()['stalled']
        return 'An OCR page provides enough academic attention content for retrieval and translation.'
    monkeypatch.setattr(ocr,'recognize',recognize)
    client.post(f'/api/papers/{pid}/ocr')
    job=client.get(f'/api/papers/{pid}/ocr').json()
    assert job['status']=='done' and job['phase']=='finished'
    assert job['finished_at']>=job['started_at'] and not job['stalled']

def test_recognize_uses_grayscale_and_one_cpu_thread(monkeypatch):
    captured={}
    class Page:
        rect=pymupdf.Rect(0,0,600,800)
        def get_pixmap(self,**kwargs):
            captured.update(kwargs)
            class Pixmap:
                def save(self,path): captured['path']=str(path)
            return Pixmap()
    def run(args,**kwargs):
        captured['args']=args;captured.update(kwargs)
        return subprocess.CompletedProcess(args,0,stdout=b'Original scanned text')
    monkeypatch.setattr(ocr.subprocess,'run',run)
    calls=[]
    assert ocr.recognize(Page(),['tesseract'],lambda:calls.append('rendered'))=='Original scanned text'
    assert captured['colorspace'] is pymupdf.csGRAY
    assert captured['env']['OMP_THREAD_LIMIT']==captured['env']['OMP_NUM_THREADS']=='1'
    assert captured['timeout']==90 and calls==['rendered']

@pytest.mark.parametrize('error,expected',[
    (subprocess.TimeoutExpired(['tesseract'],90),'90 秒'),
    (subprocess.CalledProcessError(1,['tesseract'],stderr=b'Error loading eng.traineddata'),'语言包'),
    (subprocess.CalledProcessError(-9,['tesseract']),'内存'),
])
def test_ocr_failure_reason_is_actionable(error,expected):
    assert expected in ocr._page_error(error)

def test_native_pdf_and_translation_anchor_validation(client,monkeypatch):
    p=upload(client,'Read',['An academic attention method has parameters beta = 0.9 and code sample.'])
    pid=p['paper_id']
    response=client.get(f'/api/papers/{pid}/source.pdf')
    assert response.headers['content-type']=='application/pdf'
    assert response.content.startswith(b'%PDF-')
    rendered=client.get(f'/api/papers/{pid}/render/1')
    assert rendered.status_code==200 and rendered.content.startswith(b'\x89PNG')
    assert client.get(f'/api/papers/{pid}/render/999').status_code==404
    assert response.headers['x-frame-options']=='SAMEORIGIN'
    called=[]
    def complete(messages,**kwargs): called.append(messages); return '一种学术注意力方法。'
    monkeypatch.setattr(reading,'complete_messages',complete)
    text=client.get(f'/api/papers/{pid}/pages/1').json()['text']
    assert client.post(f'/api/papers/{pid}/translate',json={'page':1,'text':'unrelated content'}).status_code==422
    result=client.post(f'/api/papers/{pid}/translate',json={'page':1,'text':text}).json()
    assert result['source']=={'paper_id':pid,'page':1} and result['translation']
    assert 'Preserve code' in called[0][0]['content']
    def fail(*args,**kwargs): raise LLMServiceError('timeout',status_code=504)
    monkeypatch.setattr(reading,'complete_messages',fail)
    assert client.post(f'/api/papers/{pid}/translate',json={'page':1,'text':text}).status_code==504

def test_graph_edges_require_bibliography_evidence_not_body_mentions(client):
    a=upload(client,'Attention Models',['Abstract\nAttention models provide useful neural research representations.'])
    b=upload(client,'Transfer Learning For Vision',['This body discusses Attention Models but is not a reference.',
        'References\n[1] Alice Example. Attention Models. 2020.\n[2] Other Authors. Other Study.'])
    c=upload(client,'Biology And Soil Research',['Attention Models is mentioned here. This is plain body text only.'])
    graph=client.post('/api/library/graph',json={'paper_ids':[a['paper_id'],b['paper_id'],c['paper_id']]}).json()
    assert len(graph['edges'])==1
    assert graph['edges'][0]['source']==b['paper_id'] and graph['edges'][0]['target']==a['paper_id']
    assert graph['edges'][0]['page']==2
    assert max(graph['nodes'],key=lambda n:n['pagerank'])['id']==a['paper_id']
    assert abs(sum(n['pagerank'] for n in graph['nodes'])-1)<.00001

def test_recommendation_explains_shared_terms_and_outline_uses_real_sources(client):
    a=upload(client,'Attention Learning Models',['Abstract\nAttention learning models are useful for sequence research.'])
    b=upload(client,'Attention For Vision Models',['Abstract\nAttention learning and vision models are useful for research.'])
    rec=client.get('/api/library/recommendations/'+a['paper_id']).json()
    assert rec['items'][0]['paper']['paper_id']==b['paper_id']
    assert 'attention' in rec['items'][0]['shared_terms']
    out=client.post('/api/library/outline',json={'paper_ids':[a['paper_id'],b['paper_id']],'idea':'attention learning'}).json()
    assert {r['paper_id'] for r in out['references']}=={a['paper_id'],b['paper_id']}
    assert out['draft'] is None and out['evidence'] and out['mermaid'].startswith('flowchart')
    assert all(r['arxiv_id'] is None for r in out['references'])

def test_chart_numbers_and_script_reproduction(client):
    csv='epoch,accuracy\n1,0.5\n2,0.8\n3,0.9\n'
    result=client.post('/api/library/chart',files={'file':('data.csv',csv,'text/csv')},data={'x':'epoch','y':'accuracy'}).json()
    assert result['rows']==3 and result['stats']['max']==.9
    assert result['stats']['mean']==pytest.approx((.5+.8+.9)/3)
    assert result['image'].startswith('data:image/png;base64,')
    compile(result['script'],'plot.py','exec')
    assert 'json.loads' in result['script']
    for bad in ('epoch,accuracy\n1,NaN\n','epoch,accuracy\n1,Infinity\n','epoch,accuracy\n1,abc\n','epoch,accuracy\n1,2,3\n'):
        assert client.post('/api/library/chart',files={'file':('data.csv',bad)},data={'x':'epoch','y':'accuracy'}).status_code==422

def test_external_search_parse_import_and_url_restrictions(client,monkeypatch):
    xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title><summary>Transformer</summary><author><name>Alice</name></author></entry></feed>'
    called=[]
    def fake(url,limit,hosts): called.append(url);return xml
    monkeypatch.setattr(discovery,'fetch',fake)
    result=client.post('/api/library/search',json={'query':'Attention Is All You Need'}).json()
    assert result['items'][0]['arxiv_id']=='1706.03762v7'
    assert called[0].startswith('https://export.arxiv.org/')
    assert 'ti%3AIs' not in called[0]
    payload=pdf('Attention Is All You Need',['A real public PDF with sufficient attention learning text to extract.'])
    monkeypatch.setattr(discovery,'fetch',lambda *args:payload)
    assert client.post('/api/library/import',json={'arxiv_id':'1706.03762v7'}).status_code==201
    assert client.post('/api/library/import',json={'arxiv_id':'http://127.0.0.1/private'}).status_code==422
    assert client.post('/api/library/graph',json={'paper_ids':['../../outside']}).status_code==422


@pytest.mark.parametrize('failure, expected', [
    (TimeoutError(), '连接超时'),
    (urllib.error.URLError(TimeoutError()), '连接超时'),
    (urllib.error.URLError(socket.gaierror('test DNS failure')), '域名解析失败'),
    (urllib.error.URLError(ssl.SSLCertVerificationError('test certificate')), '安全连接失败'),
    (urllib.error.HTTPError('https://export.arxiv.org', 429, 'limited', {}, None), '已被限流'),
    (urllib.error.HTTPError('https://export.arxiv.org', 503, 'unavailable', {}, None), '接口暂时无法处理'),
    (urllib.error.URLError(ConnectionRefusedError()), '连接失败'),
], ids=['timeout', 'wrapped-timeout', 'dns', 'tls', 'rate-limit', 'unavailable', 'connection'])
def test_external_search_distinguishes_upstream_failures(client, monkeypatch, failure, expected):
    class FailingOpener:
        def open(self, *args, **kwargs):
            raise failure

    monkeypatch.setattr(discovery.urllib.request, 'build_opener', lambda *args: FailingOpener())
    response = client.post('/api/library/search', json={'query': 'Attention Is All You Need'})
    assert response.status_code == 502
    assert expected in response.json()['detail']
    assert '手动导入' in response.json()['detail']


def test_external_search_separates_empty_results_from_invalid_upstream_response(client, monkeypatch):
    monkeypatch.setattr(discovery.time, 'sleep', lambda _: None)
    monkeypatch.setattr(discovery, 'fetch', lambda *args: b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
    response = client.post('/api/library/search', json={'query': 'Unknown paper title'})
    assert response.status_code == 200
    assert response.json()['items'] == []
    monkeypatch.setattr(discovery, 'fetch', lambda *args: b'not an XML response')
    response = client.post('/api/library/search', json={'query': 'Unknown paper title'})
    assert response.status_code == 502
    assert '无法解析' in response.json()['detail']


def test_external_search_normalizes_long_title_and_removes_stopwords(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(discovery, 'fetch', lambda url, *args: calls.append(url) or b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
    monkeypatch.setattr(discovery.time, 'sleep', lambda _: None)
    client.post('/api/library/search', json={'query':'Born in the Dark: The Catastrophic Collapse of Fuzzy Dark Matter Solitons as the Origin of Little Red Dots'})
    query=discovery.urllib.parse.parse_qs(discovery.urllib.parse.urlparse(calls[0]).query)['search_query'][0]
    assert 'ti:as' not in query and 'ti:the' not in query
    assert query.count('ti:dark') == 1
    assert len(calls) == 2


def test_external_search_relaxes_empty_title_once_and_marks_candidates(client, monkeypatch):
    calls=[]; waits=[]
    xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2601.00044v3</id><title>Born in the Dark: The Catastrophic Collapse of Fuzzy Dark Matter Solitons</title></entry></feed>'
    def fake(url, *args):
        calls.append(url)
        return b'<feed xmlns="http://www.w3.org/2005/Atom"/>' if len(calls) == 1 else xml
    monkeypatch.setattr(discovery, 'fetch', fake)
    monkeypatch.setattr(discovery.time, 'sleep', waits.append)
    result=client.post('/api/library/search', json={'query':'Born in the Dark: The Catastrophic Collapse of Fuzzy Dark Matter So'}).json()
    assert len(calls) == 2 and waits == [3]
    query=discovery.urllib.parse.parse_qs(discovery.urllib.parse.urlparse(calls[1]).query)['search_query'][0]
    assert 'ti:so' not in query
    assert ' OR ' not in query
    assert result['items'][0]['arxiv_id'] == '2601.00044v3'
    assert result['search_mode'] == 'keywords'
    assert '相近论文' in result['notice']


def test_external_search_does_not_retry_successful_query(client, monkeypatch):
    calls=[]
    xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title></entry></feed>'
    monkeypatch.setattr(discovery, 'fetch', lambda url, *args: calls.append(url) or xml)
    result=client.post('/api/library/search', json={'query':'Attention Is All You Need'}).json()
    assert len(calls) == 1
    assert result['search_mode'] == 'title'


@pytest.mark.parametrize('payload', [
    b'<html><body>Temporary error</body></html>',
    b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#query</id><title>Error</title></entry></feed>',
    b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>unknown-record-format</id></entry></feed>',
])
def test_external_search_does_not_disguise_upstream_error_as_no_results(client, monkeypatch, payload):
    calls=[]
    monkeypatch.setattr(discovery, 'fetch', lambda *args: calls.append(True) or payload)
    response=client.post('/api/library/search', json={'query':'Born in the Dark catastrophic collapse'})
    assert response.status_code == 502
    assert len(calls) == 1


@pytest.mark.parametrize('query', [
    '1706.03762v7', 'arXiv:1706.03762v7', ' arxiv: 1706.03762v7 ',
    'https://arxiv.org/abs/1706.03762v7', 'https://arxiv.org/pdf/1706.03762v7.pdf',
    'https://arxiv.org/pdf/1706.03762v7?download=1',
])
def test_external_search_looks_up_identifiers_instead_of_title_words(client, monkeypatch, query):
    calls=[]
    xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title></entry></feed>'
    monkeypatch.setattr(discovery, 'fetch', lambda url, *args: calls.append(url) or xml)
    result=client.post('/api/library/search', json={'query':query}).json()
    assert len(calls) == 1
    params=discovery.urllib.parse.parse_qs(discovery.urllib.parse.urlparse(calls[0]).query)
    assert params['id_list'] == ['1706.03762v7']
    assert 'search_query' not in params
    assert result['search_mode'] == 'identifier'
    assert result['items'][0]['title'] == 'Attention Is All You Need'


@pytest.mark.parametrize('query', [
    'arxiv:invalid', 'https://example.com/abs/1706.03762',
    'https://arxiv.org@127.0.0.1/abs/1706.03762', 'https://arxiv.org:443/abs/1706.03762',
    'https://arxiv.org/pdf/../../private', 'https://arxiv.org:invalid/abs/1706.03762',
])
def test_external_search_rejects_invalid_identifiers_and_untrusted_links(client, monkeypatch, query):
    def forbidden(*args):
        raise AssertionError('Invalid input must not be fetched')
    monkeypatch.setattr(discovery, 'fetch', forbidden)
    assert client.post('/api/library/search', json={'query':query}).status_code == 422


def test_external_search_identifier_missing_is_not_treated_as_title_search(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(discovery, 'fetch', lambda url, *args: calls.append(url) or b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
    result=client.post('/api/library/search', json={'query':'arXiv:2611.21545'}).json()
    assert len(calls) == 1
    assert result['items'] == [] and result['search_mode'] == 'identifier'
    assert '核对编号' in result['notice']


def test_external_search_identifier_does_not_return_a_different_paper_or_version(client, monkeypatch):
    xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title></entry></feed>'
    monkeypatch.setattr(discovery, 'fetch', lambda *args: xml)
    assert client.post('/api/library/search', json={'query':'1706.03762'}).json()['items']
    assert client.post('/api/library/search', json={'query':'1706.03762v1'}).json()['items'] == []
    assert client.post('/api/library/search', json={'query':'2611.21545'}).json()['items'] == []
