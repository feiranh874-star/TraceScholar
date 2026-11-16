"""Reproducible official-package geometry, retrieval, graph and book benchmark.
No model calls by default. --live explicitly enables small paid model checks.
"""
from __future__ import annotations
import argparse,json,os,re,resource,sys,tempfile,time
from pathlib import Path
BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from fastapi.testclient import TestClient
from app import papers
from app.main import create_app
from app.config import Settings

def norm(text):return re.sub(r'\W+','',text.casefold())
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-dir',type=Path,default=os.getenv('TRACESCHOLAR_SAMPLE_DIR'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--case-ids',nargs='+',help='Only the selected fine-grained cases')
    args=parser.parse_args()
    if not args.sample_dir or not args.sample_dir.is_dir():parser.error('Specify the official PDF directory')
    settings=Settings()
    if args.live:
        from evaluate_answers import load_settings
        settings=load_settings()
    report={'date':'2026-11-16','platform':sys.platform,'live':args.live,'fine_grained':[]}
    cases=json.loads((BACKEND/'tests/evaluation/fine_grained_cases.json').read_text())
    if args.case_ids:cases=[case for case in cases if case['id'] in args.case_ids]
    with tempfile.TemporaryDirectory(prefix='tracescholar-extended-') as tmp:
        papers.DATA_DIR=Path(tmp)
        with TestClient(create_app(settings)) as c:
            def upload(name):
                with (args.sample_dir/name).open('rb') as f:r=c.post('/api/papers',files={'file':(name,f,'application/pdf')})
                r.raise_for_status();return r.json()
            p=upload('1706.03762v7.pdf');pid=p['paper_id']
            t=c.get(f'/api/papers/{pid}/analysis/8').json()['tables'][0]
            rows={row[0]:row for row in t['rows'][1:]}
            report['table2']={'base':rows.get('Transformer (base model)'),'big':rows.get('Transformer (big)'), 'merged_cells':t.get('merged_cells')}
            assert report['table2']['base'][1:3]==['27.3','38.1']
            assert report['table2']['big'][1:3]==['28.4','41.8']
            for case in cases:
                r=c.post('/api/research/retrieve',json={'question':case['question'],'paper_ids':[pid],'limit':6})
                r.raise_for_status();hits=r.json()['items'];text=' '.join(h['text'] for h in hits)
                row={'id':case['id'],'pages':[h['source']['page_start'] for h in hits],
                     'page_hit':any(h['source']['page_start'] in case['pages'] for h in hits),
                     'fact_groups_found':sum(any(norm(v) in norm(text) for v in group) for group in case['facts']),
                     'fact_groups_total':len(case['facts'])}
                if args.live:
                    started=time.monotonic()
                    r=c.post('/api/research/answer',json={'question':case['question'],'paper_ids':[pid],'limit':6})
                    d=r.json();row['model']={'http_status':r.status_code,'seconds':round(time.monotonic()-started,2),'answer':d.get('answer'),'citations':[i['source']['page_start'] for i in d.get('citations',[])],'error':d.get('detail')}
                report['fine_grained'].append(row)
            ids=[pid]
            excluded={'1706.03762v7.pdf','1706.03762v1.pdf','1706.03762v1_img.pdf','UnderstandingDeepLearning_02_09_26_C.pdf'}
            for path in sorted(args.sample_dir.glob('*.pdf')):
                if path.name in excluded:continue
                ids.append(upload(path.name)['paper_id'])
                if len(ids)==20:break
            started=time.monotonic();r=c.post('/api/library/graph',json={'paper_ids':ids});r.raise_for_status();g=r.json()
            report['graph']={'nodes':len(g['nodes']),'edges':len(g['edges']),'seconds':round(time.monotonic()-started,3),'pagerank_sum':sum(n['pagerank'] for n in g['nodes'])}
            started=time.monotonic();book=upload('UnderstandingDeepLearning_02_09_26_C.pdf');elapsed=time.monotonic()-started
            r=c.post('/api/research/retrieve',json={'question':'diffusion models denoising score matching','paper_ids':[book['paper_id']],'limit':6});r.raise_for_status()
            report['book']={'pages':book['page_count'],'chunks':book['chunk_count'],'parse_seconds':round(elapsed,3),'retrieved_pages':[h['source']['page_start'] for h in r.json()['items']]}
            peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report['process_peak_bytes']=peak if sys.platform=='darwin' else peak*1024
    report['notice']='Local sampled benchmark, not cloud memory guarantee or final answer accuracy. Page/fact metrics measure retrieval; table geometry is heuristic. No scan table or image understanding.'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
