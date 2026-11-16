"""Source-backed reviews, future-work evidence timelines and explicit diagram scripts."""
from __future__ import annotations
import re
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app import papers
from app.library_tools import Selection, citation_graph
from app.retrieval import search_evidence, tokenize
from app.models import RetrievalEvidenceRecord, SourceReference
from app.research import _answer_with_evidence
from app.document_analysis import references, source

router=APIRouter(prefix='/api/library',tags=['research-extensions'])

class Review(Selection):
    topic:str=Field(min_length=2,max_length=500)
    generate:bool=False

@router.post('/review')
def review(body:Review,request:Request):
    graph=citation_graph(Selection(paper_ids=body.paper_ids))
    evidence=[];timeline=[]
    for pid in body.paper_ids:
        metadata=papers._load_paper(pid)
        hits,_=search_evidence(body.topic,paper_ids=[str(pid)],limit=2,relax_query_coverage=True)
        evidence.extend(hits)
        candidates=[]
        for path in sorted((papers._papers_dir()/str(pid)/'pages').glob('*.json')):
            p=papers._read_metadata(path) or {};text=p.get('text','')
            for match in re.finditer(r'future\s+(?:work|research|direction)|limitation|further\s+(?:work|research)|未来工作|局限',text,re.I):
                candidates.append({'text':text[max(0,match.start()-150):match.end()+750],
                                   'source':source(metadata,p['page'])})
        identifier=(metadata.get('identifiers') or {}).get('arxiv_id','')
        date=('20'+identifier[:2]+'-'+identifier[2:4]) if re.match(r'^\d{4}\.',identifier) else None
        timeline.append({'paper_id':str(pid),'title':metadata.get('title') or metadata['filename'],
                         'arxiv_month':date,'future_work':candidates[:5]})
    timeline.sort(key=lambda p:p['arxiv_month'] or '9999')
    rank=sorted(graph['nodes'],key=lambda n:n['pagerank'],reverse=True)
    result={'topic':body.topic,'graph':graph,'central_papers':rank[:5],'timeline':timeline,
            'evidence':[e.model_dump() for e in evidence], 'draft':None,
            'notice':'时间按 arXiv 标识月份估计，不是首次发表日期。Future Work 为原文候选；发现较新论文不等于旧问题已被解决，需逐条验证。'}
    if body.generate:
        if not evidence:raise HTTPException(422,'没有可用证据。')
        result['draft']=_answer_with_evidence('围绕主题“'+body.topic+'”生成简短文献综述，按研究方法、已报告结果、局限和待验证方向组织。'
              '不要宣称某想法无人研究，不把 PageRank 当作领域公认地位。',evidence,len(evidence),request.app.state.settings).model_dump()
    return result

class Diagram(BaseModel):
    title:str=Field(min_length=2,max_length=150)
    nodes:list[str]=Field(min_length=2,max_length=20)
    edges:list[tuple[int,int]]=Field(max_length=60)

@router.post('/diagram')
def diagram(body:Diagram):
    if any(not n.strip() or len(n)>120 for n in body.nodes):raise HTTPException(422,'节点名称需为 1–120 字符。')
    if any(a<0 or b<0 or a>=len(body.nodes) or b>=len(body.nodes) for a,b in body.edges):raise HTTPException(422,'连线引用了不存在的节点。')
    import json
    clean=lambda value:re.sub(r'[\[\]{}<>"`\\\r\n]',' ',value).strip()
    mermaid='flowchart LR\n'+'\n'.join(f'  N{i}["{clean(n)}"]' for i,n in enumerate(body.nodes))+'\n'+'\n'.join(f'  N{a} --> N{b}' for a,b in body.edges)
    dot='digraph Research {\n'+'\n'.join(' N'+str(i)+' [label='+json.dumps(n,ensure_ascii=False)+'];' for i,n in enumerate(body.nodes))+'\n'+'\n'.join(f' N{a} -> N{b};' for a,b in body.edges)+'\n}'
    return {'title':body.title,'mermaid':mermaid,'graphviz':dot,'notice':'按照你提供的节点与连接生成；是待验证设计，不是已完成实验。脚本仅下载，不在服务端执行。'}

@router.get('/reference-context/{paper_id}')
def reference_context(paper_id:uuid.UUID):
    metadata=papers._load_paper(paper_id);items=references(paper_id)
    pages=[papers._read_metadata(path) or {} for path in sorted((papers._papers_dir()/str(paper_id)/'pages').glob('*.json'))]
    ref_start=min((e['page'] for e in items),default=0)
    for entry in items:
        contexts=[]
        for page in pages:
            if page.get('page',0)>ref_start:continue
            text=page.get('text','')
            if page.get('page',0)==ref_start:
                text=re.split(r'(?im)^\s*(?:References|Bibliography)\s*$',text,maxsplit=1)[0]

            for m in re.finditer(r'\['+re.escape(entry['label'])+r'\]',text):
                contexts.append({'text':text[max(0,m.start()-180):m.end()+220],'page':page['page']})
        entry.update(contexts=contexts[:8],mention_count=len(contexts),assessment='正文引用上下文已找到' if contexts else '未匹配到独立编号引用，可能是合并引用或抽取遗漏')
    last_ref=max((r['page'] for r in items),default=metadata['page_count'])
    appendices=[{'page':p['page'],'title':next(iter(p.get('text','').splitlines()),'附录候选')[:150],
                 'text':p.get('text','')[:700],'source':source(metadata,p['page'])}
                for p in pages if p.get('page',0)>last_ref and p.get('text','').strip()]
    return {'items':items,'appendix_candidates':appendices,'notice':'展示引用上下文供人工筛选；出现次数不等于引用质量，未自动判定应付式引用。参考文献之后的页面仅标记为附录候选。'}

class ClaimReview(Selection):
    claim:str=Field(min_length=5,max_length=600)
    generate:bool=False

@router.post('/claim-review')
def claim_review(body:ClaimReview,request:Request):
    """Check a research direction against selected local papers, never certify novelty."""
    evidence=[]
    for pid in body.paper_ids:
        hits,_=search_evidence(body.claim,paper_ids=[str(pid)],limit=2,relax_query_coverage=True)
        evidence.extend(hits)
    result={'claim':body.claim,'evidence':[e.model_dump() for e in evidence],'assessment':None,
            'scope':'仅限所选本地论文，不能证明无人研究或全球首次。',
            'checklist':['问题设置和输入条件是否相同','是否使用可比数据集、指标与基线','论文报告的是实验结果还是 Future Work','支持、部分支持、反例与证据不足分别列出','在 arXiv 检索后先导入新论文，再重新核对']}
    if body.generate:
        if not evidence:raise HTTPException(422,'没有可核对的证据，请先导入或检索相关论文。')
        result['assessment']=_answer_with_evidence('请审查这条研究方向：'+body.claim+
            '。只核对提供的论文证据。按支持、部分支持、反例、证据不足四类说明，找不到的类别写未发现。'
            '区分作者计划与已报告实验，对条件、数据、指标不一致的情况明确说明。每条结论附原文引用。'
            '最后列仍需查证的问题，禁止宣称全球首次、无人研究或已经证明新颖性。',evidence,len(evidence),request.app.state.settings).model_dump()
    return result

@router.get('/code-links/{paper_id}')
def code_links(paper_id:uuid.UUID):
    metadata=papers._load_paper(paper_id);items=[];seen=set()
    # Read local pages once. Joined PDF lines are a common source of broken links.
    for path in sorted((papers._papers_dir()/str(paper_id)/'pages').glob('*.json')):
        page=papers._read_metadata(path) or {};text=page.get('text','')
        joined=re.sub(r'(https://github\.com/)\s+',r'\1',text)
        for match in re.finditer(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',joined):
            url=match.group(0).rstrip('.')
            if url in seen:continue
            seen.add(url);items.append({'url':url,'source':source(metadata,page['page']),
                'context':joined[max(0,match.start()-100):match.end()+100],
                'verified':False})
    return {'items':items,'notice':'仅提取论文明确给出的 GitHub 仓库地址；未验证可用性、许可证、复现难度或质量。'}
