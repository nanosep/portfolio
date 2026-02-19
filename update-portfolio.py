#!/usr/bin/env python3
"""
update-portfolio.py
───────────────────
Escanea la carpeta Portfolio, detecta álbumes (subcarpetas) y archivos
de foto/video, y regenera el bloque ASSETS dentro de portfolio.html.

Uso:
  python3 update-portfolio.py
  python3 update-portfolio.py --dry-run

Cada carpeta de álbum puede contener un archivo opcional meta.json:

  {
    "albumTitle": "Años 70",
    "assets": {
      "nombre-archivo.jpg": { "caption": "...", "featured": true }
    }
  }

Convención de portada para videos:
  Si existe poster.jpg, poster.png, cover.jpg o cover.png en la carpeta
  del álbum, se usa como thumbnail del video. Si no, usa la primera foto.

Campos opcionales por asset: caption, credit, featured, order, layout.

No necesita instalar nada — usa solo la librería estándar de Python.
"""

import os
import re
import json
import argparse
import datetime

# ── Configuración ──────────────────────────────────────────────────────────────

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
HTML_FILE    = os.path.join(SCRIPT_DIR, 'portfolio.html')
PHOTO_EXTS   = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
VIDEO_EXTS   = {'.mp4', '.mov', '.webm', '.avi'}

# Nombres de archivo reservados para portada de video (en orden de preferencia)
POSTER_NAMES = ['poster.jpg', 'poster.jpeg', 'poster.png', 'cover.jpg', 'cover.jpeg', 'cover.png']

# Sufijos que marcan un archivo como poster generado (no se indexan como fotos)
POSTER_SUFFIX = '_poster'

# Carpetas a ignorar
IGNORE_DIRS  = {'__pycache__', '.DS_Store', '.git', 'thumbs', 'node_modules'}

# Prefijos genéricos que no son títulos útiles → se sustituyen por "Álbum — N"
GENERIC_PREFIXES = {
    'gemini generated image',
    'grok video',
    'magnifics mystic',
    'download',
    'image',
    'photo',
    'img',
    'file',
    'untitled',
    'screenshot',
    'captura de pantalla',
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_date(path):
    """Fecha de modificación del archivo como string YYYY-MM-DD."""
    ts = os.path.getmtime(path)
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


def make_title(album, filename, index, total):
    """Genera un título legible a partir del nombre de archivo."""
    stem = os.path.splitext(filename)[0]

    # 1. Elimina hashes UUID completos
    stem = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '', stem, flags=re.I
    )
    # 2. Elimina sufijos de hash al final: guión O guión_bajo + 12+ alfanuméricos
    #    Cubre: -PG0ypRgDrFtnBmIDPB3G  _7brk8p7brk8p7brk  -afe0c8fd (residuo uuid)
    stem = re.sub(r'[-_][A-Za-z0-9]{12,}$', '', stem)

    # 3. Reemplaza separadores por espacio y limpia
    stem = re.sub(r'[-_]+', ' ', stem).strip()
    stem = re.sub(r'\s+', ' ', stem)

    # 4. Si quedó vacío o muy corto → fallback numérico
    if not stem or len(stem) < 2:
        pad = str(index).zfill(len(str(total)))
        return f'{album.capitalize()} — {pad}'

    # 5. Capitaliza
    stem = stem.title()

    # 6. Si el título (o su comienzo) es un prefijo genérico → fallback numérico
    stem_lower = stem.lower()
    for prefix in GENERIC_PREFIXES:
        if stem_lower == prefix or stem_lower.startswith(prefix):
            pad = str(index).zfill(len(str(total)))
            return f'{album.capitalize()} — {pad}'

    # 7. Si hay varios archivos, añade número para diferenciarlos
    if total > 1:
        pad = str(index).zfill(len(str(total)))
        return f'{stem} — {pad}'

    return stem


def find_thumb_for_video(album_dir, album_name, video_filename):
    """
    Busca la portada de un video específico en este orden:
      1. {video_stem}_poster.jpg/png  — frame extraído por generate-video-thumbs.py
      2. poster.jpg / cover.jpg       — portada global del álbum
      3. Primera foto del álbum que no sea un poster reservado (último recurso)
    """
    video_stem = os.path.splitext(video_filename)[0]
    files_lower = {f.lower(): f for f in os.listdir(album_dir)
                   if os.path.isfile(os.path.join(album_dir, f))}

    # 1. Poster específico del video
    for ext in ('.jpg', '.jpeg', '.png'):
        candidate = (video_stem + POSTER_SUFFIX + ext).lower()
        if candidate in files_lower:
            return f'{album_name}/{files_lower[candidate]}'

    # 2. Poster global del álbum
    for name in POSTER_NAMES:
        if name in files_lower:
            return f'{album_name}/{files_lower[name]}'

    # 3. Primera foto que no sea poster ni tenga sufijo _poster
    for f in sorted(os.listdir(album_dir)):
        fl = f.lower()
        if fl in [p.lower() for p in POSTER_NAMES]:
            continue
        stem_lower = os.path.splitext(fl)[0]
        if stem_lower.endswith(POSTER_SUFFIX):
            continue
        ext = os.path.splitext(fl)[1]
        if ext in PHOTO_EXTS and os.path.isfile(os.path.join(album_dir, f)):
            return f'{album_name}/{f}'

    return None


def load_album_meta(album_dir):
    """
    Lee meta.json de un álbum si existe.
    Devuelve (assets_dict, albumTitle | None).
    """
    meta_path = os.path.join(album_dir, 'meta.json')
    if not os.path.isfile(meta_path):
        return {}, None
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('assets', {}), data.get('albumTitle', None)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠️  Error leyendo {meta_path}: {e}")
        return {}, None


# Campos opcionales que meta.json puede aportar por asset
META_FIELDS = ('caption', 'credit', 'featured', 'order', 'layout')


def merge_meta(asset, meta_for_file):
    """Fusiona campos de meta.json en un asset dict."""
    for field in META_FIELDS:
        if field in meta_for_file:
            asset[field] = meta_for_file[field]


def js_entry(asset):
    """Formatea un objeto JS de un ítem."""
    lines = [
        "  {",
        f"    type:  '{asset['type']}',",
        f"    src:   '{asset['src']}',",
        f"    thumb: '{asset['thumb']}',",
        f"    title: '{asset['title']}',",
        f"    album: '{asset['album']}',",
        f"    date:  '{asset['date']}'",
    ]
    trailing = []
    if asset.get('albumTitle'):
        escaped = asset['albumTitle'].replace("'", "\\'")
        trailing.append(f"    albumTitle: '{escaped}'")
    if 'duration' in asset:
        trailing.append(f"    duration: '{asset['duration']}'")
    if 'caption' in asset:
        escaped = asset['caption'].replace("'", "\\'")
        trailing.append(f"    caption:  '{escaped}'")
    if 'credit' in asset:
        escaped = asset['credit'].replace("'", "\\'")
        trailing.append(f"    credit:   '{escaped}'")
    if asset.get('featured'):
        trailing.append(f"    featured: true")
    if 'order' in asset:
        trailing.append(f"    order:    {asset['order']}")
    if 'layout' in asset:
        trailing.append(f"    layout:   '{asset['layout']}'")
    if 'tags' in asset and asset['tags']:
        tags_str = ', '.join(f"'{t}'" for t in asset['tags'])
        trailing.append(f"    tags:     [{tags_str}]")

    for t in trailing:
        lines[-1] += ","
        lines.append(t)

    lines.append("  }")
    return '\n'.join(lines)


# ── Escaneo ────────────────────────────────────────────────────────────────────

def load_tags():
    """Lee tags.json si existe. Devuelve dict path → [tag, ...]."""
    tags_path = os.path.join(SCRIPT_DIR, 'tags.json')
    if not os.path.isfile(tags_path):
        return {}
    try:
        with open(tags_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠️  Error leyendo tags.json: {e}")
        return {}


def scan_portfolio():
    assets = []
    tags_data = load_tags()

    albums = sorted([
        d for d in os.listdir(SCRIPT_DIR)
        if os.path.isdir(os.path.join(SCRIPT_DIR, d))
        and d not in IGNORE_DIRS
        and not d.startswith('.')
    ])

    for album in albums:
        album_dir  = os.path.join(SCRIPT_DIR, album)
        album_file_meta, album_title = load_album_meta(album_dir)

        photos = []
        videos = []
        for f in sorted(os.listdir(album_dir)):
            fl = f.lower()
            # Salta portadas reservadas y archivos _poster generados
            if fl in [p.lower() for p in POSTER_NAMES]:
                continue
            stem_lower = os.path.splitext(fl)[0]
            if stem_lower.endswith(POSTER_SUFFIX):
                continue
            ext   = os.path.splitext(fl)[1]
            fpath = os.path.join(album_dir, f)
            if not os.path.isfile(fpath):
                continue
            if ext in PHOTO_EXTS:
                photos.append(f)
            elif ext in VIDEO_EXTS:
                videos.append(f)

        # Fotos
        for i, fname in enumerate(photos, start=1):
            fpath = os.path.join(album_dir, fname)
            entry = {
                'type':  'photo',
                'src':   f'{album}/{fname}',
                'thumb': f'{album}/{fname}',
                'title': make_title(album, fname, i, len(photos)),
                'album': album,
                'date':  get_date(fpath),
            }
            if album_title and i == 1:
                entry['albumTitle'] = album_title
            if fname in album_file_meta:
                merge_meta(entry, album_file_meta[fname])
            tag_key = f'{album}/{fname}'
            if tag_key in tags_data:
                entry['tags'] = tags_data[tag_key]
            assets.append(entry)

        # Videos — cada uno busca su propio thumb
        for i, fname in enumerate(videos, start=1):
            fpath     = os.path.join(album_dir, fname)
            thumb_src = find_thumb_for_video(album_dir, album, fname)
            entry = {
                'type':  'video',
                'src':   f'{album}/{fname}',
                'thumb': thumb_src or f'{album}/{fname}',
                'title': make_title(album, fname, i, len(videos)),
                'album': album,
                'date':  get_date(fpath),
            }
            if album_title and not photos:
                entry['albumTitle'] = album_title
            if fname in album_file_meta:
                merge_meta(entry, album_file_meta[fname])
            tag_key = f'{album}/{fname}'
            if tag_key in tags_data:
                entry['tags'] = tags_data[tag_key]
            assets.append(entry)

    return assets, albums


# ── Inyección en HTML ──────────────────────────────────────────────────────────

def update_html(assets, albums):
    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    header_lines = ["// ASSETS:START", "const ASSETS = ["]
    body_lines   = []
    current_album = None

    for asset in assets:
        if asset['album'] != current_album:
            current_album = asset['album']
            body_lines.append(
                f"\n  // ── Álbum: {current_album} ─────────────────────────────────────────────"
            )
        body_lines.append(js_entry(asset) + ",")

    footer_lines = ["];", "// ASSETS:END"]
    new_block = '\n'.join(header_lines) + '\n' + '\n'.join(body_lines) + '\n' + '\n'.join(footer_lines)

    pattern = r'// ASSETS:START.*?// ASSETS:END'
    if not re.search(pattern, html, flags=re.DOTALL):
        print("⚠️  No se encontraron marcadores ASSETS:START / ASSETS:END en portfolio.html")
        return False

    new_html = re.sub(pattern, new_block, html, flags=re.DOTALL)

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(new_html)

    return True


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Actualiza ASSETS en portfolio.html')
    parser.add_argument('--dry-run', action='store_true',
                        help='Muestra resumen sin modificar el HTML')
    args = parser.parse_args()

    print("🔍  Escaneando Portfolio…")
    assets, albums = scan_portfolio()

    print(f"📁  Álbumes encontrados: {', '.join(albums)}")
    photos    = sum(1 for a in assets if a['type'] == 'photo')
    videos    = sum(1 for a in assets if a['type'] == 'video')
    with_meta  = sum(1 for a in assets if any(k in a for k in META_FIELDS))
    with_title = sum(1 for a in assets if 'albumTitle' in a)
    with_tags  = sum(1 for a in assets if 'tags' in a)
    print(f"🖼️   Fotos: {photos}  |  🎬  Videos: {videos}  |  Total: {len(assets)}")
    if with_meta:
        print(f"📋  Assets con metadatos:  {with_meta}")
    if with_title:
        print(f"🏷️   Álbumes con título personalizado: {with_title}")
    if with_tags:
        print(f"🏷️   Assets con tags: {with_tags}")

    if not assets:
        print("⚠️  No se encontraron archivos de media.")
        exit(1)

    if args.dry_run:
        print("🏁  Dry run — no se modificó ningún archivo.")
        exit(0)

    print(f"✏️   Actualizando {HTML_FILE}…")
    ok = update_html(assets, albums)

    if ok:
        print("✅  portfolio.html actualizado correctamente.")
        print("    Recarga el archivo en el navegador para ver los cambios.")
    else:
        exit(1)
