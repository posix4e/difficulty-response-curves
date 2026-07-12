"""Generate docs/index.html from numbers.json — the GitHub Pages site.
Baked at build time so the page needs no JavaScript to show results."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
N = json.loads((ROOT / "analysis" / "numbers.json").read_text())
T = json.loads((ROOT / "analysis" / "traces.json").read_text())

SLOTS = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
ROSTER = [
    "openai/gpt-oss-20b", "openai/gpt-oss-120b", "minimax/minimax-m2.5",
    "qwen/qwen3-235b-a22b-thinking-2507", "deepseek/deepseek-r1-0528",
    "openai/o4-mini", "z-ai/glm-5", "anthropic/claude-haiku-4.5",
]
COLOR = {m: SLOTS[i] for i, m in enumerate(ROSTER)}


def fmt(v, d=2, dash="&mdash;"):
    if v is None or not isinstance(v, (int, float)):
        return dash
    return f"{v:.{d}f}"


ROUTE_LABELS = {
    "anthropic/prepaid": "TrustedRouter &rarr; Anthropic (chat translation)",
    "anthropic-messages": "TrustedRouter &rarr; Anthropic Messages (native)",
    "openai/prepaid": "TrustedRouter &rarr; OpenAI",
    "novita/prepaid": "TrustedRouter &rarr; novita",
    "parasail/prepaid": "TrustedRouter &rarr; parasail",
    "cerebras/prepaid": "TrustedRouter &rarr; cerebras",
    "baseten/prepaid": "TrustedRouter &rarr; baseten",
}


def trace_rows() -> str:
    rows = []
    for r in sorted(T["availability"], key=lambda r: -r["delivered_share"]):
        share = r["delivered_share"]
        verdict = ("full trace delivered" if share > 0.4
                   else "mostly withheld" if share > 0.02 else "count only &mdash; text withheld")
        route = r["route"] or "?"
        route = ROUTE_LABELS.get(route, "OpenRouter &rarr; " + route.split("/")[-1] if route.startswith("openrouter") else route)
        label = r["model"].split("/")[-1]
        rows.append(f"""      <tr><td class="runner"><strong>{label}</strong></td><td>{route}</td>
        <td class="num">{r['avg_billed_tokens']:,}</td><td class="num">{share*100:.0f}%</td><td>{verdict}</td></tr>""")
    return "\n".join(rows)


def card_rows() -> str:
    rows = []
    entries = []
    for m in ROSTER:
        e = N["models"].get(m)
        if not e:
            continue
        s = e.get("sat", {})
        if not isinstance(s.get("x50"), (int, float)):
            continue
        entries.append((m, e, s))
    entries.sort(key=lambda t: t[2]["x50"], reverse=True)
    for i, (m, e, s) in enumerate(entries, 1):
        ci = s.get("x50_ci") or [None, None]
        aci = s.get("a_ci") or [None, None]
        rt = e.get("retest", {}).get("x50")
        rates = s.get("rates", {})
        rows.append(f"""      <tr>
        <td class="pos">{i}</td>
        <td class="silks"><span class="swatch" style="background:{COLOR[m]}"></span></td>
        <td class="runner"><strong>{e['label']}</strong><span class="mono">{m}</span></td>
        <td class="num"><strong>{fmt(s['x50'])}</strong><span class="ci">[{fmt(ci[0])}, {fmt(ci[1])}]</span></td>
        <td class="num">{fmt(s.get('a'))}<span class="ci">[{fmt(aci[0])}, {fmt(aci[1])}]</span></td>
        <td class="num">{fmt(rt)}</td>
        <td class="num">{fmt(s.get('lapse'), 3)}</td>
        <td class="num">{fmt(rates.get('parse'), 3)} / {fmt(rates.get('trunc'), 3)}</td>
      </tr>""")
    return "\n".join(rows)


A = N.get("abstract", {})
P = N.get("provenance", {})


# ============================================================================
# multi-page generation
# ============================================================================

CSS = f"""<style>
:root {{
  --paper:#faf9f4; --card:#ffffff; --ink:#1c1b17; --ink-2:#5d5b51; --rule:#d8d5c8;
  --green:#12421f; --green-2:#1d5c30; --accent:#b8860b;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --paper:#151713; --card:#1d201b; --ink:#f0eee6; --ink-2:#a5a294; --rule:#3a3d35;
           --green:#8fc9a0; --green-2:#6fae82; --accent:#d9a441; }}
  img.fig {{ background:#fcfcfb; border-radius:6px; padding:10px; }}
}}
* {{ box-sizing:border-box; margin:0; }}
html {{ scroll-behavior:smooth; }}
@media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior:auto; }} }}
body {{
  background:var(--paper); color:var(--ink);
  font-family:"Newsreader", Georgia, serif; font-size:17px; line-height:1.55;
}}
.wrap {{ max-width:920px; margin:0 auto; padding:0 20px; }}
.disp {{ font-family:"Barlow Condensed", "Arial Narrow", sans-serif; }}
.mono {{ font-family:"Spline Sans Mono", ui-monospace, monospace; }}

/* masthead */
header {{ border-bottom:3px double var(--rule); padding:26px 0 18px; }}
.wip {{ background:var(--accent); color:var(--paper); padding:3px 10px; border-radius:3px; font-weight:600; }}
.race-meta {{ display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:6px;
  font-family:"Barlow Condensed",sans-serif; font-size:14px; letter-spacing:.14em; text-transform:uppercase; color:var(--ink-2); }}
h1 {{ font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:clamp(34px,6vw,58px);
  line-height:1.02; text-transform:uppercase; letter-spacing:.01em; margin:14px 0 8px; color:var(--ink); }}
h1 .thin {{ font-weight:500; color:var(--green); }}
.standfirst {{ font-size:19px; max-width:64ch; color:var(--ink); font-style:italic; }}
.links {{ margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; }}
.links a {{ font-family:"Barlow Condensed",sans-serif; text-transform:uppercase; letter-spacing:.1em; font-size:14px;
  color:var(--paper); background:var(--green); text-decoration:none; padding:7px 14px; border-radius:3px; }}
.links a.ghost {{ background:transparent; color:var(--green); border:1px solid var(--green); }}
.links a:focus-visible {{ outline:3px solid var(--accent); outline-offset:2px; }}
.explainer {{ margin-top:18px; padding:14px 16px; background:var(--card); border:1px solid var(--rule);
  border-left:4px solid var(--green); border-radius:4px; font-size:15.5px; max-width:76ch; }}
.explainer p {{ margin:0; }}
/* multi-page chrome */
.pagenav {{ margin-top:16px; display:flex; flex-wrap:wrap; gap:2px;
  font-family:"Barlow Condensed",sans-serif; font-size:14px; letter-spacing:.08em; text-transform:uppercase; }}
.pagenav a {{ color:var(--green-2); text-decoration:none; padding:6px 12px; border:1px solid var(--rule);
  border-bottom:none; border-radius:4px 4px 0 0; background:var(--card); }}
.pagenav a.active {{ background:var(--green); color:var(--paper); border-color:var(--green); }}
.pagenav a:hover {{ color:var(--accent); }}
header.compact {{ padding-bottom:0; border-bottom:none; }}
header.compact h1 {{ margin-bottom:2px; }}
header.compact + section {{ border-top:3px double var(--rule); padding-top:18px; margin-top:0; }}
.teasers {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:12px; margin-top:14px; }}
.teaser {{ display:block; background:var(--card); border:1px solid var(--rule); border-left:4px solid var(--green);
  border-radius:4px; padding:14px 16px; text-decoration:none; color:var(--ink); }}
.teaser:hover {{ border-left-color:var(--accent); }}
.teaser strong {{ font-family:"Barlow Condensed",sans-serif; text-transform:uppercase; letter-spacing:.08em;
  color:var(--green); display:block; margin-bottom:4px; }}
.teaser span {{ font-size:14px; color:var(--ink-2); }}
.journal {{ margin-top:14px; }}
.jentry {{ display:flex; gap:18px; padding:14px 0; border-bottom:1px dotted var(--rule); }}
.jdate {{ flex:0 0 130px; font-family:"Barlow Condensed",sans-serif; text-transform:uppercase;
  letter-spacing:.06em; font-size:14px; color:var(--accent); padding-top:2px; }}
.jbody p {{ max-width:66ch; }}
.toc {{ margin-top:16px; display:flex; flex-wrap:wrap; gap:4px 14px;
  font-family:"Barlow Condensed",sans-serif; font-size:13.5px; letter-spacing:.08em; text-transform:uppercase; }}
.toc a {{ color:var(--green-2); text-decoration:none; border-bottom:1px dotted var(--rule); }}
.toc a:hover {{ color:var(--accent); }}

/* race card */
.card {{ background:var(--card); border:1px solid var(--rule); border-radius:6px; margin:30px 0 8px;
  overflow-x:auto; box-shadow:0 1px 0 var(--rule); }}
.card table {{ border-collapse:collapse; width:100%; min-width:680px; }}
.card caption {{ text-align:left; padding:14px 16px 4px;
  font-family:"Barlow Condensed",sans-serif; font-size:18px; font-weight:600; letter-spacing:.12em; text-transform:uppercase; color:var(--green); }}
.card th {{ font-family:"Barlow Condensed",sans-serif; font-size:13px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-2); text-align:left; padding:10px 12px 6px; border-bottom:2px solid var(--ink); font-weight:600; }}
.card td {{ padding:10px 12px; border-bottom:1px solid var(--rule); vertical-align:top; }}
.card tr:last-child td {{ border-bottom:none; }}
.pos {{ font-family:"Barlow Condensed",sans-serif; font-size:22px; font-weight:700; color:var(--ink-2); width:2ch; }}
.swatch {{ display:inline-block; width:16px; height:16px; border-radius:3px; margin-top:4px; }}
.runner strong {{ display:block; font-size:16px; }}
.runner .mono {{ font-size:11.5px; color:var(--ink-2); }}
td.num {{ font-family:"Spline Sans Mono",monospace; font-size:14.5px; white-space:nowrap; }}
td.num .ci {{ display:block; font-size:11px; color:var(--ink-2); }}
.card-note {{ font-size:13.5px; color:var(--ink-2); margin:6px 2px 0; }}
.leadout {{ font-style:italic; color:var(--ink-2); border-top:1px dotted var(--rule); padding-top:10px;
  margin-top:18px; max-width:64ch; }}
.explainer.thesis {{ border-left-color:var(--accent); font-size:17px; }}
.card.late {{ margin-top:22px; border-left:4px solid var(--accent); }}
.card.late td {{ font-size:14.5px; }}
.datafiles {{ margin:8px 0 8px 22px; line-height:1.9; }}
.cartoon {{ margin:22px 0; }}
.cartoon svg {{ width:100%; max-width:640px; height:auto; display:block; background:var(--card);
  border:1px solid var(--rule); border-radius:6px; padding:8px; }}
.cartoon figcaption {{ font-size:13px; color:var(--ink-2); margin-top:6px; max-width:70ch; }}
.tracequote {{ border-left:3px solid var(--green); margin:12px 0; padding:10px 16px; background:var(--card);
  font-family:"Spline Sans Mono",monospace; font-size:13px; color:var(--ink); max-width:72ch; }}
.datafiles .mono, .datafiles a {{ font-size:15px; }}

/* signals */
.signal {{ margin:54px 0; }}
.flag {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }}
.flag .t {{ font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:20px; color:var(--paper);
  background:var(--green); width:44px; height:44px; display:grid; place-items:center; border-radius:3px; flex:none; }}
.flag h2 {{ font-family:"Barlow Condensed",sans-serif; font-size:26px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; }}
.flag .dies {{ margin-left:auto; font-size:12.5px; color:var(--ink-2); font-style:italic; max-width:34ch; text-align:right; }}
.signal p {{ max-width:70ch; margin:10px 0; }}
img.fig {{ width:100%; height:auto; margin:14px 0 4px; }}
.headline {{ font-family:"Barlow Condensed",sans-serif; font-size:20px; font-weight:600; color:var(--green); }}
.plain {{ font-size:17px; }}
th .sub {{ font-weight:400; font-size:10.5px; letter-spacing:.04em; text-transform:none; color:var(--ink-2); }}

/* tools */
pre {{ background:var(--card); border:1px solid var(--rule); border-radius:6px; padding:16px;
  overflow-x:auto; font-family:"Spline Sans Mono",monospace; font-size:13.5px; line-height:1.6; color:var(--ink); }}
.notclaim {{ border-top:3px double var(--rule); margin-top:60px; padding:26px 0 10px; font-style:italic; color:var(--ink-2); max-width:70ch; }}
footer {{ padding:20px 0 44px; font-size:13.5px; color:var(--ink-2); }}
footer a {{ color:var(--green-2); }}
a {{ color:var(--green-2); }}
</style>"""

NAV = [("research.html", "Research Programme"), ("index.html", "Overview"), ("method.html", "The Method"),
       ("findings.html", "Findings 1–4"), ("traces.html", "5 · Traces"),
       ("pipes.html", "6 · The Pipes"), ("router.html", "7 · The Router"),
       ("routing2.html", "8 · No Referee"), ("consistency.html", "9 · Ask Twice"),
       ("journal.html", "Journal")]


def navbar(active: str) -> str:
    links = "".join(
        f'<a href="{href}"{" class=~active~".replace("~", chr(34)) if href == active else ""}>{label}</a>'
        for href, label in NAV
    )
    return f'<nav class="pagenav" aria-label="Pages">{links}</nav>'


def compact_head(title: str, active: str) -> str:
    return f"""<header class="compact">
  <div class="race-meta">
    <span class="wip">&#9888; working notes &mdash; what we've learnt so far · updated 12 July 2026</span>
    <span><a href="index.html" style="color:inherit;text-decoration:none">difficulty&ndash;response curves</a></span>
  </div>
  <h1 style="font-size:clamp(26px,4vw,40px)">{title}</h1>
  {navbar(active)}
</header>"""


def page(filename: str, title: str, body: str, description: str) -> None:
    doc = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&family=Spline+Sans+Mono:wght@400;500&display=swap" rel="stylesheet">
{CSS}
</head>
<body>
<div class="wrap">
{body}
<footer>
  <p>alex newman · <a href="https://github.com/posix4e/difficulty-response-curves">github.com/posix4e/difficulty-response-curves</a>
  · every number regenerable via <span class="mono">analysis/run_analysis.py</span> · <a href="paper.pdf">paper (PDF)</a></p>
</footer>
</div>
</body>
</html>
"""
    (ROOT / "docs" / filename).write_text(doc)
    print("wrote docs/" + filename)


B_METHOD = f"""
<section class="signal" id="method">
  <div class="flag"><span class="t">F</span><h2>The whole idea in one picture</h2></div>
  <p class="plain">The difficulty dial is concrete: a puzzle has 20 true/false switches, and the dial sets
  how many constraints those switches must satisfy at once. At &alpha; = 2 (40 loose constraints) almost any
  settings work &mdash; every model cruises. At &alpha; = 5.6 (112 interlocking constraints) valid settings are
  needles in a haystack of a million possibilities. Somewhere in between, each model stops coping. The
  picture below is the entire method: every dot is "how often did this model solve puzzles at this dial
  setting", and the S-curve fitted through the dots pins down each model's <strong>breaking point</strong>
  (the 50/50 crossing) and how <strong>suddenly</strong> it arrives.</p>
  <figure class="cartoon">
    <svg viewBox="0 0 560 640" role="img" aria-label="Three-panel comic explaining 3-SAT: switches, picky friends as constraints, and the difficulty dial">
      <!-- panel 1: the switches -->
      <rect x="8" y="8" width="544" height="188" rx="8" fill="var(--card)" stroke="var(--ink)" stroke-width="2"/>
      <text x="24" y="34" font-size="13" font-weight="bold" fill="var(--green)" letter-spacing="2">PANEL 1 · THE SWITCHES</text>
      <g font-size="10" fill="var(--ink-2)">
        <g transform="translate(40,60)">
          <rect width="26" height="52" rx="13" fill="none" stroke="var(--ink)" stroke-width="2"/>
          <circle cx="13" cy="14" r="9" fill="var(--green)"/><text x="13" y="80" text-anchor="middle">x1 ON</text>
        </g>
        <g transform="translate(110,60)">
          <rect width="26" height="52" rx="13" fill="none" stroke="var(--ink)" stroke-width="2"/>
          <circle cx="13" cy="38" r="9" fill="var(--rule)"/><text x="13" y="80" text-anchor="middle">x2 OFF</text>
        </g>
        <g transform="translate(180,60)">
          <rect width="26" height="52" rx="13" fill="none" stroke="var(--ink)" stroke-width="2"/>
          <circle cx="13" cy="14" r="9" fill="var(--green)"/><text x="13" y="80" text-anchor="middle">x3 ON</text>
        </g>
        <g transform="translate(250,60)">
          <rect width="26" height="52" rx="13" fill="none" stroke="var(--ink)" stroke-width="2"/>
          <circle cx="13" cy="38" r="9" fill="var(--rule)"/><text x="13" y="80" text-anchor="middle">x4 OFF</text>
        </g>
        <g transform="translate(320,60)">
          <rect width="26" height="52" rx="13" fill="none" stroke="var(--ink)" stroke-width="2"/>
          <circle cx="13" cy="14" r="9" fill="var(--green)"/><text x="13" y="80" text-anchor="middle">x5 ON</text>
        </g>
        <text x="390" y="95" font-size="22" fill="var(--ink-2)">&hellip;</text>
        <g transform="translate(430,60)">
          <rect width="26" height="52" rx="13" fill="none" stroke="var(--ink)" stroke-width="2"/>
          <circle cx="13" cy="38" r="9" fill="var(--rule)"/><text x="13" y="80" text-anchor="middle">x20</text>
        </g>
      </g>
      <text x="280" y="172" text-anchor="middle" font-size="12" fill="var(--ink)">One puzzle = 20 switches, each ON or OFF. That's 2&#178;&#8304; = 1,048,576 possible settings.</text>

      <!-- panel 2: the picky friends -->
      <rect x="8" y="212" width="544" height="200" rx="8" fill="var(--card)" stroke="var(--ink)" stroke-width="2"/>
      <text x="24" y="238" font-size="13" font-weight="bold" fill="var(--green)" letter-spacing="2">PANEL 2 · THE PICKY FRIENDS</text>
      <g stroke="var(--ink)" stroke-width="2.2" fill="var(--card)">
        <rect x="258" y="300" width="42" height="34" rx="8"/>
        <rect x="252" y="336" width="54" height="30" rx="6"/>
      </g>
      <g fill="var(--ink)"><circle cx="271" cy="313" r="3"/><circle cx="287" cy="313" r="3"/></g>
      <path d="M265 324 q14 8 28 0" stroke="var(--ink)" stroke-width="2" fill="none"/>
      <ellipse cx="120" cy="285" rx="105" ry="27" fill="var(--card)" stroke="var(--ink-2)" stroke-width="1.3"/>
      <text x="120" y="281" text-anchor="middle" font-size="10">"I'm happy if x3 is ON,</text>
      <text x="120" y="294" text-anchor="middle" font-size="10">or x7 is OFF, or x12 is ON."</text>
      <ellipse cx="438" cy="285" rx="100" ry="27" fill="var(--card)" stroke="var(--ink-2)" stroke-width="1.3"/>
      <text x="438" y="281" text-anchor="middle" font-size="10">"x1 OFF, or x9 ON,</text>
      <text x="438" y="294" text-anchor="middle" font-size="10">or x14 ON. Or I sulk."</text>
      <ellipse cx="150" cy="360" rx="88" ry="22" fill="var(--card)" stroke="var(--accent)" stroke-width="1.4"/>
      <text x="150" y="365" text-anchor="middle" font-size="10" fill="var(--accent)">"&hellip;and 110 more of us."</text>
      <text x="280" y="398" text-anchor="middle" font-size="12" fill="var(--ink)">Each friend is happy if AT LEAST ONE of their three demands holds. Please ALL of them at once.</text>

      <!-- panel 3: the dial -->
      <rect x="8" y="428" width="544" height="200" rx="8" fill="var(--card)" stroke="var(--ink)" stroke-width="2"/>
      <text x="24" y="454" font-size="13" font-weight="bold" fill="var(--green)" letter-spacing="2">PANEL 3 · THE DIAL</text>
      <g stroke="var(--ink)" stroke-width="2" fill="var(--card)">
        <rect x="95" y="500" width="34" height="28" rx="7"/>
      </g>
      <g fill="var(--ink)"><circle cx="106" cy="511" r="2.5"/><circle cx="118" cy="511" r="2.5"/></g>
      <path d="M101 520 q11 7 22 0" stroke="var(--ink)" stroke-width="2" fill="none"/>
      <ellipse cx="112" cy="475" rx="60" ry="16" fill="var(--card)" stroke="var(--ink-2)" stroke-width="1.2"/>
      <text x="112" y="480" text-anchor="middle" font-size="9.5">"40 friends? easy."</text>
      <text x="112" y="560" text-anchor="middle" font-size="11" fill="var(--green)" font-weight="bold">&alpha; = 2 &middot; loose</text>
      <text x="112" y="576" text-anchor="middle" font-size="10" fill="var(--ink-2)">thousands of settings work</text>
      <g transform="translate(250,492)">
        <path d="M0 24 a30 30 0 0 1 60 0" fill="none" stroke="var(--ink)" stroke-width="3"/>
        <line x1="30" y1="24" x2="48" y2="6" stroke="var(--accent)" stroke-width="3"/>
        <text x="30" y="44" text-anchor="middle" font-size="10" fill="var(--ink-2)">the dial: more friends</text>
      </g>
      <g stroke="var(--ink)" stroke-width="2" fill="var(--card)">
        <rect x="428" y="500" width="34" height="28" rx="7"/>
      </g>
      <g fill="var(--ink)"><circle cx="439" cy="511" r="2.5"/><circle cx="451" cy="511" r="2.5"/></g>
      <path d="M434 523 q11 -6 22 0" stroke="var(--ink)" stroke-width="2" fill="none"/>
      <g stroke="var(--ink-2)" stroke-width="1">
        <ellipse cx="404" cy="470" rx="42" ry="12" fill="var(--card)"/>
        <ellipse cx="474" cy="458" rx="42" ry="12" fill="var(--card)"/>
        <ellipse cx="500" cy="484" rx="38" ry="12" fill="var(--card)"/>
        <ellipse cx="420" cy="446" rx="38" ry="12" fill="var(--card)"/>
      </g>
      <line x1="440" y1="494" x2="436" y2="488" stroke="var(--accent)" stroke-width="2"/>
      <text x="445" y="560" text-anchor="middle" font-size="11" fill="var(--accent)" font-weight="bold">&alpha; = 5.6 &middot; 112 friends</text>
      <text x="445" y="576" text-anchor="middle" font-size="10" fill="var(--ink-2)">needles in the haystack</text>
      <text x="280" y="614" text-anchor="middle" font-size="12" fill="var(--ink)">Turning the dial doesn't change the KIND of puzzle &mdash; only how contradictory it is.</text>
    </svg>
    <figcaption>Fig. F1 &mdash; the whole task in three panels. Computer scientists call this "random 3-SAT";
    everyone else can call it pleasing a hundred picky friends with twenty light switches.</figcaption>
  </figure>

  <p>Try one yourself, pocket-sized &mdash; three switches, three friends:</p>
  <blockquote class="tracequote">friend 1: (x1 ON) or (x2 ON) or (x3 ON)&#10;friend 2: (x1 OFF) or (x2 ON) or (x3 ON)&#10;friend 3: (x1 ON) or (x2 OFF) or (x3 OFF)&#10;&#10;Setting <strong>x1=ON, x2=OFF, x3=ON</strong>: friend 1 &check; (x1 is ON) &middot; friend 2 &check; (x3 is ON) &middot; friend 3 &check; (x1 is ON).&#10;The model must end with exactly: <strong>ANSWER: x1=T x2=F x3=T</strong> &mdash; and a program checks every friend.</blockquote>
  <p>Two properties make the measurement trustworthy. Puzzles are <em>freshly generated</em>, so nothing can
  have been memorised from training data. And scoring is <em>cheat-proof</em>: the model must print the full
  switch settings, which a program checks against every constraint &mdash; no multiple choice, no guessing
  floor, no human judgement.</p>
  <img class="fig" src="figs/fig1_curves.svg" alt="Fitted difficulty-response curves for all models with empirical pass rates">
  <p>One caution to carry through everything below: a breaking point belongs to a model <em>and a task
  family</em>. The same models that fail these logic puzzles around &alpha; &asymp; 3.3 sailed through 42-step
  arithmetic untouched &mdash; we had to build 240&ndash;960-step monsters before Haiku finally cracked,
  somewhere past 300 steps. There is no single "difficulty" dial and no single "smart" number. That is why
  the results come as a card with rows, not a ranking with a winner.</p>
  <p class="leadout">Before the card: a word on how this differs from every leaderboard you've seen.</p>
</section>
"""

B_FIELD_CONTEXT = f"""
<section class="signal" id="context">
  <div class="flag"><span class="t">?</span><h2>How AI ability is usually measured &mdash; and why we didn't</h2></div>
  <p class="plain">The field mostly measures models three ways. <strong>Static benchmark suites</strong>
  (MMLU, GSM8K, MATH): fixed lists of questions, score = per cent correct. They're convenient and
  comparable &mdash; and famously compromised: the questions are on the internet, so training data absorbs
  them, and a score mixes memory with ability in unknown proportions. <strong>Human-preference arenas</strong>
  (Chatbot Arena and friends): people vote between two answers, models get chess-style Elo ratings. Honest
  about vibes, silent about <em>where a model breaks</em> &mdash; a great bedside manner can outscore a better
  reasoner. <strong>Flagship demos</strong>: a hard problem solved once, impressively. One sample, no error
  bar, no repeat.</p>
  <p>What all three lack is a <em>difficulty axis</em>: none can say "this model copes up to here, then
  collapses at this rate". Psychometrics solved exactly that problem for human test-takers seventy years
  ago (item response theory &mdash; the S-curves in this page's figures are its bread and butter), and a
  small literature already fits IRT curves to models' results on static benchmarks. The missing move,
  and this project's whole contribution, is to combine the old curve-fitting with tasks where difficulty
  is a <em>generator knob</em>: infinite fresh puzzles, difficulty set by construction, answers checked by
  machine. Closest prior art in that direction: the SAT-hardness evaluations from the theory community,
  and Apple's "Illusion of Thinking" (Tower-of-Hanoi with a size dial) &mdash; whose famous dispute, where
  critics showed part of the measured "collapse" was models hitting token limits rather than reasoning
  limits, is precisely why this page counts truncations, states budgets, and treats pipes as findings.</p>
  <div class="explainer">
    <p><strong>Why this puzzle, of all puzzles?</strong> Because it is the rare task where the three things a
    measuring instrument needs come built-in. <em>A theory-backed dial:</em> thirty years of computer-science
    research (Mitchell, Selman &amp; Levesque 1992; Cheeseman 1991) established that random 3-SAT gets harder
    along a single knob &mdash; the constraint-to-switch ratio &mdash; with a famous hardness peak; no other family
    hands you a one-number difficulty axis with three decades of pedigree. <em>Uncheatable grading:</em> a
    proposed answer is verified mechanically against every constraint in microseconds &mdash; no answer key to
    leak, no judge to bias, no partial credit to argue. <em>No memorisation:</em> instances are generated fresh
    from random seeds, so unlike the standard maths benchmarks (GSM8K, MATH &mdash; static question lists that
    models have long since seen in training), nothing can be recalled, only solved.</p>
    <p style="margin-top:10px"><strong>Why not "primitive maths" then?</strong> We ran arithmetic too, as the
    control (the F-section caution): its dial measures something else &mdash; bookkeeping stamina rather than
    search &mdash; and models that fail SAT at &alpha; &asymp; 3.3 breeze through 240-step arithmetic. Prior art has
    tried other knobs: Apple's "Illusion of Thinking" used Tower-of-Hanoi-style puzzles with a size dial, and
    the ensuing dispute &mdash; critics showed part of the "collapse" was models hitting token limits, not
    reasoning limits &mdash; is precisely why this project counts truncations, discloses budgets, and treats the
    pipes as part of the experiment (finding 6). Psychometric (IRT) analyses of language models existed
    before this too, but typically fitted to static benchmark banks; the combination attempted here is the
    dial + fresh generation + certificate grading + budget honesty, all at once.</p>
  </div>
  <p class="leadout">Now you can read the card.</p>
</section>
"""

B_THE_FIELD = f"""
<section class="signal" id="field">
  <div class="flag"><span class="t">&#9670;</span><h2>Meet the field</h2></div>
  <p class="plain">Ten runners, chosen to span the market: open-weight models you could host yourself
  (the gpt-oss pair &mdash; the same architecture at two sizes &mdash; DeepSeek-R1, Qwen3, MiniMax, GLM) and
  closed commercial ones behind APIs (OpenAI's o4-mini and GPT-5.5, Anthropic's Claude Haiku and Claude
  Fable). Prices per unit of thinking span roughly <strong>two hundred-fold</strong>, from gpt-oss-20b at
  pennies to Fable 5 at $49.50 per million tokens &mdash; which is exactly why the card's most expensive
  rows were measured with the cheap search of finding 4 rather than full sweeps, and why "how much
  thinking a model needs" (finding 3) turns out to matter as much as "how much it knows".</p>
</section>
"""

B_THE_CARD = f"""
<div id="card" class="card">
  <table>
    <caption>The card &mdash; each model's measured breaking point (random 3-SAT, 20 variables)</caption>
    <thead>
      <tr><th></th><th>silks</th><th>runner</th><th>breaking point<br><span class="sub">frontier x&#8325;&#8320; [95% CI]</span></th><th>how sudden<br><span class="sub">sharpness a</span></th><th>re-measured<br><span class="sub">retest x&#8325;&#8320;</span></th><th>easy slips<br><span class="sub">lapse</span></th><th>format / cut-off<br><span class="sub">fail rates</span></th></tr>
    </thead>
    <tbody>
{card_rows()}
    </tbody>
  </table>
</div>
<p class="card-note"><strong>How to read the card:</strong> the <em>breaking point</em> is the difficulty-dial
setting where the model succeeds on exactly half its attempts &mdash; higher means it survives harder puzzles.
<em>How sudden</em> is the slope of the collapse: a big number means a cliff, a small one a long fade.
<em>Re-measured</em> is the breaking point found again on completely fresh puzzles.
<em>Easy slips</em> is how often the model fumbles puzzles it should trivially solve.
Every reading was taken at a stated thinking-token budget (<a href="findings.html#f3">finding 3</a> explains why that matters), and
MiniMax's row comes from an extended dial after it beat the standard range outright.
Total spend for every number on this page: ${fmt(P.get('spend_usd'), 2)} of a $300 cap, ledger below.</p>

<div class="card late">
  <table>
    <caption>Late entries &mdash; premium models, single adaptive runs (not full sweeps)</caption>
    <thead><tr><th>runner</th><th>verdict</th><th>cost of the reading</th></tr></thead>
    <tbody>
      <tr>
        <td class="runner"><strong>GPT-5.5</strong><span class="mono">openai/gpt-5.5</span></td>
        <td>Breaking point <strong>beyond 7.2</strong> &mdash; ran off the end of even the extended track;
        no 20-variable puzzle we can generate is hard enough. On the bigger 50-variable track (<a href="findings.html#f4">finding 4</a>)
        it finally lands: &alpha; &asymp; 4.6&ndash;5.0, solving within practical budgets, joint top of the card.</td>
        <td class="num">48 calls<br>$14.52</td>
      </tr>
      <tr>
        <td class="runner"><strong>Claude Fable 5</strong><span class="mono">anthropic/claude-fable-5</span></td>
        <td>Breaking point <strong>beyond 7.2</strong> &mdash; joint top with GPT-5.5, after a saga: a router
        bug made it look broken (<a href="pipes.html">finding 6</a>), its fitted 6.34 replicated perfectly and was then falsified by
        direct test (10/10 at &alpha; = 7.2 &mdash; a track-edge extrapolation; precision is not truth), and at
        n = 50 it out-thinks every budget we could buy (<a href="findings.html#f3">finding 3</a>).</td>
        <td class="num">337 calls<br>$56</td>
      </tr>
    </tbody>
  </table>
</div>
"""

B_FINDINGS_PREAMBLE = f"""
<section class="signal" id="findings">
  <div class="flag"><span class="t">!</span><h2>So: one number per model?</h2></div>
  <p class="plain">That was the plan. Instead, every experiment complicated the number in a different way
  &mdash; and one experiment was the consolation prize that makes the whole thing usable. The six findings
  below are one story: <em>what a "breaking point" actually is once you look closely.</em></p>
</section>
"""

B_FINDING_1 = f"""
<section class="signal" id="f1">
  <div class="flag"><span class="t">1</span><h2>The frontier is mist, not a wall</h2>
    <span class="dies">this one cannot fail, only surprise: whichever way it splits, we report the split</span></div>
  <p class="plain">When a model fails a puzzle at its breaking point, why? Two candidate stories: the puzzle
  was secretly harder than its difficulty setting suggests &mdash; or the model is genuinely a coin-flip there,
  and the <em>same</em> puzzle passes on one attempt and fails on the next. We ran every frontier puzzle
  16 times to find out.</p>
  <p><span class="headline">{fmt(A.get('Y_within_pct'), 0)} per cent of the variation is the coin-flip kind.</span>
  The frontier is mist, not a wall &mdash; which means retrying a failed problem near the frontier genuinely
  helps, and that is exactly where retry budgets earn their keep.</p>
  <img class="fig" src="figs/fig3_variance.svg" alt="Within-instance versus between-instance variance decomposition at the frontier">
  <p class="leadout">So a breaking point is a coin-flip zone, not a line. Fine &mdash; but is it at least a
  <em>stable</em> zone? Measure twice, get the same answer?</p>
</section>
"""

B_FINDING_2 = f"""
<section class="signal" id="f2">
  <div class="flag"><span class="t">2</span><h2>The measurement repeats &mdash; but the models drift</h2>
    <span class="dies">pre-registered failure condition: error bars so wide that rankings reshuffle between runs</span></div>
  <p class="plain">A measurement you can't repeat is a rumour. So we measured everything twice &mdash;
  fresh puzzles, fresh attempts &mdash; and checked that the numbers came back the same.</p>
  <p><span class="headline">They did: split-half reliability r = {fmt(A.get('X_reliability_r'))} across models,</span>
  and the two models re-tested in full repeated their breaking points to within 0.02 and 0.12 dial units
  (open vs filled markers below). Post-fix probes re-checked the rest: o4-mini 3.28&rarr;3.20 &check;;
  gpt-oss-120b 4.24&rarr;4.41 &check;; DeepSeek-R1 3.78&rarr;3.77 &check;.</p>
  <p><strong>The exception is its own finding:</strong> gpt-oss-20b read 4.63 in the afternoon and
  3.58 &plusmn; 0.10 the same evening <em>on the same pinned endpoint</em> &mdash; the served model changed
  under the label. Both readings are reported. The instrument repeats; the thing being measured is not
  obliged to. Form guides expire; a $0.36 probe (finding 4) is enough to notice.</p>
  <img class="fig" src="figs/fig2_formguide.svg" alt="Forest plot of frontier and sharpness with confidence intervals, main run versus retest">
  <p class="leadout">The instrument repeats; the world drifts. And both of those assumed the models could
  think as long as they liked. They can't &mdash; thinking is metered &mdash;</p>
</section>
"""

B_FINDING_3 = f"""
<section class="signal" id="f3">
  <div class="flag"><span class="t">3</span><h2>The frontier has a price axis</h2>
    <span class="dies">pre-registered failure condition: no spending peak, or one unrelated to the frontier</span></div>
  <p class="plain">Reasoning models bill you for their "thinking" tokens, and they think hardest near their
  own breaking point &mdash; effort climbs as puzzles approach the frontier, peaks just past it, then sags
  as the model gives up. You can locate a model's cliff from billing metadata alone.</p>
  <img class="fig" src="figs/fig4_effort.svg" alt="Mean log completion tokens by difficulty with effort peaks marked">
  <p><span class="headline">And the budget doesn't just reveal the frontier &mdash; it moves it.</span>
  We found this by accident: fixing a router bug (finding 6) made token limits <em>enforced</em> on routes
  that had ignored them, silently re-running MiniMax's measurement with one variable changed. Uncapped,
  MiniMax's breaking point is 6.58 &mdash; top of the sweep card. Capped at 32k tokens it collapses to
  <strong>&asymp;3.6</strong> (56 of 108 calls died at the token wall mid-thought). At n = 50, even 64k wasn't
  enough (0/17). Its long grinds aren't a quirk &mdash; <em>they are the capability</em>. Three models now
  span the spectrum: <strong>GPT-5.5 budget-efficient</strong> (frontier intact under 32k),
  <strong>MiniMax budget-elastic</strong> (frontier moves three dial units with the cap),
  <strong>Fable budget-insatiable</strong> (out-thinks 64k). A frontier is not one number &mdash; it is a
  curve against the thinking budget, and a datasheet should state the budget it was measured at.</p>
  <p class="leadout">Distributions, drift, budget curves &mdash; measuring all this properly sounds ruinously
  expensive. Here is the consolation prize:</p>
</section>
"""

B_FINDING_4 = f"""
<section class="signal" id="f4">
  <div class="flag"><span class="t">4</span><h2>You can find a frontier for pocket change</h2>
    <span class="dies">pure engineering: the ratio is stated without a dinner jacket</span></div>
  <p class="plain">Testing every difficulty level thoroughly is the expensive way to find a breaking point.
  The cheap way is a binary search: try a middling difficulty, jump harder after a success, easier after a
  failure, then home in.</p>
  <p><span class="headline">The search recovers the frontier with {fmt(A.get('W_efficiency'), 1)}&times; fewer
  model calls</span> than uniform testing at the same precision &mdash; proved live: it found Haiku's frontier
  in 20 calls ($1.03) and o4-mini's in 84 ($4.62), matching their 600&ndash;980-call sweeps.</p>
  <p>The same procedure then became the campaign's workhorse: it audited every card row (finding 2's
  clean bill), priced the premium late entries, and ran the head-to-head duels. Those duels are their own
  short story: at 20 variables Fable and GPT-5.5 <em>tie</em> &mdash; both beyond the hardest generatable
  puzzle (Fable went 42/45 vs GPT-5.5's 29/29 on identical instances). On the bigger 50-variable track,
  GPT-5.5 separates: <strong>13/21 with zero truncations</strong> while Fable converted 11/40, out-thinking
  even 64k-token budgets on half its calls (though slightly the more accurate, 11/16, when it finished) and
  MiniMax &mdash; king of the small track &mdash; went <strong>0/17</strong>. Per-track frontiers, per-budget
  frontiers: the card is a snapshot, not a soul.</p>
  <p>We sent the search back to pin where MiniMax's big-track frontier actually sits, and learned the
  answer in two instalments. First the pipe: through a standard ten-minute read window, <em>nothing
  ships</em> &mdash; at &alpha;&nbsp;3.9 every response outlived the socket (eight retries, 103 minutes,
  nothing delivered) and the search starved to death. Widen the window to thirty minutes and the answers
  arrive &mdash; averaging 1,791 seconds and 49,000 thinking tokens each, on the very same provider. Then
  the capability: even delivered, MiniMax converted <strong>3 of 12</strong> at &alpha;&nbsp;3.0&ndash;3.6,
  the easiest end of the big track (one call still died at the 64k token wall). So its 50-variable frontier
  sits at or below &alpha;&nbsp;3 &mdash; more than three dial units under its small-track crown of 6.58 &mdash;
  and merely <em>reaching</em> it costs half an hour of silence per question. Somewhere below "too hard"
  sits <em>too long to ship</em>, and this model lives between the two.</p>
  <p class="leadout">The probe works by counting thinking tokens. Which raises a question: could
  <em>reading</em> the thinking do even better?</p>
</section>
"""

B_FINDING_5 = f"""
<section class="signal" id="f5">
  <div class="flag"><span class="t">5</span><h2>Traces: the thinking you pay for but rarely see</h2></div>
  <p class="plain">A reasoning model doesn't just answer. First it fills a private scratchpad &mdash;
  often ten to forty thousand words of trying things, checking clauses, muttering "wait" &mdash; and
  <em>then</em> writes the short answer you see. That scratchpad is called a <strong>trace</strong>.
  Every word of it lands on your bill. Whether the words themselves are handed back to you is,
  it turns out, a lottery decided by the pipe.</p>
  <figure class="cartoon">
    <svg viewBox="0 0 560 190" role="img" aria-label="Robot at a desk with an enormous thinking pile and a tiny answer note">
      <rect x="30" y="130" width="500" height="6" rx="3" fill="var(--rule)"/>
      <g stroke="var(--ink)" stroke-width="2.5" fill="none" stroke-linecap="round">
        <rect x="255" y="62" width="44" height="36" rx="8" fill="var(--card)"/>
        <circle cx="269" cy="76" r="3.5" fill="var(--ink)" stroke="none"/>
        <circle cx="285" cy="76" r="3.5" fill="var(--ink)" stroke="none"/>
        <path d="M266 89 q11 7 22 0"/>
        <line x1="277" y1="62" x2="277" y2="50"/><circle cx="277" cy="47" r="4" fill="var(--accent)" stroke="none"/>
        <rect x="248" y="98" width="58" height="32" rx="6" fill="var(--card)"/>
        <line x1="248" y1="112" x2="212" y2="104"/><line x1="306" y1="112" x2="352" y2="118"/>
      </g>
      <g>
        <rect x="60" y="52" width="130" height="12" rx="2" fill="var(--green)" opacity="0.25" transform="rotate(-4 125 58)"/>
        <rect x="55" y="66" width="140" height="12" rx="2" fill="var(--green)" opacity="0.35" transform="rotate(3 125 72)"/>
        <rect x="62" y="80" width="128" height="12" rx="2" fill="var(--green)" opacity="0.45" transform="rotate(-2 126 86)"/>
        <rect x="57" y="94" width="138" height="12" rx="2" fill="var(--green)" opacity="0.55"/>
        <rect x="60" y="108" width="132" height="12" rx="2" fill="var(--green)" opacity="0.7"/>
        <rect x="56" y="122" width="140" height="10" rx="2" fill="var(--green)" opacity="0.85"/>
        <text x="126" y="160" text-anchor="middle" font-size="12" fill="var(--ink-2)">THINKING &middot; 14,000 words</text>
        <text x="126" y="175" text-anchor="middle" font-size="11" fill="var(--accent)" font-style="italic">(you pay for every one)</text>
      </g>
      <g>
        <rect x="365" y="106" width="82" height="26" rx="3" fill="#fff6c9" stroke="var(--ink)" stroke-width="1.5"/>
        <text x="406" y="123" text-anchor="middle" font-size="10" fill="var(--ink)">ANSWER: x1=T&hellip;</text>
        <text x="406" y="160" text-anchor="middle" font-size="12" fill="var(--ink-2)">THE ANSWER &middot; 20 words</text>
      </g>
      <g>
        <path d="M310 45 q40 -18 90 -6" stroke="var(--ink-2)" stroke-width="1.2" fill="none"/>
        <ellipse cx="435" cy="34" rx="95" ry="20" fill="var(--card)" stroke="var(--ink-2)" stroke-width="1.2"/>
        <text x="435" y="39" text-anchor="middle" font-size="11.5" font-style="italic" fill="var(--ink)">it's around here somewhere&hellip;</text>
      </g>
    </svg>
    <figcaption>Fig. T5a &mdash; what a reasoning model actually produces. You are billed by the pile, not the sticky note.</figcaption>
  </figure>
  <p>Here is a real slice of one, from DeepSeek-R1 solving one of our puzzles (we hold ~130 of these in full):</p>
  <blockquote class="tracequote">&hellip;so we need x8 to be T for the clause to be true. So x8 must be T.
  Similarly, clause 47: (NOT x8 OR NOT x5 OR x4), x5 T, so NOT x8 OR x4 must be true? <strong>Wait.</strong>
  (NOT x8 OR NOT x5 OR x4), x5 T, NOT x5 F, so NOT x8 OR x4 must be true&hellip;</blockquote>
  <p class="plain">Now the lottery. Ask three different companies for the scratchpad and you get three
  very different experiences at the counter:</p>
  <figure class="cartoon">
    <svg viewBox="0 0 560 235" role="img" aria-label="Three service counters: open models hand over everything, OpenAI hands a receipt, Claude depends on the door">
      <g stroke="var(--ink)" stroke-width="2" fill="var(--card)">
        <rect x="18" y="24" width="160" height="150" rx="8"/>
        <rect x="200" y="24" width="160" height="150" rx="8"/>
        <rect x="382" y="24" width="160" height="150" rx="8"/>
      </g>
      <text x="98" y="45" text-anchor="middle" font-size="11" font-weight="bold" fill="var(--green)">DEEPSEEK &middot; QWEN &middot; MINIMAX</text>
      <text x="280" y="45" text-anchor="middle" font-size="11" font-weight="bold" fill="var(--green)">OPENAI</text>
      <text x="462" y="45" text-anchor="middle" font-size="11" font-weight="bold" fill="var(--green)">CLAUDE</text>
      <g>
        <rect x="45" y="70" width="105" height="10" rx="2" fill="var(--green)" opacity="0.3" transform="rotate(-3 98 75)"/>
        <rect x="42" y="83" width="110" height="10" rx="2" fill="var(--green)" opacity="0.5" transform="rotate(2 98 88)"/>
        <rect x="46" y="96" width="104" height="10" rx="2" fill="var(--green)" opacity="0.7"/>
        <rect x="43" y="109" width="108" height="10" rx="2" fill="var(--green)" opacity="0.9"/>
        <text x="98" y="140" text-anchor="middle" font-size="10.5" font-style="italic" fill="var(--ink)">"everything. even the typos."</text>
      </g>
      <g>
        <rect x="245" y="65" width="70" height="34" rx="4" fill="var(--ink)" opacity="0.85"/>
        <text x="280" y="86" text-anchor="middle" font-size="9" fill="var(--paper)">SHREDDER</text>
        <line x1="252" y1="104" x2="250" y2="120" stroke="var(--ink-2)" stroke-width="1.5"/>
        <line x1="266" y1="104" x2="268" y2="122" stroke="var(--ink-2)" stroke-width="1.5"/>
        <line x1="282" y1="104" x2="279" y2="119" stroke="var(--ink-2)" stroke-width="1.5"/>
        <line x1="297" y1="104" x2="300" y2="121" stroke="var(--ink-2)" stroke-width="1.5"/>
        <rect x="252" y="126" width="58" height="22" rx="2" fill="#fff" stroke="var(--ink)" stroke-width="1.2"/>
        <text x="281" y="140" text-anchor="middle" font-size="8.5" fill="var(--ink)">RECEIPT: 14,373 tokens</text>
        <text x="280" y="163" text-anchor="middle" font-size="10.5" font-style="italic" fill="var(--ink)">"you had to be there."</text>
      </g>
      <g>
        <rect x="398" y="62" width="40" height="14" rx="2" fill="var(--green)" opacity="0.7"/>
        <text x="418" y="90" text-anchor="middle" font-size="9.5" fill="var(--ink)">direct: full pile</text>
        <path d="M492 62 l18 0 l0 14 l-18 0 z M492 62 l9 8 l9 -8" fill="none" stroke="var(--ink)" stroke-width="1.4"/>
        <text x="501" y="90" text-anchor="middle" font-size="9.5" fill="var(--ink)">OpenRouter:</text>
        <text x="501" y="101" text-anchor="middle" font-size="9.5" fill="var(--ink)">side window</text>
        <path d="M448 108 l24 0 l-3 26 l-18 0 z" fill="none" stroke="var(--ink)" stroke-width="1.6"/>
        <line x1="446" y1="108" x2="474" y2="108" stroke="var(--ink)" stroke-width="2"/>
        <text x="460" y="150" text-anchor="middle" font-size="9.5" fill="var(--accent)">TrustedRouter: bin</text>
        <text x="460" y="161" text-anchor="middle" font-size="9" font-style="italic" fill="var(--accent)">(billed anyway)</text>
      </g>
      <text x="280" y="205" text-anchor="middle" font-size="12" fill="var(--ink-2)">same product. three counters. measured numbers in the table below.</text>
    </svg>
    <figcaption>Fig. T5b &mdash; trace delivery in practice. The open models hand it all over; OpenAI shreds it and gives you the count (on <em>every</em> route, including their own); Claude's depends entirely on which door you knock at.</figcaption>
  </figure>
  <div class="card"><table>
    <caption>The receipts &mdash; billed thinking vs delivered text, measured from our own calls</caption>
    <thead><tr><th>model</th><th>route</th><th>billed tok/call</th><th>delivered</th><th>verdict</th></tr></thead>
    <tbody>
{trace_rows()}
    </tbody>
  </table></div>
  <p class="card-note">The strangest row is gpt-oss: those models are <em>open weights</em> and emit reasoning
  by design, yet every serving stack we used strips it. Open weights &ne; open traces.</p>
  <p class="plain">And the payoff question: where you <em>do</em> get the scratchpad, is reading it better
  than counting it? Yes &mdash; because of what stress sounds like:</p>
  <figure class="cartoon">
    <svg viewBox="0 0 560 225" role="img" aria-label="Three robots on ground ending in a cliff: calm work, looping at the edge, long doomed monologue past it">
      <path d="M20 170 L420 170 L420 210 L555 210" stroke="var(--ink)" stroke-width="2.5" fill="none"/>
      <text x="428" y="196" font-size="10" fill="var(--ink-2)">the cliff</text>
      <g stroke="var(--ink)" stroke-width="2" fill="var(--card)">
        <rect x="70" y="138" width="26" height="22" rx="5"/>
        <rect x="330" y="138" width="26" height="22" rx="5"/>
        <rect x="470" y="178" width="26" height="22" rx="5" transform="rotate(14 483 189)"/>
      </g>
      <g fill="var(--ink)"><circle cx="78" cy="146" r="2"/><circle cx="88" cy="146" r="2"/>
        <circle cx="338" cy="146" r="2"/><circle cx="348" cy="146" r="2"/></g>
      <ellipse cx="86" cy="102" rx="66" ry="21" fill="var(--card)" stroke="var(--ink-2)" stroke-width="1.2"/>
      <text x="86" y="99" text-anchor="middle" font-size="10">x1=T, x2=F, x3=T&hellip;</text>
      <text x="86" y="112" text-anchor="middle" font-size="10">done &#10003;</text>
      <text x="86" y="185" text-anchor="middle" font-size="10.5" fill="var(--ink-2)">easy: steady work</text>
      <ellipse cx="343" cy="95" rx="78" ry="27" fill="var(--card)" stroke="var(--accent)" stroke-width="1.6"/>
      <text x="343" y="88" text-anchor="middle" font-size="10">wait, try x3&hellip; wait,</text>
      <text x="343" y="101" text-anchor="middle" font-size="10">try x3&hellip; wait, try x3&hellip;</text>
      <path d="M394 68 a14 14 0 1 1 4 22" fill="none" stroke="var(--accent)" stroke-width="1.8"/>
      <path d="M396 88 l4 6 l-8 1 z" fill="var(--accent)"/>
      <text x="343" y="185" text-anchor="middle" font-size="10.5" font-weight="bold" fill="var(--accent)">loops = it is AT the wall</text>
      <path d="M496 176 q30 -30 20 -68 q-6 -26 -40 -30" stroke="var(--ink-2)" stroke-width="1.2" fill="none"/>
      <ellipse cx="452" cy="62" rx="100" ry="24" fill="var(--card)" stroke="var(--ink-2)" stroke-width="1.2"/>
      <text x="452" y="58" text-anchor="middle" font-size="9.5" font-style="italic">&hellip;reconsidering clause 197</text>
      <text x="452" y="70" text-anchor="middle" font-size="9.5" font-style="italic">from first principles&hellip; (word 31,000)</text>
      <text x="480" y="222" text-anchor="middle" font-size="10.5" fill="var(--ink-2)">past it: the long doomed monologue</text>
    </svg>
    <figcaption>Fig. T5c &mdash; what we measured in the traces. Repetition ("wait, try x3&hellip;" on loop) spikes
    <em>exactly at</em> each model's breaking point (within 0.5 dial units for R1, dead-on for Qwen); sheer
    length peaks well <em>past</em> it (+1.4 to +1.8). MiniMax is the exception that proves it: its giant
    scratchpads barely repeat &mdash; that's genuine search, not circling.</figcaption>
  </figure>
  <p><span class="headline">Working conclusion: count tokens to find the cliff anywhere; listen for the
  stutter to find it precisely &mdash; on the rare pipes that let you listen at all.</span></p>
  <p class="leadout">"The rare pipes that let you" is doing a lot of work in that sentence. Time to talk about <a href="pipes.html">the pipes</a>.</p>
</section>
"""

B_FINDING_6 = f"""
<section class="signal" id="f6">
  <div class="flag"><span class="t">6</span><h2>The pipes are part of the experiment</h2></div>
  <p class="plain">Every measurement travels through a gateway and a serving provider before it reaches a
  model, and this campaign kept catching the plumbing red-handed. Treat this section as the safety leaflet.</p>
  <p><strong>The bug:</strong> our gateway (TrustedRouter) silently drops the
  <span class="mono">max_completion_tokens</span> parameter when translating requests for several providers;
  reply length then falls to each provider's default &mdash; 4,096 tokens on some. Every truncation artefact in
  this project traced to that one bug. It made Fable 5 look broken (billed for thinking, delivered nothing)
  and framed an innocent provider (baseten happily delivers 30,000 tokens when the limit is phrased as
  <span class="mono">max_tokens</span>). Fix on our side: send both spellings. Verified same-day.</p>
  <p><strong>Vendor response:</strong> we reported it; TrustedRouter credited the account $20 and reported it
  fixed. Re-verified with the same differential probe on 6 July: <strong>not fixed</strong> &mdash; the
  parameter still returns exactly 4,096 tokens and an empty reply. A second $20 credit and a second claimed
  fix arrived on 7 July, and this one held: the same probe now sails past the wall (7,217 and 10,855 billed
  tokens, natural stops, answers delivered &mdash; and both <em>scored passes</em> on fresh hard instances at
  &alpha; 5.0 and 5.6). The model this route once made unmeasurable now solves hard SAT through it. The probe
  ships in the toolkit; run it before trusting any gateway with a reasoning workload &mdash; and run it again
  after every "fixed".</p>
  <p><strong>What this means for the card:</strong> passes can't be faked (every pass is a checked
  certificate), so plumbing failures only ever make models look <em>worse</em>, and they announce themselves
  as truncations and empties &mdash; which we count, disclose per row, and purge as artefacts when the pipe
  (not the model) was at fault. The endpoint that served every call is recorded in the released data.</p>
</section>
"""

B_THESIS = f"""
<section class="signal" id="thesis">
  <div class="flag"><span class="t">&#9733;</span><h2>So what is a frontier?</h2></div>
  <div class="explainer thesis">
    <p>Six findings, one sentence: <strong>a model's breaking point is not a constant &mdash; it is a
    coin-flip zone (1), measured on a date (2), at a thinking budget (3), on one task family (F),
    through a particular pipe (6) &mdash; and the only reason any of that is workable is that re-measuring
    costs pocket change (4), with the model's own stutter as a second opinion where the pipe allows (5).</strong>
    The card above states its family, budgets, dates, and pipes. Any capability number that doesn't is a rumour
    with confidence intervals missing.</p>
  </div>
</section>
"""

B_DATA = f"""
<section class="signal" id="data">
  <div class="flag"><span class="t">&#9633;</span><h2>The raw data, right here</h2></div>
  <p class="plain">Every API call this project made &mdash; prompt hashes, full response text, token counts,
  cost in microdollars, and the provider endpoint that actually served it &mdash; downloadable directly:</p>
  <ul class="datafiles">
    <li><a href="data/calls.jsonl.gz">calls.jsonl.gz</a> &mdash; every scored call (one JSON object per line)</li>
    <li><a href="data/instances.jsonl.gz">instances.jsonl.gz</a> &mdash; every generated puzzle, with its solution witness</li>
    <li><a href="data/drc.sqlite.gz">drc.sqlite.gz</a> &mdash; the complete database, the exact file the analysis reads</li>
    <li><a href="data/ledger.txt">ledger.txt</a> &mdash; the spend ledger, stage by stage</li>
    <li><a href="data/manifest.json">manifest.json</a> &mdash; sha256 hashes and byte sizes for all of the above</li>
  </ul>
  <p>Reanalysis from scratch: <span class="mono">gunzip drc.sqlite.gz &rarr; data/drc.sqlite</span>, then
  <span class="mono">python analysis/run_analysis.py</span> in the repo regenerates every number on this
  page and in the paper.</p>
</section>
"""

B_TOOLS = f"""
<section class="signal" id="tools">
  <div class="flag"><span class="t">&sect;</span><h2>Measure your own model</h2></div>
  <p>The whole instrument is released: generators, runner, fitting code, raw per-call records.
  Point it at any OpenAI-compatible endpoint. The dollar cap is enforced per call, not estimated.</p>
  <pre>python3 -m venv .venv &amp;&amp; .venv/bin/pip install -e .
export TRUSTEDROUTER_API_KEY=sk-tr-...

.venv/bin/drc sweep --model your/model --grid sat-n20-main --instances 15 --k 4 --cap 2.0
.venv/bin/drc fit   --model your/model --sets adhoc --stages adhoc --bootstrap 2000 --gof
.venv/bin/drc adaptive --model your/model --cap 2.0   # the fast way to x50
.venv/bin/drc budget                                  # where every microdollar went</pre>
</section>
"""

HEADER_FULL = f"""<header>
  <div class="race-meta">
    <span class="wip">&#9888; working notes &mdash; what we've learnt so far · updated 8 July 2026</span>
    <span>going: procedurally generated · surface: random 3-SAT</span>
  </div>
  <h1>Difficulty&ndash;Response Curves<br><span class="thin">A form guide for reasoning models</span></h1>
  <p class="standfirst">Nobody at the races asks whether a horse is good. They ask what distance,
  what going, and does it fade in the straight. This is that card, for reasoning models &mdash; a living
  document where the corrections are part of the findings.</p>
  <div class="explainer">
    <p><strong>What is this?</strong> We generated thousands of logic puzzles with a
    <em>difficulty dial</em> (random 3-SAT: find true/false values satisfying a list of
    constraints; more constraints = harder), tested ten AI models repeatedly across the dial, and
    plotted each model's success rate as difficulty rises. Every model produces an S-shaped curve,
    summarised by two numbers: the <strong>frontier x&#8325;&#8320;</strong> (the difficulty where it
    succeeds half the time) and the <strong>sharpness a</strong> (how suddenly success collapses).
    Psychometricians have fitted these curves to human test-takers since the 1950s &mdash; item response
    theory &mdash; and this project points the same instrument at machines: fresh unmemorisable puzzles,
    mechanically checkable answers, error bars on everything, all data and tools released below.</p>
  </div>
  <div class="links">
    <a href="research.html">Confidence &amp; control protocols</a>
    <a href="paper.pdf">Read the paper (PDF)</a>
    <a class="ghost" href="https://github.com/posix4e/difficulty-response-curves">Code &amp; generators</a>
    <a class="ghost" href="index.html#data">Raw data</a>
    <a class="ghost" href="index.html#tools">Measure your own model</a>
  </div>
  </header>"""


R = json.loads((ROOT / "analysis" / "routing.json").read_text())

# ---------------------------------------------------------------- overview --
teasers = f"""
<section class="signal" id="tour">
  <div class="flag"><span class="t">&#9776;</span><h2>The tour</h2></div>
  <div class="teasers">
    <a class="teaser" href="research.html"><strong>Living research programme</strong><span>MiniMax confidence,
      trace-triggered speculative execution, and the registered gates separating evidence from ideas.</span></a>
    <a class="teaser" href="method.html"><strong>The method</strong><span>What a difficulty dial is, the
      SAT comic, why this puzzle beats maths benchmarks, and how this differs from leaderboards and arenas.</span></a>
    <a class="teaser" href="findings.html"><strong>Findings 1&ndash;4</strong><span>The frontier is mist; the
      measurement repeats but models drift; budgets move frontiers; and a $0.36 probe finds any of it.</span></a>
    <a class="teaser" href="traces.html"><strong>Finding 5 &middot; Traces</strong><span>The thinking you pay
      for but rarely see &mdash; with cartoons, real scratchpad excerpts, and the loops that mark the cliff.</span></a>
    <a class="teaser" href="pipes.html"><strong>Finding 6 &middot; The pipes</strong><span>The router bug that
      framed two innocents, the vendor fix that wasn't, and why the card survives its own plumbing.</span></a>
    <a class="teaser" href="router.html"><strong>Finding 7 &middot; The router</strong><span>The practical
      payoff: a LiteLLM router driven by the card &mdash; retries beat escalation, and premium &ne; stronger.</span></a>
    <a class="teaser" href="journal.html"><strong>The journal</strong><span>The whole campaign, dated: outages,
      credit walls, convictions, corrections, and what each cost.</span></a>
  </div>
</section>
"""

overview_body = (
    HEADER_FULL.replace("</header>", navbar("index.html") + "</header>")
    + teasers + B_THE_CARD + B_THESIS + B_DATA + B_TOOLS
    + """<p class="notclaim">What this site does not claim: no mechanism, no physics vocabulary, nobody's water is
freezing, no reading of trace contents beyond what is measured, and no claim yet that trace risk gives useful early warning.
The restraint is the brand.</p>"""
)
page("index.html", "Difficulty–Response Curves: A Form Guide for Reasoning Models",
     overview_body, "Item response theory pointed at language models: measured frontiers with confidence intervals.")

# ---------------------------------------------------------------- method --
page("method.html", "The Method — Difficulty–Response Curves",
     compact_head("The method: dials, puzzles, and honest grading", "method.html")
     + B_METHOD + B_FIELD_CONTEXT + B_THE_FIELD
     + '<p class="leadout">Next: <a href="index.html#card">the card</a> these methods produced, or the <a href="findings.html">findings</a> it led to.</p>',
     "What a difficulty dial is, why random 3-SAT, and how this differs from benchmarks and arenas.")

# ---------------------------------------------------------------- findings --
page("findings.html", "Findings 1–4 — Difficulty–Response Curves",
     compact_head("Findings 1–4: mist, drift, budgets, and pocket-change probes", "findings.html")
     + B_FINDINGS_PREAMBLE + B_FINDING_1 + B_FINDING_2 + B_FINDING_3 + B_FINDING_4
     + '<p class="leadout">The story continues in <a href="traces.html">finding 5 (traces)</a> and <a href="pipes.html">finding 6 (the pipes)</a>.</p>'
     + B_THESIS,
     "The frontier is mist; measurements repeat but models drift; budgets move frontiers; cheap probes find all of it.")

# ---------------------------------------------------------------- traces --
page("traces.html", "Finding 5: Traces — Difficulty–Response Curves",
     compact_head("Finding 5 · Traces: the thinking you pay for but rarely see", "traces.html") + B_FINDING_5,
     "Reasoning traces: billed everywhere, delivered rarely, and where delivered, the loops mark the cliff.")

# ---------------------------------------------------------------- pipes --
page("pipes.html", "Finding 6: The Pipes — Difficulty–Response Curves",
     compact_head("Finding 6 · The pipes are part of the experiment", "pipes.html") + B_FINDING_6,
     "Gateway bugs, provider drift, a vendor fix that wasn't — and why the card survives its own plumbing.")

# ---------------------------------------------------------------- router --
a3 = R.get("a3_replay", {}).get("gpt-oss-20b->o4-mini", {}).get("policies", {})
def prow(name, label):
    p = a3.get(name, {})
    return f"<tr><td>{label}</td><td class=\"num\">{p.get('solve_rate','—')}</td><td class=\"num\">${p.get('cost_per_solved_usd','—')}</td></tr>"

live = R.get("live_eval")
live_html = ""
if live:
    rows = "".join(
        f"<tr><td>{k}</td><td class=\"num\">{v['solved']}</td><td class=\"num\">${v['cost_per_solved_usd']}</td></tr>"
        for k, v in live["results"].items())
    progress = "" if live.get("complete", True) else " The run is still going; these are the policies banked so far."
    live_html = f"""
  <h3 class="disp" style="margin-top:26px">Live validation (fresh puzzles, real spend)</h3>
  <p>{live['design']}; total spend ${live['total_spend_usd']}.{progress}</p>
  <div class="card"><table>
    <thead><tr><th>policy</th><th>solved</th><th>$/solved</th></tr></thead><tbody>{rows}</tbody>
  </table></div>"""
else:
    live_html = """
  <p class="card-note">Live validation on fresh never-seen puzzles is running as this page is written
  &mdash; results land here when it finishes. Working notes, remember.</p>"""

router_body = compact_head("Finding 7 · The router: making the card earn a living", "router.html") + f"""
<section class="signal" id="f7">
  <p class="plain">Everything on this site condenses to a practical question: <em>given a request, which
  model should answer it?</em> We turned the card into a router and replayed it against our own recorded
  data &mdash; hundreds of real attempts on shared puzzles, with real per-call costs.</p>

  <p><strong>First, the idea that died</strong> (reported per the house rules): using a single call's token
  count to judge whether <em>that answer</em> is wrong. Measured AUC &asymp; 0.5 &mdash; a coin flip. The invoice
  locates frontiers in aggregate; it does not grade individual answers. Bring a verifier.</p>

  <p><strong>Then, the replay that pays</strong> &mdash; policies over the same instances, real costs
  (cheap rung: gpt-oss-20b; "premium": o4-mini):</p>
  <div class="card"><table>
    <thead><tr><th>policy</th><th>solve rate</th><th>$/solved</th></tr></thead>
    <tbody>
    {prow('always_cheap', 'always cheap (gpt-oss-20b)')}
    {prow('cheap_retry3', 'cheap, retry &times;3 on verified failure')}
    {prow('cascade_on_verify', 'cascade: cheap &rarr; premium on failure')}
    {prow('always_strong', 'always premium (o4-mini)')}
    </tbody>
  </table></div>
  <p>Two rules fall out, both violations of routing folklore. <strong>Retries beat escalation:</strong>
  near-frontier failures are coin-flips (<a href="findings.html#f1">finding 1</a>), so re-rolling the cheap
  model solves more, cheaper, than calling in the big one. <strong>Premium &ne; stronger:</strong> on this
  task family the $4.84/M model solved half as much as the $0.22/M one &mdash; the only ladder that means
  anything is <em>measured frontier on your task</em>, which is what the card is.</p>
{live_html}
  <h3 class="disp" style="margin-top:26px">Use it</h3>
  <p>The router ships in the repo under
  <a href="https://github.com/posix4e/difficulty-response-curves/tree/main/integrations/litellm">integrations/litellm</a>:
  a LiteLLM-compatible <span class="mono">FormGuideRouter</span> (cheapest capable rung &rarr; mist retries
  &rarr; frontier escalation, per-rung token budgets, both max-token spellings), a machine-readable
  <span class="mono">formguide.json</span> generated from the measured card, and
  <span class="mono">recalibrate.py</span> for the drift problem (<a href="findings.html#f2">finding 2</a>):
  frontiers moved a full dial unit in twelve hours in our data, so calibrations carry dates and a re-probe
  costs cents.</p>
  <p class="leadout">The card is a snapshot; the router is the reason to keep the snapshot fresh.
  One load-bearing caveat: this router had a free referee &mdash; SAT answers are checkable. Whether the
  trace can stand in for the verifier got its own round of experiments: <a href="routing2.html">finding 8</a>.
  (Spoiler: bring the referee.)</p>
</section>
"""
page("router.html", "Finding 7: The Router — Difficulty–Response Curves", router_body,
     "A LiteLLM router driven by measured frontiers: retries beat escalation; premium is not stronger.")

# ---------------------------------------------------------------- routing2 --
R2 = json.loads((ROOT / "analysis" / "routing2.json").read_text())
PC = json.loads((ROOT / "analysis" / "percall-percall.json").read_text())

def gate_rows() -> str:
    rows = []
    for m, e in PC["models"].items():
        if "auc" not in e:
            rows.append(f"<tr><td>{m.split('/')[-1]}</td><td class=\"num\">{e['n_traced']}</td>"
                        f"<td class=\"num\">{e['n_pairs']}</td><td colspan=\"4\">no scoreable pairs</td></tr>")
            continue
        a = e["auc"]
        def cell(f):
            p, (lo, hi) = a[f]["point"], a[f]["ci95"]
            strong = ' style="font-weight:700"' if p >= 0.65 else ""
            return f"<td class=\"num\"{strong}>{p:.2f} <span style=\"opacity:.6\">[{lo:.2f}&ndash;{hi:.2f}]</span></td>"
        rows.append(f"<tr><td>{m.split('/')[-1]}</td><td class=\"num\">{e['n_traced']}</td>"
                    f"<td class=\"num\">{e['n_pairs']}</td>"
                    + cell("hedge_tail") + cell("bt_tail") + cell("wait_tail") + cell("tok") + "</tr>")
    return "".join(rows)

def live2_rows(fam: str) -> str:
    arms = R2["live_eval_v2"]["results"][fam]
    label = {"always_cheap": "always cheap (R1@deepinfra)", "always_premium": "always premium (GPT-5.5)",
             "judged_router": "trace-judged router", "random_escalate": "random escalation (control)"}
    return "".join(
        f"<tr><td>{label[k]}</td><td class=\"num\">{v['solved']}</td><td class=\"num\">${v['cost_per_solved_usd']}</td>"
        f"<td class=\"num\">{int(v['escalation_rate']*100)}%</td></tr>"
        for k, v in arms.items())

sweep_rows = "".join(
    f"<tr><td class=\"num\">{r['threshold']}</td><td class=\"num\">{r['tpr']:.2f}</td>"
    f"<td class=\"num\">{r['fpr']:.2f}</td><td class=\"num\">{r['sat_expected_solve']:.2f}</td>"
    f"<td class=\"num\">${r['sat_expected_cost_per_inst']}</td></tr>"
    for r in R2["counterfactual_sweep"]["rows"])

PJ = json.loads((ROOT / "analysis" / "percall-judge.json").read_text())
PCON = json.loads((ROOT / "analysis" / "percall-consistency.json").read_text())

def consistency_rows() -> str:
    rows = []
    for m, e in PCON["models"].items():
        if "auc" not in e:
            continue
        rows.append(
            f"<tr><td>{m.split('/')[-1]}</td><td class=\"num\">{e['auc']:.2f}</td>"
            f"<td class=\"num\">{e['recall']:.2f}</td><td class=\"num\">{e['fpr']:.2f}</td>"
            f"<td class=\"num\">{int(e['escalation_rate']*100)}%</td>"
            f"<td class=\"num\">{e['p_correct_given_agree']:.2f}</td></tr>")
    return "".join(rows)

def judge_rows() -> str:
    rows = []
    for m, e in PJ["models"].items():
        c = e.get("confirmatory")
        if not c:
            rows.append(f"<tr><td>{m.split('/')[-1]}</td><td colspan=\"5\">{e.get('skipped','')}</td></tr>")
            continue
        rows.append(
            f"<tr><td>{m.split('/')[-1]}</td><td class=\"mono\">{' + '.join(e['features'])}</td>"
            f"<td class=\"num\">{e['cv_auc_train']:.2f}</td><td class=\"num\">{c['auc']:.2f}</td>"
            f"<td class=\"num\">{c['recall_at_frozen_threshold']:.2f}</td>"
            f"<td class=\"num\">{c['fpr_at_frozen_threshold']:.2f}</td></tr>")
    return "".join(rows)

routing2_body = compact_head("Finding 8 · No referee: the trace cannot route itself", "routing2.html") + f"""
<section class="signal" id="f8">
  <p class="plain">Finding 7's router solved 24/25 because SAT hands you a free referee &mdash; every answer
  is checkable. Real tasks aren't. Round 2 asked the obvious next question, with money on it:
  <em>can the model's own reasoning trace replace the verifier?</em> Pre-registered gates, fresh spend,
  a second task family, and a live four-arm race. Short version: one model's trace whispers, one mumbles,
  one is silent &mdash; and none of it routes.</p>

  <h3 class="disp" style="margin-top:26px">The offline gate (pre-registered, confirmatory)</h3>
  <p>Hypotheses declared before the purpose-built batch ran: PRIMARY <span class="mono">hedge_tail</span>
  (hedging density, final 15% + answer region), SECONDARY <span class="mono">bt_tail</span> (backtrack
  density, last 30%). Labels are silent wrongs only &mdash; truncations are loud and free to catch.
  Pairs form within a difficulty level on one route, so difficulty itself cannot do the predicting.
  Gate: AUC &ge; 0.65 on &ge; 2 of 3 traced models.</p>
  <div class="card"><table>
    <thead><tr><th>model</th><th>traced</th><th>pairs</th><th>hedge_tail</th><th>bt_tail</th>
    <th>wait_tail</th><th>tokens</th></tr></thead><tbody>{gate_rows()}</tbody>
  </table></div>
  <p>Two lessons in one table. First, the textures: <strong>MiniMax backtracks and rambles when wrong</strong>
  (its hedging is noise; token count is its loudest tell &mdash; uncapped, wrong answers run long),
  <strong>R1 hedges, faintly</strong> (its backtracking is noise), and <strong>Qwen gives nothing away</strong>
  &mdash; every feature within a whisker of a coin flip on four hundred pairs. There is no universal tell;
  a trace judge is one more per-model calibration. Second, the confession: mid-evening, with the batch half
  landed, the table read 2-of-3 over the bar (R1's hedging then at 0.68) and <strong>we called the gate
  passed and funded the live arm</strong>. The completed set walked R1 back under the line &mdash; the
  final verdict is <strong>one model of three</strong>. Our pre-registration named the hypotheses and the
  bar but not the stopping rule, and sequential peeking did what it always does. Both the interim call and
  the walk-back are preserved in the devlog; the live results below should be read as funded by a gate
  that, on complete data, fails.</p>

  <h3 class="disp" style="margin-top:26px">The second family, third attempt</h3>
  <p>Transfer needed a task with hidden ground truth. Design one showed the model rule specs to transcribe
  into code: flat &mdash; R1 went 58/60 out to forty rules; transcription is not difficulty. Design two hid
  the rules behind eight examples but kept two conditional rules: R1 fit all eight examples at depth 2 and
  still failed the hidden tests &mdash; ambiguity, not difficulty. Design three (deterministic rules only,
  twelve examples) produced the real thing, confirmed by paired pilots: R1 75% at depth 1 and 0/11 at
  depths 2&ndash;5; GPT-5.5 solves 7/8 in exactly that band and dies at 6. A routable gap, certified
  before the live run spent a dollar.</p>

  <h3 class="disp" style="margin-top:26px">The live race (fresh instances, real spend)</h3>
  <p>Four arms, both families, ground truth never visible to routing. The judge: cheap rung's trace scored
  by <span class="mono">hedge_tail</span> at the Youden-optimal threshold from the confirmatory set; judged
  failure triggers a retry, then escalation. The control escalates at random, rate-matched to the judged
  arm's realized rate &mdash; the judge's marginal value over spending the same money blindly.</p>
  <div class="card"><table>
    <thead><tr><th>SAT (n=20, &alpha; 3.0&ndash;5.3)</th><th>solved</th><th>$/solved</th><th>escalated</th></tr></thead>
    <tbody>{live2_rows('sat')}</tbody>
  </table></div>
  <div class="card" style="margin-top:10px"><table>
    <thead><tr><th>program synthesis (n=20, D 1&ndash;5)</th><th>solved</th><th>$/solved</th><th>escalated</th></tr></thead>
    <tbody>{live2_rows('synth')}</tbody>
  </table></div>
  <p><strong>The pre-registered bar &mdash; beat both single-model arms on both families &mdash; was missed,
  and the random control beat the judge on both.</strong> Three honest footnotes. One: GPT-5.5 saturated SAT
  (20/20), which makes that family's bar unreachable &mdash; you cannot out-solve perfection, only undercut
  it. Two: the SAT control got lucky &mdash; its RNG realized 35% escalation against the judge's 15%, so it
  is not a clean rate-match there; on synthesis the rates nearly matched (45% vs 40%) and the control still
  won on both solve rate and cost. Three: the judge's escalations were <em>precise</em> &mdash; on SAT every
  one converted &mdash; it simply fired far too rarely (live recall ~0.21), and at the closer's own frontier
  it fired on the closer too, buying expensive retries that converted nothing ($0.72/solve on synthesis:
  worse than just buying premium).</p>

  <h3 class="disp" style="margin-top:26px">What the threshold could never buy</h3>
  <p>Was Youden the mistake? Routing wants recall &mdash; a false escalation costs $0.23, a missed wrong
  costs a solve. Sweeping the threshold over the confirmatory traces:</p>
  <div class="card"><table>
    <thead><tr><th>threshold</th><th>recall</th><th>false alarm</th><th>expected SAT solve</th><th>$/instance</th></tr></thead>
    <tbody>{sweep_rows}</tbody>
  </table></div>
  <p>{R2['counterfactual_sweep']['note'].replace('0.65-0.68', '0.65&ndash;0.68').replace(' - ', ' &mdash; ')}.</p>

  <h3 class="disp" style="margin-top:26px">Round 3, same morning: the stronger judge ($0)</h3>
  <p>The obvious objection to everything above: one feature at a balance-tuned threshold is a weak judge.
  So we built the strong one &mdash; per-model trained combos over sixteen trace features, selected by
  instance-grouped cross-validation on the <em>exploratory</em> corpus only, recall-oriented threshold
  frozen on training data, and this time the pre-registration included the stopping rule round 2 lacked:
  one evaluation on the frozen confirmatory set, no interim looks. Gate: AUC &ge; 0.75 <em>and</em>
  recall &ge; 0.5 at false-alarm &le; 0.25, on two of three models.</p>
  <div class="card"><table>
    <thead><tr><th>model</th><th>trained combo</th><th>CV AUC (train)</th><th>confirmatory AUC</th>
    <th>recall</th><th>false alarm</th></tr></thead><tbody>{judge_rows()}</tbody>
  </table></div>
  <p><strong>Zero of three clear; no live money was spent.</strong> The autopsy writes the epitaph:
  R1's cross-validated 0.81 evaporated to 0.56 on the frozen set (the combo had learnt the training
  corpus, not the model); Qwen's perfect-looking CV was noise on eleven training wrongs, exactly as
  flagged before the gate ran; and MiniMax &mdash; whose trace genuinely does tell, in every analysis
  we have run &mdash; posted 0.93 AUC at 92% recall and still missed the false-alarm arm of the bar.
  One talkative model out of three cannot crew a fleet, and the fleet's cheap rung was R1.</p>

  <h3 class="disp" style="margin-top:26px">Round 4, same day: ask the model twice ($0)</h3>
  <p>One signal source left standing, and it is the one finding 1 itself predicts: the mist. If
  near-frontier answers are coin flips (81% within-instance variance), two samples of the same model
  should <em>disagree</em> exactly where the answer cannot be trusted. Pre-registered before the number
  existed (same bar as round 3, one look at the frozen k=6 corpus, hazard declared in writing: satisfiable
  SAT admits many correct assignments, so right answers may disagree too), then computed once:</p>
  <div class="card"><table>
    <thead><tr><th>model</th><th>AUC</th><th>recall</th><th>false alarm</th><th>escalation</th>
    <th>P(correct&nbsp;|&nbsp;agree)</th></tr></thead><tbody>{consistency_rows()}</tbody>
  </table></div>
  <p><strong>Zero of three clear &mdash; and it is the best negative of the campaign.</strong> Recall is
  a perfect 1.000 on all three models: every silently wrong answer disagreed with its partners. P(correct
  given agreement) is also a perfect 1.000 on all three: exact agreement never once shipped a wrong answer.
  Self-consistency is a <em>flawless certificate</em> &mdash; that almost never certifies. The declared
  hazard ate the economics whole: correct answers pick different satisfying assignments, so false alarms
  run 76&ndash;94% and the router degenerates to escalate-everything. The signal is real, universal across
  our fleet, and priced out by answer multiplicity on exactly this task family. On families with unique
  answers the same arithmetic could land very differently &mdash; that is the one door this page leaves
  ajar, stated and unspent.</p>

  <p class="leadout">Finding 7 said <em>bring a verifier</em>; rounds 2, 3, and 4 priced every alternative
  we could buy &mdash; a simple trace judge with live money, a trained judge behind a locked gate, and
  agreement between independent samples. Three designs, three pre-registered failures, each for a different
  articulated reason: the simple judge under-fires, the trained judge learns the corpus instead of the
  model, and agreement is a perfect certificate that almost never certifies. The certificate is not an
  implementation detail of the router. It <em>is</em> the router &mdash; on families where answers are
  many. Where the answer is unique, the door round 4 left ajar swings open:
  <a href="consistency.html">finding 9</a>.</p>
</section>
"""
page("routing2.html", "Finding 8: No Referee — Difficulty–Response Curves", routing2_body,
     "Round 2: trace signals whisper offline (one model of three), lose a live routing race to random escalation, and teach a peeking lesson.")

# ---------------------------------------------------------------- consistency --
CG = json.loads((ROOT / "analysis" / "consistency-synth-gate.json").read_text())
R3J = json.loads((ROOT / "analysis" / "routing3.json").read_text())["live_consistency"]

def live3_rows() -> str:
    label = {"always_cheap": "always cheap (R1@deepinfra)", "always_premium": "always premium (GPT-5.5)",
             "consistency_router": "consistency router (ask twice)", "quota_random": "random escalation (same quota)"}
    return "".join(
        f"<tr><td>{label[k]}</td><td class=\"num\">{v['solved']}</td>"
        f"<td class=\"num\">${v['cost_per_solved_usd']}</td><td class=\"num\">{v['n_escalated']}</td></tr>"
        for k, v in R3J["results"].items())

_c9 = R3J["results"]["consistency_router"]
_r9 = R3J["results"]["quota_random"]
_recs9 = [r for r in R3J["records"] if r["arm"] == "consistency_router"]
_ship9 = [r for r in _recs9 if not r["escalated"]]

consistency_body = compact_head("Finding 9 · Ask the model twice", "consistency.html") + f"""
<section class="signal" id="f9">
  <p class="plain">Round 4 ended on a door left ajar: agreement between two samples never once vouched for
  a wrong answer, but on SAT &mdash; where many assignments are correct &mdash; right answers disagree too,
  and the economics die. The synthesis family has <em>unique</em> answers: two programs either compute the
  same function on probe inputs or they don't. Round 5 walked through the door with the same rules as every
  round before it &mdash; pre-registration first, stopping rule included, live money only behind a gate.</p>

  <h3 class="disp" style="margin-top:26px">The gate that finally passed</h3>
  <p>Fresh corpus (120 calls, D&nbsp;1&ndash;3, committed hypotheses before it existed): flag a call when its
  partner sample's program disagrees on eight seeded probe inputs. Bar: recall &ge; 0.9 and false alarm
  &le; 0.25, one look.</p>
  <div class="card"><table>
    <thead><tr><th>recall</th><th>false alarm</th><th>AUC</th><th>escalation share</th><th>corpus</th></tr></thead>
    <tbody><tr><td class="num">{CG['recall']:.2f}</td><td class="num">{CG['fpr']:.2f}</td>
    <td class="num">{CG['auc_reported']:.2f}</td><td class="num">{int(CG['escalation_rate']*100)}%</td>
    <td class="num">{CG['n_right']} right / {CG['n_wrong']} wrong</td></tr></tbody>
  </table></div>
  <p>First gate of the campaign to survive its one look. The declared hazard &mdash; a correct answer
  flagged because its <em>partner</em> missed &mdash; stayed contained ({int(CG['fpr']*100)}% false alarms)
  because the cheap rung's home turf passes at 96%.</p>

  <h3 class="disp" style="margin-top:26px">The live race (fresh instances, real spend)</h3>
  <div class="card"><table>
    <thead><tr><th>policy</th><th>solved</th><th>$/solved</th><th>escalated</th></tr></thead>
    <tbody>{live3_rows()}</tbody>
  </table></div>
  <p>Three facts, in order of importance. <strong>One: the certificate never lied live</strong> &mdash;
  all {len(_ship9)} answers shipped on agreement were correct, replicating the perfect precision of
  round 4 and the gate. <strong>Two: the signal's marginal value is now causally clean</strong> &mdash;
  the control escalated <em>exactly</em> the same number of instances ({_r9['n_escalated']}, quota-matched
  by draw, the fix for round 2's flawed control) and solved {_r9['solved']} to the router's
  {_c9['solved']}: six extra solves are attributable to <em>where</em> the disagreement signal pointed,
  not to how much was spent. <strong>Three: the economics are mix-dependent, reported without spin</strong>
  &mdash; the router tied always-premium's solve rate ({_c9['solved']}) but paid
  \\${_c9['cost_per_solved_usd']} per solve against premium's
  \\${R3J['results']['always_premium']['cost_per_solved_usd']}, because this instance mix was deliberately
  frontier-heavy: 20 of 25 puzzles sat beyond the cheap rung, so the double-probe was overhead on most of
  them. The pre-registered stretch bar (beat premium outright) was therefore missed; the primary bar
  (beat the matched control) was cleared by six solves. On a workload where the cheap rung's home turf is
  the majority &mdash; most real workloads &mdash; the skip-rate arithmetic flips.</p>

  <h3 class="disp" style="margin-top:26px">Honest edges</h3>
  <p>One cheap rung (R1), one family (synthesis), one mix. The closer's own frontier caps every arm near
  0.68 here &mdash; ten of eighteen escalations converted, and no router fixes the closer. The live run
  overshot its $25 cap to $28.67 on in-flight calls; recorded as spent. And the signal costs a second
  cheap call on every instance &mdash; it is a toll, not a trick.</p>

  <p class="leadout">Four rounds of <em>no</em> bought one conditioned <em>yes</em>: where answers are
  unique, two cheap samples grade each other &mdash; perfectly, in every dataset this campaign produced
  &mdash; and route six solves past a coin at equal spend. The certificate is still the router; it turns
  out you can sometimes mint one from agreement.</p>
</section>
"""
page("consistency.html", "Finding 9: Ask the Model Twice — Difficulty–Response Curves", consistency_body,
     "Round 5: functional agreement between two cheap samples — perfect precision live, +6 solves over a quota-matched control, economics that depend on the mix.")

# ---------------------------------------------------------------- journal --
J = [
 ("4 July, afternoon", "The brief lands: measure where reasoning models break, publish everything, one commit, $300 cap. Probes find the gateway speaks two APIs; a pilot roster of eight models is chosen. The plan prices the textbook protocol; the pilot will price reality."),
 ("4 July, evening", "Pilot runs into a declared router-core outage mid-flight; the resumable store shrugs. Gate 1 arithmetic: the textbook design would cost ~$530 &mdash; roster rescoped (Haiku promoted to core; Qwen and GLM to budget extras). MiniMax passes <em>everything</em> on the standard dial and is moved to an extended one."),
 ("4 July, night", "The throughput wars: one provider serves ~3 calls an hour; pins are switched (novita &rarr; parasail/cerebras/baseten); 1,446 calls die at a mysterious 4,096-token wall on baseten and are purged. At $97.56 the gateway account runs dry mid-campaign. Everything pauses, resumably."),
 ("5 July, morning", "Credits topped up; sweeps resume; the session hosting the runs crashes twice and the jobs are re-launched detached, out of its reach. Haiku and o4-mini finish their full designs including fresh-instance retests."),
 ("5 July, midday", "The check family embarrasses everyone: 480/480 on arithmetic to 42 steps; the grid is extended twice before Haiku finally cracks past ~300 steps. The adaptive probe proves itself live: Haiku's frontier in 20 calls for $1.03."),
 ("5 July, 18:00", "Data cutoff. Full statistics (B=2000), four figures, paper compiled with the abstract reading its numbers from disk; site and repo published as one commit: split-half r = 0.99, 81% within-instance variance at the frontier, effort peak lagging it, 6.75&times; adaptive efficiency."),
 ("5 July, evening", "Late entries: GPT-5.5 runs off the end of both tracks (censored &gt; 7.2). Fable 5 looks <em>broken</em> &mdash; until a differential probe through a second router convicts the gateway: it silently drops <span class=\"mono\">max_completion_tokens</span> and replies default to 4,096 tokens. Baseten exonerated (same bug). Fable re-measured fairly: 6.34 &plusmn; 0.21. A validation fleet re-checks every row: four agree; gpt-oss-20b has <em>drifted</em> a full dial unit on the same endpoint in twelve hours."),
 ("6 July, morning", "The correction that earned its keep: Fable's 6.34 replicates perfectly on fresh puzzles (6.33) and is then falsified by direct test &mdash; 10/10 at &alpha; = 7.2; both runs had extrapolated past the track edge. Corrected verdict: censored, joint top with GPT-5.5. Precision is not truth."),
 ("6 July, midday", "The n=50 separator: GPT-5.5 13/21 with zero truncations; Fable 11/40, out-thinking even 64k budgets (but more accurate when it finishes); MiniMax 0/17. Fixing the parameter bug had silently re-run MiniMax's measurement at an enforced cap: frontier 6.58 uncapped &rarr; &asymp;3.6 at 32k. Budget elasticity becomes finding 3's second half: a frontier is a curve against the thinking budget."),
 ("6 July, afternoon", "The vendor credits $20 and reports the bug fixed; the same probe says otherwise: still 4,096, still empty. Raw data moves onto the page itself. The trace ledger is computed: billed thinking vs delivered text, by model and route &mdash; OpenAI withholds everywhere, open-weights gpt-oss stripped by every serving stack, Claude's trace depends entirely on the door. Where traces flow, loops mark the cliff better than length."),
 ("6 July, late", "The practical turn: can the card drive a router? Offline replay over shared instances says yes, with two folklore-violating rules &mdash; retries beat escalation, and premium &ne; stronger. A LiteLLM integration ships; a live validation runs on fresh puzzles; MiniMax's n=50 failure hunt continues. The document you are reading reorganised itself twice in the meantime."),
 ("6 July, evening", "Both verdicts land. MiniMax's n=50 hunt dies of timeout &mdash; through a ten-minute read window nothing ships &mdash; then a thirty-minute window delivers the answer: 3/12 at the easy end, frontier at or below &alpha;&nbsp;3. And the router meets 25 never-seen puzzles for real: cheap-always solves 12/25, premium-always 9/25 (at 19&times; the price per solve), the form-guide router <strong>24/25</strong> for $4.45 &mdash; escalating only where the card says the cheap horse falls. An accidental duplicate run re-measured the single-model legs at 10/25 and 6/25: the mist, live. Total cost of knowing all this: about $332 across two gateways &mdash; $306 on the recorded ledgers, the rest off-book: duplicate legs from a session collision and calls the meters never saw complete."),
 ("7 July", "The vendor's second attempt: another $20 credit, another claimed fix &mdash; and this one is real. The differential probe that convicted the gateway twice now clears it: 7,217 and 10,855 billed tokens through the once-immovable 4,096 wall, natural stops, delivered answers, and two scored passes on fresh instances at &alpha; 5.0 and 5.6. Fable 5 is measurable through the front door at last. The moral survives the fix: don't trust a gateway's word about its own plumbing &mdash; the probe costs $0.94."),
 ("7 July, evening", "Round 2 opens on the question finding 7 left loaded: can the trace replace the verifier? Hypotheses pre-registered before the data existed (primary <span class=\"mono\">hedge_tail</span>, gate AUC &ge; 0.65 on 2 of 3 models), a purpose-built batch of frontier calls launched &mdash; and the first save of the night lands within the hour: the second gateway delivers reasoning in a separate field the runner was silently discarding. $7 of gate calls had banked answers with no traces. One fix, every lane bounced, and from then on every call carries its evidence."),
 ("7 July, night", "The gate wobbles &mdash; and the wobble is the story: R1's hedging crosses 0.65, dips to 0.648 at 440 pairs, recovers to 0.68; at the interim 2-of-3 read the gate is called <em>passed</em> and the live arm funded. (Hold that thought until dawn.) MiniMax's backtracking firms to 0.81 on a fresh-seed top-up. Two textures, not one signal &mdash; R1 hedges when wrong, MiniMax rambles. Meanwhile the transfer family earns its keep the hard way: design one (transcribe forty rules into code) is flat &mdash; R1 58/60; design two (induce hidden rules from eight examples) fails all its hidden tests <em>while fitting every example</em> &mdash; ambiguity, not difficulty; design three (deterministic rules, twelve examples) finally slopes, and paired pilots certify a routable band: the cheap rung 0/11 at depths 2&ndash;5, the closer 7/8 in exactly that band. GPT-5.5's real prices are caught wrong in the fleet file ($1.25 vs $5.50 per million in) before they could poison a single $/solve figure."),
 ("8 July, dawn", "The live race answers everything, mostly with a no. GPT-5.5 saturates SAT 20/20 &mdash; the pre-registered bar (beat both single arms) is unreachable against perfection. On synthesis the closer is honestly fallible (13/20) and the bar is live &mdash; and the trace-judged router still misses it: 10/20, at a worse price per solve than always-buying-premium, because the judge fires precisely but rarely (live recall &asymp; 0.21) and, at the closer's own frontier, fires on the closer too &mdash; expensive retries that convert nothing. The kicker, reported per the house rules: the signal-free random-escalation control beat the judge on <em>both</em> families. Then the last witness reports: Qwen's completed lane is flat &mdash; nothing in its trace separates wrong from right &mdash; and R1's hedging settles at 0.615, <em>under</em> the bar it danced around all night. The evening's 2-of-3 gate call, on complete data, walks back to 1-of-3: the pre-registration fixed the bar but not the stopping rule, and sequential peeking did what it always does. Offline whisper, live silence, and a methods bruise &mdash; all three published. The certificate is not an implementation detail of the router; it is the router. Round 2's whole interrogation: about $75."),
 ("8 July, morning", "Round 3, rescoped with the owner over coffee: the stronger judge. Per-model trained combos over sixteen trace features, selection and thresholds locked on the exploratory corpus only, and the pre-registration finally carries a stopping rule &mdash; one look at the frozen confirmatory set, ever. Training flatters as training does: R1 cross-validates at 0.81, MiniMax and Qwen post perfect 1.0s on eleven wrongs apiece (flagged as overfit-smell <em>before</em> the gate ran, in writing). The single permitted look: zero of three clear. R1's combo collapses to 0.56 &mdash; it had learnt the corpus, not the model; Qwen's perfection was noise; MiniMax posts a genuinely excellent 0.93 at 92% recall and still clips the false-alarm bar. No live dollar spent. Two rounds, two designs, one verdict: the trace cannot grade itself into a router. The door gets a trained-judge stamp on its way shut."),
 ("8 July, midday", "Round 4, the last signal standing: ask the model twice. Finding 1's mist says near-frontier answers are coin flips, and coin flips should disagree &mdash; so sample the cheap rung twice and escalate on disagreement. Pre-registered (hazard included, in writing: satisfiable SAT admits many right answers), one look at the frozen corpus: recall a perfect 1.000 on all three models &mdash; every silent wrong disagreed &mdash; and P(correct given agreement) also a perfect 1.000: exact agreement never shipped a wrong answer. A flawless certificate. That fires on 2&ndash;20% of calls, because right answers pick different satisfying assignments too: false alarms 76&ndash;94%, escalate-everything economics, gate failed 0-of-3 on the arm the hazard named. Three rounds, three pre-registered negatives, three different reasons. The campaign's verdict stands at a sentence: the certificate is not an implementation detail of the router &mdash; it is the router. Spend for rounds 3 and 4 combined: $0."),
 ("8 July, night", "Round 5 walks through round 4's ajar door: on the synthesis family answers are unique, so agreement means two programs computing the same function on probe inputs &mdash; multiplicity can't tax it. A fresh 120-call gate corpus (pre-registered, stopping rule included, hazard named: your correct answer gets flagged when your <em>partner</em> misses) delivers the campaign's first gate PASS on its one look: recall 0.92, false alarm 0.163, AUC 0.822. The live race runs into the small hours: the router ships 7 answers on agreement &mdash; all 7 correct, the certificate still has never lied &mdash; and solves 17/25, six clear of a control that escalated the <em>exact same number</em> of instances by coin flip (round 2's control flaw, fixed and avenged). The spin-free ledger: it ties always-premium's solve rate but pays $0.69 a solve to premium's $0.50, because this mix was deliberately frontier-heavy and the double-probe is a toll on every instance. Four rounds of no, one conditioned yes: where answers are unique, two cheap samples grade each other. Finding 9 goes up before dawn."),
 ("12 July", "The confidence programme becomes a control programme. The question: instead of waiting for a trace score, use persistent backtracking, hedging, give-up, and repetition to launch backup models while the primary is still thinking. The distinction from a model council is fixed in writing: a council waits to combine completed answers; the speculative controller races candidates, accepts only an externally verified winner, cancels losers, and invokes a council judge only as an exception. The implementation expands to all four registered arms, deterministic ordering, durable result validation, isolated Git worktrees, and explicit unknown usage for cancelled calls. Then the zero-spend gate answers with another useful no: 84 of 89 visible traces trigger, including every failure but also 34 of 39 correct calls. At 87.2% false hedges the trace controller is an always-on council wearing a sensor; a matched-rate timer also catches every failure. Old traces have no chunk timestamps, so warning time is censored. The false-hedge bar already fails; the paid branch stops at $0."),
]
entries = "".join(
    f"""<div class="jentry"><div class="jdate">{d}</div><div class="jbody"><p>{t}</p></div></div>"""
    for d, t in J)
journal_body = compact_head("The journal: how it actually went", "journal.html") + f"""
<section class="signal">
  <p class="plain">A form guide is tidy; fieldwork is not. This is the campaign as it happened &mdash; the
  outages, the convictions, the corrections kept in the text &mdash; because on a working-notes site the
  <em>process is evidence</em>: every number above survived this.</p>
  <div class="journal">{entries}</div>
  <p class="card-note">Spend to date: ledgers in <a href="index.html#data">the raw data</a>. Round 1:
  gateway account ~$258 of a $300 cap (including the vendor's $20 credit); second-router spend ~$75 for
  diagnostics, duels, and the failure hunts. Round 2 (the verifier-free interrogation,
  <a href="routing2.html">finding 8</a>): ~$70 of a fresh $300 cap &mdash; $38 on the offline gate and
  dial pilots, $27 on the live four-arm race, the rest on delivery probes.</p>
</section>
"""
page("journal.html", "Journal — Difficulty–Response Curves", journal_body,
     "The campaign chronicle: outages, convictions, corrections, and costs, dated.")
