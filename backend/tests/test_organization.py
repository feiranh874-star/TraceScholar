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


def upload(client, notes='', collection_id=''):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 50), 'A scientific study of neural attention. Original verified source text.')
    content = document.tobytes()
    document.close()
    response = client.post('/api/papers', files={'file': ('paper.pdf', content, 'application/pdf')}, data={'notes': notes, 'collection_id': collection_id})
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


def test_remove_one_membership_keeps_library_other_folder_notes_and_evidence(client):
    p = upload(client, 'keep my notes')
    pid = p['paper_id']
    a, b = [client.post('/api/library/collections', json={'name': name}).json()
            for name in ('folder 1', 'folder 2')]
    client.patch(f'/api/papers/{pid}/organization', json={
        'notes': 'keep my notes', 'collection_ids': [a['id'], b['id']]})
    page = client.get(f'/api/papers/{pid}/pages/1').json()
    pdf = client.get(f'/api/papers/{pid}/source.pdf').content
    url = f"/api/library/collections/{a['id']}/papers/{pid}"
    # A repeated click is safe and never changes the other folder.
    for _ in range(2):
        response = client.delete(url)
        assert response.status_code == 200
        assert response.json()['collection_ids'] == [b['id']]
    assert client.get('/api/papers').json()['total'] == 1
    assert client.get(f'/api/papers/{pid}').json()['notes'] == 'keep my notes'
    assert client.get(f'/api/papers/{pid}/pages/1').json() == page
    assert client.get(f'/api/papers/{pid}/source.pdf').content == pdf
    folders = {c['id']: c['paper_ids'] for c in client.get('/api/library/collections').json()['items']}
    assert folders == {a['id']: [], b['id']: [pid]}
    assert client.delete(f'/api/library/collections/{uuid.uuid4()}/papers/{pid}').status_code == 404


def test_upload_into_folder_is_in_library_and_duplicate_adds_only_membership(client):
    first = upload(client, 'original note')
    a, b = [client.post('/api/library/collections', json={'name': name}).json()
            for name in ('folder 1', 'folder 2')]
    second = upload(client, 'new note', a['id'])
    assert second['collection_ids'] == [a['id']]
    assert [p['paper_id'] for p in client.get('/api/papers').json()['items']] == [second['paper_id'], first['paper_id']]
    source = client.get(f"/api/papers/{second['paper_id']}/source.pdf").content
    files = {'file': ('same.pdf', source, 'application/pdf')}
    for _ in range(2):
        response = client.post('/api/papers', files=files, data={'collection_id': b['id'], 'notes': 'do not overwrite'})
        assert response.status_code == 200
        result = response.json()
        assert result['duplicate']
        assert result['collection_ids'] == [a['id'], b['id']]
        assert result['notes'] == 'new note'
        assert result['created_at'] == second['created_at']
    assert client.get('/api/papers').json()['total'] == 2
    assert client.post('/api/papers', files=files, data={'collection_id': str(uuid.uuid4())}).status_code == 404
    assert client.post('/api/papers', files=files, data={'collection_id': '../bad'}).status_code == 422
    assert client.get(f"/api/papers/{second['paper_id']}").json()['collection_ids'] == [a['id'], b['id']]
