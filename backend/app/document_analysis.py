"""On-demand PDF layout, table, figure and citation evidence without image guessing."""
from __future__ import annotations
import csv
import io
import re
import threading
import uuid
import pymupdf as fitz
from fastapi import APIRouter, HTTPException, Query, Response
from app import papers

router=APIRouter(prefix='/api/papers',tags=['document-analysis'])
_SLOT=threading.BoundedSemaphore(1)
CAPTION=re.compile(r'^(Figure|Fig\.?|Table|图|表)\s*([A-Za-z]?\d+[A-Za-z]?)\s*[:.：]?\s*(.*)',re.I)
REF=re.compile(r'^\s*\[(\d{1,4})\]\s*(.*)')


def source(metadata,page,bbox=None):
    return {'paper_id':metadata['paper_id'],'work_id':metadata['work_id'],
            'version_label':metadata.get('version_label'),'page_start':page,'page_end':page,'bbox':bbox}


def references(paper_id):
    metadata=papers._load_paper(uuid.UUID(str(paper_id)))
    structure=papers._read_metadata(papers._papers_dir()/str(paper_id)/'structure.json') or {}
    starts=[s['page_start'] for s in structure.get('sections',[]) if s['title'].lower() in ('references','bibliography')]
    active=False; result=[]; current=None
    pages=[papers._read_metadata(path) or {} for path in sorted((papers._papers_dir()/str(paper_id)/'pages').glob('*.json'))]
    # Stop before unlabelled appendices: otherwise the last citation absorbs
    # all remaining figures and appendix prose. Cross-page entries with no
    # numbered reference on the following page need manual verification.
    last_numbered=max((p.get('page',0) for p in pages if any(REF.match(line) for line in p.get('text','').splitlines())),default=0)
    for page in pages:
        number=page.get('page',0)
        if last_numbered and number>last_numbered:break
        for line in page.get('text','').splitlines():
            if re.fullmatch(r'\s*(?:\d+[. ]+)?(?:References|Bibliography)\s*',line,re.I):
                active=True; continue
            if not active and starts and number>=min(starts): active=True
            if not active: continue
            if re.match(r'^\s*(?:[A-Z][. ]+)?Appendix\b',line): active=False; continue
            match=REF.match(line)
            if match:
                current={'label':match[1],'text':match[2],'page':number,'source':source(metadata,number)}
                result.append(current)
            elif current and line.strip() and not re.fullmatch(r'\d{1,4}',line.strip()): current['text']+=' '+line.strip()
    return result


def _lines(page):
    result=[]
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            spans=line['spans']; text=''.join(('^('+s['text']+')' if s['flags'] & 1 and s['text'].strip() else s['text']) for s in spans).strip()
            if text: result.append({'text':text,'bbox':list(line['bbox']),
                                    'fonts':[s['font'] for s in spans]})
    return result


def _horizontal_tables(page, lines, captions):
    """Recover sparse rows from repeated horizontal rules and native text fragments.

    Keep explicit merged ranges and never forward-fill missing experimental values.
    This is a geometry heuristic, not a general table recognition model.
    """
    rules=[]
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0]=='l' and abs(item[1].y-item[2].y)<.7 and abs(item[1].x-item[2].x)>100:
                rules.append((min(item[1].x,item[2].x),max(item[1].x,item[2].x),item[1].y))
    groups=[]
    for rule in sorted(rules,key=lambda r:r[2]):
        group=next((g for g in groups if abs(g[0][0]-rule[0])<3 and abs(g[0][1]-rule[1])<3),None)
        if group is None:groups.append([rule])
        elif all(abs(r[2]-rule[2])>1 for r in group):group.append(rule)
    result=[]
    for group in groups:
        if len(group)<3:continue
        left,right,top=group[0];bottom=group[-1][2];header_end=group[1][2]
        near=[c for c in captions if c['kind']=='table' and 0<top-c['bbox'][1]<150]
        if not near:continue
        caption=min(near,key=lambda c:abs(top-c['bbox'][3]))
        entries=[l for l in lines if l['bbox'][0]>=left-3 and l['bbox'][2]<=right+3 and l['bbox'][1]>=top-2 and l['bbox'][3]<=bottom+3]
        body=[l for l in entries if l['bbox'][1]>=header_end-2]
        rows=[]
        for entry in sorted(body,key=lambda l:(l['bbox'][1]+l['bbox'][3])/2):
            cy=(entry['bbox'][1]+entry['bbox'][3])/2
            row=next((r for r in rows if abs(r['y']-cy)<=3.3),None)
            if row is None:rows.append({'y':cy,'items':[entry]})
            else:row['items'].append(entry)
        if not rows:continue
        anchor=sorted(max(rows,key=lambda r:len(r['items']))['items'],key=lambda l:l['bbox'][0])
        if not 2<=len(anchor)<=30:continue
        centers=[(l['bbox'][0]+l['bbox'][2])/2 for l in anchor]
        boundaries=[left]+[(anchor[i]['bbox'][2]+anchor[i+1]['bbox'][0])/2 for i in range(len(anchor)-1)]+[right]
        headings=[[] for _ in anchor];merged=[];raw=[]
        for line in sorted((l for l in entries if l['bbox'][1]<header_end-2),key=lambda l:l['bbox'][1]):
            x0,_,x1,_=line['bbox'];cx=(x0+x1)/2
            overlap=[i for i in range(len(anchor)) if min(x1,boundaries[i+1])-max(x0,boundaries[i])>2]
            if not overlap:overlap=[min(range(len(anchor)),key=lambda i:abs(centers[i]-cx))]
            for i in overlap:headings[i].append(line['text'])
        values=[[' / '.join(dict.fromkeys(h)) or f'列 {i+1}' for i,h in enumerate(headings)]]
        for row in rows:
            cells=[None]*len(anchor);row_index=len(values)
            for line in sorted(row['items'],key=lambda l:l['bbox'][0]):
                x0,y0,x1,y1=line['bbox'];cx=(x0+x1)/2
                column=0 if x0<boundaries[1] else min(range(1,len(anchor)),key=lambda i:abs(centers[i]-cx))
                overlapping=[i for i in range(len(anchor)) if min(x1,boundaries[i+1])-max(x0,boundaries[i])>4]
                if len(overlapping)>1 and column!=0:
                    column=overlapping[0]
                    merged.append({'row':row_index,'columns':overlapping,'text':line['text']})
                cells[column]=(cells[column]+' '+line['text']) if cells[column] else line['text']
                raw.append({'row':row_index,'column':column,'text':line['text'],'bbox':line['bbox']})
            if any(cells):values.append(cells)
        if len(values)<3:continue
        result.append({'bbox':[left,top,right,bottom],'rows':values,'caption':caption['text'],
                       'label':caption['label'],'merged_cells':merged,'raw_cells':raw})
    return result


def analyze(paper_id,number):
    metadata=papers._load_paper(uuid.UUID(str(paper_id)))
    if not 1<=number<=metadata['page_count']: raise HTTPException(404,'页面不存在。')
    with fitz.open(papers._papers_dir()/str(paper_id)/'source.pdf') as doc:
        page=doc[number-1]; lines=_lines(page); tables=[]; figures=[]; equations=[]
        captions=[]
        for line in lines:
            match=CAPTION.match(line['text'])
            if match:
                captions.append({**line,'kind':'table' if match[1].lower() in ('table','表') else 'figure','label':match[1]+' '+match[2]})
        # Ruled and borderless tables need different strategies. Fall back only when ruled extraction finds none.
        found=page.find_tables().tables
        if not found and any(c['kind']=='table' for c in captions):
            found=page.find_tables(vertical_strategy='text',horizontal_strategy='text',min_words_vertical=3,min_words_horizontal=2).tables
        for i,table in enumerate(found[:15]):
            if table.row_count<2 or table.col_count<2 or table.col_count>40 or table.row_count>300: continue
            box=list(table.bbox)
            near=sorted((c for c in captions if c['kind']=='table'),key=lambda c:abs(c['bbox'][3]-box[1])+abs(c['bbox'][0]-box[0]))
            caption=near[0] if near and abs(near[0]['bbox'][3]-box[1])<200 else None
            rows=[[v if v is not None else None for v in row] for row in table.extract()]
            tables.append({'id':f'table-{i+1}','kind':'table','label':caption['label'] if caption else f'表格候选 {i+1}',
                'caption':caption['text'] if caption else '', 'bbox':box,'rows':rows,
                'cells':[list(c) if c else None for c in table.cells],
                'source':source(metadata,number,box),'method':'PDF 单元格布局提取',
                'verified':False,'notice':'自动提取待核对；空单元格或合并单元格不补值。无框线表可能包含正文误检。'})
        horizontal = _horizontal_tables(page,lines,captions)
        if horizontal:
            tables=[]
            for i,table in enumerate(horizontal):
                tables.append({**table,'id':f'table-{i+1}','kind':'table','source':source(metadata,number,table['bbox']),
                               'verified':False,'method':'横线边界 + 原生文字坐标行列匹配',
                               'notice':'几何提取待核对；合并范围另列，不把空值复制为实验数值。复杂多级表头请同时检查原图。'})
        image_boxes=[fitz.Rect(info['bbox']) for info in page.get_image_info() if fitz.Rect(info['bbox']).get_area()>1000]
        for c in (c for c in captions if c['kind']=='figure'):
            # Bound a caption-associated crop using preceding text and the column. Retain whole page as fallback.
            x0,y0,x1,y1=c['bbox']; half=page.rect.width/2
            col_left=0 if x0<half else half; col_right=half if x1<half else page.rect.width
            matching=[b for b in image_boxes if b.y1<=y0+10 and y0-b.y1<120 and b.x0<col_right and b.x1>col_left]
            if matching:
                box=matching[0]
                for b in matching[1:]: box|=b
                method='嵌入图片与邻近图注匹配'
            else:
                previous=[l['bbox'][3] for l in lines if l['bbox'][3]<y0-30 and l['bbox'][0]>=col_left and
                          l['bbox'][2]<=col_right and len(l['text'])>90]
                top=max(previous,default=max(0,y0-340))
                box=fitz.Rect(col_left,max(0,top+3),col_right,y0)
                method='图注邻近区域候选；可能包含相邻正文，请核对整页'
            if box.is_empty: box=page.rect
            box=box & page.rect
            figures.append({'id':f'figure-{len(figures)+1}','kind':'figure','label':c['label'],'caption':c['text'],
                'bbox':list(box),'source':source(metadata,number,list(box)),'method':method,'verified':False})
        for i,box in enumerate(image_boxes):
            if box.get_area()>page.rect.get_area()*.8 or any(fitz.Rect(f['bbox']).intersects(box) for f in figures): continue
            figures.append({'id':f'image-{i+1}','kind':'figure','label':f'图片候选 {i+1}','caption':'',
                'bbox':list(box),'source':source(metadata,number,list(box)),'method':'PDF 嵌入图片位置','verified':False})
        for line in lines:
            symbolic=any(re.search(r'Symbol|Math|CMSY|CMMI|CMEX',font,re.I) for font in line['fonts'])
            if symbolic or (re.search(r'[=∑∏∫√]',line['text']) and re.search(r'\(\d{1,3}\)\s*$',line['text'])):
                equations.append({'text':line['text'],'bbox':line['bbox'],'latex':None,
                    'source':source(metadata,number,line['bbox']),'notice':'公式候选原文；尚未转写为 LaTeX，需核对截图。'})
        words=[{'bbox':list(w[:4]),'text':w[4]} for w in page.get_text('words')[:18000]]
        markers=[]
        for line in lines:
            for match in re.finditer(r'\[(\d{1,4}(?:\s*[,–-]\s*\d{1,4})*)\]',line['text']):
                markers.append({'labels':re.findall(r'\d+',match[1]),'bbox':line['bbox'],'text':match[0]})
        institutions=[l for l in lines if number<=2 and re.search(r'University|Institute|Research|Google|Laborator|College|大学|学院|研究所',l['text'],re.I)]
        record=papers.get_paper_page(uuid.UUID(str(paper_id)),number)
        return {'paper_id':str(paper_id),'page':number,'width':page.rect.width,'height':page.rect.height,
                'tables':tables,'figures':figures,'equations':equations,'words':words,'citation_markers':markers,
                'institution_candidates':institutions,'scan':record.get('text_origin')=='ocr' or record.get('needs_ocr'),
                'notice':'扫描页可显示原图与 OCR 文字，复杂表格行列、图片理解及公式 LaTeX 需要后续视觉接口。'}


@router.get('/{paper_id}/analysis/{page_number}')
def page_analysis(paper_id:uuid.UUID,page_number:int):
    if not _SLOT.acquire(blocking=False): raise HTTPException(429,'正在解析其他页面，请稍后重试。')
    try: return analyze(paper_id,page_number)
    finally: _SLOT.release()


@router.get('/{paper_id}/references')
def paper_references(paper_id:uuid.UUID):
    return {'items':references(paper_id),'notice':'编号参考文献抽取；未匹配不代表原文没有引用。'}


@router.get('/{paper_id}/crop/{page_number}')
def crop(paper_id:uuid.UUID,page_number:int,x0:float=Query(...,ge=0),y0:float=Query(...,ge=0),
         x1:float=Query(...,gt=0),y1:float=Query(...,gt=0)):
    papers.get_paper_page(paper_id,page_number)
    with fitz.open(papers._papers_dir()/str(paper_id)/'source.pdf') as doc:
        page=doc[page_number-1];box=fitz.Rect(x0,y0,x1,y1)&page.rect
        if box.is_empty or box.width<1 or box.height<1: raise HTTPException(422,'截图区域无效。')
        scale=min(2,2000/max(box.width,box.height))
        image=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=box,alpha=False).tobytes('png')
    return Response(image,media_type='image/png')


@router.get('/{paper_id}/tables/{page_number}/{table_id}.csv')
def table_csv(paper_id:uuid.UUID,page_number:int,table_id:str):
    result=page_analysis(paper_id,page_number)
    table=next((t for t in result['tables'] if t['id']==table_id),None)
    if not table: raise HTTPException(404,'未找到表格。')
    out=io.StringIO();writer=csv.writer(out)
    # Spreadsheet programs must not execute document strings as formulas.
    writer.writerows([['\''+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in row] for row in table['rows']])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=table.csv'})

@router.get('/{paper_id}/positions/{page_number}')
def positions(paper_id:uuid.UUID,page_number:int,q:str=Query(min_length=1,max_length=200)):
    papers.get_paper_page(paper_id,page_number)
    with fitz.open(papers._papers_dir()/str(paper_id)/'source.pdf') as doc:
        page=doc[page_number-1]
        return {'boxes':[list(r) for r in page.search_for(q)[:100]],'width':page.rect.width,'height':page.rect.height,
                'notice':'仅定位 PDF 原生文字。扫描页暂无文字坐标，请对照整页。'}
