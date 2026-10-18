"""Generate HUD-styled SVG assets for the TheWeion profile README."""
import base64
import io
import sys
from pathlib import Path

from PIL import Image, ImageOps

SITE = Path('/home/weion/Workspace/Repos/weion.dev')
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

C = dict(void='#05080C', panel='#0B1E2E', line='#1E3A52', muted='#7A8794', ink='#C0CAD3',
         bright='#E8F1F7', halo='#B6D6EB', amber='#F5A623', cyan='#03D8F3',
         magenta='#FF0055', ok='#7CE8C9', bronze='#8A6A3A')

FONTS = SITE / 'node_modules/@fontsource'


def font_face(family, pkg, weight):
    from fontTools import subset
    opts = subset.Options()
    opts.flavor = 'woff2'
    font = subset.load_font(str(FONTS / pkg / f'files/{pkg}-latin-{weight}-normal.woff2'), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=''.join(map(chr, range(32, 127))) + '·—█●')
    sub.subset(font)
    buf = io.BytesIO()
    subset.save_font(font, buf, opts)
    data = buf.getvalue()
    b64 = base64.b64encode(data).decode()
    return (f"@font-face{{font-family:'{family}';font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}")


DISPLAY = font_face('Orbitron', 'orbitron', 700)
BODY = font_face('Rajdhani', 'rajdhani', 700)
MONO = font_face('Share Tech Mono', 'share-tech-mono', 400)

BASE_CSS = f"""
{DISPLAY}{BODY}{MONO}
.d{{font-family:'Orbitron',sans-serif;font-weight:700}}
.b{{font-family:'Rajdhani',sans-serif;font-weight:700}}
.m{{font-family:'Share Tech Mono',monospace}}
@keyframes blink{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.35}}}}
.blink{{animation:blink 1.1s steps(1) infinite}}
.pulse{{animation:pulse 2s ease-in-out infinite}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
"""


def brackets(x, y, w, h, s=18, color=C['amber'], sw=2):
    pts = [
        f'M{x},{y + s} V{y} H{x + s}',
        f'M{x + w - s},{y} H{x + w} V{y + s}',
        f'M{x + w},{y + h - s} V{y + h} H{x + w - s}',
        f'M{x + s},{y + h} H{x} V{y + h - s}',
    ]
    return ''.join(f'<path d="{p}" fill="none" stroke="{color}" stroke-width="{sw}"/>' for p in pts)


def cut_rect(x, y, w, h, c=14):
    return (f'M{x},{y + c} L{x + c},{y} H{x + w - c} L{x + w},{y + c} '
            f'V{y + h - c} L{x + w - c},{y + h} H{x + c} L{x},{y + h - c} Z')


def portrait_uri(size=300):
    img = Image.open(SITE / 'public/hero-hologram.webp').convert('RGBA')
    img.thumbnail((size, size * 2))
    buf = io.BytesIO()
    img.save(buf, 'WEBP', quality=82)
    return 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()


def chips():
    out, x = [], 60
    for i, label in enumerate(['CODENAME · WEION', 'LOC · EARTH // SOL SYSTEM', 'CLEARANCE · GRANTED']):
        w = len(label) * 9.2 + 28
        stroke, fill = (C['amber'], C['amber']) if i == 0 else (C['line'], C['halo'])
        out.append(f'<path d="M{x},318 h{w} v14 l-8,8 h-{w - 8} z" fill="none" stroke="{stroke}"/>'
                   f'<text x="{x + 14}" y="334" class="m" font-size="12" letter-spacing="2" fill="{fill}">{label}</text>')
        x += w + 14
    return ''.join(out)


def banner():
    W, H = 1200, 400
    px, pw, ph = 860, 280, 300  # portrait frame
    portrait = portrait_uri(260)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="WEION // Terry Fallows, Senior Software Engineer at Vantiva">
<style>{BASE_CSS}
@keyframes sweep{{0%{{transform:translateY(-40px)}}100%{{transform:translateY({H + 40}px)}}}}
@keyframes glitchA{{0%,92%,100%{{transform:translate(0,0)}}93%{{transform:translate(-4px,1px)}}95%{{transform:translate(3px,-1px)}}97%{{transform:translate(-2px,0)}}}}
@keyframes glitchB{{0%,92%,100%{{transform:translate(0,0)}}93%{{transform:translate(4px,-1px)}}95%{{transform:translate(-3px,1px)}}97%{{transform:translate(2px,0)}}}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-6px)}}}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.sweep{{animation:sweep 6s linear infinite}}
.ga{{animation:glitchA 5s infinite}}
.gb{{animation:glitchB 5s infinite}}
.float{{animation:float 6s ease-in-out infinite}}
.spin{{transform-origin:{px + pw / 2}px {60 + ph / 2}px;animation:spin 40s linear infinite}}
.spinr{{transform-origin:{px + pw / 2}px {60 + ph / 2}px;animation:spin 28s linear infinite reverse}}
</style>
<defs>
  <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
    <path d="M40,0 H0 V40" fill="none" stroke="{C['line']}" stroke-width="1" opacity=".35"/>
  </pattern>
  <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="2" fill="#000" opacity=".28"/>
  </pattern>
  <radialGradient id="warm" cx=".78" cy=".5" r=".55">
    <stop offset="0" stop-color="{C['amber']}" stop-opacity=".22"/>
    <stop offset="1" stop-color="{C['amber']}" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="cool" cx=".15" cy=".2" r=".6">
    <stop offset="0" stop-color="{C['cyan']}" stop-opacity=".10"/>
    <stop offset="1" stop-color="{C['cyan']}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="sweepg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{C['halo']}" stop-opacity="0"/>
    <stop offset=".5" stop-color="{C['halo']}" stop-opacity=".09"/>
    <stop offset="1" stop-color="{C['halo']}" stop-opacity="0"/>
  </linearGradient>
  <clipPath id="frame"><path d="{cut_rect(0, 0, W, H, 22)}"/></clipPath>
  <clipPath id="pframe"><path d="{cut_rect(px, 60, pw, ph, 14)}"/></clipPath>
</defs>
<g clip-path="url(#frame)">
  <rect width="{W}" height="{H}" fill="{C['void']}"/>
  <rect width="{W}" height="{H}" fill="url(#grid)"/>
  <rect width="{W}" height="{H}" fill="url(#cool)"/>
  <rect width="{W}" height="{H}" fill="url(#warm)"/>

  <!-- top chrome -->
  <rect x="0" y="0" width="{W}" height="34" fill="{C['panel']}" opacity=".85"/>
  <line x1="0" y1="34" x2="{W}" y2="34" stroke="{C['line']}"/>
  <text x="28" y="22" class="m" font-size="13" fill="{C['amber']}" letter-spacing="2">WEION.DEV //</text>
  <text x="150" y="22" class="m" font-size="13" fill="{C['muted']}" letter-spacing="2">OPERATOR CONSOLE · LINK SECURE · TZ EUROPE/LONDON</text>
  <circle cx="{W - 190}" cy="17" r="4" fill="{C['ok']}" class="pulse"/>
  <text x="{W - 178}" y="22" class="m" font-size="13" fill="{C['ok']}" letter-spacing="2">STATUS: ACTIVE</text>

  <!-- left copy -->
  <rect x="60" y="86" width="7" height="7" fill="{C['amber']}" class="pulse"/>
  <text x="78" y="94" class="b" font-size="13" fill="{C['amber']}" letter-spacing="4.5">// OPERATOR PROFILE</text>

  <g class="d" font-size="74" letter-spacing="-1">
    <text x="58" y="178" fill="{C['cyan']}" opacity=".7" class="ga">TERRY FALLOWS</text>
    <text x="58" y="178" fill="{C['magenta']}" opacity=".7" class="gb">TERRY FALLOWS</text>
    <text x="58" y="178" fill="{C['bright']}">TERRY FALLOWS</text>
  </g>

  <text x="60" y="218" class="b" font-size="20" letter-spacing="5" xml:space="preserve"><tspan fill="{C['amber']}">SENIOR SOFTWARE ENGINEER</tspan><tspan fill="{C['muted']}"> @ </tspan><tspan fill="{C['halo']}">VANTIVA</tspan></text>

  <text x="60" y="262" class="b" font-size="19" fill="{C['ink']}" style="font-weight:400">
    <tspan x="60">Lover of all things code — currently enhancing STB and Healthcare</tspan>
    <tspan x="60" dy="26">UI/UX for the customers of Vantiva.</tspan>
  </text>

  {chips()}
  <text x="60" y="372" class="m" font-size="14" fill="{C['muted']}" letter-spacing="1">&gt; ACCESS GRANTED. WELCOME.<tspan fill="{C['amber']}" class="blink"> █</tspan></text>

  <!-- portrait -->
  <circle cx="{px + pw / 2}" cy="{60 + ph / 2}" r="190" fill="none" stroke="{C['line']}" stroke-dasharray="2 10" class="spin"/>
  <circle cx="{px + pw / 2}" cy="{60 + ph / 2}" r="170" fill="none" stroke="{C['bronze']}" stroke-opacity=".6" stroke-dasharray="40 14 4 14" class="spinr"/>
  <path d="{cut_rect(px, 60, pw, ph, 14)}" fill="{C['panel']}" fill-opacity=".55" stroke="{C['line']}"/>
  <g clip-path="url(#pframe)">
    <g class="float">
      <image href="{portrait}" x="{px + 10}" y="70" width="{pw - 20}" height="{ph}" preserveAspectRatio="xMidYMin meet" opacity=".92"/>
    </g>
    <rect x="{px}" y="60" width="{pw}" height="{ph}" fill="url(#scan)"/>
    <rect x="{px}" y="{60 + ph - 28}" width="{pw}" height="28" fill="{C['void']}" opacity=".8"/>
    <text x="{px + 14}" y="{60 + ph - 9}" class="m" font-size="12" fill="{C['cyan']}" letter-spacing="2">HOLO-FEED · OP-01</text>
    <text x="{px + pw - 14}" y="{60 + ph - 9}" class="m blink" font-size="12" fill="{C['amber']}" text-anchor="end" letter-spacing="2">● REC</text>
  </g>
  {brackets(px - 8, 52, pw + 16, ph + 16, 20)}

  <!-- FX -->
  <rect x="0" y="0" width="{W}" height="40" fill="url(#sweepg)" class="sweep"/>
  <rect width="{W}" height="{H}" fill="url(#scan)" opacity=".5"/>
</g>
<path d="{cut_rect(1, 1, W - 2, H - 2, 22)}" fill="none" stroke="{C['line']}" stroke-width="2"/>
{brackets(10, 10, W - 20, H - 20, 28)}
</svg>"""


def heading(eyebrow, title, right=''):
    W, H = 1200, 96
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{eyebrow} — {title}">
<style>{BASE_CSS}</style>
<rect x="0" y="22" width="7" height="7" fill="{C['amber']}" class="pulse"/>
<text x="18" y="30" class="b" font-size="15" fill="{C['amber']}" letter-spacing="5">{eyebrow}</text>
<text x="0" y="74" class="d" font-size="36" fill="{C['bright']}" letter-spacing="1">{title}</text>
<line x1="0" y1="90" x2="{W}" y2="90" stroke="{C['line']}" stroke-width="2"/>
<line x1="0" y1="90" x2="160" y2="90" stroke="{C['amber']}" stroke-width="2"/>
{''.join(f'<line x1="{W - 8 - i * 14}" y1="84" x2="{W - 8 - i * 14}" y2="90" stroke="{C["line"]}" stroke-width="2"/>' for i in range(12))}
<text x="{W}" y="30" class="m" font-size="13" fill="{C['muted']}" text-anchor="end" letter-spacing="2">{right}</text>
</svg>"""


def footer():
    W, H = 1200, 60
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="End of file — connection terminated">
<style>{BASE_CSS}</style>
<line x1="0" y1="10" x2="{W}" y2="10" stroke="{C['line']}" stroke-width="2"/>
<text x="0" y="44" class="m" font-size="14" fill="{C['muted']}" letter-spacing="3">&gt; END OF FILE · CONNECTION TERMINATED<tspan fill="{C['amber']}" class="blink"> █</tspan></text>
<text x="{W}" y="44" class="m" font-size="14" fill="{C['amber']}" text-anchor="end" letter-spacing="3">WEION.DEV //</text>
</svg>"""


(OUT / 'banner.svg').write_text(banner())
for name, eyebrow, title, right in [
    ('dossier', '// 02 · DOSSIER', 'PERSONNEL FILE', 'REC · FALLOWS, T.'),
    ('capabilities', '// 03 · SYSTEMS', 'CAPABILITIES MATRIX', 'MODULES ONLINE'),
    ('archive', '// 04 · ARCHIVE', 'OPERATIONS LOG', 'CLASSIFIED · DECLASSIFIED'),
    ('telemetry', '// 05 · TELEMETRY', 'DEVELOPER STATS', 'LIVE FEED'),
    ('eof', '// 06 · END OF FILE', 'ESTABLISH LINK', 'CHANNEL OPEN'),
]:
    (OUT / f'{name}.svg').write_text(heading(eyebrow, title, right))
(OUT / 'footer.svg').write_text(footer())
for f in sorted(OUT.iterdir()):
    print(f.name, f.stat().st_size)
