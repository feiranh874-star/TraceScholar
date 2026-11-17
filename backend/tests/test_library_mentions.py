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
                    'archived': archived, 'work_id': pid}
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


def test_comparison_still_requires_small_explicit_scope(library):
    client, add = library
    ids = [add('Attention experiment.') for _ in range(6)]
    assert client.post('/api/research/compare', json={'question': 'compare attention', 'paper_ids': ids}).status_code == 422
