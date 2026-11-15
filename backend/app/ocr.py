"""Restartable page OCR using CPU Tesseract or macOS Vision; no model API calls."""
from __future__ import annotations
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
import pymupdf
from fastapi import APIRouter, BackgroundTasks, HTTPException
from app import papers
from app.processing import build_chunks, extract_sections
from app.similarity import content_signature

router = APIRouter(prefix='/api/papers', tags=['ocr'])
_ACTIVE: set[str] = set()
_LOCK = threading.Lock()
_SLOT = threading.BoundedSemaphore(1)


def _atomic(path, value):
    temporary = path.with_suffix('.tmp')
    papers._write_json(temporary, value)
    os.replace(temporary, path)


def engine_command() -> list[str]:
    if shutil.which('tesseract'):
        return ['tesseract']
    if platform.system() == 'Darwin' and shutil.which('swiftc'):
        source = Path(__file__).parent / 'native' / 'ocr.swift'
        import hashlib
        suffix = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        executable = Path(tempfile.gettempdir()) / f'tracescholar-vision-{suffix}'
        if not executable.exists():
            subprocess.run(['swiftc', '-module-cache-path', str(executable)+'-cache', str(source), '-o', str(executable)],
                           check=True, timeout=90, capture_output=True)
        return [str(executable)]
    raise RuntimeError('未找到 OCR 引擎。Linux 请安装 tesseract-ocr；macOS 需 Xcode Command Line Tools。')


def recognize(page, command: list[str]) -> str:
    scale = min(2.0, 2200/max(page.rect.width, page.rect.height))
    with tempfile.TemporaryDirectory(prefix='tracescholar-ocr-') as temp:
        image = Path(temp) / 'page.png'
        page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(image)
        args = [*command, str(image)]
        if command[0] == 'tesseract':
            args += ['stdout', '-l', os.getenv('OCR_LANGUAGES', 'eng'), '--psm', '3']
        result = subprocess.run(args, check=True, capture_output=True, timeout=90)
        return result.stdout.decode('utf-8').strip()


def _reindex(paper_id):
    directory = papers._papers_dir()/paper_id
    pages_ = [papers._read_metadata(p) for p in sorted((directory/'pages').glob('*.json'))]
    sections = extract_sections(pages_)
    metadata = papers._read_metadata(directory/'metadata.json')
    chunks = build_chunks(pages_, sections, paper_id=paper_id, work_id=metadata['work_id'], version_label=metadata.get('version_label'))
    metadata.update(needs_ocr_pages=[p['page'] for p in pages_ if p['needs_ocr']],
                    section_count=len(sections), chunk_count=len(chunks), content_signature=content_signature(pages_))
    metadata['parse_status'] = 'needs_ocr' if metadata['needs_ocr_pages'] else 'ready'
    metadata['warnings'] = [w for w in metadata.get('warnings', []) if 'may need OCR' not in w]
    if metadata['needs_ocr_pages']:
        metadata['warnings'].append(f"{len(metadata['needs_ocr_pages'])} page(s) have little or no text and may need OCR")
    with papers._STORE_LOCK:
        # A concurrent version replacement may archive this paper while OCR runs.
        latest = papers._read_metadata(directory/'metadata.json')
        metadata.update({key: latest[key] for key in ('archived', 'replaced_by') if key in latest})
        _atomic(directory/'structure.json', {'sections': sections, 'chunks': chunks})
        _atomic(directory/'metadata.json', metadata)


def run_ocr(paper_id: str, job: dict):
    directory = papers._papers_dir()/paper_id
    path = directory/'ocr-job.json'
    try:
        command = engine_command()
        job['engine'] = 'tesseract' if command[0] == 'tesseract' else 'macOS Vision'
        _atomic(path, job)
        with pymupdf.open(directory/'source.pdf') as document:
            for number in job['requested_pages']:
                page_path = directory/'pages'/f'{number:06d}.json'
                record = papers._read_metadata(page_path)
                if not record.get('needs_ocr'):
                    continue
                try:
                    text = recognize(document[number-1], command)
                    if len(text) < papers.MIN_PAGE_TEXT_CHARS:
                        raise RuntimeError('该页识别文字不足，可能为空白页或图表页。')
                    record.update(text=text, char_count=len(text), needs_ocr=False, text_origin='ocr', ocr_engine=job['engine'])
                    # Respect the same total storage bound before persisting OCR output.
                    if papers._storage_usage_bytes() + len(text.encode())*4 > papers.MAX_STORAGE_BYTES:
                        raise RuntimeError('存储配额不足，无法保存识别结果。')
                    _atomic(page_path, record)
                    job['completed_pages'].append(number)
                except (RuntimeError, subprocess.SubprocessError, OSError) as error:
                    job['failed_pages'].append({'page': number, 'message': str(error) if isinstance(error, RuntimeError) else 'OCR 引擎执行失败，可重试该页。'})
                job['processed'] += 1
                _atomic(path, job)
        _reindex(paper_id)
        job['status'] = 'partial' if job['failed_pages'] else 'done'
    except Exception as error:
        job['status'] = 'failed'
        job['message'] = str(error) if isinstance(error, RuntimeError) else 'OCR 未完成，已保存成功页，可重试。'
        try:
            _reindex(paper_id)
        except Exception:
            pass
    finally:
        try:
            _atomic(path, job)
        finally:
            with _LOCK:
                _ACTIVE.discard(paper_id)
            _SLOT.release()


@router.get('/{paper_id}/ocr')
def ocr_status(paper_id: uuid.UUID):
    metadata = papers._load_paper(paper_id)
    job = papers._read_metadata(papers._papers_dir()/str(paper_id)/'ocr-job.json') or {'status': 'idle'}
    if job.get('status') == 'running' and str(paper_id) not in _ACTIVE:
        job = {**job, 'status': 'interrupted', 'message': '服务中断，点击继续识别可跳过已完成页。'}
    remaining = [page['page'] for path in sorted((papers._papers_dir()/str(paper_id)/'pages').glob('*.json'))
                 if (page := papers._read_metadata(path)) and page.get('needs_ocr')]
    return {**job, 'remaining_pages': remaining}


@router.post('/{paper_id}/ocr', status_code=202)
def start_ocr(paper_id: uuid.UUID, background: BackgroundTasks):
    metadata = papers._load_paper(paper_id)
    remaining = [page['page'] for path in sorted((papers._papers_dir()/str(paper_id)/'pages').glob('*.json'))
                 if (page := papers._read_metadata(path)) and page.get('needs_ocr')]
    if not remaining:
        _reindex(str(paper_id))
        return {'status': 'done', 'remaining_pages': []}
    with _LOCK:
        if str(paper_id) in _ACTIVE or not _SLOT.acquire(blocking=False):
            raise HTTPException(409, '已有 OCR 任务运行，请等待完成后重试。')
        _ACTIVE.add(str(paper_id))
    job = {'status': 'running', 'requested_pages': remaining, 'total': len(remaining),
           'processed': 0, 'completed_pages': [], 'failed_pages': []}
    try:
        _atomic(papers._papers_dir()/str(paper_id)/'ocr-job.json', job)
    except Exception:
        with _LOCK: _ACTIVE.discard(str(paper_id))
        _SLOT.release()
        raise
    background.add_task(run_ocr, str(paper_id), job)
    return job
