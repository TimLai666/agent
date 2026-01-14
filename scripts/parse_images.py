"""Utility script to test image parsing logic from circle_ui._split_images.

Usage:
  python scripts/parse_images.py "<markdown or text>"
  or echo "<text>" | python scripts/parse_images.py

This is a small standalone parser that mirrors the logic used in the app but does NOT import PySide6
so it is safe to run in environments without GUI dependencies.
"""
import sys
import re
import json

md_img = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
# allow broken URLs with whitespace/newlines before extension
url_img = re.compile(r'https?://[^\s<)]*(?:\s+[^\s<)]*)*?\.(?:png|jpe?g|gif|svg)(?:\?[^\s]*)?', re.IGNORECASE)
width_brace = re.compile(r'^\s*\{\s*width\s*[:=]?\s*(\d+)(?:px)?\s*\}')


def split_images(text: str):
    parts = []
    pos = 0
    # Normalize CRLF
    text = text.replace('\r\n', '\n')
    while pos < len(text):
        m_md = md_img.search(text, pos)
        m_url = url_img.search(text, pos)
        found = None
        found_type = None
        found_pos = None
        for m, t in ((m_md, 'md'), (m_url, 'url')):
            if m:
                if found is None or m.start() < found_pos:
                    found = m
                    found_type = t
                    found_pos = m.start()
        if not found:
            rest = text[pos:]
            if rest:
                parts.append(('text', rest))
            break
        if found_pos > pos:
            parts.append(('text', text[pos:found_pos]))
        if found_type == 'md':
            alt = found.group(1)
            inside = found.group(2)
            inside_norm = re.sub(r"[\r\n]+", " ", inside).strip()
            if inside_norm.startswith('<') and '>' in inside_norm:
                url = inside_norm[1:inside_norm.find('>')].strip()
                remainder = inside_norm[inside_norm.find('>')+1:].strip()
            else:
                toks = inside_norm.split()
                url = toks[0] if toks else ''
                remainder_tokens = toks[1:] if len(toks) > 1 else []
                if not re.search(r'\.(png|jpe?g|gif|svg)(?:$|\?)', url, re.IGNORECASE):
                    for i, tk in enumerate(remainder_tokens):
                        url += tk
                        if re.search(r'\.(png|jpe?g|gif|svg)(?:$|\?)', tk, re.IGNORECASE):
                            remainder_tokens = remainder_tokens[i+1:]
                            break
                remainder = ' '.join(remainder_tokens) if remainder_tokens else ''
            url = url.strip().strip('<>').strip()
            url = re.sub(r'\s+', '%20', url)
            look_pos = found.end()
            width = None
            if look_pos < len(text):
                m_br = width_brace.match(text[look_pos:])
                if m_br:
                    try:
                        width = int(m_br.group(1))
                    except Exception:
                        width = None
                    look_len = m_br.end()
                    pos = found.end() + look_len
                    parts.append(('image', url, alt, width))
                    continue
            parts.append(('image', url, alt, width))
        else:
            url = found.group(0)
            parts.append(('image', url, '', None))
        pos = found.end()
    return parts


if __name__ == '__main__':
    if len(sys.argv) > 1:
        text = sys.argv[1]
    else:
        text = sys.stdin.read()
    parts = split_images(text)
    print(json.dumps(parts, ensure_ascii=False, indent=2))
