"""Build the TheWeion profile README from the live weion.dev content.

Pulls the Pages CMS JSON from the weion.dev repo and the same edge-cached
WakaTime share feeds the site's Telemetry section uses, then renders each
portfolio section as a HUD-styled SVG panel under ``assets/`` and rewrites
``README.md``. Run by ``.github/workflows/build.yml`` on a daily schedule.

Environment overrides (for local runs):
  CONTENT_DIR   read the CMS JSON from a local ``src/content`` instead of GitHub
  CONTENT_REF   weion.dev commit/branch to read the CMS JSON from (default main)
  SITE_URL      site origin for the WakaTime proxy and portrait (default weion.dev)
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from fontTools import subset
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets'
FONT_DIR = ROOT / 'scripts' / 'fonts'
SITE = os.environ.get('SITE_URL', 'https://weion.dev').rstrip('/')
CONTENT_REF = os.environ.get('CONTENT_REF') or 'main'
CONTENT_RAW = f'https://raw.githubusercontent.com/TheWeion/weion.dev/{CONTENT_REF}/src/content'
WAKATIME = {
    'waveform': '/api/wakatime/share/@Weion/6b858290-31aa-4626-9973-44e3fe47826b.json',
    'languages': '/api/wakatime/share/@Weion/5af1726d-42dd-428f-b84c-4d5fe825002e.json',
    'year': '/api/wakatime/share/@Weion/e7721aa6-b409-4e94-8c7f-43271fe0a81e.json',
}

# `dark` mirrors src/lib/tokens.ts in weion.dev. `light` keeps the same roles with
# the accents darkened for contrast on GitHub's light theme. Every asset is
# rendered once per theme; the README serves the right one via <picture>.
THEMES = {
    'dark': dict(
        void='#05080C', panel='#0B1E2E', panel2='#132C3F', line='#1E3A52', muted='#7A8794',
        ink='#C0CAD3', bright='#E8F1F7', halo='#B6D6EB', amber='#F5A623', amber_hot='#FFB547',
        bronze='#8A6A3A', cyan='#03D8F3', magenta='#FF0055', ok='#7CE8C9', alarm='#E4412B',
        scan='#000000', scan_op='.28', panel_op='.92', heat0='rgba(30,58,82,.55)',
        heat_rgb='3,216,243', lang_l=(.5, .65)),
    'light': dict(
        void='#F4F7FA', panel='#FFFFFF', panel2='#E8EFF5', line='#C3D2DF', muted='#5E6E7D',
        ink='#2B3B4A', bright='#0B1E2E', halo='#2D6A94', amber='#B86A00', amber_hot='#C27400',
        bronze='#9A7440', cyan='#0088A6', magenta='#D6004A', ok='#11806A', alarm='#C2341F',
        scan='#0B1E2E', scan_op='.05', panel_op='.96', heat0='rgba(195,210,223,.7)',
        heat_rgb='0,136,166', lang_l=(.34, .44)),
}
C = dict(THEMES['dark'])


def set_theme(name):
    C.clear()
    C.update(THEMES[name])

W = 1200


# ---------------------------------------------------------------- fetching

def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'TheWeion-readme-builder'})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def load_content(name):
    local = os.environ.get('CONTENT_DIR')
    if local:
        return json.loads((Path(local) / f'{name}.json').read_text())
    return json.loads(fetch(f'{CONTENT_RAW}/{name}.json'))


def blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


# ---------------------------------------------------------------- fonts

class Font:
    """An embeddable, measurable webfont subset."""

    def __init__(self, family, weight, file, css_class):
        self.family, self.weight, self.css_class = family, weight, css_class
        self.path = FONT_DIR / file
        tt = TTFont(self.path)
        self.upm = tt['head'].unitsPerEm
        self.cmap = tt.getBestCmap()
        self.hmtx = tt['hmtx']
        self.fallback = self.hmtx[self.cmap.get(ord('M'), '.notdef')][0]
        self.face = None

    def width(self, text, size, ls=0.0):
        units = sum(self.hmtx[self.cmap[ord(ch)]][0] if ord(ch) in self.cmap else self.fallback
                    for ch in text)
        return units / self.upm * size + ls * len(text)

    def embed(self, charset):
        if self.face is None:
            opts = subset.Options()
            opts.flavor = 'woff2'
            font = subset.load_font(str(self.path), opts)
            font.recalcTimestamp = False  # keep output byte-stable so unchanged data doesn't commit
            sub = subset.Subsetter(opts)
            sub.populate(text=charset)
            sub.subset(font)
            buf = io.BytesIO()
            subset.save_font(font, buf, opts)
            b64 = base64.b64encode(buf.getvalue()).decode()
            self.face = (f"@font-face{{font-family:'{self.family}';font-weight:{self.weight};"
                         f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}"
                         f".{self.css_class}{{font-family:'{self.family}',sans-serif;"
                         f"font-weight:{self.weight}}}")
        return self.face


FONTS = {
    'd': Font('Orbitron', 900, 'orbitron-900.woff2', 'd'),
    'd7': Font('Orbitron', 700, 'orbitron-700.woff2', 'd7'),
    'r': Font('Rajdhani', 400, 'rajdhani-400.woff2', 'r'),
    'b': Font('Rajdhani', 600, 'rajdhani-600.woff2', 'b'),
    'bb': Font('Rajdhani', 700, 'rajdhani-700.woff2', 'bb'),
    'm': Font('Share Tech Mono', 400, 'share-tech-mono-400.woff2', 'm'),
}
CHARSET = ''.join(map(chr, range(32, 127))) + '·—–█●▸◆→■'


def wrap(text, font, size, max_w, ls=0.0):
    lines, line = [], ''
    for word in text.split():
        trial = f'{line} {word}'.strip()
        if line and font.width(trial, size, ls) > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


# ---------------------------------------------------------------- svg primitives

BASE_CSS = """
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes growX{from{transform:scaleX(0)}}
@keyframes growY{from{transform:scaleY(.02)}}
@keyframes fadeIn{from{opacity:0}}
.blink{animation:blink 1.1s steps(1) infinite}
.pulse{animation:pulse 2s ease-in-out infinite}
.gx{transform-box:fill-box;transform-origin:left;animation:growX .8s ease-out both}
.gy{transform-box:fill-box;transform-origin:bottom;animation:growY .6s ease-out both}
.fi{animation:fadeIn .5s ease-out both}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""

def panel_defs():
    return (f'<linearGradient id="pg" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{C["panel"]}" stop-opacity="{C["panel_op"]}"/>'
            f'<stop offset="1" stop-color="{C["panel2"]}" stop-opacity="{C["panel_op"]}"/>'
            f'</linearGradient>')


def svg(w, h, body, label, css='', defs='', scale=1.0):
    classes = {c for attr in re.findall(r'class="([^"]*)"', body) for c in attr.split()}
    used = [f for k, f in FONTS.items() if k in classes]
    faces = ''.join(f.embed(CHARSET) for f in used)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" '
            f'width="{w * scale:g}" height="{h * scale:g}" role="img" aria-label="{escape(label)}">'
            f'<style>{faces}{BASE_CSS}{css}</style><defs>{panel_defs()}{defs}</defs>{body}</svg>')


def text(x, y, s, cls, size, fill, ls=0.0, anchor='start', extra=''):
    a = f' text-anchor="{anchor}"' if anchor != 'start' else ''
    l = f' letter-spacing="{ls:g}"' if ls else ''
    return (f'<text x="{x:g}" y="{y:g}" class="{cls}" font-size="{size:g}" fill="{fill}"{l}{a}'
            f'{extra}>{escape(s)}</text>')


def cut_rect(x, y, w, h, c=12):
    return (f'M{x:g},{y + c:g} L{x + c:g},{y:g} H{x + w - c:g} L{x + w:g},{y + c:g} '
            f'V{y + h - c:g} L{x + w - c:g},{y + h:g} H{x + c:g} L{x:g},{y + h - c:g} Z')


def chip_path(x, y, w, h, c=6):
    return f'M{x + c:g},{y:g} H{x + w:g} V{y + h - c:g} L{x + w - c:g},{y + h:g} H{x:g} V{y + c:g} Z'


def brackets(x, y, w, h, s=14, color=C['halo'], sw=1.5):
    paths = [f'M{x},{y + s} V{y} H{x + s}', f'M{x + w - s},{y} H{x + w} V{y + s}',
             f'M{x + w},{y + h - s} V{y + h} H{x + w - s}', f'M{x + s},{y + h} H{x} V{y + h - s}']
    return ''.join(f'<path d="{p}" fill="none" stroke="{color}" stroke-width="{sw}"/>'
                   for p in paths)


def panel(x, y, w, h, label=None, meta=None, accent=C['halo']):
    """HUD ``Panel``: label row, cut-corner glass body, corner brackets.

    Returns (svg, body_top) — ``h`` is the body height, excluding the label row.
    """
    out = []
    top = y
    if label:
        out.append(f'<rect x="{x + 4}" y="{y + 4}" width="6" height="6" fill="{accent}"/>')
        out.append(text(x + 16, y + 11, label.upper(), 'b', 11, accent, 3.3))
        if meta:
            out.append(text(x + w - 6, y + 11, meta.upper(), 'm', 11, C['muted'], 2.2, 'end'))
        y += 22
    out.append(f'<path d="{cut_rect(x, y, w, h)}" fill="url(#pg)" stroke="{C["line"]}"/>')
    out.append(brackets(x - 1, top - 1, w + 2, y + h - top + 2, 14, accent))
    return ''.join(out), y


def tile(x, y, w, label, value, color):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="56" fill="{C["void"]}" fill-opacity=".35" '
            f'stroke="{C["line"]}"/>'
            + text(x + 10, y + 18, label, 'b', 10, color, 2.5)
            + text(x + 10, y + 44, value, 'd7', 17, C['bright']))


def stream_status(x, y, note='LIVE FEED · UPDATED DAILY'):
    return (f'<rect x="{x}" y="{y - 7}" width="6" height="6" fill="{C["amber"]}" class="pulse"/>'
            + text(x + 14, y, 'STREAM STATUS', 'b', 11, C['amber'], 2.6)
            + text(x + 132, y, f'· {note}', 'b', 11, C['muted'], 2.6))


WRITTEN = set()
THEME = ['dark']


def write(name, content):
    path = ASSETS / THEME[0] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    WRITTEN.add(path)
    path.write_text(content)


# ---------------------------------------------------------------- sections

def heading(eyebrow, title, center=False):
    h = 112
    x = W / 2 if center else 2
    anchor = 'middle' if center else 'start'
    ul_x = W / 2 - 220 if center else 2
    ul_w = 440 if center else W * 0.9
    body = (text(x, 22, eyebrow, 'b', 13, C['amber'], 4.5, anchor)
            + text(x, 80, title, 'd', 52, C['bright'], 0, anchor)
            + f'<rect x="{ul_x}" y="102" width="40" height="2" fill="{C["amber"]}"/>'
            + f'<rect x="{ul_x + 48}" y="102" width="8" height="2" fill="{C["amber"]}"/>'
            + f'<line x1="{ul_x + 64}" y1="103" x2="{ul_x + ul_w}" y2="103" stroke="{C["line"]}"/>')
    return svg(W, h, body, f'{eyebrow} — {title}')


def banner(op, portrait):
    H = 400
    F = 12  # frame inset — corner brackets sit outside it, like the holo-feed frame
    px, py, pw, ph = 856, 66, 280, 296
    name_size = 74
    while FONTS['d7'].width(op['realName'], name_size, -1) > 760:
        name_size -= 2
    tagline = wrap(op.get('tagline', ''), FONTS['bb'], 19, 640)[:2]
    role = f"{op['role']}"
    css = f"""
@keyframes sweep{{0%{{transform:translateY(-40px)}}100%{{transform:translateY({H + 40}px)}}}}
@keyframes glitchA{{0%,92%,100%{{transform:translate(0,0)}}93%{{transform:translate(-4px,1px)}}95%{{transform:translate(3px,-1px)}}97%{{transform:translate(-2px,0)}}}}
@keyframes glitchB{{0%,92%,100%{{transform:translate(0,0)}}93%{{transform:translate(4px,-1px)}}95%{{transform:translate(-3px,1px)}}97%{{transform:translate(2px,0)}}}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-6px)}}}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.sweep{{animation:sweep 6s linear infinite}}
.ga{{animation:glitchA 5s infinite}}
.gb{{animation:glitchB 5s infinite}}
.float{{animation:float 6s ease-in-out infinite}}
.spin{{transform-origin:{px + pw / 2}px {py + ph / 2}px;animation:spin 40s linear infinite}}
.spinr{{transform-origin:{px + pw / 2}px {py + ph / 2}px;animation:spin 28s linear infinite reverse}}
"""
    defs = f"""
<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40,0 H0 V40" fill="none" stroke="{C['line']}" opacity=".35"/></pattern>
<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="{C['scan']}" opacity="{C['scan_op']}"/></pattern>
<radialGradient id="warm" cx=".78" cy=".5" r=".55"><stop offset="0" stop-color="{C['amber']}" stop-opacity=".22"/><stop offset="1" stop-color="{C['amber']}" stop-opacity="0"/></radialGradient>
<radialGradient id="cool" cx=".15" cy=".2" r=".6"><stop offset="0" stop-color="{C['cyan']}" stop-opacity=".10"/><stop offset="1" stop-color="{C['cyan']}" stop-opacity="0"/></radialGradient>
<linearGradient id="sweepg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{C['halo']}" stop-opacity="0"/><stop offset=".5" stop-color="{C['halo']}" stop-opacity=".09"/><stop offset="1" stop-color="{C['halo']}" stop-opacity="0"/></linearGradient>
<clipPath id="frame"><path d="{cut_rect(F, F, W - 2 * F, H - 2 * F, 20)}"/></clipPath>
<clipPath id="pframe"><path d="{cut_rect(px, py, pw, ph, 14)}"/></clipPath>"""
    chips, cx = [], 60
    for i, label in enumerate([f"CODENAME · {op['codename']}", f"LOC · {op['location']}",
                               'CLEARANCE · GRANTED']):
        cw = FONTS['m'].width(label, 12, 2) + 28
        stroke, fill = (C['amber'], C['amber']) if i == 0 else (C['line'], C['halo'])
        chips.append(f'<path d="M{cx:g},314 h{cw:g} v14 l-8,8 h-{cw - 8:g} z" fill="none" stroke="{stroke}"/>'
                     + text(cx + 14, 330, label, 'm', 12, fill, 2))
        cx += cw + 14
    status = f"STATUS: {op.get('status', 'ACTIVE')}"
    sw = FONTS['m'].width(status, 13, 2)
    role_w = FONTS['b'].width(role, 20, 5)
    at_w = FONTS['b'].width(' @ ', 20, 5)
    name_layers = (
        f'<g font-size="{name_size}" letter-spacing="-1" class="d7">'
        f'<text x="58" y="176" fill="{C["cyan"]}" opacity=".7" class="d7 ga">{escape(op["realName"])}</text>'
        f'<text x="58" y="176" fill="{C["magenta"]}" opacity=".7" class="d7 gb">{escape(op["realName"])}</text>'
        f'<text x="58" y="176" fill="{C["bright"]}" class="d7">{escape(op["realName"])}</text></g>')
    body = f"""
<g clip-path="url(#frame)">
  <rect width="{W}" height="{H}" fill="{C['void']}"/>
  <rect width="{W}" height="{H}" fill="url(#grid)"/>
  <rect width="{W}" height="{H}" fill="url(#cool)"/>
  <rect width="{W}" height="{H}" fill="url(#warm)"/>
  <rect x="0" y="0" width="{W}" height="{F + 32}" fill="{C['panel']}" opacity=".85"/>
  <line x1="0" y1="{F + 32}" x2="{W}" y2="{F + 32}" stroke="{C['line']}"/>
  {text(40, F + 21, 'WEION.DEV //', 'm', 13, C['amber'], 2)}
  {text(162, F + 21, f"OPERATOR CONSOLE · LINK SECURE · TZ {op.get('timezone', 'UTC').upper()}", 'm', 13, C['muted'], 2)}
  <circle cx="{W - 40 - sw - 12:g}" cy="{F + 16}" r="4" fill="{C['ok']}" class="pulse"/>
  {text(W - 40, F + 21, status, 'm', 13, C['ok'], 2, 'end')}
  <rect x="60" y="86" width="7" height="7" fill="{C['amber']}" class="pulse"/>
  {text(78, 94, '// OPERATOR PROFILE', 'b', 13, C['amber'], 4.5)}
  {name_layers}
  {text(60, 216, role, 'b', 20, C['amber'], 5)}
  {text(60 + role_w, 216, '@', 'b', 20, C['muted'], 5, extra=f' dx="{at_w / 3:g}"') if op.get('affiliation') else ''}
  {text(60 + role_w + at_w, 216, op.get('affiliation', ''), 'b', 20, C['halo'], 5)}
  {''.join(text(60, 258 + i * 26, ln, 'bb', 19, C['ink']) for i, ln in enumerate(tagline))}
  {''.join(chips)}
  <text x="60" y="368" class="m" font-size="14" fill="{C['muted']}" letter-spacing="1">&gt; ACCESS GRANTED. WELCOME.<tspan fill="{C['amber']}" class="blink"> █</tspan></text>
  <circle cx="{px + pw / 2}" cy="{py + ph / 2}" r="188" fill="none" stroke="{C['line']}" stroke-dasharray="2 10" class="spin"/>
  <circle cx="{px + pw / 2}" cy="{py + ph / 2}" r="168" fill="none" stroke="{C['bronze']}" stroke-opacity=".6" stroke-dasharray="40 14 4 14" class="spinr"/>
  <path d="{cut_rect(px, py, pw, ph, 14)}" fill="{C['panel']}" fill-opacity=".55" stroke="{C['line']}"/>
  <g clip-path="url(#pframe)">
    <g class="float"><image href="{portrait}" x="{px + 10}" y="{py + 10}" width="{pw - 20}" height="{ph}" preserveAspectRatio="xMidYMin meet" opacity=".92"/></g>
    <rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="url(#scan)"/>
    <rect x="{px}" y="{py + ph - 28}" width="{pw}" height="28" fill="{C['void']}" opacity=".8"/>
    {text(px + 14, py + ph - 9, 'HOLO-FEED · OP-01', 'm', 12, C['cyan'], 2)}
    {text(px + pw - 14, py + ph - 9, '● REC', 'm blink', 12, C['amber'], 2, 'end')}
  </g>
  {brackets(px - 8, py - 8, pw + 16, ph + 16, 20, C['amber'], 2)}
  <rect x="0" y="0" width="{W}" height="40" fill="url(#sweepg)" class="sweep"/>
  <rect width="{W}" height="{H}" fill="url(#scan)" opacity=".5"/>
</g>
<path d="{cut_rect(F, F, W - 2 * F, H - 2 * F, 20)}" fill="none" stroke="{C['line']}" stroke-width="2"/>
{brackets(2, 2, W - 4, H - 4, 28, C['amber'], 2)}"""
    return svg(W, H, body, f"{op['codename']} // {op['realName']}, {role} @ {op.get('affiliation', '')}",
               css, defs)


def tz_label(tz):
    off = datetime.now(ZoneInfo(tz)).utcoffset() or timedelta()
    mins = int(off.total_seconds() // 60)
    sign = '+' if mins >= 0 else '-'
    return f'UTC{sign}{abs(mins) // 60:02d}:{abs(mins) % 60:02d} · {tz.upper()}'


def dossier(profile):
    op = profile['operative']
    gap = 24
    lw = 700
    rx, rw = lw + gap + 2, W - lw - gap - 4
    bio = wrap(profile['bio'], FONTS['r'], 18, lw - 52)
    bio_h = 28 + len(bio) * 30 + 64
    left, ly = panel(2, 2, lw, bio_h, 'BIOGRAPHICAL RECORD', 'CLASSIFICATION: OPEN', C['halo'])
    left += ''.join(text(26, ly + 40 + i * 30, ln, 'r', 18, C['ink']) for i, ln in enumerate(bio))
    fy = ly + bio_h - 44
    left += f'<line x1="26" y1="{fy}" x2="{lw - 24}" y2="{fy}" stroke="{C["line"]}"/>'
    left += (f'<text x="26" y="{fy + 28}" class="m" font-size="12" letter-spacing="2.4" fill="{C["muted"]}">'
             f'<tspan fill="{C["amber"]}">&gt;</tspan> {escape(profile.get("signoff", "END OF FILE"))}</text>')

    vitals = [('CODENAME', op['codename']), ('AFFILIATION', op.get('affiliation')),
              ('SECTOR', op.get('location')), ('TZ', tz_label(op.get('timezone', 'UTC'))),
              ('STATUS', op.get('status'))]
    vitals = [(k, v) for k, v in vitals if not blank(v)]
    vh = 28 + len(vitals) * 28
    right, vy = panel(rx, 2, rw, vh, 'VITALS', 'LIVE', C['amber'])
    for i, (k, v) in enumerate(vitals):
        right += text(rx + 24, vy + 36 + i * 28, k, 'm', 13, C['amber'], 2.6)
        right += text(rx + 150, vy + 36 + i * 28, str(v).upper(), 'm', 13, C['bright'], 0.5)
    y2 = vy + vh + 22
    assoc = profile.get('associates') or []
    if assoc:
        ah = 20 + len(assoc) * 30
        a, ay = panel(rx, y2, rw, ah, 'KNOWN ASSOCIATES', None, C['cyan'])
        right += a
        for i, item in enumerate(assoc):
            right += (f'<text x="{rx + 24}" y="{ay + 34 + i * 30}" class="r" font-size="16" fill="{C["ink"]}">'
                      f'{escape(item["label"])}<tspan fill="{C["muted"]}"> · </tspan>'
                      f'{escape(item.get("detail") or "")}</text>')
        y2 = ay + ah
    h = max(ly + bio_h, y2) + 4
    return svg(W, h, left + right, f"Personnel file — {op['realName']}")


def fmt_period(start, end):
    def f(v):
        return 'PRESENT' if blank(v) else str(v).replace('-', '.')
    return f'{f(start)} — {f(end)}'


def timeline(entries, label):
    row = 84
    h = 24 + len(entries) * row
    out, y = panel(2, 2, W - 4, h, label, f'{len(entries)} ENTRIES', C['halo'])
    out += (f'<line x1="28" y1="{y + 30}" x2="28" y2="{y + h - 30}" stroke="{C["line"]}"/>')
    for i, e in enumerate(entries):
        ry = y + 28 + i * row
        color = C['amber'] if i == 0 else C['muted']
        out += f'<rect x="23" y="{ry + 2}" width="9" height="9" transform="rotate(45 27.5 {ry + 6.5})" fill="{color}"/>'
        out += text(52, ry + 12, fmt_period(e.get('start'), e.get('end')), 'm', 12, C['amber'], 3)
        out += text(52, ry + 34, e['role'], 'b', 17, C['ink'], 0.4)
        meta = e['org'] + (f"   ·   {e['location']}" if not blank(e.get('location')) else '')
        out += text(52, ry + 54, meta, 'm', 12, C['halo'], 1.2)
    return out, y + h


def service_record(experience, education):
    exp, y = timeline(experience, 'SERVICE RECORD')
    edu, y2 = timeline(education, 'EDUCATION')
    return svg(W, y + 30 + y2 + 4, exp + f'<g transform="translate(0 {y + 30})">{edu}</g>',
               'Service record and education')


def capabilities(skills, core):
    core = set(core)
    size, ls, pad, ch, gap = 13, 2, 14, 32, 10
    inner = W - 4 - 48
    rows, x, y = [], 0, 0
    for s in skills:
        label = s.upper()
        cw = FONTS['b'].width(label, size, ls) + pad * 2 - ls
        if x and x + cw > inner:
            x, y = 0, y + ch + gap
        rows.append((x, y, cw, label, s in core))
        x += cw + gap
    h = y + ch + 48
    out, py = panel(2, 2, W - 4, h, 'LOADED MODULES', f'COUNT: {len(skills):03d}', C['halo'])
    for i, (x, y, cw, label, hi) in enumerate(rows):
        bx, by = 26 + x, py + 24 + y
        fill, stroke, color, op = ((C['amber'], C['amber'], C['amber_hot'], .1) if hi
                                   else (C['halo'], C['line'], C['ink'], .04))
        out += (f'<g class="fi" style="animation-delay:{i * 18}ms">'
                f'<path d="{chip_path(bx, by, cw, ch)}" fill="{fill}" fill-opacity="{op}" stroke="{stroke}"/>'
                + text(bx + pad, by + 21, label, 'b', size, color, ls) + '</g>')
    return svg(W, py + h + 4, out, f'Capabilities matrix — {len(skills)} modules')


def project_card(p):
    w = W - 4
    summary = wrap(p['summary'], FONTS['r'], 17, w - 56)
    h = 150 + len(summary) * 26  # 24px below the stack chips
    out = (f'<path d="{cut_rect(2, 2, w, h, 12)}" fill="url(#pg)" stroke="{C["line"]}"/>'
           + brackets(1, 1, w + 2, h + 2, 14, C['halo']))
    out += (f'<text x="26" y="34" class="m" font-size="12" letter-spacing="1.5" fill="{C["amber"]}">'
            f'OP-{escape(p["id"])}<tspan fill="{C["line"]}">  |  </tspan>'
            f'<tspan fill="{C["muted"]}">{escape(p["codename"])}</tspan></text>')
    sl = '● OPERATIONAL'
    sw = FONTS['b'].width(sl, 11, 2.2) - 2.2 + 24
    out += (f'<rect x="{w - 22 - sw:g}" y="18" width="{sw:g}" height="24" fill="{C["ok"]}" fill-opacity=".06" stroke="{C["ok"]}"/>'
            + text(w - 22 - sw / 2 + 1.1, 34, sl, 'b', 11, C['ok'], 2.2, 'middle'))
    out += text(26, 78, p['name'], 'd7', 28, C['bright'])
    out += ''.join(text(26, 112 + i * 26, ln, 'r', 17, C['muted']) for i, ln in enumerate(summary))
    x, cy = 26, 112 + len(summary) * 26 - 8
    for s in p.get('stack', []):
        label = s.upper()
        cw = FONTS['b'].width(label, 11, 2.2) - 2.2 + 24  # trailing letter-spacing excluded
        out += (f'<rect x="{x:g}" y="{cy}" width="{cw:g}" height="22" fill="{C["cyan"]}" fill-opacity=".05" stroke="{C["cyan"]}" stroke-opacity=".7"/>'
                + text(x + cw / 2 + 1.1, cy + 15, label, 'b', 11, C['cyan'], 2.2, 'middle'))
        x += cw + 8
    return svg(W, h + 4, out, f"{p['name']} — {p['summary']}")


ICONS = {
    'play': '<circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M5.5,4.5 L9.5,7 L5.5,9.5 Z" fill="currentColor"/>',
    'ext': '<path d="M8,1.5 H12.5 V6 M12.5,1.5 L6.5,7.5 M10.5,8.5 V12.5 H1.5 V3.5 H5.5" fill="none" stroke="currentColor" stroke-width="1.4"/>',
    'code': '<path d="M4.5,3 L1,7 L4.5,11 M9.5,3 L13,7 L9.5,11" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    'mail': '<rect x="1" y="2.5" width="12" height="9" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M1,3 L7,8 L13,3" fill="none" stroke="currentColor" stroke-width="1.3"/>',
    'link': '<rect x="1" y="1" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M4,6 V10.5 M4,3.6 V4.4 M6.5,10.5 V6 M6.5,7.8 Q6.5,6 8.3,6 Q10,6 10,7.8 V10.5" fill="none" stroke="currentColor" stroke-width="1.3"/>',
    'chev': '<path d="M4.5,2.5 L9,7 L4.5,11.5" fill="none" stroke="currentColor" stroke-width="1.8"/>',
}


def button(label, icon, variant='ghost', size='md'):
    """``AngularButton`` as a standalone, linkable image."""
    fs, h, ls = (12, 38, 3) if size == 'md' else (11, 32, 2.6)
    tw = FONTS['bb'].width(label, fs, ls) - ls
    w = 16 + 14 + 10 + tw + 18
    color, fill, op, stroke = {
        'amber': (C['amber'], C['amber'], .08, C['amber']),
        'ghost': (C['bright'], C['halo'], .03, C['muted']),
        'quiet': (C['muted'], C['halo'], .02, C['bronze']),
    }[variant]
    body = (f'<path d="M8,.5 H{w - .5:g} V{h - 8.5:g} L{w - 8.5:g},{h - .5:g} H.5 V8.5 Z" '
            f'fill="{fill}" fill-opacity="{op}" stroke="{stroke}"/>'
            f'<g transform="translate(16 {(h - 14) / 2:g})" color="{color}" style="color:{color}">{ICONS[icon]}</g>'
            + text(40, h / 2 + fs * .36, label, 'bb', fs, color, ls))
    return svg(w, h, body, label, scale=.85)


def hex_to_hsl(hx):
    hx = hx.lstrip('#').rjust(6, '0')
    r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2 - mx - mn) if l > .5 else d / (mx + mn)
    if mx == r:
        h = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60, s, l


def hsl_to_hex(h, s, l):
    c = (1 - abs(2 * l - 1)) * s
    hh = ((h % 360) + 360) % 360 / 60
    x = c * (1 - abs(hh % 2 - 1))
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][min(int(hh), 5)]
    m = l - c / 2
    return '#' + ''.join(f'{round((v + m) * 255):02x}' for v in (r, g, b))


def bar_color(hx):
    """Port of ``pickBarColor`` / ``sciFiTune`` in useWakatime.ts."""
    h, s, l = hex_to_hsl(hx)
    if s >= .1:
        lo, hi = C['lang_l']
        return hsl_to_hex(h, max(s, .8), min(hi, max(lo, l)))
    if l < .3:
        return C['bronze']
    if l > .7:
        return C['halo']
    return C['muted']


def fmt_duration(secs):
    secs = max(0, round(secs or 0))
    if secs < 86400:
        return f'{secs // 3600}h {(secs % 3600) // 60:02d}m'
    if secs < 7 * 86400:
        return f'{secs // 86400}d {(secs % 86400) // 3600:02d}h'
    return f'{secs // (7 * 86400)}w {(secs % (7 * 86400)) // 86400}d'


def fmt_streak(n):
    n = max(0, int(n or 0))
    return f"{n} day{'' if n == 1 else 's'}" if n < 7 else f'{n // 7}w {n % 7}d'


def telemetry_model(wave, langs, year):
    """Port of the transforms in useWakatime.ts, so numbers match the site."""
    langs = langs.get('data') or []
    named = [l for l in langs if l['name'] != 'Other' and (l.get('percent') or 0) > 0]
    bars = [(l['name'], round(l['percent'] * 10) / 10, bar_color(l.get('color') or C['muted']))
            for l in named[:5]]
    other = sum(l.get('percent') or 0 for l in named[5:]) + next(
        (l.get('percent') or 0 for l in langs if l['name'] == 'Other'), 0)
    if other >= .1:
        bars.append(('Other', round(other * 10) / 10, C['muted']))

    days = [(d['range']['date'], d['grand_total']['total_seconds'])
            for d in wave.get('data') or [] if d.get('range', {}).get('date')]
    peak = max((s for _, s in days), default=0)
    avg = sum(s for _, s in days) / len(days) if days else 0
    streak, started = 0, False
    for _, s in reversed(days):
        if s > 0:
            streak, started = streak + 1, True
        elif started:
            break
    waveform = [s / peak if peak else 0 for _, s in days]

    pts = [(d['date'], d.get('total') or 0) for d in year.get('days') or []]
    nz = sorted(s for _, s in pts if s > 0)

    def q(p):
        return nz[min(len(nz) - 1, int(len(nz) * p))] if nz else 0
    t1, t2, t3 = q(.25), q(.5), q(.75)
    heat = [(d, 0 if s <= 0 else 1 if s <= t1 else 2 if s <= t2 else 3 if s <= t3 else 4)
            for d, s in pts]
    total = sum(s for _, s in pts)
    best = max(pts, key=lambda p: p[1], default=('', 0))
    best_day = (datetime.strptime(best[0], '%Y-%m-%d').strftime('%d %b').upper()
                if best[1] > 0 else '—')
    top = next((l['name'] for l in langs if l['name'] != 'Other'), '—')
    return dict(
        bars=bars, waveform=waveform,
        tiles=[('AVG/DAY', fmt_duration(avg), C['amber']), ('PEAK', fmt_duration(peak), C['cyan']),
               ('STREAK', fmt_streak(streak), C['ok'])],
        heat=heat,
        year_tiles=[('TOTAL', fmt_duration(total), C['cyan']), ('TOP LANG', top, C['amber']),
                    ('BEST DAY', best_day, C['ok'])])


def heat_colors():
    return [C['heat0']] + [f"rgba({C['heat_rgb']},{a})" for a in ('.18', '.42', '.70', '1')]


def telemetry(m, synced):
    note = f'SYNCED {synced} · UPDATED DAILY'
    cw = (W - 4 - 24) / 2
    top_h = 320
    out, ly = panel(2, 2, cw, top_h, '30-DAY LANGUAGE DISTRIBUTION', 'VIA WAKATIME', C['halo'])
    for i, (name, pct, color) in enumerate(m['bars']):
        by = ly + 34 + i * 40
        out += text(26, by, name.upper(), 'b', 11, color, 2.4)
        out += text(cw - 22, by, f'{pct:g}%', 'm', 12, C['muted'], 2, 'end')
        bw = cw - 48
        out += f'<rect x="26" y="{by + 8}" width="{bw:g}" height="6" fill="{C["panel"]}" stroke="{C["line"]}"/>'
        gid = f'lg{i}'
        out += (f'<linearGradient id="{gid}"><stop offset="0" stop-color="{color}"/>'
                f'<stop offset="1" stop-color="{color}" stop-opacity=".25"/></linearGradient>'
                f'<rect x="26" y="{by + 8}" width="{bw * min(pct, 100) / 100:g}" height="6" fill="url(#{gid})" '
                f'class="gx" style="animation-delay:{150 + i * 120}ms"/>')
    out += stream_status(26, ly + top_h - 22, note)

    rx = 2 + cw + 24
    w, wy = panel(rx, 2, cw, top_h, 'ACTIVITY WAVEFORM', 'LAST 30 DAYS', C['amber'])
    out += w
    n = max(len(m['waveform']), 1)
    gap = 4
    bw = (cw - 48 - gap * (n - 1)) / n
    base = wy + 24 + 150
    out += (f'<linearGradient id="wg" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="{C["amber"]}"/>'
            f'<stop offset="1" stop-color="{C["amber_hot"]}"/></linearGradient>')
    for i, v in enumerate(m['waveform']):
        bh = max(.02, v) * 150
        out += (f'<rect x="{rx + 24 + i * (bw + gap):.1f}" y="{base - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                f'fill="url(#wg)" class="gy" style="animation-delay:{i * 30}ms"/>')
    tw = (cw - 48 - 2 * 12) / 3
    for i, (label, value, color) in enumerate(m['tiles']):
        out += tile(rx + 24 + i * (tw + 12), base + 16, tw, label, value, color)
    out += stream_status(rx + 24, wy + top_h - 22, note)

    by0 = ly + top_h + 26
    heat = m['heat']
    if heat:
        first = datetime.strptime(heat[0][0], '%Y-%m-%d').date()
        pad = (first.weekday() + 1) % 7
        cells = [None] * pad + heat
        while len(cells) % 7:
            cells.append(None)
        cols = len(cells) // 7
    else:
        cells, cols = [], 53
    hg = 3
    HEAT = heat_colors()
    cell = (W - 4 - 48 - hg * (cols - 1)) / cols
    grid_h = 7 * cell + 6 * hg
    bh_ = 30 + grid_h + 30 + 56 + 66
    b, by = panel(2, by0, W - 4, bh_, 'ACTIVITY · LAST YEAR', 'VIA WAKATIME', C['cyan'])
    out += b
    gy = by + 44
    runs, last = [], None
    for c in range(cols):
        col = [x for x in cells[c * 7:(c + 1) * 7] if x]
        if not col:
            continue
        mo = datetime.strptime(col[0][0], '%Y-%m-%d').strftime('%b').upper()
        if mo != last:
            runs.append([c, mo, 0])
            last = mo
        runs[-1][2] += 1
    for c, mo, span in runs:
        if span >= 3:
            out += text(26 + c * (cell + hg), gy - 10, mo, 'm', 11, C['muted'], 2)
    for idx, cv in enumerate(cells):
        if cv is None:
            continue
        c, r = divmod(idx, 7)
        out += (f'<rect x="{26 + c * (cell + hg):.1f}" y="{gy + r * (cell + hg):.1f}" width="{cell:.1f}" '
                f'height="{cell:.1f}" fill="{HEAT[cv[1]]}"/>')
    ly2 = gy + grid_h + 20
    lx = W - 26 - 5 * 15 - 46
    out += text(lx - 8, ly2, 'LESS', 'm', 10, C['muted'], 2, 'end')
    out += ''.join(f'<rect x="{lx + i * 15}" y="{ly2 - 10}" width="11" height="11" fill="{HEAT[i]}"/>'
                   for i in range(5))
    out += text(lx + 5 * 15 + 4, ly2, 'MORE', 'm', 10, C['muted'], 2)
    tw = (W - 4 - 48 - 2 * 12) / 3
    for i, (label, value, color) in enumerate(m['year_tiles']):
        out += tile(26 + i * (tw + 12), ly2 + 16, tw, label, value, color)
    out += stream_status(26, by + bh_ - 22, note)
    return svg(W, by + bh_ + 4, out, 'Developer stats — WakaTime telemetry')


def eof_copy():
    lines = wrap('Remote terminals stand open. For collaboration, contract, or casual comms — '
                 'route through the channels below.', FONTS['r'], 20, 720)
    body = ''.join(text(W / 2, 26 + i * 32, ln, 'r', 20, C['ink'], 0, 'middle')
                   for i, ln in enumerate(lines))
    return svg(W, 26 + len(lines) * 32, body, ' '.join(lines))


def footer(signoff):
    body = (f'<text x="{W / 2}" y="22" class="m" font-size="13" letter-spacing="3" fill="{C["muted"]}" text-anchor="middle">'
            f'<tspan fill="{C["amber"]}">&gt;_</tspan> WEION.DEV · REACT 19 · TYPESCRIPT · REACT THREE FIBER</text>'
            f'<text x="{W / 2}" y="50" class="m" font-size="13" letter-spacing="3" fill="{C["muted"]}" text-anchor="middle">'
            f'{escape(signoff)} · <tspan fill="{C["amber"]}">[PRINTF TO PAY RESPECTS]</tspan>'
            f'<tspan fill="{C["amber"]}" class="blink"> █</tspan></text>')
    return svg(W, 60, body, f'{signoff} · [PRINTF TO PAY RESPECTS]')


def portrait_uri():
    img = Image.open(io.BytesIO(fetch(f'{SITE}/hero-hologram.webp'))).convert('RGBA')
    img.thumbnail((260, 520))
    buf = io.BytesIO()
    img.save(buf, 'WEBP', quality=82)
    return 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- readme

def typing_url(op):
    last, first = op['realName'].split()[-1], op['realName'].split()[0]
    lines = ['> INITIATING REMOTE LINK ........', '> ESTABLISHING SECURE CHANNEL ........',
             '> DECRYPTING OPERATOR PROFILE ........',
             f'> PROFILE: {last}, {first[0]}. — CLEARANCE GRANTED', '> WEION.DEV // ACCESS GRANTED. WELCOME.']
    q = ';'.join(quote(l, safe='').replace('%20', '+') for l in lines)
    return ('https://readme-typing-svg.demolab.com?font=Share+Tech+Mono&size=16&duration=1800&pause=500'
            f'&color=F5A623&center=true&vCenter=true&width=640&repeat=false&lines={q}')


def picture(name, alt, width=None):
    """Theme-aware image. GitHub swaps <picture> sources with its own appearance
    setting and, unlike a bare <img>, doesn't wrap it in a link to the raw file."""
    w = f' width="{width}"' if width else ''
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="./assets/dark/{name}"/>'
            f'<source media="(prefers-color-scheme: light)" srcset="./assets/light/{name}"/>'
            f'<img src="./assets/dark/{name}" alt="{escape(alt, {chr(34): "&quot;"})}"{w}/></picture>')


def link_pic(href, name, alt, width=None):
    return f'<a href="{escape(href)}">{picture(name, alt, width)}</a>'


def handle(url):
    return urlparse(url).path.strip('/').split('/')[-1].upper()


def render_assets(data, portrait, feeds):
    profile, experience, education, skills, projects = data
    op = {k: v for k, v in profile['operative'].items() if not blank(v)}
    socials = profile.get('socials', {})
    write('banner.svg', banner(op, portrait))
    for name, eyebrow, title, center in [
        ('h-dossier.svg', '// 02 · DOSSIER', 'PERSONNEL FILE', False),
        ('h-capabilities.svg', '// 03 · SYSTEMS', 'CAPABILITIES MATRIX', False),
        ('h-archive.svg', '// 04 · ARCHIVE', 'OPERATIONS LOG', False),
        ('h-telemetry.svg', '// 05 · TELEMETRY', 'DEVELOPER STATS', False),
        ('h-eof.svg', '// 06 · END OF FILE', 'ESTABLISH LINK', True),
    ]:
        write(name, heading(eyebrow, title, center))
    write('dossier.svg', dossier(profile))
    write('record.svg', service_record(experience, education))
    write('capabilities.svg', capabilities(skills['skills'], skills.get('coreSkills', [])))
    write('eof.svg', eof_copy())
    write('footer.svg', footer(profile.get('signoff') or 'END OF FILE'))
    for name, (label, icon, variant, size) in {
        'btn-console.svg': ('OPERATIONS ARCHIVE', 'chev', 'amber', 'md'),
        'btn-github.svg': ('GITHUB', 'code', 'ghost', 'md'),
        'btn-linkedin.svg': ('LINKEDIN', 'link', 'ghost', 'md'),
        'btn-eof-github.svg': (f"GITHUB / {handle(socials.get('github', ''))}", 'code', 'amber', 'md'),
        'btn-eof-linkedin.svg': (f"LINKEDIN / {handle(socials.get('linkedin', ''))}", 'link', 'ghost', 'md'),
        'btn-eof-mail.svg': ('SEND TRANSMISSION', 'mail', 'ghost', 'md'),
        'btn-feed.svg': ('VIEW FEED', 'play', 'amber', 'sm'),
        'btn-live.svg': ('LIVE', 'ext', 'quiet', 'sm'),
        'btn-fe.svg': ('FE', 'code', 'quiet', 'sm'),
        'btn-be.svg': ('BE', 'code', 'quiet', 'sm'),
    }.items():
        write(name, button(label, icon, variant, size))
    for p in projects:
        write(f"project-{p['id']}.svg", project_card(p))

    # Telemetry: keep the last good render if WakaTime is unreachable.
    target = ASSETS / THEME[0] / 'telemetry.svg'
    WRITTEN.add(target)
    if feeds is not None:
        synced = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        write('telemetry.svg', telemetry(telemetry_model(feeds['waveform'], feeds['languages'],
                                                         feeds['year']), synced))
    elif not target.exists():
        raise RuntimeError(f'no WakaTime data and no previous {target.relative_to(ROOT)}')


def readme(data):
    profile, experience, education, skills, projects = data
    op = {k: v for k, v in profile['operative'].items() if not blank(v)}
    socials = profile.get('socials', {})
    email = socials.get('email', '')
    mailto = email if email.startswith('mailto:') else f'mailto:{email}'
    archive = []
    for p in projects:
        pid = p['id']
        links = []
        if p.get('preview'):
            links.append(link_pic(f'{SITE}/?feed={quote(pid)}#archive', 'btn-feed.svg', 'View feed'))
        for key, btn in (('live', 'btn-live.svg'), ('fe', 'btn-fe.svg'), ('be', 'btn-be.svg')):
            if not blank(p.get(key)):
                links.append(link_pic(p[key], btn, key.upper()))
        card = picture(f'project-{pid}.svg', f"{p['name']} — {p['summary']}", '100%')
        archive.append((link_pic(p['live'], f'project-{pid}.svg', p['name'], '100%')
                        if not blank(p.get('live')) else card)
                       + f'\n<p>\n  {chr(10).join(links)}\n</p>\n')
    typing = typing_url(op)
    return f"""<!--
  GENERATED FILE — do not edit by hand.
  Built by scripts/build.py from the weion.dev Pages CMS content and WakaTime feeds;
  .github/workflows/build.yml refreshes it hourly and on CMS edits.
-->

{link_pic(SITE, 'banner.svg', f"{op['codename']} // {op['realName']} — {op['role']}", '100%')}

<p align="center">
  <a href="{SITE}"><picture><source media="(prefers-color-scheme: dark)" srcset="{escape(typing)}"/><source media="(prefers-color-scheme: light)" srcset="{escape(typing.replace('color=F5A623', 'color=B86A00'))}"/><img src="{escape(typing)}" alt="&gt; WEION.DEV // ACCESS GRANTED. WELCOME."/></picture></a>
</p>

<p align="center">
  {link_pic(f'{SITE}/#archive', 'btn-console.svg', 'Operations archive')}
  {link_pic(socials.get('github', ''), 'btn-github.svg', 'GitHub')}
  {link_pic(socials.get('linkedin', ''), 'btn-linkedin.svg', 'LinkedIn')}
</p>

<br/>

{picture('h-dossier.svg', '// 02 · DOSSIER — PERSONNEL FILE', '100%')}

{picture('dossier.svg', profile['bio'], '100%')}

<details>
<summary><b><code>// SERVICE RECORD</code></b> — {len(experience)} entries · expand</summary>
<br/>

{picture('record.svg', 'Service record and education', '100%')}

</details>

<br/>

{picture('h-capabilities.svg', '// 03 · SYSTEMS — CAPABILITIES MATRIX', '100%')}

{picture('capabilities.svg', ', '.join(skills['skills']), '100%')}

<br/>

{picture('h-archive.svg', '// 04 · ARCHIVE — OPERATIONS LOG', '100%')}

{chr(10).join(archive)}
<br/>

{picture('h-telemetry.svg', '// 05 · TELEMETRY — DEVELOPER STATS', '100%')}

{link_pic(f'{SITE}/#telemetry', 'telemetry.svg', 'WakaTime language distribution, 30-day activity waveform and yearly heatmap', '100%')}

<br/>
<br/>

{picture('h-eof.svg', '// 06 · END OF FILE — ESTABLISH LINK', '100%')}

{picture('eof.svg', 'Remote terminals stand open.', '100%')}

<p align="center">
  {link_pic(socials.get('github', ''), 'btn-eof-github.svg', 'GitHub')}
  {link_pic(socials.get('linkedin', ''), 'btn-eof-linkedin.svg', 'LinkedIn')}
  {link_pic(mailto, 'btn-eof-mail.svg', 'Send transmission')}
</p>

<br/>

{picture('footer.svg', profile.get('signoff') or 'END OF FILE', '100%')}
"""


def main():
    data = [load_content(n) for n in ('profile', 'experience', 'education', 'skills', 'projects')]
    global CHARSET
    CHARSET += ''.join(sorted({ch for ch in json.dumps(data, ensure_ascii=False) if ord(ch) > 126}))
    portrait = portrait_uri()
    try:
        feeds = {k: json.loads(fetch(SITE + path, timeout=180)) for k, path in WAKATIME.items()}
    except Exception as err:  # noqa: BLE001 — any fetch/parse failure keeps the previous stats
        print(f'warning: WakaTime telemetry unavailable ({err}); keeping previous telemetry.svg',
              file=sys.stderr)
        feeds = None
    for theme in THEMES:
        set_theme(theme)
        THEME[0] = theme
        render_assets(data, portrait, feeds)
    (ROOT / 'README.md').write_text(readme(data))
    for stale in ASSETS.rglob('*.svg'):
        if stale not in WRITTEN:
            stale.unlink()
    print('built', len(list(ASSETS.rglob('*.svg'))), 'assets')


if __name__ == '__main__':
    main()
