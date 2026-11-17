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


def test_folder_batch_keeps_destination_for_duplicates_and_version_confirmation(client):
    folder=client.post('/api/library/collections',json={'name':'直接上传'}).json()
    content=pdf('Attention networks combine reliable representations with original research evidence.')
    newer=client.post('/api/papers',files={'file':('1706.03762v7.pdf',content,'application/pdf')}).json()
    response=client.post('/api/library/batch-upload',files=[
        ('files',('same.pdf',content,'application/pdf')),
        ('files',('1706.03762v1.pdf',pdf('Attention networks combine revised representations with alternative research evidence.'),'application/pdf')),
        ('files',('2401.22222.pdf',pdf('A botanical study of seasonal flowers and ecological habitats.'),'application/pdf'))],
        data={'collection_id':folder['id'],'notes':'folder note'})
    assert response.status_code==202,response.text
    job=wait(client,response.json()['id'])
    assert job['payload']['collection_id']==folder['id']
    assert job['file_results'][0]['result']['duplicate']
    assert job['file_results'][0]['result']['collection_ids']==[folder['id']]
    assert job['file_results'][1]['status']==409
    assert job['file_results'][2]['result']['collection_ids']==[folder['id']]
    resolved=client.post(f"/api/jobs/{job['id']}/files/1/resolve",json={'action':'keep_both'})
    assert resolved.status_code==200,resolved.text
    assert resolved.json()['result']['collection_ids']==[folder['id']]
    library=client.get('/api/papers').json()['items']
    assert len(library)==3
    assert library[0]['paper_id']==resolved.json()['result']['paper_id']
    assert library[-1]['paper_id']==newer['paper_id']
    assert len(client.get('/api/library/collections').json()['items'][0]['paper_ids'])==3


def test_removed_folder_rejects_pending_batch_import_without_orphan_paper(client):
    folder=client.post('/api/library/collections',json={'name':'temporary'}).json()
    client.post('/api/papers',files={'file':('1706.03762v7.pdf',pdf('Attention networks combine reliable representations with original research evidence.'),'application/pdf')})
    response=client.post('/api/library/batch-upload',files=[('files',('1706.03762v1.pdf',pdf('Attention networks combine revised representations with alternative research evidence.'),'application/pdf'))],data={'collection_id':folder['id']})
    job=wait(client,response.json()['id'])
    assert job['file_results'][0]['status']==409
    assert client.delete('/api/library/collections/'+folder['id']).status_code==204
    assert client.post(f"/api/jobs/{job['id']}/files/0/resolve",json={'action':'keep_both'}).status_code==404
    assert client.get('/api/papers').json()['total']==1
    # A stale destination must also be rejected before a new batch stages files.
    assert client.post('/api/library/batch-upload',files=[('files',('a.pdf',pdf('Valid scientific original evidence.'),'application/pdf'))],data={'collection_id':folder['id']}).status_code==404
