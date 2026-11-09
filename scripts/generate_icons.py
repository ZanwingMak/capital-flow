"""Generate Flowdesk's original brand assets. Requires Pillow==12.2.0.

Run from any directory: python scripts/generate_icons.py
All geometry uses a 1024-unit canvas; SVG and raster share these constants.
No fonts, network downloads, local user files or platform tools are needed.
"""
from io import BytesIO
from pathlib import Path
import struct

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / 'dist' / 'brand'
BACKGROUND = '#101e2d'
BARS = ((256, 580, 368, 752), (456, 460, 568, 752), (656, 340, 768, 752))
COLORS = ('#205d68', '#247e83', '#2aa498')
FLOW = ((256, 468), (456, 348), (568, 348), (768, 228))
ACCENT = '#65f0cb'


def png_bytes(image):
    output = BytesIO()
    image.save(output, format='PNG', optimize=False)
    return output.getvalue()


def render(size):
    # Supersampling keeps 16/24/32px silhouettes legible without tiny details.
    scale = 4
    image = Image.new('RGBA', (1024 * scale, 1024 * scale))
    draw = ImageDraw.Draw(image)
    box = lambda points: tuple(value * scale for value in points)
    draw.rounded_rectangle(box((64, 64, 960, 960)), radius=200 * scale, fill=BACKGROUND)
    for bounds, color in zip(BARS, COLORS):
        draw.rounded_rectangle(box(bounds), radius=28 * scale, fill=color)
    points = [(x * scale, y * scale) for x, y in FLOW]
    draw.line(points, fill=ACCENT, width=56 * scale, joint='curve')
    for x, y in FLOW:
        draw.ellipse(box((x - 28, y - 28, x + 28, y + 28)), fill=ACCENT)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    BRAND.mkdir(parents=True, exist_ok=True)
    bars = '\n'.join(f'  <rect x="{x}" y="{y}" width="{right-x}" height="{bottom-y}" rx="28" fill="{color}"/>'
                     for (x, y, right, bottom), color in zip(BARS, COLORS))
    points = ' '.join(f'{x},{y}' for x, y in FLOW)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-labelledby="title">
  <title id="title">Flowdesk — capital in motion</title>
  <rect x="64" y="64" width="896" height="896" rx="200" fill="{BACKGROUND}"/>
{bars}
  <polyline points="{points}" fill="none" stroke="{ACCENT}" stroke-width="56" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
'''
    (BRAND / 'flowdesk.svg').write_text(svg, encoding='utf-8')
    for size in (32, 192, 512, 1024):
        (BRAND / f'flowdesk-{size}.png').write_bytes(png_bytes(render(size)))
    render(1024).save(ROOT / 'dist' / 'favicon.ico', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    # Modern ICNS PNG entries: omit legacy icp4/icp5, which IconServices
    # interprets as ARGB on some macOS versions (same layout as pinned MyGo).
    body = bytearray()
    for kind, size in (('ic11', 32), ('ic12', 64), ('ic07', 128), ('ic13', 256),
                       ('ic08', 256), ('ic14', 512), ('ic09', 512), ('ic10', 1024)):
        payload = png_bytes(render(size))
        body.extend(kind.encode('ascii') + struct.pack('>I', len(payload) + 8) + payload)
    native = ROOT / 'desktop' / 'icons'
    native.mkdir(parents=True, exist_ok=True)
    (native / 'flowdesk.icns').write_bytes(b'icns' + struct.pack('>I', len(body) + 8) + body)
    (native / 'flowdesk.ico').write_bytes((ROOT / 'dist' / 'favicon.ico').read_bytes())
    print('Generated SVG, PNG (32/192/512/1024), favicon, native ICO and ICNS.')


if __name__ == '__main__':
    main()
