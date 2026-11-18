import json
import time
import uuid
import threading
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app import papers,jobs,document_ops,agent_tools,tracking,discovery,research
from app.main import create_app
from app.config import Settings

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(papers,'DATA_DIR',tmp_path/'data')
    with TestClient(create_app(Settings(llm_api_key='test',llm_model='test',llm_base_url='https://example.invalid'))) as c:yield c
    assert not jobs._ACTIVE

def pdf(text,table=False):
    doc=pymupdf.open();p=doc.new_page();p.insert_text((40,40),text,fontsize=11)
    if table:
        xs=[40,180,300];ys=[100,130,160,190]
        for x in xs:p.draw_line((x,ys[0]),(x,ys[-1]))
        for y in ys:p.draw_line((xs[0],y),(xs[-1],y))
        for r,row in enumerate([['Model','BLEU'],['Base','27.3'],['Big','28.4']]):
            for c,v in enumerate(row):p.insert_text((xs[c]+8,ys[r]+20),v)
        p.insert_text((40,90),'Table 1: Translation scores')
    data=doc.tobytes();doc.close();return data

def upload(c,text='1 Introduction\nAcademic attention research uses verified evidence and sources.',name='1706.03762v7.pdf',table=False):
    r=c.post('/api/papers',files={'file':(name,pdf(text,table),'application/pdf')});assert r.status_code==201,r.text;return r.json()

def wait(c,i):
    for _ in range(200):
        r=c.get('/api/jobs/'+i).json()
        if r['status'] not in ('running','queued'):return r
        time.sleep(.01)
    pytest.fail('Task did not finish')

def test_tables_csv_positions_and_crop(client):
    p=upload(client,table=True);pid=p['paper_id'];a=client.get(f'/api/papers/{pid}/analysis/1').json();t=a['tables'][0]
    assert t['rows']==[['Model','BLEU'],['Base','27.3'],['Big','28.4']]
    assert t['source']['paper_id']==pid and not t['verified']
    assert 'Base,27.3' in client.get(f'/api/papers/{pid}/tables/1/'+t['id']+'.csv').text
    r=client.get(f'/api/papers/{pid}/crop/1',params=dict(zip(('x0','y0','x1','y1'),t['bbox'])));assert r.content.startswith(b'\x89PNG')
    assert client.get(f'/api/papers/{pid}/crop/1?x0=200&y0=20&x1=10&y1=50').status_code==422
    assert client.get(f'/api/papers/{pid}/positions/1?q=verified').json()['boxes']
    assert client.get(f'/api/papers/{pid}/analysis/2').status_code==404

def test_versions_archives_and_restore(client):
    a=upload(client,'1 Introduction\nOld attention experiment reports a research result.');pid=a['paper_id']
    b=client.post('/api/papers',files={'file':('1706.03762v1.pdf',pdf('1 Introduction\nNew attention experiment reports revised measurements.'),'application/pdf')},data={'conflict_action':'replace','target_paper_id':pid,'target_sha256':a['sha256']}).json()
    r=client.post('/api/library/version-diff',json={'older':pid,'newer':b['paper_id']});assert r.status_code==200,r.text
    assert r.json()['changes'][0]['before'][0]['page']==1
    assert client.get('/api/library/archives').json()['items'][0]['paper_id']==pid
    assert client.post(f'/api/papers/{pid}/restore').status_code==200
    assert client.get('/api/papers').json()['total']==2
    other=upload(client,'Botanical climate research and soil experiments.',name='2401.12345.pdf')
    assert client.post('/api/library/version-diff',json={'older':pid,'newer':other['paper_id']}).status_code==422

def test_metadata_and_rebuild(client):
    pid=upload(client)['paper_id']
    r=client.patch('/api/papers/'+pid,json={'title':'Corrected title','authors':['A','B'],'abstract':'Corrected abstract'});assert r.json()['authors']==['A','B']
    job=client.post(f'/api/papers/{pid}/rebuild').json();r=wait(client,job['id']);assert r['status']=='done',r
    assert r['completed']==[1] and client.get('/api/papers/'+pid).json()['title']=='Corrected title'

def test_translation_cache_export_and_failure_resume(client,monkeypatch):
    pid=upload(client)['paper_id'];calls=[]
    def translate(*a,**k):calls.append(1);return '经过核对的学术原文译文。'
    monkeypatch.setattr(document_ops,'complete_messages',translate)
    for _ in range(2):
        job=client.post(f'/api/papers/{pid}/translate-document',json={'target':'zh'}).json();r=wait(client,job['id']);assert r['status']=='done',r
    assert len(calls)==1 and client.get(f'/api/papers/{pid}/translations/zh').json()['translation']
    assert '译文' in client.get(f'/api/papers/{pid}/translations/zh/export').text
    entered=threading.Event();release=threading.Event()
    def fail(*a,**k):entered.set();release.wait(3);raise RuntimeError('temporary failure')
    monkeypatch.setattr(document_ops,'complete_messages',fail)
    job=client.post(f'/api/papers/{pid}/translate-document',json={'target':'en'}).json();assert entered.wait(2)
    assert client.delete('/api/papers/'+pid).status_code==409
    assert client.post(f'/api/papers/{pid}/ocr').status_code==409
    release.set();assert wait(client,job['id'])['status']=='failed'
    monkeypatch.setattr(document_ops,'complete_messages',translate)
    assert client.post('/api/jobs/'+job['id']+'/resume').status_code==202
    assert wait(client,job['id'])['status']=='done'

def test_batch_conflicts_and_progress(client):
    upload(client)
    r=client.post('/api/library/batch-upload',files=[('files',('1706.03762v1.pdf',pdf('An old attention paper contains enough text for research.'),'application/pdf')),('files',('2401.11111.pdf',pdf('A distinct calibrated scientific experiment contains measurements.'),'application/pdf'))]);assert r.status_code==202,r.text
    job=wait(client,r.json()['id']);assert job['status']=='done',job
    assert [f['status'] for f in job['result']['files']]==[409,201]
    assert client.get('/api/papers').json()['total']==2

def test_function_call_dispatch_and_foreign_paper_rejection(client,monkeypatch):
    pid=upload(client)['paper_id'];calls=[]
    def turn(messages,tools,settings):
        calls.append(messages.copy())
        return {'tool_calls':[{'id':'call1','type':'function','function':{'name':'inspect_page','arguments':json.dumps({'paper_id':pid,'page':1})}}]} if len(calls)==1 else {'content':'Enough evidence.'}
    monkeypatch.setattr(agent_tools,'turn',turn);monkeypatch.setattr(research,'generate_grounded_answer',lambda *a,**k:'Research uses verified evidence. [E1]')
    r=client.post('/api/research/run',json={'question':'Inspect the first page','paper_ids':[pid]});assert r.status_code==200,r.text
    d=r.json();assert d['steps'][0]['status']=='done' and d['answer']['citations'][0]['source']['paper_id']==pid
    assert any(m['role']=='tool' for m in calls[-1])
    monkeypatch.setattr(agent_tools,'turn',lambda *a:{'tool_calls':[{'id':'bad','type':'function','function':{'name':'inspect_page','arguments':json.dumps({'paper_id':str(uuid.uuid4()),'page':1})}}]})
    d=client.post('/api/research/run',json={'question':'Inspect other','paper_ids':[pid],'max_steps':1}).json()
    assert d['steps'][0]['status']=='failed' and d['answer']['insufficient']
    assert len(client.get('/api/research/runs').json()['items'])==2

def test_tracking_feedback_and_recommendation_exclusion(client,monkeypatch):
    a=upload(client,'Abstract\nAttention learning improves neural model representations.')
    b=upload(client,'Abstract\nAttention learning compares neural model representations.',name='2401.22222.pdf')
    assert client.get('/api/library/recommendations/'+a['paper_id']).json()['items']
    assert client.post('/api/library/feedback',json={'paper_id':b['paper_id'],'vote':'dislike'}).status_code==200
    assert not client.get('/api/library/recommendations/'+a['paper_id']).json()['items']
    entry=client.post('/api/library/tracking',json={'query':'neural attention','hours':6}).json()
    monkeypatch.setattr(discovery,'fetch',lambda *a:b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/2401.12345v2</id><title>Attention Study</title><summary>Code https://github.com/example/research</summary><published>2026-01-01</published></entry></feed>')
    r=client.post('/api/library/tracking/'+entry['id']+'/refresh').json();assert r['items'][0]['items'][0]['code_links']==['https://github.com/example/research']
    assert client.get('/api/library/tracking').json()['subscriptions'][0]['last_checked']
    assert client.delete('/api/library/tracking/'+entry['id']).status_code==204

def test_diagram_and_future_work_sources(client):
    p=upload(client,'1 Introduction\nAttention models support reliable research and measurements.\nFuture work will test longer sequences and more languages.')
    r=client.post('/api/library/review',json={'paper_ids':[p['paper_id']],'topic':'attention','generate':False}).json()
    assert r['timeline'][0]['future_work'][0]['source']['paper_id']==p['paper_id'] and r['draft'] is None
    d=client.post('/api/library/diagram',json={'title':'Test','nodes':['Input','Evaluate'],'edges':[[0,1]]}).json();assert 'N0 --> N1' in d['mermaid']
    assert client.post('/api/library/diagram',json={'title':'Test','nodes':['Input','Evaluate'],'edges':[[0,4]]}).status_code==422

@pytest.mark.parametrize('kind',['radar','radar3d','scatter','scatter3d','table'])
def test_chart_extensions_preserve_values(client,kind):
    r=client.post('/api/library/chart',files={'file':('data.csv','x,y,z\n1,0.5,2\n2,0.8,3\n3,0.9,4\n','text/csv')},data={'x':'x','y':'y','z':'z','kind':kind});assert r.status_code==200,r.text
    d=r.json();assert d['stats']['mean']==pytest.approx((.5+.8+.9)/3) and d['table']['rows'][0][1]==.5
    compile(d['script'],'plot.py','exec')

def test_batch_resolve_both_cancel_and_discard(client):
    upload(client)
    r=client.post('/api/library/batch-upload',files=[('files',('1706.03762v1.pdf',pdf('An old attention paper contains enough text for research.'),'application/pdf'))])
    j=wait(client,r.json()['id']);assert j['result']['files'][0]['status']==409
    r=client.post(f"/api/jobs/{j['id']}/files/0/resolve",json={'action':'keep_both'});assert r.status_code==200,r.text
    assert r.json()['status']==201 and client.get('/api/papers').json()['total']==2
    assert not (jobs.directory()/(j['id']+'-0.pdf')).exists()
    assert client.delete('/api/jobs/'+j['id']).status_code==204
    assert client.get('/api/jobs/'+j['id']).status_code==404
    r=client.post('/api/library/batch-upload',files=[('files',('1706.03762v2.pdf',pdf('Another old attention paper with changed research measurements.'),'application/pdf'))])
    j=wait(client,r.json()['id']);assert j['result']['files'][0]['status']==409
    assert client.post(f"/api/jobs/{j['id']}/files/0/resolve",json={'action':'cancel'}).json()['status']==204
    assert not (jobs.directory()/(j['id']+'-0.pdf')).exists()

def test_failed_tracking_obeys_interval(client,monkeypatch):
    entry=client.post('/api/library/tracking',json={'query':'neural attention','hours':6}).json();calls=[]
    def fail(*args):calls.append(1);raise RuntimeError('unavailable')
    monkeypatch.setattr(discovery,'fetch',fail)
    tracking.refresh();tracking.refresh()
    assert len(calls)==1
    assert client.get('/api/library/tracking').json()['subscriptions'][0]['last_attempt']

def test_tool_result_truncation_keeps_valid_json():
    data=json.loads(agent_tools._bounded_result({'large':'a'*40000}))
    assert data['truncated'] and len(data['preview'])<=24000

def test_official_table_geometry_when_samples_available(client):
    import os
    from pathlib import Path
    base=os.getenv('TRACESCHOLAR_SAMPLE_DIR')
    if not base:pytest.skip('Set TRACESCHOLAR_SAMPLE_DIR for official native-table regression')
    path=Path(base)/'1706.03762v7.pdf'
    with path.open('rb') as stream:r=client.post('/api/papers',files={'file':(path.name,stream,'application/pdf')})
    pid=r.json()['paper_id'];t=client.get(f'/api/papers/{pid}/analysis/8').json()['tables'][0]
    rows={row[0]:row for row in t['rows'][1:]}
    assert rows['Transformer (base model)'][1:3]==['27.3','38.1']
    assert rows['Transformer (big)'][1:3]==['28.4','41.8']
    assert rows['Transformer (base model)'][3:] == ['3.3 · 10^(18)',None]
    assert t['merged_cells'][0]['columns']==[3,4]
    refs=client.get(f'/api/papers/{pid}/references').json()['items']
    assert len(refs)==40 and 'Attention Visualizations' not in refs[-1]['text']
    cases=json.loads((Path(__file__).parent/'evaluation/fine_grained_cases.json').read_text())
    for case in cases:
        data=client.post('/api/research/retrieve',json={'paper_ids':[pid],'question':case['question'],'limit':6}).json()
        assert any(h['source']['page_start'] in case['pages'] for h in data['items']),case['id']

def test_claim_review_scope_and_code_source(client,monkeypatch):
    p=upload(client,'1 Introduction\nAttention research reports measurements with reliable evidence.\nFuture work will test long sequences.\nCode: https://github.com/example/research')
    pid=p['paper_id']
    r=client.post('/api/library/claim-review',json={'paper_ids':[pid],'claim':'attention long sequences','generate':False});assert r.status_code==200,r.text
    assert r.json()['evidence'] and '不能证明' in r.json()['scope']
    monkeypatch.setattr(research,'generate_grounded_answer',lambda *a,**k:'需进一步核对。 [E1]')
    d=client.post('/api/library/claim-review',json={'paper_ids':[pid],'claim':'attention long sequences','generate':True}).json()
    assert d['assessment']['citations'][0]['source']['paper_id']==pid
    links=client.get('/api/library/code-links/'+pid).json()['items']
    assert links[0]['url']=='https://github.com/example/research' and links[0]['source']['page_start']==1
    assert not links[0]['verified']

def test_translation_invalidated_when_original_changes(client,monkeypatch):
    pid=upload(client)['paper_id'];monkeypatch.setattr(document_ops,'complete_messages',lambda *a,**k:'译文')
    j=client.post(f'/api/papers/{pid}/translate-document',json={'target':'zh'}).json();assert wait(client,j['id'])['status']=='done'
    path=papers._papers_dir()/pid/'pages/000001.json';record=papers._read_metadata(path);record['text']+=' Updated source.';jobs.atomic(path,record)
    assert client.get(f'/api/papers/{pid}/translations/zh').json()['translation'] is None
    assert client.get(f'/api/papers/{pid}/translations/zh/export').status_code==404

def test_agent_comparison_needs_each_selected_paper(client,monkeypatch):
    a=upload(client);b=upload(client,'Distinct study of climate measurements and calibrated sensors.',name='2401.22222.pdf')
    monkeypatch.setattr(agent_tools,'turn',lambda *args:{'tool_calls':[{'id':'one','type':'function','function':{'name':'inspect_page','arguments':json.dumps({'paper_id':a['paper_id'],'page':1})}}]})
    def forbidden(*a,**k):pytest.fail('Must not generate before all selected sources exist')
    monkeypatch.setattr(research,'generate_grounded_answer',forbidden)
    d=client.post('/api/research/run',json={'paper_ids':[a['paper_id'],b['paper_id']],'question':'比较这两篇研究的结果','max_steps':1}).json()
    assert d['answer']['insufficient'] and d['answer']['answer'] is None


def upload_pages(c, count, label):
    doc=pymupdf.open()
    for number in range(1,count+1):
        page=doc.new_page();page.insert_text((40,50),f'{label} page {number}. Verified academic research evidence and evaluation results.',fontsize=11)
    data=doc.tobytes();doc.close()
    r=c.post('/api/papers',files={'file':(label+'.pdf',data,'application/pdf')},data={'conflict_action':'keep_both'})
    assert r.status_code==201,r.text
    return r.json()['paper_id']


def test_translation_ranges_explain_total_and_validate_before_start(client,monkeypatch):
    a=upload_pages(client,2,'Alpha');b=upload_pages(client,3,'Beta')
    monkeypatch.setattr(document_ops,'complete_messages',lambda *a,**k:pytest.fail('Invalid range must not call a model'))
    r=client.post(f'/api/papers/{a}/translate-document',json={'start':1,'end':20})
    assert r.status_code==422 and '共 2 页' in r.json()['detail'] and '1–2' in r.json()['detail']
    for payload in [dict(mode='range',start=1,end=3),dict(mode='range',start=2,end=1),dict(mode='range',start=1)]:
        r=client.post('/api/library/translate-batch',json={'paper_ids':[b,a],**payload})
        assert r.status_code==422 and '共 ' in r.json()['detail'],r.text
    assert client.get('/api/jobs').json()['items']==[]
    assert client.post('/api/library/translate-batch',json={'paper_ids':[a,a]}).status_code==422
    assert client.post('/api/library/translate-batch',json={'paper_ids':[]}).status_code==422


def test_batch_translation_each_paper_uses_own_page_count_and_cache(client,monkeypatch):
    a=upload_pages(client,2,'Alpha');b=upload_pages(client,3,'Beta');calls=[]
    def translated(messages,**kwargs):calls.append(messages[-1]['content']);return '学术译文。'
    monkeypatch.setattr(document_ops,'complete_messages',translated)
    for _ in range(2):
        r=client.post('/api/library/translate-batch',json={'paper_ids':[a,b],'target':'zh','mode':'all'})
        assert r.status_code==202,r.text
        job=wait(client,r.json()['id']);assert job['status']=='done',job
        assert job['total']==job['progress']==5 and len(set(job['completed']))==5
        assert [(p['start'],p['end']) for p in job['result']['papers']]==[(1,2),(1,3)]
    assert len(calls)==5
    assert client.get(f'/api/papers/{a}/translations/zh?page=2').json()['translation']=='学术译文。'
    assert client.get(f'/api/papers/{b}/translations/zh?page=3').json()['translation']=='学术译文。'
    assert '## 第 3 页' in client.get(f'/api/papers/{b}/translations/zh/export').text


def test_batch_translation_failure_isolated_and_resume_skips_saved_pages(client,monkeypatch):
    a=upload_pages(client,2,'Alpha');b=upload_pages(client,3,'Beta');calls=[]
    def partial(messages,**kwargs):
        source=messages[-1]['content'];calls.append(source)
        if 'Alpha page 2' in source:raise RuntimeError('Temporary failure')
        return '已保存译文。'
    monkeypatch.setattr(document_ops,'complete_messages',partial)
    r=client.post('/api/library/translate-batch',json={'paper_ids':[a,b]});job=wait(client,r.json()['id'])
    assert job['status']=='failed' and job['progress']==4
    assert [p['status'] for p in job['paper_results']]==['failed','done']
    assert job['paper_results'][0]['failed_page']==2
    assert client.get(f'/api/papers/{b}/translations/zh?page=3').json()['translation']
    calls.clear()
    def recovered(messages,**kwargs):calls.append(messages[-1]['content']);return '恢复后译文。'
    monkeypatch.setattr(document_ops,'complete_messages',recovered)
    assert client.post('/api/jobs/'+job['id']+'/resume').status_code==202
    job=wait(client,job['id']);assert job['status']=='done' and job['progress']==5,job
    assert len(calls)==1 and 'Alpha page 2' in calls[0]
    assert all(p['status']=='done' for p in job['result']['papers'])


def test_batch_translation_range_and_all_selected_papers_locked(client,monkeypatch):
    a=upload_pages(client,2,'Alpha');b=upload_pages(client,3,'Beta')
    entered=threading.Event();release=threading.Event()
    def translated(*args,**kwargs):entered.set();release.wait(3);return '指定页译文。'
    monkeypatch.setattr(document_ops,'complete_messages',translated)
    r=client.post('/api/library/translate-batch',json={'paper_ids':[a,b],'mode':'range','start':2,'end':2,'target':'en'})
    assert r.status_code==202,r.text
    try:
        assert entered.wait(2)
        assert client.delete('/api/papers/'+b).status_code==409
        assert client.post(f'/api/papers/{b}/translate-document',json={'target':'en'}).status_code==409
        assert client.post(f'/api/papers/{b}/ocr').status_code==409
    finally:release.set()
    job=wait(client,r.json()['id']);assert job['status']=='done' and job['progress']==2,job
    for pid in [a,b]:
        assert not client.get(f'/api/papers/{pid}/translations/en?page=1').json()['translation']
        assert client.get(f'/api/papers/{pid}/translations/en?page=2').json()['translation']
