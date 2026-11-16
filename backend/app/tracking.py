"""Opt-in local arXiv polling and recommendation feedback; no external messages."""
from __future__ import annotations
import re
import threading
import time
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel,Field
from typing import Literal
from app import discovery, jobs, papers

router=APIRouter(prefix='/api/library',tags=['tracking'])
_LOCK=threading.RLock()
_RUN_LOCK=threading.Lock()

def _path():return papers.DATA_DIR/'tracking.json'
def _read():return papers._read_metadata(_path()) or {'subscriptions':[],'feedback':{}}
def _save(data):jobs.atomic(_path(),data)

class Subscription(BaseModel):
    query:str=Field(min_length=3,max_length=180)
    hours:int=Field(default=24,ge=6,le=720)

@router.get('/tracking')
def subscriptions():
    with _LOCK:return _read()

@router.post('/tracking',status_code=201)
def subscribe(body:Subscription):
    with _LOCK:
        data=_read()
        if len(data['subscriptions'])>=10:raise HTTPException(422,'最多追踪十个主题。')
        entry={'id':str(uuid.uuid4()),'query':body.query,'hours':body.hours,'enabled':True,'last_checked':None,'items':[]}
        data['subscriptions'].append(entry);_save(data)
        return entry

@router.delete('/tracking/{identifier}',status_code=204)
def unsubscribe(identifier:uuid.UUID):
    with _LOCK:
        data=_read();data['subscriptions']=[s for s in data['subscriptions'] if s['id']!=str(identifier)];_save(data)


def refresh(identifier=None):
    if not _RUN_LOCK.acquire(blocking=False):raise HTTPException(409,'正在检查其他追踪主题。')
    try:
        with _LOCK:entries=list(_read()['subscriptions'])
        changed=[]
        for entry in entries:
            if not entry.get('enabled') or (identifier and entry['id']!=str(identifier)):continue
            if not identifier and time.time()-max(entry.get('last_checked') or 0, entry.get('last_attempt') or 0)<entry['hours']*3600:continue
            try:
                # Use date-sorted all-field topic search rather than title-only exact matching.
                from urllib.parse import urlencode
                import xml.etree.ElementTree as ET
                words=re.findall(r'[\w-]+',entry['query'])[:12]
                url='https://export.arxiv.org/api/query?'+urlencode({'search_query':' AND '.join('all:'+w for w in words),'max_results':10,'sortBy':'submittedDate','sortOrder':'descending'})
                payload=discovery.fetch(url,1024*1024,{'export.arxiv.org'})
                root=ET.fromstring(payload);ns={'a':'http://www.w3.org/2005/Atom'};items=[]
                for node in root.findall('a:entry',ns):
                    aid=node.findtext('a:id','',ns).rstrip('/').split('/')[-1]
                    if not discovery.ARXIV_ID.fullmatch(aid):continue
                    summary=' '.join(node.findtext('a:summary','',ns).split())[:2000]
                    links=re.findall(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',summary)
                    items.append({'arxiv_id':aid,'title':' '.join(node.findtext('a:title','',ns).split()),'summary':summary,
                                  'published':node.findtext('a:published','',ns),'code_links':links,'url':'https://arxiv.org/abs/'+aid})
                update={'items':items,'last_checked':time.time(),'error':None}
            except Exception as error:
                update={'last_attempt':time.time(),'error':getattr(error,'detail','追踪更新失败，请稍后重试。')}
            with _LOCK:
                data=_read();target=next((s for s in data['subscriptions'] if s['id']==entry['id']),None)
                if target:target.update(update);_save(data);changed.append(target)
        return {'items':changed,'notice':'仅在服务运行且本地数据保留期间按间隔检查；免费实例休眠时不会运行。代码链接来自摘要，未核验代码质量。'}
    finally:_RUN_LOCK.release()

@router.post('/tracking/{identifier}/refresh')
def refresh_one(identifier:uuid.UUID):
    with _LOCK:
        if not any(s['id']==str(identifier) for s in _read()['subscriptions']):raise HTTPException(404,'追踪主题不存在。')
    return refresh(identifier)

class Feedback(BaseModel):
    paper_id:uuid.UUID
    vote:Literal['like','dislike','clear']

@router.post('/feedback')
def feedback(body:Feedback):
    papers._load_paper(body.paper_id)
    with _LOCK:
        data=_read()
        if body.vote=='clear':data['feedback'].pop(str(body.paper_id),None)
        else:data['feedback'][str(body.paper_id)]={'vote':body.vote,'at':time.time()}
        _save(data)
    return {'saved':True,'notice':'演示账号共享反馈；不是多用户个性化画像。'}


def start(stop):
    def loop():
        while not stop.wait(60):
            try:refresh()
            except Exception:pass
    thread=threading.Thread(target=loop,daemon=True,name='tracescholar-tracking');thread.start()
    return thread
