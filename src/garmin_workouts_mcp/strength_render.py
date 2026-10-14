"""
SVG body map for the strength analysis (see strength.py).

Three states like Garmin's own muscle map: primary (red), secondary (yellow) and
not targeted (grey), on a front and a back figure, with the numbers underneath as a
grouped list. The colours follow the viewer's light/dark setting (theme="auto");
hover titles name every muscle.
"""
from typing import Dict, List
from xml.sax.saxutils import escape

PRIMARY = "#e5302c"
SECONDARY = "#f2b705"

THEMES = {
    "light": {
        "bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "line": "#e1e0d9",
        "body": "#f3f2ee", "outline": "#b4b3ab", "nt": "#d4d3cc", "gap": "#fcfcfb",
    },
    "dark": {
        "bg": "#0e0e0f", "ink": "#f4f4f5", "ink2": "#c3c2b7", "muted": "#8d8d93", "line": "#2c2c2e",
        "body": "#19191b", "outline": "#6b6b70", "nt": "#3a3a3e", "gap": "#0e0e0f",
    },
}

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

# Smooth outline of one half of the body (front and back share it); the other half is mirrored.
_OUTLINE = (
    "M100 56 L92 56 Q91 66 77 70 Q58 73 52 88 Q46 100 44 122 Q40 150 36 162 "
    "Q30 192 26 222 L24 240 Q29 248 35 240 L41 222 Q47 194 55 164 L60 120 "
    "Q62 134 66 142 Q68 172 72 198 Q64 216 66 238 Q60 282 66 312 "
    "Q64 340 68 368 L66 394 Q64 406 71 410 L92 410 Q94 400 94 388 "
    "Q94 360 92 340 Q96 322 96 312 Q98 280 99 250 L100 242 Z"
)

# Left-half muscle shapes (mirrored for the right half), anatomically more detailed.
_FRONT: Dict[str, List[str]] = {
    "traps": ['<path d="M92 58 Q86 64 76 70 Q68 73 62 79 Q80 77 93 67 Z"/>'],
    "shoulders": ['<path d="M62 79 Q50 81 48 96 Q50 109 58 109 Q66 101 69 89 Q69 81 62 79 Z"/>'],
    "chest": ['<path d="M98 90 Q82 84 69 92 Q62 106 70 121 Q86 129 98 123 Z"/>'],
    "biceps": ['<path d="M48 111 Q42 127 46 145 Q52 149 58 141 Q60 125 56 109 Z"/>'],
    "forearms": ['<path d="M44 149 Q36 171 31 199 Q36 205 42 199 Q52 173 54 149 Z"/>'],
    "abs": [
        '<rect x="88" y="127" width="10" height="14" rx="4"/>',
        '<rect x="88" y="144" width="10" height="14" rx="4"/>',
        '<rect x="88" y="161" width="10" height="14" rx="4"/>',
        '<rect x="88" y="178" width="10" height="15" rx="4"/>',
    ],
    "obliques": ['<path d="M84 128 Q74 138 72 160 Q72 182 78 198 L84 194 Q80 168 84 128 Z"/>'],
    "hip_stabilizers": [
        '<path d="M78 200 Q67 208 66 226 Q72 240 82 232 Q88 218 84 204 Z"/>',
        '<path d="M92 246 Q88 264 90 288 Q96 288 98 268 Q99 254 96 246 Z"/>',
    ],
    "quads": [
        '<path d="M68 238 Q61 272 68 306 Q75 313 83 307 Q83 272 81 240 Z"/>',
        '<path d="M83 242 Q85 274 85 308 Q92 311 94 301 Q96 272 92 248 Z"/>',
    ],
    "calves": ['<path d="M70 322 Q66 350 72 380 Q82 384 88 378 Q92 350 90 324 Q80 316 70 322 Z"/>'],
}
_BACK: Dict[str, List[str]] = {
    "traps": ['<path d="M100 58 L88 62 L72 74 L66 82 Q80 90 90 106 L100 124 Z"/>'],
    "shoulders": ['<path d="M62 79 Q50 81 48 96 Q50 109 58 109 Q66 101 69 89 Q69 81 62 79 Z"/>'],
    "triceps": ['<path d="M48 111 Q42 127 46 147 Q52 151 58 143 Q60 125 56 109 Z"/>'],
    "forearms": ['<path d="M44 151 Q36 173 31 199 Q36 205 42 199 Q52 175 54 151 Z"/>'],
    "lats": ['<path d="M98 126 L84 106 Q72 108 68 122 Q66 148 76 168 L98 178 Z"/>'],
    "lower_back": ['<path d="M98 154 L88 158 Q86 180 90 200 L98 200 Z"/>'],
    "glutes": ['<path d="M98 200 Q84 198 72 208 Q66 224 74 240 Q88 246 98 234 Z"/>'],
    "hip_stabilizers": ['<path d="M70 204 Q63 212 65 226 Q72 222 77 212 Z"/>'],
    "hamstrings": ['<path d="M72 248 Q66 280 72 306 Q82 312 92 306 Q98 280 96 250 Q84 244 72 248 Z"/>'],
    "calves": ['<path d="M70 322 Q64 350 70 374 Q80 382 90 374 Q94 348 90 322 Q80 316 70 322 Z"/>'],
}
_ALWAYS_SHOWN = ("obliques", "abs")  # shapes that exist on the front only; others as listed per view


def _state(m: dict) -> str:
    return {"worked": "pri", "assisted": "sec"}.get(m["status"], "nt")


def _tip(m: dict) -> str:
    if m["status"] == "not worked":
        return f'{m["label"]}: not targeted'
    last = f', last {m["last_worked"]}' if m["last_worked"] else ""
    tag = "primary" if m["status"] == "worked" else "secondary"
    return f'{m["label"]}: {tag}, {m["weighted_sets"]:g} weighted sets ({m["primary_sets"]} primary, {m["secondary_sets"]} secondary){last}'


def _palette_css(theme: str) -> str:
    def block(t: dict) -> str:
        return (
            f".bg{{fill:{t['bg']}}} .ink{{fill:{t['ink']}}} .ink2{{fill:{t['ink2']}}} .muted{{fill:{t['muted']}}} "
            f".line{{stroke:{t['line']}}} .body{{fill:{t['body']};stroke:{t['outline']}}} .nt{{fill:{t['nt']}}} "
            f".gap{{stroke:{t['gap']}}} .dot-nt{{fill:{t['nt']}}} .pri{{fill:{PRIMARY}}} .sec{{fill:{SECONDARY}}}"
        )
    if theme == "auto":
        return block(THEMES["light"]) + "\n@media (prefers-color-scheme: dark){" + block(THEMES["dark"]) + "}"
    return block(THEMES[theme])


def _figure(x: float, y: float, scale: float, shapes: Dict[str, List[str]], by_key: Dict[str, dict], caption: str) -> str:
    out = [f'<g transform="translate({x} {y}) scale({scale})">',
           f'<text x="100" y="-10" text-anchor="middle" class="muted cap">{caption}</text>',
           '<circle cx="100" cy="30" r="17" class="body" stroke-width="1"/>',
           f'<path d="{_OUTLINE}" class="body" stroke-width="1"/>',
           f'<path d="{_OUTLINE}" class="body" stroke-width="1" transform="translate(200 0) scale(-1 1)"/>']
    for key, parts in shapes.items():
        m = by_key[key]
        cls = _state(m)
        title = f"<title>{escape(_tip(m))}</title>"
        for mirror in ("", ' transform="translate(200 0) scale(-1 1)"'):
            out.append(f'<g class="{cls} gap" stroke-width="1.6" stroke-linejoin="round"{mirror}>{title}{"".join(parts)}</g>')
    out.append("</g>")
    return "\n".join(out)


def render_svg(result: dict, theme: str = "auto") -> str:
    if theme not in ("auto", "light", "dark"):
        raise ValueError("theme must be auto, light or dark")
    muscles = result["muscles"]
    by_key = {m["muscle"]: m for m in muscles}
    window = result["window"]
    n_act = len(result["activities"])
    when = window["start"] if window["start"] == window["end"] else f'{window["start"]} to {window["end"]}'
    flagged = len(result["flagged_sets"])

    groups = [
        ("Primary muscles", "pri", [m for m in muscles if m["status"] == "worked"]),
        ("Secondary muscles", "sec", [m for m in muscles if m["status"] == "assisted"]),
        ("Not targeted", "dot-nt", [m for m in muscles if m["status"] == "not worked"]),
    ]

    W = 640
    fig_scale = 1.12
    fig_top = 112
    fig_h = int(420 * fig_scale)
    legend_y = fig_top + fig_h + 30
    parts = []
    y = legend_y + 52
    for title, dot, items in groups:
        if not items:
            continue
        parts.append(f'<circle cx="46" cy="{y - 4}" r="6" class="{dot}"/><text x="62" y="{y}" class="ink hd">{title} ({len(items)})</text>')
        y += 12
        for i, m in enumerate(items):
            col, row = i % 2, i // 2
            cx = 62 + col * 290
            cy = y + 22 + row * 24
            value = "" if m["status"] == "not worked" else f'{m["weighted_sets"]:g}'
            parts.append(
                f'<g><title>{escape(_tip(m))}</title><text x="{cx}" y="{cy}" class="ink2 lab">{escape(m["label"])}</text>'
                f'<text x="{cx + 230}" y="{cy}" text-anchor="end" class="ink lab">{value}</text></g>'
            )
        y += 22 + ((len(items) + 1) // 2) * 24 + 18
    height = y + 72
    foot = f"{flagged} rest-period or phantom set{'s' if flagged != 1 else ''} left out. " if flagged else ""

    legend = (
        f'<circle cx="150" cy="{legend_y}" r="7" class="pri"/><text x="164" y="{legend_y + 4}" class="ink2 lab">Primary</text>'
        f'<circle cx="262" cy="{legend_y}" r="7" class="sec"/><text x="276" y="{legend_y + 4}" class="ink2 lab">Secondary</text>'
        f'<circle cx="392" cy="{legend_y}" r="7" class="dot-nt"/><text x="406" y="{legend_y + 4}" class="ink2 lab">Not targeted</text>'
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" role="img" aria-label="Muscle map {escape(when)}">
<title>Muscle map {escape(when)}</title>
<style>
  text {{ font-family: {FONT}; }}
  .h1 {{ font-size: 22px; font-weight: 600; }} .h2 {{ font-size: 13px; }}
  .cap {{ font-size: 10px; font-weight: 600; letter-spacing: 0.1em; }}
  .hd {{ font-size: 14px; font-weight: 600; }} .lab {{ font-size: 13px; }} .small {{ font-size: 11px; }}
  {_palette_css(theme)}
</style>
<rect width="{W}" height="{height}" class="bg"/>
<text x="32" y="42" class="ink h1">Muscle map</text>
<text x="32" y="64" class="ink2 h2">{escape(when)} - {n_act} strength workout{'s' if n_act != 1 else ''}</text>
{_figure(48, fig_top, fig_scale, _FRONT, by_key, "FRONT")}
{_figure(W - 48 - 200 * fig_scale, fig_top, fig_scale, _BACK, by_key, "BACK")}
{legend}
<line x1="32" y1="{legend_y + 24}" x2="{W - 32}" y2="{legend_y + 24}" class="line" stroke-width="1"/>
{''.join(parts)}
<line x1="32" y1="{height - 56}" x2="{W - 32}" y2="{height - 56}" class="line" stroke-width="1"/>
<text x="32" y="{height - 40}" class="muted small">Weighted sets: primary 1.0, secondary 0.5. {escape(foot)}</text>
<text x="32" y="{height - 24}" class="muted small">Estimate from exercise names, not Garmin's muscle map. Training analysis only.</text>
</svg>'''
