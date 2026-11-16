"""Evidence-backed citation graph, lexical recommendations and outline planning."""
from __future__ import annotations
import math
import re
import uuid
from collections import Counter
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from app import papers
from app.models import RetrievalEvidenceRecord, SourceReference
from app.retrieval import tokenize, search_evidence
from app.research import _answer_with_evidence

router = APIRouter(prefix='/api/library', tags=['library-tools'])

class Selection(BaseModel):
    paper_ids: list[uuid.UUID] = Field(min_length=1, max_length=30)
    @field_validator('paper_ids')
    @classmethod
    def unique(cls, ids):
        if len(ids)!=len(set(ids)): raise ValueError('不能重复选择论文')
        return ids

class OutlineRequest(Selection):
    paper_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    idea: str = Field(min_length=3, max_length=500)
    generate: bool = False


def _selected(ids):
    return [papers._load_paper(uuid.UUID(str(pid))) for pid in ids]


def _pages(metadata):
    return [papers._read_metadata(p) or {} for p in sorted(
        (papers._papers_dir()/metadata['paper_id']/'pages').glob('*.json'))]


def _reference_pages(metadata):
    active = False
    result = []
    for page in _pages(metadata):
        text = page.get('text', '')
        match = re.search(r'(?:^|\n)\s*(?:\d+[. ]+)?(?:References|Bibliography)\s*\n', text, re.I)
        if match: active = True; text = text[match.end():]
        if active:
            stop = re.search(r'(?:^|\n)\s*(?:[A-Z][. ]+)?Appendix(?:\s|$)',text)
            if stop: text = text[:stop.start()]
            result.append({'page': page['page'], 'text': text})
            if stop: break
    return result


def _compact(text):
    return re.sub(r'[^a-z0-9\u3400-\u9fff]', '', text.casefold())


@router.post('/graph')
def citation_graph(body: Selection):
    metadata = _selected(body.paper_ids)
    nodes = [{'id': m['paper_id'], 'title': m.get('title') or m['filename'],
              'version': m.get('version_label'), 'incoming': 0, 'pagerank': 0.0} for m in metadata]
    edges = []
    for source in metadata:
        references = _reference_pages(source)
        for target in metadata:
            if source['work_id'] == target['work_id']: continue
            title = target.get('title') or ''
            if len(title)<10 or len(title.split())<2: continue
            for entry in references:
                if _compact(title) in _compact(entry['text']):
                    # Keep the actual matching bibliography page as the evidence anchor.
                    text = entry['text']
                    lines = text.splitlines()
                    best = next((i for i in range(len(lines)) if _compact(title) in _compact(' '.join(lines[i:i+5]))),0)
                    edges.append({'source': source['paper_id'], 'target': target['paper_id'],
                                  'page': entry['page'], 'evidence': '\n'.join(lines[best:best+6])[:1400],
                                  'method': 'bibliography_title_match'})
                    break
    ranks = {n['id']:1/len(nodes) for n in nodes}
    outgoing=Counter(e['source'] for e in edges)
    incoming=Counter(e['target'] for e in edges)
    for _ in range(40):
        dangling = sum(value for key,value in ranks.items() if not outgoing[key])
        new = {key:(.15+.85*dangling)/len(nodes) for key in ranks}
        for edge in edges: new[edge['target']] += .85*ranks[edge['source']]/outgoing[edge['source']]
        ranks=new
    for node in nodes: node.update(pagerank=round(ranks[node['id']],6),incoming=incoming[node['id']])
    return {'nodes': nodes,'edges': edges,'scope': '当前所选文献子图；未匹配不代表不存在引用。中心性不是领域公认影响力。',
            'method': '参考文献区题名匹配 + PageRank(d=0.85)，不生成模型猜测边'}


@router.get('/recommendations/{paper_id}')
def recommendations(paper_id: uuid.UUID):
    anchor = papers._load_paper(paper_id)
    records = papers._all_metadata()
    if not any(m['paper_id']==str(paper_id) for m in records): records.append(anchor)
    counters = {m['paper_id']: Counter(t for t in tokenize((m.get('title') or '')+' '+(m.get('abstract') or '')) if len(t)>2) for m in records}
    df=Counter(t for c in counters.values() for t in c)
    idf={t: math.log((len(records)+1)/(count+1))+1 for t,count in df.items()}
    vectors={pid:{t:count*idf[t] for t,count in c.items()} for pid,c in counters.items()}
    a=vectors[str(paper_id)]; norm_a=math.sqrt(sum(v*v for v in a.values()))
    from app.tracking import _read
    feedback = _read().get('feedback', {})
    result=[]
    for m in records:
        if m['work_id']==anchor['work_id']: continue
        if feedback.get(m['paper_id'], {}).get('vote') == 'dislike': continue
        b=vectors[m['paper_id']]; shared=set(a)&set(b)
        score=sum(a[t]*b[t] for t in shared)/max(1e-12,norm_a*math.sqrt(sum(v*v for v in b.values())))
        if score<=0: continue
        terms=sorted(shared,key=lambda t:a[t]*b[t],reverse=True)[:6]
        code_links = re.findall(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', m.get('abstract') or '')
        result.append({'paper': papers._public_paper(m),'score':round(score,4), 'shared_terms':terms,
                       'feedback':feedback.get(m['paper_id'],{}).get('vote'),'code_links':code_links,
                       'reason':'题名/摘要中的共同术语：'+', '.join(terms)})
    return {'items': sorted(result,key=lambda m:(m['feedback']=='like',bool(m['code_links']),m['score']),reverse=True)[:5],
            'method':'本地题名/摘要 TF-IDF；排除不相关反馈，优先有帮助及摘要有代码线索的相关项。共享演示反馈不是多用户画像，代码链接未做质量保证。'}


@router.post('/outline')
def outline(body: OutlineRequest, request: Request):
    metadata=_selected(body.paper_ids)
    sources=[]
    for m in metadata:
        items,_=search_evidence(body.idea,paper_ids=[m['paper_id']],limit=2)
        structure=papers._read_metadata(papers._papers_dir()/m['paper_id']/'structure.json') or {}
        sections={section['section_id']:section['title'] for section in structure.get('sections',[])}
        abstract=next((chunk for chunk in structure.get('chunks',[])
                       if sections.get(chunk['source'].get('section_id'),'').casefold()=='abstract'),None)
        seed=abstract or next(iter(structure.get('chunks',[])),None)
        if seed and not any(item.evidence_id==seed['chunk_id'] for item in items):
            items.insert(0,RetrievalEvidenceRecord(evidence_id=seed['chunk_id'],text=seed['text'],
                source=SourceReference.model_validate(seed['source']),filename=m['filename'],paper_title=m.get('title'),
                section_title=sections.get(seed['source'].get('section_id'))))
        sources.extend(items)
    if not sources: raise HTTPException(422,'所选论文没有可用正文，请先完成解析或 OCR。')
    references=[{'label':f'R{i}', 'paper_id':m['paper_id'],'title':m.get('title') or m['filename'],
                 'authors':m.get('authors',[]),'arxiv_id':(m.get('identifiers') or {}).get('arxiv_id'),
                 'doi':(m.get('identifiers') or {}).get('doi'), 'version':m.get('version_label')} for i,m in enumerate(metadata,1)]
    result={'idea':body.idea,'sections':[
        {'title':'Abstract','guidance':'填写研究问题、拟议方法与计划；未开展实验的结果标记待验证。'},
        {'title':'Introduction','guidance':'说明问题与动机，将事实论述关联到下方真实来源。'},
        {'title':'Related Work','guidance':'按方法/任务对比已有工作，逐条核对证据，避免代写实验结论。'},
        {'title':'Method / Evaluation Plan','guidance':'描述拟议方法、对照组、数据与评价指标；这些是计划，不是现有结果。'}],
        'references':references,'evidence':[x.model_dump() for x in sources],
        'mermaid':'flowchart LR\n  A[Local Papers] --> B[Evidence Retrieval]\n  B --> C[Source Validation]\n  C --> D[Research Outline]\n  D --> E[Human Verification]',
        'draft':None}
    if body.generate:
        answer=_answer_with_evidence('请整理所选论文的中文综述提纲，研究主题只是组织方向，不要求原论文已解决该主题。用 Abstract、Introduction、Related Work、待验证计划四个小节。'
                                    '每个小节简短描述证据支持的内容，未支持的细节单独标待验证。禁止编造参考文献或实验；每个已有工作论述附 [E数字]。研究主题：'+body.idea,
                                    sources,len(sources),request.app.state.settings,answer_mode='general')
        result['draft']=answer.model_dump()
    return result
