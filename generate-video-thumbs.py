#!/usr/bin/env python3
"""
generate-video-thumbs.py
─────────────────────────
Extrae un frame representativo de cada video y lo guarda como
{video_stem}_poster.jpg junto al video, para que portfolio.html
muestre la portada correcta de cada clip.

Requiere ffmpeg instalado en el sistema.
  Windows: https://ffmpeg.org/download.html  (añadir a PATH)
  Mac:     brew install ffmpeg
  Linux:   sudo apt install ffmpeg

Uso:
  python3 generate-video-thumbs.py              # todos los álbumes
  python3 generate-video-thumbs.py --album 70s  # solo un álbum
  python3 generate-video-thumbs.py --dry-run    # sin modificar nada
  python3 generate-video-thumbs.py --force      # regenera aunque ya exista
  python3 generate-video-thumbs.py --time 5     # extrae frame en el segundo 5
"""

import os
import sys
import subprocess
import argparse
import shutil

# ── Configuración ──────────────────────────────────────────────────────────────

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
VIDEO_EXTS   = {'.mp4', '.mov', '.webm', '.avi', '.mkv'}
POSTER_SUFFIX = '_poster'
IGNORE_DIRS  = {'__pycache__', '.DS_Store', '.git', 'thumbs', 'node_modules'}

# Segundo en el que se extrae el frame por defecto
DEFAULT_TIME = 2   # segundos desde el inicio

# Calidad JPEG del poster (1-31, menor = mejor)
JPEG_QUALITY = 3

# ── Helpers ────────────────────────────────────────────────────────────────────

def check_ffmpeg():
    """Verifica que ffmpeg está instalado."""
    if not shutil.which('ffmpeg'):
        print("❌  ffmpeg no encontrado.")
        print("    Windows: https://ffmpeg.org/download.html (añadir a PATH)")
        print("    Mac:     brew install ffmpeg")
        print("    Linux:   sudo apt install ffmpeg")
        sys.exit(1)


def get_video_duration(video_path):
    """Devuelve la duración del video en segundos (float). -1 si falla."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return -1.0


def extract_frame(video_path, output_path, at_second):
    """
    Extrae un frame del video en `at_second` y lo guarda en `output_path`.
    Devuelve True si tuvo éxito.
    """
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(at_second),
        '-i', video_path,
        '-frames:v', '1',
        '-q:v', str(JPEG_QUALITY),
        '-vf', 'scale=960:-1',   # ancho máximo 960px, alto proporcional
        output_path
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0 and os.path.isfile(output_path)
    except subprocess.TimeoutExpired:
        print(f"    ⚠️  Timeout extrayendo frame de {os.path.basename(video_path)}")
        return False
    except Exception as e:
        print(f"    ⚠️  Error: {e}")
        return False


def choose_timestamp(video_path, requested_time):
    """
    Elige el timestamp de extracción:
    - Si la duración es conocida y requested_time > duración, usa 10% de la duración.
    - Si la duración < 1s, usa 0.
    - Siempre devuelve un valor válido.
    """
    duration = get_video_duration(video_path)
    if duration <= 0:
        return min(requested_time, 2)
    if duration < 1:
        return 0
    if requested_time >= duration:
        return max(0, duration * 0.1)
    return requested_time


# ── Core ───────────────────────────────────────────────────────────────────────

def process_album(album, album_dir, args):
    videos = [
        f for f in sorted(os.listdir(album_dir))
        if os.path.splitext(f)[1].lower() in VIDEO_EXTS
        and os.path.isfile(os.path.join(album_dir, f))
    ]

    if not videos:
        return 0, 0

    generated = 0
    skipped   = 0

    for fname in videos:
        stem        = os.path.splitext(fname)[0]
        poster_name = stem + POSTER_SUFFIX + '.jpg'
        poster_path = os.path.join(album_dir, poster_name)
        video_path  = os.path.join(album_dir, fname)

        if os.path.isfile(poster_path) and not args.force:
            print(f"  ⏭️  {fname[:60]}  →  ya tiene poster")
            skipped += 1
            continue

        at = choose_timestamp(video_path, args.time)
        print(f"  🎬  {fname[:60]}")
        print(f"      → extrayendo frame en {at:.1f}s…")

        if args.dry_run:
            print(f"      [dry-run] se crearía: {poster_name}")
            skipped += 1
            continue

        ok = extract_frame(video_path, poster_path, at)
        if ok:
            size_kb = os.path.getsize(poster_path) // 1024
            print(f"      ✅  {poster_name}  ({size_kb} KB)")
            generated += 1
        else:
            # Intento con frame en 0s como fallback
            print(f"      ↩️  Reintentando en 0s…")
            ok = extract_frame(video_path, poster_path, 0)
            if ok:
                size_kb = os.path.getsize(poster_path) // 1024
                print(f"      ✅  {poster_name}  ({size_kb} KB, frame 0s)")
                generated += 1
            else:
                print(f"      ❌  No se pudo extraer frame de {fname}")

    return generated, skipped


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Genera thumbnails reales para cada video del portfolio'
    )
    parser.add_argument('--album', metavar='NOMBRE',
                        help='Procesa solo este álbum')
    parser.add_argument('--dry-run', action='store_true',
                        help='Muestra qué haría sin crear archivos')
    parser.add_argument('--force', action='store_true',
                        help='Regenera posters aunque ya existan')
    parser.add_argument('--time', type=float, default=DEFAULT_TIME,
                        help=f'Segundo del que extraer el frame (default: {DEFAULT_TIME})')
    args = parser.parse_args()

    check_ffmpeg()

    albums = sorted([
        d for d in os.listdir(SCRIPT_DIR)
        if os.path.isdir(os.path.join(SCRIPT_DIR, d))
        and d not in IGNORE_DIRS
        and not d.startswith('.')
        and (args.album is None or d == args.album)
    ])

    if not albums:
        name = args.album or '(ninguno)'
        print(f"⚠️  No se encontraron álbumes que coincidan con: {name}")
        sys.exit(1)

    total_gen = 0
    total_skip = 0

    for album in albums:
        album_dir = os.path.join(SCRIPT_DIR, album)
        print(f"\n📁  Álbum: {album}")
        gen, skip = process_album(album, album_dir, args)
        total_gen  += gen
        total_skip += skip

    print(f"\n{'─'*50}")
    print(f"✅  Generados: {total_gen}  |  ⏭️  Saltados: {total_skip}")

    if total_gen > 0 and not args.dry_run:
        print("\n🔄  Actualizando portfolio.html…")
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, 'update-portfolio.py')],
            cwd=SCRIPT_DIR
        )
        if result.returncode == 0:
            print("✅  portfolio.html actualizado. Recarga el navegador.")
        else:
            print("⚠️  Revisa update-portfolio.py manualmente.")
    elif args.dry_run:
        print("\n[dry-run] — ningún archivo fue creado o modificado.")
