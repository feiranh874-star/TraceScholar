"""User annotations and many-to-many logical collections, separate from evidence."""
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from app import papers, jobs, ocr

router = APIRouter(prefix='/api', tags=['library-organization'])


class CollectionName(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator('name')
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('收藏夹名称不能为空')
        return value


class Organization(BaseModel):
    notes: str = Field(default='', max_length=4000)
    collection_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


def _path():
    papers._papers_dir()  # Ensure data directory exists on a new installation.
    return papers.DATA_DIR / 'collections.json'


def _collections():
    return (papers._read_metadata(_path()) or {}).get('items', [])


def _save(items):
    jobs.atomic(_path(), {'items': items})


def _find(items, collection_id):
    item = next((c for c in items if c['id'] == str(collection_id)), None)
    if item is None:
        raise HTTPException(404, '收藏夹不存在，请刷新后重试。')
    return item


@router.get('/library/collections')
def list_collections():
    with papers._STORE_LOCK:
        metadata = papers._all_metadata()
        return {'items': [{**c, 'paper_ids': [p['paper_id'] for p in metadata
                if c['id'] in p.get('collection_ids', [])]} for c in _collections()]}


@router.post('/library/collections', status_code=201)
def create_collection(body: CollectionName):
    with papers._STORE_LOCK:
        items = _collections()
        if len(items) >= 100:
            raise HTTPException(422, '最多建立 100 个收藏夹。')
        if any(c['name'].casefold() == body.name.casefold() for c in items):
            raise HTTPException(409, '已经有同名收藏夹。')
        item = {'id': str(uuid.uuid4()), 'name': body.name,
                'created_at': datetime.now(timezone.utc).isoformat()}
        _save([*items, item])
        return {**item, 'paper_ids': []}


@router.patch('/library/collections/{collection_id}')
def rename_collection(collection_id: uuid.UUID, body: CollectionName):
    with papers._STORE_LOCK:
        items = _collections()
        item = _find(items, collection_id)
        if any(c['id'] != str(collection_id) and c['name'].casefold() == body.name.casefold() for c in items):
            raise HTTPException(409, '已经有同名收藏夹。')
        item['name'] = body.name
        _save(items)
        return item


@router.delete('/library/collections/{collection_id}', status_code=204)
def delete_collection(collection_id: uuid.UUID):
    # Memberships are metadata references. Removing a folder never removes a PDF.
    with papers._STORE_LOCK:
        items = _collections()
        _find(items, collection_id)
        _save([c for c in items if c['id'] != str(collection_id)])


@router.patch('/papers/{paper_id}/organization')
def organize_paper(paper_id: uuid.UUID, body: Organization):
    with ocr._LOCK, jobs._LOCK, papers._STORE_LOCK:
        metadata = papers._load_paper(paper_id)
        if metadata.get('archived'):
            raise HTTPException(409, '请先恢复归档论文。')
        if str(paper_id) in ocr._ACTIVE or jobs.busy(paper_id):
            raise HTTPException(409, '论文任务正在运行，请完成后再整理。')
        valid_ids = {c['id'] for c in _collections()}
        ids = list(dict.fromkeys(str(i) for i in body.collection_ids))
        if any(i not in valid_ids for i in ids):
            raise HTTPException(409, '收藏夹已变化，请刷新后重试。')
        metadata.update(notes=body.notes.strip(), collection_ids=ids)
        jobs.atomic(papers._metadata_path(paper_id), metadata)
        return papers._public_paper(metadata)
