"""Conservative, offline lookup hints; these are not verified publication records."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit


# A venue may suggest a discovery platform, but never proves a matching paper exists there.
_SOURCES = [
    (r'\b(?:arxiv|CoRR)\b', 'arXiv / CoRR（预印本线索）', 'arXiv：按题名或 arXiv 编号检索'),
    (r'\bIEEE\b|ieeexplore\.ieee\.org', 'IEEE', 'IEEE Xplore：按题名或 DOI 检索'),
    (r'\bACM\b|dl\.acm\.org', 'ACM', 'ACM Digital Library：按题名或 DOI 检索'),
    (r'\bACL\b|\bEMNLP\b|\bNAACL\b|aclanthology\.org|Association for Computational Linguistics', 'ACL 系列会议', 'ACL Anthology：按题名检索'),
    (r'\b(?:NeurIPS|NIPS)\b|Advances in Neural Information Processing Systems', 'NeurIPS / NIPS', 'NeurIPS Proceedings：按题名检索'),
    (r'\bICML\b|\bPMLR\b|International Conference on Machine Learning', 'ICML / PMLR', 'PMLR：按题名检索会议论文集'),
    (r'\bICLR\b|openreview\.net|International Conference on Learning Representations', 'ICLR / OpenReview', 'OpenReview：按题名查找并核对论文版本'),
    (r'\b(?:CVPR|ICCV|ECCV)\b|openaccess\.thecvf\.com', '计算机视觉会议线索', 'CVF Open Access / 对应会议论文集：按题名检索'),
    (r'\bSpringer\b|link\.springer\.com', 'Springer', 'SpringerLink：按题名或 DOI 检索'),
    (r'\bElsevier\b|sciencedirect\.com', 'Elsevier', 'ScienceDirect：按题名或 DOI 检索'),
    (r'\bNature\b|nature\.com', 'Nature 相关条目线索', 'Nature 网站：用题名核对具体期刊'),
    (r'\bOpenAI\b|openai\.com', 'OpenAI 相关条目线索', 'OpenAI 官网研究或技术报告页面：按题名查找'),
]


def _author_line(text):
    """Skip obvious author lists without attempting to identify people with a model."""
    if re.search(r'\bet al\b', text, re.I):
        return True
    tokens=re.findall(r"[A-Za-zÀ-ž]+(?:[-’'][A-Za-zÀ-ž]+)*", text)
    name_like=tokens and all(t[0].isupper() or t.lower() in {'and','van','von','de','da','del','der','jr','the'} for t in tokens)
    # Reference extractors sometimes join the author block and title when a
    # ligature or line break is present.  A long comma-separated block ending
    # in ``and Name`` is still an author list even if one token contains a
    # non-ASCII ligature and therefore fails the strict token check above.
    if (text.count(',') >= 2 and re.search(r'\band\s+[A-Z]', text)
            and not re.search(r':', text)):
        return True
    return bool(name_like and (',' in text or re.search(r'\band\b',text) or re.search(r'\b[A-Z]\.',text)))


def _title(text):
    quoted=re.search(r'《([^》]{4,500})》|[“"]([^”"]{8,500})[”"]',text)
    if quoted:
        return next(g for g in quoted.groups() if g).strip(' .,，。')
    # Do not split author initials (J. D.). Keep the raw reference alongside the guess.
    parts=re.split(r'(?<!\b[A-Z])\.\s+|。\s*',text)
    for index,part in enumerate(parts):
        candidate=part.strip(' .,“”"')
        candidate=re.sub(r'^\(?\d{4}[a-z]?\)?[.,:：]?\s*','',candidate)
        tokens=re.findall(r'[A-Za-z]+',candidate)
        # Standalone capitalised 2–4 word chunks are usually an author name.
        # Keep them only when the citation has no following title-like text.
        if (index == 0 and len(tokens) in {2, 3, 4}
                and all(t[0].isupper() for t in tokens)
                and len(parts) > 1):
            continue
        if not 8<=len(candidate)<=500 or _author_line(candidate):
            continue
        if re.match(r'^(?:In\b|Proceedings\b|CoRR\b|arXiv\b|https?://|doi\b|IEEE\b|ACM\b|Journal\b)',candidate,re.I):
            continue
        if re.search(r'\b(?:et al|eds?\.)\b',candidate,re.I):
            continue
        if len(re.findall(r'\b[\w-]+\b',candidate))<2:
            if not re.search(r'[\u4e00-\u9fff]{6}',candidate):
                continue
        # A long single block with no recognizable author/title boundary is too ambiguous.
        if len(parts)==1 and (_author_line(candidate.split(':',1)[0]) or re.search(r'\b(?:19|20)\d{2}\b',candidate)):
            continue
        return re.sub(r',?\s+\(?\b(?:19|20)\d{2}[a-z]?\)?$', '', candidate).strip(' ,')
    return None


def lookup_hints(raw):
    text=re.sub(r'\s+',' ',unicodedata.normalize('NFKC', str(raw or ''))).strip()
    title=_title(text)
    identifiers=[];clues=[];places=[]
    arxiv=re.search(r'(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/|\babs/)((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?)',text,re.I)
    if arxiv:
        identifiers.append({'kind':'arXiv','value':arxiv.group(1)})
    doi=re.search(r'\b10\.\d{4,9}/[^\s<>"，。]+',text,re.I)
    if doi:
        identifiers.append({'kind':'DOI','value':doi.group(0).rstrip('.,;)]}')})
    for pattern,name,place in _SOURCES:
        match=re.search(pattern,text,re.I)
        if match:
            clues.append({'name':name,'evidence':match.group(0),'basis':'条目原文线索'})
            places.append(place)
    if arxiv and not any('arXiv' in c['name'] for c in clues):
        clues.append({'name':'arXiv 编号线索','evidence':arxiv.group(0),'basis':'条目原文线索'})
        places.append('arXiv：按题名或 arXiv 编号检索')
    if doi:
        prefix=doi.group(0).split('/')[0]
        publisher={'10.1109':('IEEE Xplore','IEEE Xplore：按 DOI 检索'),
                   '10.1145':('ACM Digital Library','ACM Digital Library：按 DOI 检索'),
                   '10.1007':('SpringerLink','SpringerLink：按 DOI 检索'),
                   '10.1016':('ScienceDirect','ScienceDirect：按 DOI 检索')}.get(prefix)
        if publisher and not any(c['name']=={'10.1109':'IEEE','10.1145':'ACM','10.1007':'Springer','10.1016':'Elsevier'}.get(prefix) for c in clues):
            clues.append({'name':publisher[0]+'（按 DOI 前缀推测）','evidence':prefix,'basis':'标识符推测，未核验'})
            places.append(publisher[1])
        places.append('Crossref / DOI 检索：使用上述 DOI 核对题名与出版信息')
    # Preserve an explicit host as a textual clue, never turn source-controlled URLs into links.
    for match in re.finditer(r'https?://[^\s<>"\']+',text,re.I):
        try:host=urlsplit(match.group(0)).hostname
        except ValueError:continue
        if host and len(host)<=253 and host not in {c['evidence'] for c in clues}:
            clues.append({'name':'条目中出现的网站','evidence':host,'basis':'条目原文线索，页面内容未核验'})
    places.append('Google Scholar（谷歌学术）：用完整题名，配合作者和年份核对')
    if not doi:places.append('Crossref：用题名查找 DOI 与出版信息；未收录时不代表论文不存在')
    return {'title':title,'title_status':'candidate' if title else 'unavailable',
            'source_clues':clues,'identifiers':identifiers,'suggested_places':list(dict.fromkeys(places)),
            'notice':'依据引用条目的文字给出查找建议，未联网核验。题名、出版出处及版本请与原条目和检索结果核对。'}
