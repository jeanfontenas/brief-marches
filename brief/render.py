"""Assemble la page HTML à partir du gabarit et des données JSON, et écrit le site."""
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "page.html"
STATIC = ROOT / "static"
CHARTJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.5.1/chart.umd.min.js"

HEAD_EXTRA = """<meta name="description" content="Brief quotidien des marchés de taux, actions, pétrole et change.">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f3f5f8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0b0e13" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{short}">
<link rel="apple-touch-icon" href="{base}apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="192x192" href="{base}icon-192.png">
<link rel="manifest" href="{base}manifest.webmanifest">"""


def _json_for_script(data: dict) -> str:
    # « < » encodé : impossible de fermer la balise <script> depuis les données.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_page(data: dict, *, base: str = "", short_title: str = "Brief", chartjs_url: str = CHARTJS_URL,
                template: Path = TEMPLATE) -> str:
    """Page complète (GitHub Pages). `base` = préfixe relatif vers la racine du site ('' ou '../')."""
    tpl = template.read_text(encoding="utf-8")
    title = data.get("meta", {}).get("title", "Brief marchés")
    return (tpl.replace("<!--HEAD_EXTRA-->", HEAD_EXTRA.format(base=base, short=html.escape(short_title)))
               .replace("__TITLE__", html.escape(title))
               .replace("__CHARTJS_URL__", chartjs_url)
               .replace("__DATA__", _json_for_script(data)))


def fragment(page: str) -> str:
    """Version sans <html>/<head>/<body> (aperçu en Artifact)."""
    a = page.index("<!--FRAGMENT_START-->") + len("<!--FRAGMENT_START-->")
    b = page.index("<!--HEAD_END-->")
    c = page.index("<!--BODY_START-->") + len("<!--BODY_START-->")
    d = page.index("<!--FRAGMENT_END-->")
    return page[a:b].strip() + "\n" + page[c:d].strip() + "\n"


ARCHIVE_INDEX = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<link rel="apple-touch-icon" href="../apple-touch-icon.png">
<title>Archives · {title}</title>
<style>
:root {{ --bg:#f3f5f8; --surface:#fff; --ink:#111826; --ink-2:#465162; --line:#dde2e9; --accent:#1f56a4; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b0e13; --surface:#141920; --ink:#edf1f6; --ink-2:#b4bdca; --line:#262e39; --accent:#7eb0f2; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; line-height:1.45; }}
.wrap {{ max-width:720px; margin:0 auto; padding-inline:16px; padding-block:24px 48px; }}
h1 {{ font-family:Georgia,"Times New Roman",serif; font-weight:500; font-size:1.875rem; margin:8px 0 16px; }}
a {{ color:var(--accent); text-decoration:none; }}
ul {{ list-style:none; margin:0; padding:0; background:var(--surface); border:1px solid var(--line); border-radius:14px; }}
li {{ border-top:1px solid var(--line); }} li:first-child {{ border-top:0; }}
li a {{ display:block; padding:12px 16px; }}
li span {{ display:block; color:var(--ink-2); font-size:.875rem; margin-top:2px; }}
</style></head>
<body><div class="wrap"><a href="../">← Brief du jour</a><h1>Archives</h1><ul>
{items}
</ul></div></body></html>
"""


def write_site(data: dict, site: Path, brief_date: date, short_title: str) -> None:
    site.mkdir(parents=True, exist_ok=True)
    arch = site / "archives"
    arch.mkdir(exist_ok=True)
    if STATIC.exists():
        for f in STATIC.iterdir():
            if f.is_file():
                shutil.copy2(f, site / f.name)
    day = brief_date.isoformat()
    existing = sorted((p.stem for p in arch.glob("????-??-??.html") if p.stem != day), reverse=True)
    prev = existing[0] if existing else None

    page_data = json.loads(json.dumps(data))
    page_data["meta"]["archive_url"] = "archives/"
    page_data["meta"]["prev_url"] = f"archives/{prev}.html" if prev else ""
    (site / "index.html").write_text(render_page(page_data, base="", short_title=short_title), encoding="utf-8")

    page_data["meta"]["archive_url"] = "./"
    page_data["meta"]["prev_url"] = f"{prev}.html" if prev else ""
    (arch / f"{day}.html").write_text(render_page(page_data, base="../", short_title=short_title), encoding="utf-8")

    # Index des archives, avec la première phrase de l'essentiel de chaque jour.
    summaries = _load_summaries(arch)
    summaries[day] = (data.get("essentiel") or [""])[0]
    (arch / "summaries.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=0), encoding="utf-8")
    items = []
    for d in sorted(summaries, reverse=True):
        if not (arch / f"{d}.html").exists():
            continue
        label = _fr_long(date.fromisoformat(d))
        items.append(f'<li><a href="{d}.html">{html.escape(label)}<span>{html.escape(_plain(summaries[d]))}</span></a></li>')
    title = data.get("meta", {}).get("title", "Brief marchés")
    (arch / "index.html").write_text(ARCHIVE_INDEX.format(title=html.escape(title), items="\n".join(items)), encoding="utf-8")


def _load_summaries(arch: Path) -> dict:
    p = arch / "summaries.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def _plain(s: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s or "")


def _fr_long(d: date) -> str:
    from .build import fr_date
    s = fr_date(d)
    return s[0].upper() + s[1:]


if __name__ == "__main__":  # aperçu : python -m brief.render donnees.json sortie.html [--fragment]
    import sys
    src, dst = sys.argv[1], sys.argv[2]
    page = render_page(json.loads(Path(src).read_text(encoding="utf-8")))
    if "--fragment" in sys.argv:
        page = fragment(page)
    if "--local-chartjs" in sys.argv:
        page = page.replace(CHARTJS_URL, sys.argv[sys.argv.index("--local-chartjs") + 1])
    Path(dst).write_text(page, encoding="utf-8")
    print(f"écrit : {dst} ({len(page) // 1024} Ko)")
