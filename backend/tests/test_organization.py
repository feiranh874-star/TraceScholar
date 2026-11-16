"""Annotations persist independently of indexed evidence; folders never own PDFs."""
import uuid
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app import papers
from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, 'DATA_DIR', tmp_path / 'data')
    return TestClient(create_app(Settings()))


def upload(client, notes=''):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 50), 'A scientific study of neural attention. Original verified source text.')
    content = document.tobytes()
    document.close()
    response = client.post('/api/papers', files={'file': ('paper.pdf', content, 'application/pdf')}, data={'notes': notes})
    assert response.status_code == 201, response.text
    return response.json()


def test_import_edit_search_and_preserve_original_evidence(client):
    p = upload(client, '老师推荐：待精读')
    pid = p['paper_id']
    assert p['notes'] == '老师推荐：待精读'
    assert client.get('/api/papers?q=待精读').json()['total'] == 1
    assert client.get('/api/papers?q=not present').json()['total'] == 0
    before = client.get(f'/api/papers/{pid}/pages/1').json()
    response = client.patch(f'/api/papers/{pid}/organization', json={'notes': '综述专用 <script>alert(1)</script>', 'collection_ids': []})
    assert response.status_code == 200, response.text
    assert client.get('/api/papers?q=待精读').json()['total'] == 0
    assert client.get('/api/papers?q=综述').json()['total'] == 1
    assert client.get(f'/api/papers/{pid}/pages/1').json() == before
    # Editing bibliographic metadata must not erase annotations.
    assert client.patch(f'/api/papers/{pid}', json={'title': 'Corrected title'}).json()['notes'].startswith('综述')
    # A new app instance reads the saved annotation, not process-local state.
    other = TestClient(create_app(Settings()))
    assert other.get(f'/api/papers/{pid}').json()['notes'].startswith('综述')


def test_many_to_many_folders_and_non_destructive_removal(client):
    p = upload(client)
    a = client.post('/api/library/collections', json={'name': '注意力'}).json()
    b = client.post('/api/library/collections', json={'name': '待精读'}).json()
    url = '/api/papers/' + p['paper_id'] + '/organization'
    assert client.patch(url, json={'notes': 'keep', 'collection_ids': [a['id'], b['id']]}).status_code == 200
    assert [c['paper_ids'] for c in client.get('/api/library/collections').json()['items']] == [[p['paper_id']], [p['paper_id']]]
    assert client.patch('/api/library/collections/' + a['id'], json={'name': '已精读'}).status_code == 200
    assert client.delete('/api/library/collections/' + a['id']).status_code == 204
    assert client.get('/api/papers/' + p['paper_id'] + '/source.pdf').status_code == 200
    assert client.get('/api/papers?q=keep').json()['total'] == 1
    assert client.patch(url, json={'notes': 'keep', 'collection_ids': []}).status_code == 200
    assert client.get('/api/library/collections').json()['items'][0]['paper_ids'] == []
    assert client.get('/api/papers').json()['total'] == 1


def test_invalid_memberships_and_names_are_rejected_without_changes(client):
    p = upload(client, 'original')
    url = '/api/papers/' + p['paper_id'] + '/organization'
    assert client.post('/api/library/collections', json={'name': '   '}).status_code == 422
    assert client.post('/api/library/collections', json={'name': 'reading'}).status_code == 201
    assert client.post('/api/library/collections', json={'name': 'READING'}).status_code == 409
    assert client.patch(url, json={'notes': 'changed', 'collection_ids': [str(uuid.uuid4())]}).status_code == 409
    assert client.patch(url, json={'notes': 'x' * 4001}).status_code == 422
    assert client.get('/api/papers/' + p['paper_id']).json()['notes'] == 'original'
    assert client.post('/api/papers', files={'file': ('a.pdf', b'%PDF-', 'application/pdf')}, data={'notes': 'x' * 4001}).status_code == 422


def test_deleted_paper_disappears_from_collection_without_deleting_collection(client):
    p = upload(client)
    c = client.post('/api/library/collections', json={'name': 'retain folder'}).json()
    assert client.patch('/api/papers/' + p['paper_id'] + '/organization', json={'collection_ids': [c['id']]}).status_code == 200
    assert client.delete('/api/papers/' + p['paper_id']).status_code == 204
    assert client.get('/api/library/collections').json()['items'][0]['paper_ids'] == []
