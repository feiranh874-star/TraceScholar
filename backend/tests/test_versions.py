import pymupdf
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import papers

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, 'DATA_DIR', tmp_path)
    return TestClient(app)

def pdf(text, title='Paper'):
    d = pymupdf.open()
    d.new_page().insert_textbox((30, 30, 570, 800), text, fontsize=10)
    d.set_metadata({'title': title})
    data = d.tobytes(); d.close()
    return data

BODY = ' '.join(f'Method {i} computes representation vector of sample {i} using calibrated attention.' for i in range(35))

def upload(client, data, filename='renamed.pdf', **fields):
    return client.post('/api/papers', files={'file': (filename, data, 'application/pdf')}, data=fields)

def test_content_overlap_works_without_title_or_identifiers(client):
    first = upload(client, pdf(BODY, 'Original')).json()
    r = upload(client, pdf(BODY + ' Further experiment.', 'Revised'), conflict_action='ask')
    assert r.status_code == 409
    assert r.json()['matches'][0]['basis'] == 'content_overlap'
    assert client.get('/api/papers').json()['total'] == 1
    kept = upload(client, pdf(BODY + ' Further experiment.', 'Revised'), conflict_action='keep_both')
    assert kept.status_code == 201
    assert kept.json()['work_id'] == first['work_id']

def test_unrelated_content_is_not_merged(client):
    upload(client, pdf(BODY))
    other = pdf(' '.join(f'Botanical soil cultivation species {i} habitat climate taxonomy.' for i in range(40)), 'Other')
    assert upload(client, other, conflict_action='ask').status_code == 201

def test_replacement_requires_current_target_and_preserves_old_citations(client):
    latest = upload(client, pdf(BODY), filename='1706.03762v7.pdf').json()
    old = pdf(BODY + ' Revision note.')
    r = upload(client, old, filename='1706.03762v1.pdf', conflict_action='ask')
    assert r.json()['recommendation'] == 'keep_existing_newer'
    bad = upload(client, old, filename='1706.03762v1.pdf', conflict_action='replace', target_paper_id=latest['paper_id'], target_sha256='stale')
    assert bad.status_code == 409
    good = upload(client, old, filename='1706.03762v1.pdf', conflict_action='replace', target_paper_id=latest['paper_id'], target_sha256=latest['sha256'])
    assert good.status_code == 201
    assert client.get('/api/papers').json()['total'] == 1
    assert client.get(f"/api/papers/{latest['paper_id']}/pages/1").status_code == 200
    assert good.json()['work_id'] == latest['work_id']
