"""Full-library searches must not silently drop papers beyond top-k snippets."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import papers
from app.main import app


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, 'DATA_DIR', tmp_path)
    client = TestClient(app)
    def add(text, section='Methods', archived=False, chunks=1):
        pid = str(uuid4())
        folder = tmp_path / 'papers' / pid
        folder.mkdir(parents=True)
        metadata = {'paper_id': pid, 'filename': pid + '.pdf', 'title': 'Study ' + pid,
                    'archived': archived, 'work_id': pid, 'sha256': '0'*64, 'page_count': 1, 'parse_status': 'ready', 'needs_ocr_pages': [], 'warnings': [], 'created_at': '2026-01-01T00:00:00Z'}
        (folder / 'metadata.json').write_text(json.dumps(metadata))
        structure = {'sections': [{'section_id': 's1', 'title': section}], 'chunks': [
            {'chunk_id': f'c{i}', 'text': text,
             'source': {'paper_id': pid, 'work_id': pid, 'page_start': i + 1,
                        'page_end': i + 1, 'section_id': 's1'}} for i in range(chunks)]}
        (folder / 'structure.json').write_text(json.dumps(structure))
        return pid
    return client, add


def test_all_papers_are_grouped_and_paginated_without_five_paper_cap(library):
    client, add = library
    expected = {add('Attention improves contextual representations in our experiment.', chunks=4) for _ in range(13)}
    add('Attention is All You Need.', section='References')
    add('Unrelated body.\nReferences\nAttention is All You Need.')
    add('Attention in archived work.', archived=True)
    response = client.post('/api/research/mentions', json={'question': '哪些论文提到过注意力？'})
    assert response.status_code == 200
    first = response.json()
    assert first['total_papers'] == 13
    assert first['scanned_papers'] == 15
    assert len(first['items']) == 10
    assert first['total_pages'] == 2
    assert all(g['matched_passages'] == 4 and len(g['items']) == 3 for g in first['items'])
    assert all(g['pages'] == [1, 2, 3, 4] for g in first['items'])
    second = client.post('/api/research/mentions', json={'question': '哪些论文提到过注意力？', 'page': 2}).json()
    assert len(second['items']) == 3
    assert {g['paper_id'] for g in first['items'] + second['items']} == expected


def test_body_before_reference_heading_is_retained(library):
    client, add = library
    pid = add('Attention improves language modeling.\nReferences\nUnrelated citation text.')
    data = client.post('/api/research/mentions', json={'question': 'attention'}).json()
    assert data['items'][0]['paper_id'] == pid
    assert 'citation' not in data['items'][0]['items'][0]['text']


def test_empty_query_and_no_matches_and_out_of_range_page(library):
    client, add = library
    add('A gradient optimizer updates weights.')
    assert client.post('/api/research/mentions', json={'question': '   '}).status_code == 422
    empty = client.post('/api/research/mentions', json={'question': 'attention', 'page': 99}).json()
    assert empty['total_papers'] == 0 and empty['items'] == [] and empty['page'] == 1
    assert client.post('/api/research/mentions', json={'question': 'gradient', 'page_size': 0}).status_code == 422


def test_comparison_still_has_a_bounded_explicit_scope(library):
    client, add = library
    ids = [add('Attention experiment.') for _ in range(31)]
    assert client.post('/api/research/compare', json={'question': 'compare attention', 'paper_ids': ids}).status_code == 422

def test_collection_scope_returns_only_members(library, tmp_path):
    client, add = library
    first, second = add('Attention in the selected collection.'), add('Attention outside the selected collection.')
    collection = client.post('/api/library/collections', json={'name': '12'}).json()
    # Attach only first paper through the public organizer endpoint.
    response = client.patch(f'/api/papers/{first}/organization', json={'collection_ids': [collection['id']], 'notes': ''})
    assert response.status_code == 200
    data = client.post('/api/research/mentions', json={'question': 'attention', 'collection_id': collection['id']}).json()
    assert data['collection_name'] == '12'
    assert data['total_papers'] == 1
    assert data['items'][0]['paper_id'] == first

@pytest.mark.parametrize('endpoint', ['mentions', 'retrieve', 'answer', 'agent'])
def test_empty_or_deleted_collection_never_falls_back_to_whole_library(library, endpoint):
    client, add = library
    add('Attention should not leak into an empty folder.')
    folder = client.post('/api/library/collections', json={'name': 'Empty'}).json()
    body = {'question': 'attention', 'collection_id': folder['id']}
    response = client.post('/api/research/' + endpoint, json=body)
    assert response.status_code == 200
    data = response.json()
    assert data['items'] == []
    if endpoint == 'mentions':
        assert data['scanned_papers'] == 0
    assert client.delete('/api/library/collections/' + folder['id']).status_code == 204
    assert client.post('/api/research/' + endpoint, json=body).status_code == 404


def test_collection_and_explicit_paper_are_not_silently_combined(library):
    client, add = library
    pid = add('Attention body.')
    folder = client.post('/api/library/collections', json={'name': '12'}).json()
    body = {'question': 'attention', 'collection_id': folder['id'], 'paper_ids': [pid]}
    assert client.post('/api/research/mentions', json=body).status_code == 422
    assert client.post('/api/research/retrieve', json=body).status_code == 422

@pytest.mark.parametrize('count', [6, 12, 30])
@pytest.mark.parametrize('endpoint', ['compare', 'agent'])
def test_comparison_covers_more_than_five_papers_even_with_legacy_evidence_limit(library, monkeypatch, count, endpoint):
    from app import research
    from app.config import Settings
    client, add = library
    ids = [add('Attention maps query and key vectors to weights.') for _ in range(count)]
    monkeypatch.setattr(client.app.state, 'settings', Settings(llm_api_key='test', llm_base_url='https://example.invalid', llm_model='fixture'))
    observed = []
    def generate(question, evidence, **kwargs):
        observed.extend(item.source.paper_id for item in evidence)
        return '；'.join(f'{item.paper_title} uses attention [E{i}]' for i, item in enumerate(evidence, 1))
    monkeypatch.setattr(research, 'generate_grounded_answer', generate)
    response = client.post('/api/research/' + endpoint, json={'question': 'Compare attention query key', 'paper_ids': ids})
    assert response.status_code == 200
    assert not response.json()['insufficient']
    assert set(observed) == set(ids)
    assert {item['source']['paper_id'] for item in response.json()['citations']} == set(ids)


def test_six_paper_comparison_rejects_answer_omitting_one_source(library, monkeypatch):
    from app import research
    from app.config import Settings
    client, add = library
    ids = [add('Attention maps query and key vectors to weights.') for _ in range(6)]
    monkeypatch.setattr(client.app.state, 'settings', Settings(llm_api_key='test', llm_base_url='https://example.invalid', llm_model='fixture'))
    monkeypatch.setattr(research, 'generate_grounded_answer', lambda *args, **kwargs: 'Attention [E1] [E2] [E3] [E4] [E5]')
    response = client.post('/api/research/compare', json={'question': 'Compare attention query key', 'paper_ids': ids})
    assert response.status_code == 502
    assert '每一篇所选论文' in response.json()['detail']
