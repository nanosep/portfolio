#!/usr/bin/env python3
"""
assign-tags.py  (FASE 2)
────────────────────────
Asigna tags temáticos a cada foto/video del portfolio usando los temas
aprobados en proposed_themes.json.

Método: matching por keywords en el filename (sin API).
Cada asset puede tener múltiples tags. Si ningún keyword hace match,
queda con tags: [].

Uso:
  python assign-tags.py                   # todos los álbumes
  python assign-tags.py --album 70s       # solo un álbum
  python assign-tags.py --dry-run         # preview sin escribir tags.json
  python assign-tags.py --use-ai          # usa Claude para asignar (más preciso, cuesta ~$0.01)
  python assign-tags.py --album 70s --use-ai --dry-run

Output: tags.json en la raíz de Portfolio.
"""

import os
import re
import sys
import json
import time
import argparse
from collections import Counter, defaultdict

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
THEMES_FILE   = os.path.join(SCRIPT_DIR, 'proposed_themes.json')
OUTPUT_FILE   = os.path.join(SCRIPT_DIR, 'tags.json')
PHOTO_EXTS    = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
VIDEO_EXTS    = {'.mp4', '.mov', '.webm', '.avi'}
MEDIA_EXTS    = PHOTO_EXTS | VIDEO_EXTS
IGNORE_DIRS   = {'__pycache__', '.DS_Store', '.git', 'thumbs', 'node_modules'}
POSTER_NAMES  = {'poster.jpg', 'poster.jpeg', 'poster.png',
                 'cover.jpg', 'cover.jpeg', 'cover.png'}
MODEL         = 'claude-haiku-4-5-20251001'
BATCH_SIZE    = 40   # files per AI request
SLEEP         = 0.3

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_themes():
    if not os.path.isfile(THEMES_FILE):
        print(f"✗ No se encontró {THEMES_FILE}")
        print("  Ejecuta primero: python propose-themes.py")
        sys.exit(1)
    with open(THEMES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def scan_media():
    """Scan all media files, return list of {album, filename, stem, path}."""
    items = []
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
            if fl in POSTER_NAMES:
                continue
            stem = os.path.splitext(f)[0]
            if stem.lower().endswith('_poster'):
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext not in MEDIA_EXTS:
                continue
            fpath = os.path.join(album_dir, f)
            if not os.path.isfile(fpath):
                continue
            items.append({
                'album': album,
                'filename': f,
                'stem': stem,
                'path': f'{album}/{f}',
            })
    return items


def tokenize(stem):
    """Split filename stem into lowercase words."""
    return set(re.split(r'[-_\s]+', stem.lower()))


# ── Keyword matching (no API) ────────────────────────────────────────────────

def assign_by_keywords(items, themes):
    """Assign tags by matching filename words against theme keywords."""
    results = {}
    for item in items:
        words = tokenize(item['stem'])
        tags = []
        for theme in themes:
            kws = set(theme['keywords'])
            if words & kws:  # intersection
                tags.append(theme['tag'])
        results[item['path']] = tags
    return results


# ── AI matching (optional, more precise) ──────────────────────────────────────

def assign_by_ai(items, themes, album_filter=None):
    """Assign tags using Claude — sends filenames in batches (no images)."""
    import anthropic

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("✗ ANTHROPIC_API_KEY no está configurada.")
        print("  Bash:       export ANTHROPIC_API_KEY=\"sk-ant-...\"")
        print("  PowerShell: $env:ANTHROPIC_API_KEY=\"sk-ant-...\"")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    tags_desc = json.dumps([{"tag": t["tag"], "label": t["label"], "keywords": t["keywords"]} for t in themes])

    results = {}
    batches = [items[i:i+BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]

    for bi, batch in enumerate(batches):
        filenames_list = [f"{it['album']}/{it['filename']}" for it in batch]
        filenames_str = '\n'.join(filenames_list)

        prompt = f"""Here are the available thematic tags for a photo/video portfolio:
{tags_desc}

Assign 1-3 tags to each file based on its filename. The filenames are descriptive.
Files:
{filenames_str}

Return ONLY a JSON object mapping each filepath to an array of tag strings:
{{
  "album/filename.jpg": ["tag1", "tag2"],
  ...
}}"""

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                batch_results = json.loads(match.group())
            else:
                batch_results = json.loads(text)
            results.update(batch_results)
            print(f"  Batch {bi+1}/{len(batches)}: {len(batch_results)} archivos tagueados")
        except Exception as e:
            print(f"  ✗ Batch {bi+1} error: {e}")
            # Fallback: leave untagged
            for it in batch:
                results[it['path']] = []

        if bi < len(batches) - 1:
            time.sleep(SLEEP)

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Asigna tags temáticos al portfolio')
    parser.add_argument('--album', type=str, default=None, help='Solo este álbum')
    parser.add_argument('--dry-run', action='store_true', help='Preview sin escribir')
    parser.add_argument('--use-ai', action='store_true', help='Usa Claude en vez de keywords')
    args = parser.parse_args()

    themes = load_themes()
    print(f"🏷️  {len(themes)} temas cargados desde proposed_themes.json\n")

    items = scan_media()
    if args.album:
        items = [it for it in items if it['album'] == args.album]
        if not items:
            print(f"✗ No se encontraron archivos en álbum '{args.album}'")
            sys.exit(1)

    print(f"📁  {len(items)} archivos a procesar")

    if args.use_ai:
        print("🤖  Asignando tags con Claude Haiku...\n")
        results = assign_by_ai(items, themes, args.album)
    else:
        print("🔤  Asignando tags por keywords...\n")
        results = assign_by_keywords(items, themes)

    # Merge with existing tags.json if processing a single album
    if args.album and os.path.isfile(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        existing.update(results)
        results = existing

    # Stats
    tag_counts = Counter()
    tag_examples = defaultdict(list)
    untagged = 0
    for path, tags in results.items():
        if not tags:
            untagged += 1
        for t in tags:
            tag_counts[t] += 1
            if len(tag_examples[t]) < 5:
                tag_examples[t].append(path.split('/')[-1])

    print(f"\n{'─' * 50}")
    print(f"📊  Resumen de tags:\n")
    for theme in themes:
        tag = theme['tag']
        count = tag_counts.get(tag, 0)
        bar = '█' * min(count // 3, 25)
        examples = tag_examples.get(tag, [])
        print(f"  [{tag:20s}] {count:4d}  {bar}")
        for ex in examples[:3]:
            print(f"    · {ex}")
        print()

    if untagged:
        print(f"  Sin tags: {untagged} archivos\n")

    total_tagged = sum(1 for v in results.values() if v)
    print(f"  Total: {len(results)} archivos, {total_tagged} con tags, {untagged} sin tags")

    if args.dry_run:
        print(f"\n(Dry run — no se escribió tags.json)")
        return

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n💾  Guardado en: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
