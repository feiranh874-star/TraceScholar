"""Bounded persistent local jobs. Completed steps survive process restarts."""
from __future__ import annotations
import json
import os
import threading
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException
from app import papers

router = APIRouter(prefix='/api/jobs', tags=['jobs'])
_LOCK = threading.RLock()
_ACTIVE = set()
_SLOT = threading.BoundedSemaphore(2)


def atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def directory():
    value = papers.DATA_DIR / 'jobs'
    value.mkdir(parents=True, exist_ok=True)
    return value


def load(identifier):
    record = papers._read_metadata(directory() / (str(uuid.UUID(str(identifier)))+'.json'))
    if not record:
        raise HTTPException(404, '任务不存在。')
    if record['status'] in ('queued', 'running') and record['id'] not in _ACTIVE:
        record['status'] = 'interrupted'
        record['message'] = '服务已重启，可继续未完成步骤。'
    return record


def save(record):
    record['updated_at'] = time.time()
    atomic(directory() / (record['id']+'.json'), record)


def busy(paper_id):
    return any((r := papers._read_metadata(directory()/(identifier+'.json')))
               and str(paper_id) in r.get('paper_ids', []) for identifier in tuple(_ACTIVE))


def launch(kind, paper_ids, payload, runner, *, identifier=None):
    with _LOCK:
        existing = load(identifier) if identifier else None
        ids = [str(p) for p in paper_ids]
        if existing and existing['id'] in _ACTIVE:
            raise HTTPException(409, '任务正在运行。')
        if any(busy(pid) for pid in ids):
            raise HTTPException(409, '所选论文已有后台任务，请等待完成。')
        if not _SLOT.acquire(blocking=False):
            raise HTTPException(429, '后台任务已满，请稍后重试。')
        record = existing or {'id':str(uuid.uuid4()), 'kind':kind,'paper_ids':ids,'payload':payload,
                              'created_at':time.time(),'completed':[], 'result':None}
        record.update(status='queued', message='', progress=len(record['completed']))
        try:
            save(record)
            _ACTIVE.add(record['id'])
        except Exception:
            _SLOT.release()
            raise
    def work():
        try:
            record['status']='running'; save(record)
            result = runner(record)
            record.update(status='done', result=result, message='任务完成。')
        except Exception as error:
            record.update(status='failed', message=getattr(error,'detail',None) or
                          (str(error) if isinstance(error,RuntimeError) else '任务未完成，可继续已保存步骤。'))
        finally:
            record['finished_at']=time.time()
            try:
                save(record)
            finally:
                with _LOCK:
                    _ACTIVE.discard(record['id'])
                _SLOT.release()
    thread=threading.Thread(target=work,daemon=True,name='tracescholar-job')
    try:
        thread.start()
    except Exception:
        with _LOCK: _ACTIVE.discard(record['id'])
        _SLOT.release()
        raise
    return record.copy()


@router.get('')
def list_jobs():
    records=[]
    for path in directory().glob('*.json'):
        try: records.append(load(path.stem))
        except (ValueError,HTTPException): continue
    return {'items':sorted(records,key=lambda r:r['created_at'],reverse=True)[:100]}


@router.get('/{identifier}')
def get_job(identifier: uuid.UUID):
    return load(identifier)
