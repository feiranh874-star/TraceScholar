"""Batch import preserves annotations, source versions and per-file outcomes."""
import time
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app import papers, jobs, document_ops
from app.main import create_app
from app.config import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, 'DATA_DIR', tmp_path / 'data')
    with TestClient(create_app(Settings())) as client:
        yield client
    assert not jobs._ACTIVE


def pdf(text):
    document=pymupdf.open();page=document.new_page()
    page.insert_text((40,40), text)
    result=document.tobytes();document.close()
    return result


def wait(client, identifier):
    for _ in range(300):
        data=client.get('/api/jobs/'+identifier).json()
        if data['status'] not in ('queued','running'):
            # The final save happens immediately before active-slot release.
            with jobs._LOCK:
                if identifier not in jobs._ACTIVE: return data
        time.sleep(.01)
    pytest.fail('Batch task did not finish')


def test_mixed_files_duplicate_and_invalid_pdf_keep_per_file_results(client):
    source=pdf('An academic investigation into botanical research and seasonal variation.')
    original=client.post('/api/papers', files={'file':('2401.11111.pdf',source,'application/pdf')},data={'notes':'original note'}).json()
    response=client.post('/api/library/batch-upload',files=[
        ('files',('same.pdf',source,'application/pdf')),
        ('files',('2401.22222.pdf',pdf('A distinct study of superconductivity and calibrated experimental devices.'),'application/pdf')),
        ('files',('broken.pdf',b'not a PDF','application/pdf'))],data={'notes':'本批待精读'})
    assert response.status_code==202,response.text
    job=wait(client,response.json()['id'])
    assert job['status']=='done'
    entries=job['file_results']
    assert entries[0]['result']['duplicate']
    assert entries[1]['result']['notes']=='本批待精读'
    assert 400<=entries[2]['status']<500
    assert job['progress']==3 and job['current_file'] is None
    assert client.get('/api/papers/'+original['paper_id']).json()['notes']=='original note'
    assert client.get('/api/papers').json()['total']==2


def test_pending_version_keeps_notes_when_confirmed_and_never_replaces_newer(client):
    newer=client.post('/api/papers',files={'file':('1706.03762v7.pdf',pdf('Attention networks combine learned representations with neural research evidence.'),'application/pdf')}).json()
    response=client.post('/api/library/batch-upload',files=[('files',('1706.03762v1.pdf',pdf('Attention networks combine alternative representations with revised research evidence.'),'application/pdf'))],data={'notes':'旧版核对'})
    job=wait(client,response.json()['id'])
    assert job['file_results'][0]['status']==409
    assert client.get('/api/papers').json()['total']==1
    url=f"/api/jobs/{job['id']}/files/0/resolve"
    result=client.post(url,json={'action':'keep_both'})
    assert result.status_code==200,result.text
    assert result.json()['result']['notes']=='旧版核对'
    assert client.get('/api/papers/'+newer['paper_id']).status_code==200
    assert client.get('/api/papers').json()['total']==2
    assert client.post(url,json={'action':'keep_both'}).status_code==422


def test_total_size_rejected_without_staged_files(client,monkeypatch):
    content=pdf('Reliable original academic text for a storage boundary test.')
    monkeypatch.setattr(document_ops,'MAX_BATCH_UPLOAD_BYTES',len(content)+10)
    response=client.post('/api/library/batch-upload',files=[('files',('a.pdf',content,'application/pdf')),('files',('b.pdf',content,'application/pdf'))])
    assert response.status_code==413,response.text
    assert not list(jobs.directory().glob('*'))
    assert client.get('/api/papers').json()['total']==0


def test_resume_skips_successes_and_preserves_notes(client,monkeypatch):
    original_upload=papers.upload_paper;calls=[]
    def flaky(file,*args,**kwargs):
        calls.append(file.filename)
        if file.filename=='retry.pdf':
            file.file.close()
            raise document_ops.HTTPException(503,'Temporary failure')
        return original_upload(file,*args,**kwargs)
    monkeypatch.setattr(papers,'upload_paper',flaky)
    response=client.post('/api/library/batch-upload',files=[('files',('2401.12345.pdf',pdf('A calibrated scientific analysis of neural models and sample efficiency.'),'application/pdf')),('files',('retry.pdf',pdf('Distinct chemistry experiment reports temperature dependent material properties.'),'application/pdf'))],data={'notes':'retry note'})
    identifier=response.json()['id'];first=wait(client,identifier)
    assert first['status']=='failed' and first['completed']==[0]
    monkeypatch.setattr(papers,'upload_paper',original_upload)
    assert client.post('/api/jobs/'+identifier+'/resume',json={}).status_code==202
    second=wait(client,identifier)
    assert second['status']=='done'
    assert client.get('/api/papers').json()['total']==2
    assert all(p['notes']=='retry note' for p in client.get('/api/papers').json()['items'])
    assert calls.count('2401.12345.pdf')==1
