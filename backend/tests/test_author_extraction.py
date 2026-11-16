"""Author header formats, safe repair and separation from table access failures."""
import uuid
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app import papers, ocr
from app.main import create_app
from app.config import Settings
from app.processing import extract_authors

TITLE = 'Proximal Policy Optimization Algorithms'
NAMES = ['John Schulman', 'Filip Wolski', 'Prafulla Dhariwal', 'Alec Radford', 'Oleg Klimov']
HEADER = TITLE + '\n' + ', '.join(NAMES) + '\nOpenAI\n{joschu, filip, prafulla, alec, oleg}@openai.com\nAbstract\nWe propose a method for policy optimization and evaluate experimental measurements.'

@pytest.mark.parametrize('header,expected', [
    (HEADER, NAMES),
    ('Methods for Reliable Research\nAlice Smith1, Bob Jones² and Chloé Martin†\nExample University, New York\nAbstract: Dana Stone is mentioned in the abstract.', ['Alice Smith', 'Bob Jones', 'Chloé Martin']),
    ('Methods for Reliable Research\nAlice Smith\nInstitute of Science\na@uni.edu\nBob Jones\nCollege of Engineering\nb@uni.edu\nAbstract\nA useful study.', ['Alice Smith', 'Bob Jones']),
    ('Methods for Reliable Research\nAlice Smith; Bob Jones\nAbstract\nCarol Brown\n1 Introduction\nDavid James', ['Alice Smith', 'Bob Jones']),
    ('Methods for Reliable Research\n张三、李四、王小明\n摘要：这是一项研究', ['张三', '李四', '王小明']),
    ('Methods for Reliable Research\nExample Research Institute\nDepartment of Computer Science\nContact: info@example.com\nAbstract\nAlice Smith', []),
    ('Methods for Reliable Research\nParameter Models\nAlice Smith, Bob Jones\nABSTRACT\nMeasurements follow.', ['Alice Smith','Bob Jones']),
    ('Methods for Reliable Research\nJeﬀRasley, Sam McCandlish\nAbstract\nResearch follows.', ['Jeff Rasley','Sam McCandlish']),
])
def test_header_formats_exclude_abstract_and_institutions(header, expected):
    title=TITLE if header.startswith(TITLE) else 'Methods for Reliable Research'
    assert extract_authors(header,title,None)==expected

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(papers,'DATA_DIR',tmp_path/'data')
    with TestClient(create_app(Settings())) as c:
        yield c

def upload(client):
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((40,40),HEADER,fontsize=9)
        doc.set_metadata({'title':TITLE})
        payload=doc.tobytes()
    response=client.post('/api/papers',files={'file':('1707.06347v2.pdf',payload,'application/pdf')},data={'notes':'待精读'})
    assert response.status_code==201,response.text
    return response.json()

def test_repair_missing_authors_preserves_notes_and_existing_metadata(client):
    paper=upload(client);pid=paper['paper_id']
    assert paper['authors']==NAMES
    metadata=papers._load_paper(uuid.UUID(pid));metadata.update(authors=[],author=None)
    papers._write_json(papers._metadata_path(uuid.UUID(pid)),metadata)
    result=client.post(f'/api/papers/{pid}/refresh-authors').json()
    assert result['updated'] and result['paper']['authors']==NAMES
    assert result['paper']['notes']=='待精读'
    client.patch(f'/api/papers/{pid}',json={'title':TITLE,'authors':['Manually Edited'],'abstract':'Edited abstract'})
    again=client.post(f'/api/papers/{pid}/refresh-authors').json()
    assert not again['updated'] and again['paper']['authors']==['Manually Edited']
    assert again['paper']['abstract']=='Edited abstract'

def test_repair_is_blocked_during_ocr(client):
    pid=upload(client)['paper_id'];ocr._ACTIVE.add(pid)
    try:
        assert client.post(f'/api/papers/{pid}/refresh-authors').status_code==409
    finally:
        ocr._ACTIVE.discard(pid)

def test_analysis_access_failure_is_not_empty_extraction(client):
    pid=upload(client)['paper_id']
    valid=client.get(f'/api/papers/{pid}/analysis/1')
    assert valid.status_code==200 and valid.json()['tables']==[]
    assert client.delete(f'/api/papers/{pid}').status_code==204
    assert client.get(f'/api/papers/{pid}/analysis/1').status_code==404
    assert client.post(f'/api/papers/{pid}/refresh-authors').status_code==404
