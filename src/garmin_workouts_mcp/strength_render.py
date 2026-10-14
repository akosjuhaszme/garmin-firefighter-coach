"""
SVG body map for the strength analysis (see strength.py).

Design follows the data-viz rules in use here: one sequential hue (blue, light to
dark) for magnitude, a neutral for "not worked", hairline chrome, a 2px surface gap
between fills, a stepped legend and a sorted bar list as the table twin of the
picture, and hover titles on every muscle.
"""
from typing import Dict, List
from xml.sax.saxutils import escape

# Surface and ink
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#898781"
HAIRLINE = "#e1e0d9"
BODY = "#efeeea"

# Sequential blue ramp (light to dark) and the neutral for "not worked"
NOT_WORKED = "#e1e0d9"
ASSISTED = "#cde2fb"
RAMP = [(10.0, "#0d366b"), (7.0, "#1c5cab"), (4.0, "#3987e5"), (0.0, "#86b6ef")]
BAR = "#2a78d6"
BAR_ASSISTED = "#c3c2b7"

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

# One smooth outline, left half; the right half is its mirror image.
_OUTLINE = (
    "M100 56 L92 56 Q91 66 77 70 Q58 73 52 88 Q46 100 44 122 Q40 150 36 162 "
    "Q30 192 26 222 L24 240 Q29 248 35 240 L41 222 Q47 194 55 164 L60 120 "
    "Q62 134 66 142 Q68 172 72 198 Q64 216 66 238 Q60 282 66 312 "
    "Q64 340 68 368 L66 394 Q64 406 71 410 L92 410 Q94 400 94 388 "
    "Q94 360 92 340 Q96 322 96 312 Q98 280 99 250 L100 242 Z"
)

# Left-half muscle shapes (front view), mirrored for the right half.
_FRONT = {
    "shoulders": ['<ellipse cx="58" cy="90" rx="12" ry="14"/>'],
    "chest": ['<path d="M98 90 Q80 86 68 97 Q64 111 72 121 Q86 129 98 122 Z"/>'],
    "biceps": ['<ellipse cx="50" cy="124" rx="7" ry="18" transform="rotate(6 50 124)"/>'],
    "forearms": ['<ellipse cx="41" cy="176" rx="6" ry="24" transform="rotate(9 41 176)"/>'],
    "abs": [
        '<rect x="88" y="128" width="10" height="16" rx="4"/>',
        '<rect x="88" y="147" width="10" height="16" rx="4"/>',
        '<rect x="88" y="166" width="10" height="16" rx="4"/>',
        '<rect x="88" y="185" width="10" height="14" rx="4"/>',
    ],
    "obliques": ['<path d="M84 130 Q75 139 74 161 Q74 182 80 197 L85 193 Q81 168 84 130 Z"/>'],
    "hip_stabilizers": ['<ellipse cx="70" cy="228" rx="6" ry="12"/>', '<ellipse cx="91" cy="262" rx="4" ry="20"/>'],
    "quads": ['<path d="M72 242 Q66 280 74 310 Q84 316 92 308 Q96 280 90 244 Q80 236 72 242 Z"/>'],
    "calves": ['<ellipse cx="80" cy="351" rx="8" ry="26"/>'],
}
_BACK = {
    "shoulders": ['<ellipse cx="58" cy="90" rx="12" ry="14"/>'],
    "traps": ['<path d="M100 58 L90 62 L76 74 L84 98 L100 116 Z"/>'],
    "lats": ['<path d="M98 118 L84 100 L70 106 Q66 130 76 160 L98 172 Z"/>'],
    "triceps": ['<ellipse cx="50" cy="124" rx="7" ry="18" transform="rotate(6 50 124)"/>'],
    "forearms": ['<ellipse cx="41" cy="176" rx="6" ry="24" transform="rotate(9 41 176)"/>'],
    "lower_back": ['<path d="M98 150 L90 152 Q87 175 91 197 L98 197 Z"/>'],
    "glutes": ['<ellipse cx="84" cy="227" rx="15" ry="16"/>'],
    "hip_stabilizers": ['<ellipse cx="68" cy="222" rx="5" ry="10"/>'],
    "hamstrings": ['<path d="M72 250 Q68 282 76 312 L92 312 Q98 282 94 252 Z"/>'],
    "calves": ['<ellipse cx="80" cy="350" rx="9" ry="28"/>'],
}


def _fill_for(m: dict) -> str:
    if m["status"] == "not worked":
        return NOT_WORKED
    if m["status"] == "assisted":
        return ASSISTED
    for threshold, color in RAMP:
        if m["weighted_sets"] >= threshold:
            return color
    return RAMP[-1][1]


def _tip(m: dict) -> str:
    if m["status"] == "not worked":
        return f'{m["label"]}: not worked'
    last = f', last {m["last_worked"]}' if m["last_worked"] else ""
    tag = "assisted only" if m["status"] == "assisted" else "worked"
    return f'{m["label"]}: {tag}, {m["weighted_sets"]:g} weighted sets, {m["primary_sets"]} primary / {m["secondary_sets"]} secondary{last}'


def _figure(x: int, y: int, shapes: Dict[str, List[str]], by_key: Dict[str, dict], caption: str) -> str:
    out = [f'<g transform="translate({x} {y})">',
           f'<text x="100" y="-10" text-anchor="middle" class="cap">{caption}</text>',
           f'<circle cx="100" cy="30" r="17" fill="{BODY}"/>',
           f'<path d="{_OUTLINE}" fill="{BODY}"/>',
           f'<path d="{_OUTLINE}" fill="{BODY}" transform="translate(200 0) scale(-1 1)"/>']
    for key, parts in shapes.items():
        m = by_key[key]
        fill = _fill_for(m)
        title = f"<title>{escape(_tip(m))}</title>"
        for mirror in ("", ' transform="translate(200 0) scale(-1 1)"'):
            out.append(f'<g fill="{fill}" stroke="{SURFACE}" stroke-width="2" stroke-linejoin="round"{mirror}>{title}{"".join(parts)}</g>')
    out.append("</g>")
    return "\n".join(out)


def render_svg(result: dict) -> str:
    muscles = result["muscles"]
    by_key = {m["muscle"]: m for m in muscles}
    window = result["window"]
    n_act = len(result["activities"])
    when = window["start"] if window["start"] == window["end"] else f'{window["start"]} to {window["end"]}'
    flagged = len(result["flagged_sets"])
    top = max((m["weighted_sets"] for m in muscles), default=1.0) or 1.0

    # right panel: the table twin of the figure, sorted, one bar colour (emphasis form)
    rows = []
    y0 = 128
    for i, m in enumerate(muscles):
        y = y0 + i * 38
        if m["status"] == "not worked":
            value, bar = "", ""
            sub = "not worked"
        else:
            width = max(4.0, 150.0 * m["weighted_sets"] / top)
            colour = BAR if m["status"] == "worked" else BAR_ASSISTED
            bar = f'<rect x="676" y="{y - 9}" width="{width:.1f}" height="8" rx="4" fill="{colour}"/>'
            value = f'<text x="{676 + width + 8:.1f}" y="{y}" class="val">{m["weighted_sets"]:g}</text>'
            parts = []
            if m["status"] == "assisted":
                parts.append("assisted only")
            if m["last_worked"] and m["last_worked"] != window["end"]:
                parts.append(f'last {m["last_worked"]}')
            sub = " - ".join(parts)
        rows.append(
            f'<g><title>{escape(_tip(m))}</title>'
            f'<text x="540" y="{y}" class="lab">{escape(m["label"])}</text>'
            + (f'<text x="540" y="{y + 15}" class="sub">{escape(sub)}</text>' if sub else "")
            + f'{bar}{value}</g>'
        )
    panel_bottom = y0 + len(muscles) * 38

    # stepped legend under the figures
    steps = [(NOT_WORKED, "not worked"), (ASSISTED, "assisted"), ("#86b6ef", "up to 4"), ("#3987e5", "4 to 7"), ("#1c5cab", "7 to 10"), ("#0d366b", "10+")]
    legend = []
    lx = 32
    for colour, label in steps:
        legend.append(f'<rect x="{lx}" y="{552}" width="14" height="14" rx="3" fill="{colour}"/>'
                      f'<text x="{lx + 20}" y="{563}" class="sub">{label}</text>')
        lx += 20 + int(6.2 * len(label)) + 14
    height = max(panel_bottom + 40, 640)
    foot = (f"{flagged} flagged set{'s' if flagged != 1 else ''} left out (rest-period detections and phantom sets). " if flagged else "")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 {height}" width="880" role="img" aria-label="Muscle map {escape(when)}">
<title>Muscle map {escape(when)}</title>
<style>
  text {{ font-family: {FONT}; }}
  .h1 {{ font-size: 20px; font-weight: 600; fill: {INK}; }}
  .h2 {{ font-size: 13px; fill: {INK_2}; }}
  .cap {{ font-size: 11px; font-weight: 600; letter-spacing: 0.08em; fill: {INK_MUTED}; }}
  .hd {{ font-size: 12px; font-weight: 600; fill: {INK_2}; }}
  .lab {{ font-size: 13px; fill: {INK}; }}
  .sub {{ font-size: 11px; fill: {INK_MUTED}; }}
  .val {{ font-size: 12px; fill: {INK_2}; }}
</style>
<rect width="880" height="{height}" fill="{SURFACE}"/>
<text x="32" y="40" class="h1">Muscle map</text>
<text x="32" y="62" class="h2">{escape(when)} - {n_act} strength workout{'s' if n_act != 1 else ''} - weighted sets per muscle</text>
<line x1="32" y1="76" x2="848" y2="76" stroke="{HAIRLINE}"/>
{_figure(32, 112, _FRONT, by_key, "FRONT")}
{_figure(272, 112, _BACK, by_key, "BACK")}
{''.join(legend)}
<line x1="500" y1="92" x2="500" y2="{panel_bottom + 4}" stroke="{HAIRLINE}"/>
<text x="540" y="104" class="hd">Weighted sets (primary 1.0, secondary 0.5)</text>
{chr(10).join(rows)}
<line x1="32" y1="{height - 40}" x2="848" y2="{height - 40}" stroke="{HAIRLINE}"/>
<text x="32" y="{height - 20}" class="sub">Estimate from exercise names, not Garmin's muscle map. {escape(foot)}Training analysis only.</text>
</svg>'''
