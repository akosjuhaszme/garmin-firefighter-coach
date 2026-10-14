"""
SVG body map for the strength analysis (see strength.py).

Three states like Garmin's own muscle map: primary (red), secondary (yellow) and
not targeted (grey), on a front and a back figure, with the numbers underneath as a
grouped list. The colours follow the viewer's light/dark setting (theme="auto");
hover titles name every muscle.

The anatomical shapes are in data/body_parts.json, taken from
react-native-body-highlighter (MIT, see data/BODY_PARTS_NOTICE.txt).
"""
import json
from pathlib import Path
from typing import Dict, List
from xml.sax.saxutils import escape

PRIMARY = "#e5302c"
SECONDARY = "#f2b705"

THEMES = {
    "light": {
        "bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "line": "#e1e0d9",
        "nt": "#d4d3cc", "gap": "#fcfcfb",
    },
    "dark": {
        "bg": "#0e0e0f", "ink": "#f4f4f5", "ink2": "#c3c2b7", "muted": "#8d8d93", "line": "#2c2c2e",
        "nt": "#3a3a3e", "gap": "#0e0e0f",
    },
}

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

_DATA = json.loads((Path(__file__).parent / "data" / "body_parts.json").read_text(encoding="utf-8"))

# our muscle group -> shape names in the data file
_SLUGS = {
    "chest": ["chest"], "shoulders": ["deltoids"], "biceps": ["biceps"], "triceps": ["triceps"],
    "forearms": ["forearm"], "traps": ["trapezius"], "lats": ["upper-back"], "lower_back": ["lower-back"],
    "abs": ["abs"], "obliques": ["obliques"], "glutes": ["gluteal"], "hip_stabilizers": ["adductors"],
    "quads": ["quadriceps"], "hamstrings": ["hamstring"], "calves": ["calves"],
}
_MUSCLE_OF = {slug: key for key, slugs in _SLUGS.items() for slug in slugs}
# drawn in the neutral colour, never coloured ("hair" is left out)
_NEUTRAL = {"head", "neck", "hands", "feet", "knees", "ankles", "tibialis"}


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
            f".line{{stroke:{t['line']}}} .nt{{fill:{t['nt']}}} .gap{{stroke:{t['gap']}}} "
            f".dot-nt{{fill:{t['nt']}}} .pri{{fill:{PRIMARY}}} .sec{{fill:{SECONDARY}}}"
        )
    if theme == "auto":
        return block(THEMES["light"]) + "\n@media (prefers-color-scheme: dark){" + block(THEMES["dark"]) + "}"
    return block(THEMES[theme])


def _figure(view: str, x: float, y: float, height: float, by_key: Dict[str, dict], caption: str) -> str:
    x0, y0, w, h = _DATA[view]["viewBox"]
    scale = height / h
    stroke = 1.6 / scale  # about 1.6px on screen
    parts = _DATA[view]["parts"]
    out = [f'<text x="{x + w * scale / 2:.1f}" y="{y - 14:.1f}" text-anchor="middle" class="muted cap">{caption}</text>',
           f'<g transform="translate({x} {y}) scale({scale:.5f}) translate({-x0} {-y0})" stroke-width="{stroke:.2f}" stroke-linejoin="round">']
    for slug, paths in parts.items():  # neutral parts first so muscles sit on top
        if slug in _NEUTRAL:
            out.append(f'<g class="nt gap">{"".join(f"<path d=\"{d}\"/>" for d in paths)}</g>')
    for slug, paths in parts.items():
        key = _MUSCLE_OF.get(slug)
        if key is None:
            continue
        m = by_key[key]
        out.append(f'<g class="{_state(m)} gap"><title>{escape(_tip(m))}</title>{"".join(f"<path d=\"{d}\"/>" for d in paths)}</g>')
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
    fig_h = 520
    fig_top = 118
    fw = {v: _DATA[v]["viewBox"][2] * fig_h / _DATA[v]["viewBox"][3] for v in ("front", "back")}
    gap = 36
    left = (W - fw["front"] - fw["back"] - gap) / 2
    legend_y = fig_top + fig_h + 32
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
{_figure("front", left, fig_top, fig_h, by_key, "FRONT")}
{_figure("back", left + fw["front"] + gap, fig_top, fig_h, by_key, "BACK")}
{legend}
<line x1="32" y1="{legend_y + 24}" x2="{W - 32}" y2="{legend_y + 24}" class="line" stroke-width="1"/>
{''.join(parts)}
<line x1="32" y1="{height - 56}" x2="{W - 32}" y2="{height - 56}" class="line" stroke-width="1"/>
<text x="32" y="{height - 40}" class="muted small">Weighted sets: primary 1.0, secondary 0.5. {escape(foot)}</text>
<text x="32" y="{height - 24}" class="muted small">Estimate from exercise names, not Garmin's muscle map. Training analysis only.</text>
</svg>'''
