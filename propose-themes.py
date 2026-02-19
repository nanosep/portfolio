#!/usr/bin/env python3
"""
propose-themes.py
─────────────────
Analiza los nombres de archivo del portfolio y propone 8-12 temas
temáticos usando Claude Haiku (un solo request de texto).

Uso:
  python propose-themes.py
  python propose-themes.py --dry-run   # solo muestra vocabulario, sin API

Requisitos:
  pip install anthropic
  export ANTHROPIC_API_KEY="sk-ant-..."   (o $env:ANTHROPIC_API_KEY en PowerShell)

Output: proposed_themes.json
"""

import os
import re
import sys
import json
import argparse
from collections import Counter

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE  = os.path.join(SCRIPT_DIR, 'proposed_themes.json')
PHOTO_EXTS   = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
VIDEO_EXTS   = {'.mp4', '.mov', '.webm', '.avi'}
MEDIA_EXTS   = PHOTO_EXTS | VIDEO_EXTS
IGNORE_DIRS  = {'__pycache__', '.DS_Store', '.git', 'thumbs', 'node_modules'}
POSTER_NAMES = {'poster.jpg', 'poster.jpeg', 'poster.png',
                'cover.jpg', 'cover.jpeg', 'cover.png'}
MODEL = 'claude-haiku-4-5-20251001'

STOPWORDS = {
    'a', 'an', 'the', 'of', 'in', 'on', 'at', 'to', 'for', 'and', 'or',
    'is', 'it', 'by', 'with', 'from', 'as', 'be', 'was', 'are', 'but',
    'not', 'no', 'up', 'out', 'so', 'if', 'its', 'has', 'had', 'do',
    'my', 'he', 'she', 'we', 'me', 'us', 'his', 'her', 'our', 'your',
    'img', 'image', 'photo', 'pic', 'file', 'download', 'untitled',
    'grok', 'video', 'freepik', 'gemini', 'generated', 'magnifics',
    'mystic', 'midjourney', 'stable', 'diffusion',
}

# ── Scan ──────────────────────────────────────────────────────────────────────

def scan_filenames():
    """Collect all media filenames from album folders."""
    filenames = []
    albums = sorted([
        d for d in os.listdir(SCRIPT_DIR)
        if os.path.isdir(os.path.join(SCRIPT_DIR, d))
        and d not in IGNORE_DIRS
        and not d.startswith('.')
    ])

    for album in albums:
        album_dir = os.path.join(SCRIPT_DIR, album)
        for f in sorted(os.listdir(album_dir)):
            fl = f.lower()
            # Skip reserved poster files
            if fl in POSTER_NAMES:
                continue
            # Skip _poster generated thumbs
            stem = os.path.splitext(f)[0]
            if stem.lower().endswith('_poster'):
                continue
            # Only media files
            ext = os.path.splitext(f)[1].lower()
            if ext not in MEDIA_EXTS:
                continue
            if not os.path.isfile(os.path.join(album_dir, f)):
                continue
            filenames.append({'album': album, 'filename': f, 'stem': stem})

    return filenames, albums


def extract_vocabulary(filenames):
    """Extract word frequencies from descriptive filenames."""
    word_counts = Counter()
    for item in filenames:
        stem = item['stem']
        # Split on hyphens, underscores, spaces, camelCase boundaries
        words = re.split(r'[-_\s]+', stem.lower())
        for w in words:
            # Skip short words, numbers, stopwords
            if len(w) < 3:
                continue
            if w.isdigit():
                continue
            if w in STOPWORDS:
                continue
            # Skip hex-looking tokens (UUIDs, hashes)
            if re.match(r'^[0-9a-f]{6,}$', w):
                continue
            word_counts[w] += 1

    return word_counts


# ── API ───────────────────────────────────────────────────────────────────────

def propose_themes(word_counts, total_files, albums):
    """Send vocabulary to Claude and get theme proposals."""
    import anthropic

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("✗ ANTHROPIC_API_KEY no está configurada.")
        print("  Bash:       export ANTHROPIC_API_KEY=\"sk-ant-...\"")
        print("  PowerShell: $env:ANTHROPIC_API_KEY=\"sk-ant-...\"")
        sys.exit(1)

    # Build compact vocab list (top 200 words)
    top_words = word_counts.most_common(200)
    vocab_str = ', '.join(f'{w}({c})' for w, c in top_words)

    prompt = f"""Here is a vocabulary frequency list from a photo/video portfolio of {total_files} files across albums [{', '.join(albums)}]:

{vocab_str}

Propose 8-12 thematic categories that would make sense as album filters for this portfolio. Each category should:
- Cover a meaningful visual/content theme (not technical metadata)
- Be broad enough to have at least 10-15 photos
- Be distinct enough not to overlap heavily with others
- Have a short, clear label (1-3 words, in English)

Return ONLY a JSON array like:
[
  {{ "tag": "urban", "label": "Urban & City", "keywords": ["street", "building", "city"] }},
  ...
]"""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON from response (in case it has markdown fences)
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(text)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Analiza filenames y propone temas para el portfolio')
    parser.add_argument('--dry-run', action='store_true',
                        help='Solo muestra vocabulario, sin llamar a la API')
    args = parser.parse_args()

    print("🔍  Escaneando filenames...")
    filenames, albums = scan_filenames()
    print(f"📁  {len(albums)} álbumes, {len(filenames)} archivos\n")

    if not filenames:
        print("✗ No se encontraron archivos de media.")
        sys.exit(1)

    word_counts = extract_vocabulary(filenames)
    top_30 = word_counts.most_common(30)

    print("📊  Top 30 palabras:")
    for w, c in top_30:
        bar = '█' * min(c // 2, 30)
        print(f"   {w:20s} {c:4d}  {bar}")
    print()

    if args.dry_run:
        print(f"Total palabras únicas: {len(word_counts)}")
        print("(Dry run — no se llamó a la API)")
        return

    print("🤖  Consultando Claude Haiku...")
    themes = propose_themes(word_counts, len(filenames), albums)

    # Save
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(themes, f, indent=2, ensure_ascii=False)

    # Display
    print(f"\n✅  {len(themes)} temas propuestos:\n")
    for t in themes:
        kw = ', '.join(t.get('keywords', [])[:6])
        print(f"   [{t['tag']:15s}]  {t['label']}")
        print(f"                     keywords: {kw}")
        print()

    print(f"💾  Guardado en: {OUTPUT_FILE}")
    print("    Edita el archivo si quieres ajustar temas antes de assign-tags.py")


if __name__ == '__main__':
    main()
