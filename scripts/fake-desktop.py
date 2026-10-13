#!/usr/bin/env python3
"""Replace public/mac/desktop.json with a fake but believable desktop.

Creates placeholder files in a temp folder, renders their real Finder icons /
QuickLook previews with scripts/.bin/icon-helper, and writes made-up names,
sizes (which drive icon mass in the sim) and Finder grid positions.
No personal file names or contents are used.

    python3 scripts/fake-desktop.py
"""
import json, os, random, shutil, subprocess, tempfile, zipfile
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'public', 'mac')
ICONS = os.path.join(OUT, 'icons')
HELPER = os.path.join(ROOT, 'scripts', '.bin', 'icon-helper')
rng = random.Random(42)

# Finder grid on a 1728 px wide desktop: columns step 72 from the right edge, rows step 88.
COL = lambda c: 1688 - 72 * c
ROW = lambda r: 69 + 88 * r

# name, kind, bytes, (col, row) or (x, y) absolute for strays, icloud
ITEMS = [
    # folders are moving boxes: the barricade
    ('Macintosh HD',                          'volume', 18_576_642_048, (0, 0)),
    ('Hallway Recordings',                    'folder',  6_660_000_000, (0, 1)),
    ('DO NOT OPEN',                           'folder',    666_000_000, (0, 2)),
    ('Costume Ideas',                         'folder',    131_000_000, (0, 3)),
    ('Old Toys',                              'folder',  1_900_000_000, (0, 4)),
    ('untitled folder',                       'folder',              0, (0, 5)),
    ('Party Playlist',                        'folder',     58_000_000, (1, 5)),
    # .usdz files are things to defend yourself with (their 3D thumbnails are rendered at runtime)
    ('candle.usdz',                           'usdz',        1_200_000, (1, 0)),
    ('candle 2.usdz',                         'usdz',        1_200_000, (1, 1)),
    ('road_flare.usdz',                       'usdz',        2_800_000, (1, 2)),
    ('salt.usdz',                             'usdz',          900_000, (1, 3)),
    ('batteries.usdz',                        'usdz',          640_000, (1, 4)),
    ('music_box.usdz',                        'usdz',        3_100_000, (2, 0)),
    # documents
    ('it_comes_at_3am.txt',                   'txt',             2_100, (2, 1)),
    ('IMG_0666.jpeg',                         'jpeg',        3_310_000, (2, 2)),
    ('candy_inventory.csv',                   'csv',            46_000, (2, 3)),
    # strays dragged out of the grid and forgotten
    ('dont_turn_around.jpeg',                 'jpeg',        2_400_000, ('abs', 1270, 860)),
    ('exorcism_checklist.md',                 'md',              1_300, ('abs', 250, 830)),
]

# macOS 26 folder colours: (hue 0..255, saturation scale, value scale)
FOLDER_TINT = {
    'costume-ideas': (14, 1.25, 1.0),       # orange
    'party-playlist': (192, 0.85, 0.92),    # purple
    'do-not-open': (250, 1.2, 0.9),         # red
    'hallway-recordings': (140, 0.0, 0.78), # graphite
}

def tint_folder(path, hue, sat, val):
    im = Image.open(path).convert('RGBA')
    a = im.getchannel('A')
    h, s_, v = im.convert('RGB').convert('HSV').split()
    h = h.point(lambda _: hue)
    s_ = s_.point(lambda x: min(255, int(x * sat)))
    v = v.point(lambda x: min(255, int(x * val)))
    out = Image.merge('HSV', (h, s_, v)).convert('RGB')
    out.putalpha(a)
    out.save(path)

def cardboard_folder(path, name):
    """Finder's folder shape, but made of corrugated cardboard with packing tape and a marker scrawl."""
    im = Image.open(path).convert('RGBA')
    w, h = im.size
    a = im.getchannel('A')
    lum = im.convert('L')
    # keep the folder's shading (its luminance), recolour to kraft board
    base = Image.new('RGB', (w, h), (176, 128, 78))
    shade = lum.point(lambda v: int(150 + (v - 180) * 1.1) if v > 0 else 0)
    board = Image.composite(base, Image.new('RGB', (w, h), (120, 82, 46)), shade)
    d = ImageDraw.Draw(board)
    rnd = random.Random(name)
    # flutes and fibres
    for y in range(0, h, max(2, h // 64)):
        d.line([(0, y), (w, y)], fill=(160, 114, 66), width=1)
    for _ in range(w * 3):
        x, y = rnd.randrange(w), rnd.randrange(h)
        c = rnd.choice([(140, 98, 56), (196, 150, 98)])
        d.point((x, y), fill=c)
    # the tab is the flap; a strip of tape down the middle of the front
    tw = w // 7
    tape = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tape)
    td.rectangle([w // 2 - tw // 2, int(h * 0.28), w // 2 + tw // 2, int(h * 0.86)], fill=(214, 184, 128, 150))
    board = Image.alpha_composite(board.convert('RGBA'), tape)
    # marker scribble standing for a label
    d = ImageDraw.Draw(board)
    y0 = int(h * 0.62)
    pts = [(int(w * 0.18) + i * w // 40, y0 + rnd.randint(-h // 60, h // 60)) for i in range(10)]
    d.line(pts, fill=(25, 20, 16, 230), width=max(2, w // 64))
    # darker edges
    edge = a.filter(ImageFilter.FIND_EDGES).point(lambda v: 90 if v > 40 else 0)
    board.paste((80, 54, 28), mask=edge)
    board.putalpha(a)
    board.save(path)

def slug(s):
    out = ''.join(ch.lower() if ch.isalnum() else '-' for ch in s)
    while '--' in out: out = out.replace('--', '-')
    return out.strip('-')

def gradient(w, h, top, bottom):
    im = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return im

TXT_3AM = """oct 12  02:58  footsteps in the hall again
oct 13  03:01  something ran past the door
oct 14  03:00  it stopped. it looked in.
oct 15  03:00  i left the flashlight on
oct 16  03:00  the flashlight was off
oct 17  03:00  it knows where i sit
"""

def grain(im, amount=18):
    noise = Image.effect_noise(im.size, amount).convert('L')
    return Image.blend(im, Image.merge('RGB', (noise, noise, noise)), 0.12)

def fake_photo(path, kind):
    """A grainy night photo: a dark doorway with a pale shape in it (or an empty hallway)."""
    w, h = 1600, 1200
    im = gradient(w, h, (22, 20, 18), (8, 7, 6))
    d = ImageDraw.Draw(im)
    # flash falloff on the wall
    glow = Image.new('L', (w, h), 0); gd = ImageDraw.Draw(glow)
    gd.ellipse([200, 50, 1400, 1150], fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    im = Image.composite(gradient(w, h, (96, 86, 70), (60, 52, 42)), im, glow)
    d = ImageDraw.Draw(im)
    if kind == 'doorway':
        d.rectangle([600, 260, 980, 1200], fill=(6, 5, 5))                # the opening
        d.rectangle([560, 230, 600, 1200], fill=(120, 110, 96)); d.rectangle([980, 230, 1020, 1200], fill=(120, 110, 96))
        d.rectangle([560, 230, 1020, 262], fill=(126, 116, 100))
        fig = Image.new('L', (w, h), 0); fd = ImageDraw.Draw(fig)
        fd.ellipse([760, 470, 830, 560], fill=120)                          # head
        fd.polygon([(735, 560), (860, 560), (880, 980), (715, 980)], fill=70)
        fd.line([(745, 580), (690, 900)], fill=70, width=16); fd.line([(850, 580), (905, 910)], fill=70, width=16)
        fig = fig.filter(ImageFilter.GaussianBlur(9))
        im = Image.composite(Image.new('RGB', (w, h), (150, 150, 146)), im, fig)
        d = ImageDraw.Draw(im)
        d.ellipse([776, 505, 784, 513], fill=(230, 220, 200)); d.ellipse([806, 505, 814, 513], fill=(230, 220, 200))
    else:
        d.polygon([(500, 300), (1100, 300), (1500, 1200), (100, 1200)], fill=(40, 34, 28))
        d.rectangle([700, 380, 900, 760], fill=(4, 4, 4))
        im = im.filter(ImageFilter.GaussianBlur(2))
    im = grain(im.filter(ImageFilter.GaussianBlur(1.5)))
    im.save(path, quality=86)

def fake_screenshot(path, variant):
    w, h = 1800, 1120
    im = Image.new('RGB', (w, h), (30, 30, 34) if variant else (242, 242, 246))
    d = ImageDraw.Draw(im)
    fg = (60, 60, 66) if variant else (210, 210, 216)
    d.rounded_rectangle([60, 60, w - 60, h - 60], 24, fill=(44, 44, 50) if variant else (255, 255, 255), outline=fg, width=2)
    d.rectangle([60, 60, 420, h - 60], fill=(38, 38, 44) if variant else (246, 246, 250))
    for i in range(9): d.rounded_rectangle([100, 140 + i * 70, 380, 170 + i * 70], 8, fill=fg)
    for i in range(6):
        d.rounded_rectangle([480, 140 + i * 150, 480 + rng.randint(500, 1200), 190 + i * 150], 10, fill=fg)
        d.rounded_rectangle([480, 210 + i * 150, 480 + rng.randint(300, 900), 230 + i * 150], 6, fill=fg)
    d.rounded_rectangle([1300, 130, 1700, 520], 20, fill=(90, 120, 240))
    im.save(path)

def fake_pdf(path, title_lines, red=False):
    pages = []
    im = Image.new('RGB', (1240, 1754), 'white'); d = ImageDraw.Draw(im)
    d.rectangle([110, 120, 700, 180], fill=(30, 30, 30))
    for i in range(title_lines): d.rectangle([110, 260 + i * 42, 110 + rng.randint(600, 1000), 280 + i * 42], fill=(150, 150, 150))
    d.rectangle([110, 1100, 1130, 1104], fill=(60, 60, 60))
    if red:
        d.line([(700, 1520), (760, 1470), (800, 1540), (880, 1460), (960, 1530), (1060, 1480)], fill=(140, 10, 10), width=9)
        for x, y in ((820, 1580), (835, 1630), (812, 1690)): d.ellipse([x, y, x + 14, y + 22], fill=(130, 8, 8))
    for i in range(6): d.rectangle([110, 1150 + i * 50, 1130, 1170 + i * 50], fill=(205, 205, 205))
    pages.append(im)
    pages[0].save(path, 'PDF', resolution=150)

def main():
    if not os.path.exists(HELPER):
        raise SystemExit('icon helper missing: run `npm run scan` once to compile scripts/.bin/icon-helper')
    tmp = tempfile.mkdtemp(prefix='fake-desktop-')
    os.makedirs(ICONS, exist_ok=True)
    # remove previously generated desktop icons (they came from real files)
    for f in os.listdir(ICONS):
        if f.startswith('desk-'): os.remove(os.path.join(ICONS, f))

    thumbs, icons, items = [], [], []
    for name, kind, size, place in ITEMS:
        id_ = slug(name)
        if kind == 'volume':
            p = '/'
        else:
            p = os.path.join(tmp, name)
            if kind in ('m4a', 'usdz'):
                open(p, 'wb').write(b'\0' * 64)
            elif kind == 'folder':
                os.makedirs(p)
            elif kind in ('png',):
                fake_screenshot(p, True)
            elif kind == 'jpeg':
                fake_photo(p, 'doorway' if '0666' in name else 'hall')
            elif kind == 'pdf':
                fake_pdf(p, 14 if 'lease' in name else 22, red='lease' in name)
            elif kind == 'zip':
                with zipfile.ZipFile(p, 'w') as z: z.writestr('readme.txt', 'archive')
            elif kind == 'csv':
                open(p, 'w').write('candy,bought,left\nfun-size bars,240,12\ncandy corn,80,80\nlollipops,120,0\n')
            elif kind == 'txt':
                open(p, 'w').write(TXT_3AM)
            elif kind == 'md':
                open(p, 'w').write('# exorcism checklist\n\n- [x] candles\n- [x] salt (a lot)\n- [ ] holy water\n- [ ] ask it to leave politely\n- [ ] move out\n')
            else:
                open(p, 'wb').write(b'\0' * 64)   # dmg / mov / psd: generic type icon by extension
        out = os.path.join(ICONS, f'desk-{id_}.png')
        (thumbs if kind in ('png', 'jpeg', 'pdf', 'txt', 'md', 'csv') else icons).append((p, out))
        if place[0] == 'abs':
            pos = {'x': place[1], 'y': place[2]}
        else:
            pos = {'x': COL(place[0]), 'y': ROW(place[1])}
        ext = '' if kind in ('folder', 'volume') else name.rsplit('.', 1)[-1].lower()
        items.append({
            'id': id_, 'name': name, 'path': p, 'kind': kind, 'ext': ext,
            'isFolder': kind in ('folder', 'volume'), 'bytes': size, 'icloud': False,
            'finderKind': kind, 'pos': pos, 'icon': f'/mac/icons/desk-{id_}.png',
        })

    def run(mode, pairs):
        if not pairs: return
        args = [HELPER, mode, '256']
        for a, b in pairs: args += [a, b]
        subprocess.run(args, check=True)
    run('thumb', thumbs)
    run('icon', icons)
    for it in items:
        if not os.path.exists(os.path.join(ICONS, f"desk-{it['id']}.png")):
            print('no icon for', it['name']); it['icon'] = None
        it['path'] = '/Users/demo/Desktop/' + it['name'] if it['kind'] != 'volume' else '/'

    for it in items:
        if it['kind'] == 'folder' and it['icon']:
            cardboard_folder(os.path.join(ICONS, f"desk-{it['id']}.png"), it['name'])

    desktop_path = os.path.join(OUT, 'desktop.json')
    prev = json.load(open(desktop_path)) if os.path.exists(desktop_path) else {}
    data = {
        'display': {'width': 1728, 'height': 1117},
        'positionsFromFinder': True,
        'view': prev.get('view', {'iconSize': 48, 'gridSpacing': 32, 'textSize': 10, 'labelOnBottom': True,
                                  'arrangeBy': 'grid', 'showItemInfo': False, 'showIconPreview': True,
                                  'showHardDrives': True, 'showExternalDrives': True}),
        'items': items,
        'fake': True,
    }
    json.dump(data, open(desktop_path, 'w'), indent=2)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'wrote {len(items)} fake desktop items to {desktop_path}')

if __name__ == '__main__':
    main()
