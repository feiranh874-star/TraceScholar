"""Bounded arXiv discovery/import through fixed public endpoints only."""
from __future__ import annotations
import io
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import certifi
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from app import papers

router=APIRouter(prefix='/api/library',tags=['discovery'])
ARXIV_ID=re.compile(r'^\d{4}\.\d{4,5}(?:v\d+)?$')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError('Redirect refused')

def fetch(url: str, limit: int, allowed_hosts: set[str]) -> bytes:
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in allowed_hosts:
        raise HTTPException(422,'仅支持指定公开论文接口。')
    opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    try:
        with opener.open(urllib.request.Request(url,headers={'User-Agent':'TraceScholar/0.2 (research demo)'}),timeout=20) as response:
            result=response.read(limit+1)
        if len(result)>limit: raise HTTPException(413,'外部文件超过导入限制。')
        return result
    except (urllib.error.URLError,TimeoutError,OSError) as error:
        raise HTTPException(502,'arXiv 暂时不可用，请稍后重试或手动下载后导入；本地问答不受影响。') from error

class SearchRequest(BaseModel):
    query: str=Field(min_length=3,max_length=180)

class ImportRequest(BaseModel):
    arxiv_id: str=Field(min_length=9,max_length=30)
    conflict_action: str='ask'
    target_paper_id: str=''
    target_sha256: str=''

@router.post('/search')
def search(body: SearchRequest):
    # Tokenized title search prevents query syntax from becoming an unrestricted expression.
    stopwords={'a','an','the','is','are','all','you','of','for','to','and','in','on','with','from','by'}
    words=[word for word in re.findall(r'[\w-]+',body.query) if word.casefold() not in stopwords][:15]
    if not words: raise HTTPException(422,'请输入有效论文题名。')
    query=' AND '.join('ti:'+word for word in words)
    url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode({'search_query':query,'max_results':5})
    payload=fetch(url,1024*1024,{'export.arxiv.org'})
    try: root=ET.fromstring(payload)
    except ET.ParseError as error: raise HTTPException(502,'论文搜索接口返回了无法解析的数据。') from error
    ns={'a':'http://www.w3.org/2005/Atom'}; items=[]
    for entry in root.findall('a:entry',ns):
        identifier=(entry.findtext('a:id','',ns)).rstrip('/').split('/')[-1]
        if not ARXIV_ID.fullmatch(identifier): continue
        items.append({'arxiv_id':identifier,'title':' '.join(entry.findtext('a:title','',ns).split()),
                      'authors':[a.findtext('a:name','',ns) for a in entry.findall('a:author',ns)],
                      'summary':' '.join(entry.findtext('a:summary','',ns).split())[:1600],
                      'url':'https://arxiv.org/abs/'+identifier,'pdf_url':'https://arxiv.org/pdf/'+identifier})
    normalize = lambda title: re.sub(r'\W+', '', title.casefold())
    items.sort(key=lambda item: normalize(item['title']) != normalize(body.query))
    return {'items':items,'source':'arXiv title search','notice':'请核对题名、作者及版本，再确认导入。主题定时追踪请使用研究工作区。'}

@router.post('/import', status_code=201)
def import_arxiv(body: ImportRequest):
    if not ARXIV_ID.fullmatch(body.arxiv_id): raise HTTPException(422,'无效的 arXiv 标识。')
    if body.conflict_action not in {'ask','keep_both','replace'}: raise HTTPException(422,'无效版本策略。')
    data=fetch('https://arxiv.org/pdf/'+body.arxiv_id,papers.MAX_UPLOAD_BYTES,{'arxiv.org'})
    return papers.upload_paper(UploadFile(file=io.BytesIO(data),filename=body.arxiv_id+'.pdf'),
                              body.conflict_action,body.target_paper_id,body.target_sha256)
