"""Bounded, explainable content overlap; not dense semantic embeddings."""
import hashlib
import re
import unicodedata


def fingerprint(text: str) -> set[str]:
    text = unicodedata.normalize('NFKC', text).casefold()
    tokens = re.findall(r'[a-z0-9]+|[\u3400-\u9fff]', text)
    # Five-token shingles tolerate layout/filename changes, preserve local context.
    return {hashlib.blake2s(' '.join(tokens[i:i+5]).encode(), digest_size=8).hexdigest()
            for i in range(max(0, len(tokens)-4))}


def content_signature(pages: list[dict]) -> dict:
    # Up to 20 evenly spaced pages, bounded to avoid book-sized comparisons.
    selected = pages if len(pages) <= 20 else [pages[i*(len(pages)-1)//19] for i in range(20)]
    values = fingerprint('\n'.join(p.get('text', '')[:20000] for p in selected))
    return {'method': 'text_shingles_v1', 'hashes': sorted(values), 'count': len(values)}


def overlap(left: dict, right: dict) -> float:
    a, b = set(left.get('hashes', [])), set(right.get('hashes', []))
    if min(len(a), len(b)) < 30:
        return 0.0
    # Jaccard avoids treating a short shared abstract as a full-book duplicate.
    return len(a & b) / max(1, len(a | b))
