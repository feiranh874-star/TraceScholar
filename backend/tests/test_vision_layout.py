"""Offline layout corrections must preserve the model's raw cells and source PDF."""
import copy

import pymupdf as fitz

from app.vision_layout import group_merges, present


def test_display_groups_preserve_blanks_and_never_cover_nonempty_labels():
    table = {'rows': [['', 'metric'], ['base', '1'], ['(A)', '2'], ['', '3'],
                      ['(B)', '4'], [None, '5'], ['big', '6']], 'merges': []}
    before = copy.deepcopy(table)
    merges, count = group_merges(table)
    assert count == 2
    assert merges == [{'row': 2, 'column': 0, 'rowspan': 2, 'colspan': 1},
                      {'row': 4, 'column': 0, 'rowspan': 2, 'colspan': 1}]
    assert table == before
    table['merges'] = [merges[0]]
    assert group_merges(table)[1] == 1  # Existing spans are not duplicated.
    table['rows'][3][0] = 'another value'
    table['merges'] = []
    assert group_merges(table)[1] == 1
    table['rows'][5][1] = None
    assert group_merges(table)[1] == 0  # Do not merge through a wholly empty row.


def test_formula_crop_includes_native_subscript_but_not_neighboring_text():
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=800)
        page.insert_text((180, 300), 'Attention = QK / sqrt(d)')
        page.insert_text((295, 308), 'k', fontsize=7)
        page.insert_text((180, 345), 'Unrelated paragraph must stay out.')
        record = {'tables': [], 'figures': [], 'equations': [
            {'label': '(1)', 'latex': r'QK/\sqrt{d_k}', 'bbox': [175, 280, 310, 301], 'source': {}}]}
        before = copy.deepcopy(record)
        result = present(record, page)
        equation = result['equations'][0]
        assert equation['bbox'][3] >= 313
        assert equation['bbox'][3] < 330
        assert equation['model_bbox'] == record['equations'][0]['bbox']
        assert equation['source']['bbox'] == equation['bbox']
        assert equation['latex'] == record['equations'][0]['latex']
        assert present(result, page) == result
        assert record == before


def test_table_crop_uses_matching_caption_and_rules_not_neighboring_table():
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=800)
        for num, top in [(3, 100), (4, 300)]:
            page.insert_text((100, top - 15), f'Table {num}: experiment results')
            for y in (top, top+25, top+80):
                page.draw_line((100, y), (500, y))
            for y, values in [(top+18, ['name', 'score']), (top+42, ['base', '1']), (top+65, ['big', '2'])]:
                for x, value in zip((120, 370), values): page.insert_text((x, y), value)
        record = {'equations': [], 'figures': [], 'tables': [
            {'label': 'Table 3', 'bbox': [100, 120, 500, 320], 'rows': [['name', 'score'], ['base', '1']], 'source': {}},
            {'label': 'Table 4', 'bbox': [100, 330, 500, 410], 'rows': [['name', 'score'], ['base', '2']], 'source': {}}]}
        result = present(record, page)
        assert result['tables'][0]['bbox'] == [97, 97, 503, 183]
        assert result['tables'][1]['bbox'] == [97, 297, 503, 383]
        assert result['tables'][0]['rows'] == record['tables'][0]['rows']


def test_scanned_page_keeps_model_table_box_and_only_adds_safe_formula_margin():
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=800)
        record = {'figures': [], 'tables': [{'label': 'Table 1', 'bbox': [10, 10, 500, 300],
                  'rows': [['x', 'y'], ['1', '2']]}], 'equations': [
                  {'label': '(1)', 'bbox': [0, 0, 100, 20], 'latex': 'x=1'}]}
        result = present(record, page)
        assert result['tables'][0]['bbox'] == [10, 10, 500, 300]
        assert result['equations'][0]['bbox'] == [0, 0, 105, 25]
