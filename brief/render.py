"""Assemble la page HTML à partir du gabarit et des données JSON."""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "page.html"
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
    out = (tpl.replace("<!--HEAD_EXTRA-->", HEAD_EXTRA.format(base=base, short=html.escape(short_title)))
              .replace("__TITLE__", html.escape(title))
              .replace("__CHARTJS_URL__", chartjs_url)
              .replace("__DATA__", _json_for_script(data)))
    return out


def fragment(page: str) -> str:
    """Version sans <html>/<head>/<body> (aperçu en Artifact)."""
    a = page.index("<!--FRAGMENT_START-->") + len("<!--FRAGMENT_START-->")
    b = page.index("<!--HEAD_END-->")
    c = page.index("<!--BODY_START-->") + len("<!--BODY_START-->")
    d = page.index("<!--FRAGMENT_END-->")
    return page[a:b].strip() + "\n" + page[c:d].strip() + "\n"


if __name__ == "__main__":  # aperçu : python -m brief.render sample.json sortie.html [--fragment]
    import sys
    src, dst = sys.argv[1], sys.argv[2]
    page = render_page(json.loads(Path(src).read_text(encoding="utf-8")))
    if "--fragment" in sys.argv:
        page = fragment(page)
    if "--local-chartjs" in sys.argv:
        page = page.replace(CHARTJS_URL, sys.argv[sys.argv.index("--local-chartjs") + 1])
    Path(dst).write_text(page, encoding="utf-8")
    print(f"écrit : {dst} ({len(page) // 1024} Ko)")
