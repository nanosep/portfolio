#!/usr/bin/env python3
"""
rename-with-ai.py
─────────────────
Usa Claude (Haiku) para renombrar fotos con nombres descriptivos.

Uso:
  python rename-with-ai.py                  # todas las carpetas
  python rename-with-ai.py --album 70s      # solo una carpeta
  python rename-with-ai.py --dry-run        # preview sin renombrar
  python rename-with-ai.py --album 70s --dry-run

Requisitos:
  pip install anthropic
  export ANTHROPIC_API_KEY="sk-ant-..."

Al terminar cada álbum ejecuta update-portfolio.py para regenerar el HTML.
Guarda rename-log.json con todos los cambios para poder revertir.
"""

import os
import re
import sys
import json
import time
import io
import base64
import argparse
import subprocess
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
IGNORE_DIRS = {'__pycache__', '.DS_Store', '.git', 'thumbs', 'node_modules'}
MODEL = 'claude-haiku-4-5-20251001'
SLEEP = 0.3
LOG_FILE = os.path.join(SCRIPT_DIR, 'rename-log.json')

PROMPT = (
    "Look at this photo and give it a concise, descriptive filename in English. "
    "Use 2-4 words, lowercase, separated by hyphens. No extension. "
    "Examples: red-alfa-romeo, woman-reading-cafe, mountain-sunset-snow. "
    "Reply with ONLY the filename, nothing else."
)

MIME_MAP = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def sanitize(name):
    """Limpia el nombre: solo a-z, 0-9, guiones."""
    name = name.strip().lower()
    name = re.sub(r'[^a-z0-9-]', '-', name)
    name = re.sub(r'-+', '-', name).strip('-')
    return name or 'unnamed'


def unique_name(directory, stem, ext):
    """Si ya existe stem.ext en directory, añade sufijo numérico."""
    candidate = stem + ext
    if not os.path.exists(os.path.join(directory, candidate)):
        return candidate
    i = 2
    while True:
        candidate = f'{stem}-{i}{ext}'
        if not os.path.exists(os.path.join(directory, candidate)):
            return candidate
        i += 1


def load_log():
    """Carga el log existente o devuelve lista vacía."""
    if os.path.isfile(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_log(log):
    """Guarda el log a disco."""
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def run_update_portfolio():
    """Ejecuta update-portfolio.py para regenerar el HTML."""
    script = os.path.join(SCRIPT_DIR, 'update-portfolio.py')
    if not os.path.isfile(script):
        print("  ⚠️  update-portfolio.py no encontrado, skip HTML update")
        return
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    subprocess.run([sys.executable, script], cwd=SCRIPT_DIR, env=env)


MAX_API_BYTES = 4_800_000  # stay under Claude's 5 MB limit

def image_to_b64(image_path):
    """Lee imagen, la reduce si >5MB, devuelve (b64_string, mime_type)."""
    ext = os.path.splitext(image_path)[1].lower()
    file_size = os.path.getsize(image_path)

    # Small enough — send as-is
    if file_size <= MAX_API_BYTES:
        mime = MIME_MAP.get(ext, 'image/jpeg')
        with open(image_path, 'rb') as f:
            return base64.standard_b64encode(f.read()).decode('ascii'), mime

    # Too large — resize with Pillow, always output as JPEG
    img = Image.open(image_path)
    img = img.convert('RGB')

    # Shrink until it fits
    quality = 85
    for scale in (1.0, 0.75, 0.5, 0.35, 0.25):
        w = int(img.width * scale)
        h = int(img.height * scale)
        resized = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format='JPEG', quality=quality)
        if buf.tell() <= MAX_API_BYTES:
            return base64.standard_b64encode(buf.getvalue()).decode('ascii'), 'image/jpeg'

    # Last resort: very small
    resized = img.resize((800, int(800 * img.height / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    resized.save(buf, format='JPEG', quality=70)
    return base64.standard_b64encode(buf.getvalue()).decode('ascii'), 'image/jpeg'


def ask_claude(client, image_path):
    """Envía la imagen a Claude y devuelve el nombre sugerido."""
    b64, mime = image_to_b64(image_path)

    response = client.messages.create(
        model=MODEL,
        max_tokens=60,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": PROMPT,
                },
            ],
        }],
    )

    return response.content[0].text.strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def process_album(client, album, dry_run, log, min_bytes=0, max_bytes=float('inf'), limit=None):
    album_dir = os.path.join(SCRIPT_DIR, album)
    files = []
    for f in sorted(os.listdir(album_dir)):
        fpath = os.path.join(album_dir, f)
        if not os.path.isfile(fpath):
            continue
        if os.path.splitext(f)[1].lower() not in PHOTO_EXTS:
            continue
        size = os.path.getsize(fpath)
        if size < min_bytes or size > max_bytes:
            continue
        files.append(f)

    if limit and len(files) > limit:
        files = files[:limit]

    if not files:
        print(f"  (sin fotos en rango)")
        return 0

    total_mb = sum(os.path.getsize(os.path.join(album_dir, f)) for f in files) / (1024*1024)
    print(f"  {len(files)} fotos ({total_mb:.1f} MB)")

    renamed = 0
    for fname in files:
        fpath = os.path.join(album_dir, fname)
        ext = os.path.splitext(fname)[1].lower()

        try:
            suggestion = ask_claude(client, fpath)
        except Exception as e:
            print(f"  ✗ {fname} — API error: {e}")
            time.sleep(SLEEP)
            continue

        clean = sanitize(suggestion)
        new_name = unique_name(album_dir, clean, ext)

        if new_name == fname:
            print(f"  · {fname} → (sin cambio)")
            time.sleep(SLEEP)
            continue

        if dry_run:
            print(f"  ○ {fname} → {new_name}")
        else:
            os.rename(fpath, os.path.join(album_dir, new_name))
            print(f"  ✓ {fname} → {new_name}")

        log.append({
            "album": album,
            "original": fname,
            "renamed": new_name,
            "suggestion": suggestion,
            "dry_run": dry_run,
        })
        renamed += 1
        time.sleep(SLEEP)

    return renamed


def main():
    parser = argparse.ArgumentParser(
        description='Renombra fotos usando Claude Vision')
    parser.add_argument('--album', type=str, default=None,
                        help='Procesar solo este álbum')
    parser.add_argument('--dry-run', action='store_true',
                        help='Mostrar cambios sin renombrar')
    parser.add_argument('--min-mb', type=float, default=0,
                        help='Tamaño mínimo en MB (default: 0)')
    parser.add_argument('--max-mb', type=float, default=0,
                        help='Tamaño máximo en MB (default: sin límite)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Máximo de archivos por álbum (default: todos)')
    args = parser.parse_args()

    # Verificar API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("✗ ANTHROPIC_API_KEY no está configurada.")
        print("  Ejecuta: export ANTHROPIC_API_KEY=\"sk-ant-...\"")
        sys.exit(1)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # Determinar álbumes a procesar
    if args.album:
        album_dir = os.path.join(SCRIPT_DIR, args.album)
        if not os.path.isdir(album_dir):
            print(f"✗ Carpeta no encontrada: {args.album}")
            sys.exit(1)
        albums = [args.album]
    else:
        albums = sorted([
            d for d in os.listdir(SCRIPT_DIR)
            if os.path.isdir(os.path.join(SCRIPT_DIR, d))
            and d not in IGNORE_DIRS
            and not d.startswith('.')
        ])

    min_bytes = int(args.min_mb * 1024 * 1024) if args.min_mb else 0
    max_bytes = int(args.max_mb * 1024 * 1024) if args.max_mb else float('inf')
    limit = args.limit or None

    mode = "DRY RUN" if args.dry_run else "RENAME"
    print(f"🏷️  rename-with-ai [{mode}] — {len(albums)} álbum(es)")
    print(f"   Modelo: {MODEL}")
    if args.min_mb or args.max_mb:
        print(f"   Filtro: {args.min_mb or 0}–{args.max_mb or '∞'} MB")
    if limit:
        print(f"   Límite: {limit} por álbum")
    print()

    log = load_log()
    total = 0

    for album in albums:
        print(f"📂 {album}/")
        count = process_album(client, album, args.dry_run, log, min_bytes, max_bytes, limit)
        total += count

        if count > 0 and not args.dry_run:
            print(f"  → Actualizando portfolio.html...")
            run_update_portfolio()

        print()

    save_log(log)
    print(f"{'─' * 40}")
    print(f"Renombrados: {total} archivo(s)")
    print(f"Log guardado en: {LOG_FILE}")

    if args.dry_run:
        print("\n(Dry run — ningún archivo fue modificado)")


if __name__ == '__main__':
    main()
