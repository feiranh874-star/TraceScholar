"""Bounded arXiv discovery/import through fixed public endpoints only."""
from __future__ import annotations
import io
import logging
import re
import socket
import ssl
import time
import unicodedata
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
logger = logging.getLogger(__name__)

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
    except urllib.error.HTTPError as error:
        logger.warning('arXiv upstream HTTP failure: host=%s status=%s', parsed.hostname, error.code)
        if error.code == 429:
            detail = 'arXiv 请求过于频繁，已被限流。请稍后重试，或到 arXiv 官网下载 PDF 后手动导入。'
        elif error.code == 404:
            detail = 'arXiv 未找到该论文资源，请核对论文标识或版本。'
        else:
            detail = 'arXiv 接口暂时无法处理请求，请稍后重试，或到 arXiv 官网下载 PDF 后手动导入。'
        raise HTTPException(502, detail) from error
    except (urllib.error.URLError,TimeoutError,OSError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        logger.warning('arXiv connection failure: host=%s reason=%s', parsed.hostname, type(reason).__name__)
        if isinstance(reason, TimeoutError):
            detail = 'arXiv 连接超时，20 秒内未完成响应。请稍后重试，或到 arXiv 官网下载 PDF 后手动导入。'
        elif isinstance(reason, ssl.SSLError):
            detail = 'arXiv 安全连接失败，请联系管理员检查服务器证书配置；也可到 arXiv 官网下载 PDF 后手动导入。'
        elif isinstance(reason, socket.gaierror):
            detail = 'arXiv 域名解析失败，服务器暂时无法连接论文网站。请稍后重试，或下载 PDF 后手动导入。'
        else:
            detail = 'arXiv 连接失败，服务器暂时无法访问论文网站。请稍后重试，或下载 PDF 后手动导入；本地问答不受影响。'
        raise HTTPException(502, detail) from error

class SearchRequest(BaseModel):
    query: str=Field(min_length=3,max_length=180)

class ImportRequest(BaseModel):
    arxiv_id: str=Field(min_length=9,max_length=30)
    conflict_action: str='ask'
    target_paper_id: str=''
    target_sha256: str=''

def _title_words(title: str) -> list[str]:
    # Quoted operators/punctuation never become part of the arXiv query language.
    stopwords={'a','an','the','is','are','all','you','of','for','to','and','in','on','with','from','by',
               'as','at','be','been','being','was','were','it','its','that','this','these','those','or','but','into','via'}
    words=re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', title), flags=re.UNICODE)
    return list(dict.fromkeys(word.casefold() for word in words if word.casefold() not in stopwords))[:15]


def _input_identifier(value: str) -> str | None:
    value = unicodedata.normalize('NFKC', value).strip()
    candidate = value
    if value.lower().startswith('arxiv:'):
        candidate = value.split(':', 1)[1].strip()
    elif re.match(r'https?://', value, re.I):
        try:
            parsed = urllib.parse.urlparse(value)
        except ValueError:
            raise HTTPException(422, 'arXiv 链接格式无效，请检查后重试。')
        if parsed.netloc.lower() not in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
            raise HTTPException(422, '请输入 arXiv 官方论文链接、编号或英文题名。')
        match = re.fullmatch(r'/(?:abs|pdf)/([^/]+)/?', parsed.path)
        candidate = match.group(1).removesuffix('.pdf') if match else ''
    elif not re.match(r'^\d{4}\.', value):
        return None
    if not ARXIV_ID.fullmatch(candidate):
        raise HTTPException(422, 'arXiv 编号格式无效，例如 1706.03762 或 arXiv:1706.03762v7。')
    return candidate


def _query_arxiv(params: dict) -> list[dict]:
    url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode(params)
    payload=fetch(url,1024*1024,{'export.arxiv.org'})
    try: root=ET.fromstring(payload)
    except ET.ParseError as error: raise HTTPException(502,'论文搜索接口返回了无法解析的数据。') from error
    if root.tag != '{http://www.w3.org/2005/Atom}feed':
        raise HTTPException(502,'论文搜索接口返回了异常响应，请稍后重试。')
    ns={'a':'http://www.w3.org/2005/Atom'}; items=[]
    entries = root.findall('a:entry',ns)
    for entry in entries:
        identifier=(entry.findtext('a:id','',ns)).rstrip('/').split('/')[-1]
        if '/api/errors' in entry.findtext('a:id','',ns):
            raise HTTPException(502,'论文搜索接口未能处理题名查询，请稍后重试或缩短题名。')
        if not ARXIV_ID.fullmatch(identifier): continue
        items.append({'arxiv_id':identifier,'title':' '.join(entry.findtext('a:title','',ns).split()),
                      'authors':[a.findtext('a:name','',ns) for a in entry.findall('a:author',ns)],
                      'summary':' '.join(entry.findtext('a:summary','',ns).split())[:1600],
                      'url':'https://arxiv.org/abs/'+identifier,'pdf_url':'https://arxiv.org/pdf/'+identifier})
    if entries and not items:
        raise HTTPException(502,'论文搜索接口返回了当前无法识别的论文记录，请前往 arXiv 官网核对。')
    return items


def _search_title(words: list[str]) -> list[dict]:
    return _query_arxiv({'search_query': ' AND '.join('ti:'+word for word in words), 'max_results': 5})


@router.post('/search')
def search(body: SearchRequest):
    identifier = _input_identifier(body.query)
    if identifier:
        items = _query_arxiv({'id_list': identifier, 'max_results': 1})
        items = [item for item in items if item['arxiv_id'] == identifier or (
            'v' not in identifier and re.sub(r'v\d+$', '', item['arxiv_id']) == identifier)]
        notice = '已按 arXiv 编号定位，请核对题名、作者及版本后再导入。' if items else 'arXiv 暂未返回该编号的论文记录，请核对编号及版本，并确认论文已公开；也可到 arXiv 官网核对。'
        return {'items':items, 'source':'arXiv identifier lookup', 'search_mode':'identifier', 'notice':notice}
    words = _title_words(body.query)
    if not words: raise HTTPException(422,'请输入有效论文题名。')
    items = _search_title(words)
    mode = 'title'
    # Keep at most six distinctive words when a long/incomplete title has no hit.
    # There is only one fallback request, and never a retry after an upstream error.
    candidates = sorted(range(len(words)), key=lambda index: -len(words[index]))
    chosen = sorted(index for index in candidates[:6] if len(words[index]) >= 4)
    fallback = [words[index] for index in chosen]
    if not items and 2 <= len(fallback) < len(words):
        time.sleep(3)  # Respect the public API's requested spacing between calls.
        items = _search_title(fallback)
        mode = 'keywords'
    normalize = lambda title: re.sub(r'\W+', '', title.casefold())
    items.sort(key=lambda item: normalize(item['title']) != normalize(body.query))
    notice = '已改用关键题名词检索，结果可能为相近论文，请核对完整题名、作者及版本后再导入。' if mode == 'keywords' else '请核对题名、作者及版本，再确认导入。'
    return {'items':items,'source':'arXiv title search','search_mode':mode,'notice':notice}

@router.post('/import', status_code=201)
def import_arxiv(body: ImportRequest):
    if not ARXIV_ID.fullmatch(body.arxiv_id): raise HTTPException(422,'无效的 arXiv 标识。')
    if body.conflict_action not in {'ask','keep_both','replace'}: raise HTTPException(422,'无效版本策略。')
    data=fetch('https://arxiv.org/pdf/'+body.arxiv_id,papers.MAX_UPLOAD_BYTES,{'arxiv.org'})
    return papers.upload_paper(UploadFile(file=io.BytesIO(data),filename=body.arxiv_id+'.pdf'),
                              body.conflict_action,body.target_paper_id,body.target_sha256)
