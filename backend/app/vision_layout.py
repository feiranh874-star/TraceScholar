"""Local presentation repairs for saved vision results; no provider calls or cell edits."""
from __future__ import annotations

import copy
import re

import pymupdf as fitz

from app.document_analysis import CAPTION, _lines


def group_merges(table):
    """Infer only explicit parenthesized row labels followed by empty label cells.

    These are display suggestions, separate from the model's validated merges.
    Never relocate a label, fill a cell, or merge over any nonempty value.
    """
    rows = table['rows']
    merges = copy.deepcopy(table.get('merges', []))
    occupied = {(r, c) for m in merges
                for r in range(m['row'], m['row'] + m['rowspan'])
                for c in range(m['column'], m['column'] + m['colspan'])}
    labels = [i for i, row in enumerate(rows[1:], 1)
              if re.fullmatch(r'\([A-Za-z0-9]{1,4}\)', str(row[0] or '').strip())]
    if len(labels) < 2:
        return merges, 0
    added = 0
    for start in labels:
        end = start + 1
        while end < len(rows) and rows[end][0] in (None, ''):
            end += 1
        if end - start < 2 or any((r, 0) in occupied for r in range(start, end)):
            continue
        if any(not any(v not in (None, '') for v in row[1:]) for row in rows[start:end]):
            continue
        merges.append({'row': start, 'column': 0, 'rowspan': end - start, 'colspan': 1})
        added += 1
    return merges, added


def _native_tables(page):
    lines = _lines(page)
    captions = []
    for line in lines:
        match = CAPTION.match(line['text'])
        if match and match[1].lower() in ('table', '表'):
            captions.append({**line, 'label': match[1] + ' ' + match[2], 'kind': 'table'})
    rules = []
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0] == 'l' and abs(item[1].y - item[2].y) < .7 and abs(item[1].x - item[2].x) > 100:
                rules.append((min(item[1].x, item[2].x), max(item[1].x, item[2].x), item[1].y))
    result = []
    for caption in captions:
        # Split at the next caption even when adjacent tables have identical width.
        top = caption['bbox'][3]
        bottom = min((c['bbox'][1] for c in captions if c['bbox'][1] > top
                      and c['bbox'][0] < caption['bbox'][2] and c['bbox'][2] > caption['bbox'][0]),
                     default=page.rect.height)
        groups = []
        for rule in sorted((r for r in rules if top < r[2] < bottom), key=lambda r: r[2]):
            group = next((g for g in groups if abs(g[0][0] - rule[0]) < 3 and abs(g[0][1] - rule[1]) < 3), None)
            if group is None:
                groups.append([rule])
            elif all(abs(r[2] - rule[2]) > 1 for r in group):
                group.append(rule)
        groups = [g for g in groups if len(g) >= 3 and g[0][2] - top < 150]
        if len(groups) == 1:
            group = groups[0]
            result.append({'label': caption['label'], 'bbox': [group[0][0], group[0][2], group[0][1], group[-1][2]]})
    return result


def _label(text):
    # Only a numbered label is used to locate a native table, never its cell values.
    match = re.match(r'\s*(?:table|表)\s*([A-Za-z]?\d+[A-Za-z]?)\b', text, re.I)
    return match[1].lower() if match else None


def present(record, page):
    """Decorate a copy on read, so old caches benefit without another paid request."""
    result = copy.deepcopy(record)
    native = _native_tables(page) if result.get('tables') else []
    words = page.get_text('words') if result.get('equations') else []
    for kind in ('tables', 'equations', 'figures'):
        for item in result.get(kind, []):
            model_box = fitz.Rect(item.get('model_bbox', item['bbox'])) & page.rect
            box = model_box
            method = '模型定位'
            if kind == 'tables':
                candidates = [t for t in native if _label(item['label']) is not None
                              and _label(t['label']) == _label(item['label'])]
                if len(candidates) == 1:
                    candidate = fitz.Rect(candidates[0]['bbox'])
                    intersection = candidate & model_box
                    if intersection.get_area() / max(1, min(candidate.get_area(), model_box.get_area())) > .35:
                        box = candidate + (-3, -3, 3, 3)
                        method = 'PDF 表格线与同编号表注校正'
                item['display_merges'], added = group_merges(item)
                item['display_note'] = (f'显示时根据首列分组标签与连续空白恢复了 {added} 组纵向合并，'
                                        '请对照原图；JSON 原始单元格与 CSV 保持不变。' if added else '')
            elif kind == 'equations':
                # Include ascenders, superscripts, radicals and subscripts which
                # overlap the proposed crop but extend beyond its vertical edge.
                vicinity = model_box + (-3, -4, 3, 4)
                for word in words:
                    rect = fitz.Rect(word[:4])
                    if rect.intersects(vicinity) and rect.y0 >= model_box.y0 - 18 and rect.y1 <= model_box.y1 + 18:
                        box = box | rect
                box = box + (-5, -5, 5, 5)
                method = '原生文字上下标边界与留白校正'
            else:
                box = box + (-4, -4, 4, 4)
            box = box & page.rect
            if not box.is_empty:
                item['model_bbox'] = list(model_box)
                item['bbox'] = list(box)
                item['source'] = {**item.get('source', {}), 'bbox': list(box)}
                item['layout_method'] = method
    result['layout_version'] = 1
    return result
