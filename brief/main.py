"""Point d'entrée : python -m brief.main [--force] [--no-commentary]

1. vérifie que c'est le bon moment (heure de Paris, jour ouvré, pas déjà fait aujourd'hui) ;
2. télécharge les données et met à jour l'historique (data/history) ;
3. calcule indicateurs, courbes, banques centrales, inflation ;
4. demande le commentaire à Claude ;
5. écrit le site (site/) et prépare la notification.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import build, commentary
from .gate import decide
from .render import _plain, write_site
from .store import Store
from .util import Http, log, now_paris, previous_business_day, setup_logging

ROOT = Path(__file__).resolve().parent.parent

HOLIDAYS_FR = {
    "New Year's Day": "Jour de l'an", "Good Friday": "Vendredi saint", "Easter Monday": "lundi de Pâques",
    "Labour Day": "fête du Travail", "Christmas Day": "Noël", "Christmas Holiday": "lendemain de Noël",
    "Martin Luther King Jr. Day": "Martin Luther King Day", "Washington's Birthday": "Presidents' Day",
    "Memorial Day": "Memorial Day", "Juneteenth National Independence Day": "Juneteenth",
    "Independence Day": "fête nationale américaine", "Independence Day (observed)": "fête nationale américaine",
    "Labor Day": "Labor Day", "Thanksgiving Day": "Thanksgiving",
}


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def gh_output(**kw) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    for k, v in kw.items():
        log.info("sortie %s=%s", k, v)
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"{k}={v}\n")


def fmt_level(ind: dict, v: float) -> str:
    u = ind["unit"]
    if u == "%":
        return build.fr_num(v, ind["decimals"]) + " %"
    if u == "bp":
        return build.fr_num(v, 0) + " bp"
    if u == "$":
        return build.fr_num(v, ind["decimals"]) + " $"
    return build.fr_num(v, ind["decimals"])


def fmt_change(ind: dict, c: float | None) -> str:
    if c is None:
        return "n.d."
    if ind["change_mode"] == "bp":
        return build.fr_signed(round(c), 0) + " bp"
    return build.fr_signed(c, 2) + " %"


def commentary_payload(today: date, data_date: date, inds: dict, curves: dict, slope: dict, cb: dict,
                       infl: list, events: list, notices: list) -> dict:
    """Chiffres déjà formatés en français : Claude doit les recopier tels quels."""
    def month_change(ind):
        t, v = ind["series"]["t"], ind["series"]["v"]
        if len(t) < 2:
            return None
        end = date.fromisoformat(t[-1])
        target = end - timedelta(days=30)
        base = next((v[i] for i in range(len(t) - 1, -1, -1) if date.fromisoformat(t[i]) <= target), None)
        if base is None:
            return None
        return (v[-1] - base) * (1 if ind["unit"] == "bp" else 100) if ind["change_mode"] == "bp" else (v[-1] / base - 1) * 100

    rows = []
    for ind in inds.values():
        if not ind["last"]:
            rows.append({"indicateur": ind["label"], "statut": "indisponible"})
            continue
        rows.append({
            "indicateur": f"{ind['label']} ({ind['sub']})" if ind["sub"] else ind["label"],
            "niveau": fmt_level(ind, ind["last"]["value"]),
            "variation_seance": fmt_change(ind, ind["change"]),
            "variation_1_mois": fmt_change(ind, month_change(ind)),
            "date": ind["last"]["date"],
            "statut": {"ok": "à jour", "stale": "pas de nouvelle donnée pour la séance couverte",
                       "unavailable": "source indisponible : dernière valeur connue"}[ind["status"]],
        })
    courbes = {}
    for c in curves["countries"]:
        snaps = {s["key"]: s for s in c["snapshots"]}
        if "j" not in snaps:
            continue
        line = {"date": snaps["j"]["date"]}
        for i, m in enumerate(curves["maturities"]):
            v = snaps["j"]["values"][i]
            if v is None:
                continue
            item = {"niveau": build.fr_num(v, 2) + " %"}
            for k, lab in (("1s", "variation_1_semaine"), ("1m", "variation_1_mois"), ("1a", "variation_1_an")):
                old = snaps.get(k, {}).get("values", [None] * len(curves["maturities"]))[i]
                if old is not None:
                    item[lab] = build.fr_signed(round((v - old) * 100), 0) + " bp"
            line[m] = item
        sv = slope["series"].get(c["id"], {}).get("v", [])
        if sv:
            line["pente_10A_2A"] = build.fr_signed(round(sv[-1]), 0) + " bp"
        courbes[c["label"]] = line
    bc = {}
    for k in ("fed", "ecb"):
        b = cb.get(k, {})
        item = {"taux": "indisponible"}
        if k == "fed" and "lower" in b:
            item["taux"] = f"{build.fr_num(b['lower'], 2)}–{build.fr_num(b['upper'], 2)} %"
        if k == "ecb" and "value" in b:
            item["taux"] = build.fr_num(b["value"], 2) + " %"
        if b.get("last_change"):
            item["derniere_decision"] = f"{build.fr_signed(b['last_change']['bp'], 0)} bp le {b['last_change']['date']}"
        if b.get("next_meeting"):
            item["prochaine_reunion"] = b["next_meeting"]["label"]
        bc[b.get("label", k)] = item
    inflation = {}
    for reg in infl:
        for v in reg["views"]:
            if v["total"]["t"]:
                inflation[f"{reg['label']} {v['label']}"] = {
                    "mois": v["total"]["t"][-1], "totale": build.fr_num(v["total"]["v"][-1], 1) + " %",
                    "sous_jacente": build.fr_num(v["core"]["v"][-1], 1) + " %" if v["core"]["v"] else "n.d.",
                }
    return {
        "date_du_brief": build.fr_date(today), "seance_couverte": build.fr_date(data_date),
        "indicateurs": rows, "courbes_de_taux": courbes, "banques_centrales": bc, "inflation": inflation,
        "evenements_prevus_aujourd_hui_reperes": events, "avertissements": notices,
    }


def run(args) -> int:
    setup_logging()
    cfg = load_config(Path(args.config))
    state_path = ROOT / "data" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    now = now_paris()
    if args.date:
        now = datetime.fromisoformat(args.date).replace(hour=8, tzinfo=now.tzinfo)
    g = cfg["general"]
    ok, why = decide(now, str(g.get("heure_cible", "08:00")), int(g.get("avance_minutes", 50)), bool(g.get("en_pause")),
                     state.get("last_brief_date"), args.force)
    log.info("Décision : %s (%s)", "génération" if ok else "rien à faire", why)
    if not ok:
        gh_output(generated="false")
        return 0

    today = now.date()
    data_date = previous_business_day(today)
    closures = build.market_closures(data_date)
    http = Http()
    store = Store(ROOT / "data" / "history")
    fetched = build.download(cfg, store, http, today)

    cache: dict = {}
    shown = [i for g in cfg["groupes"] for i in g["indicateurs"] if i in cfg["indicateurs"]]
    inds = {i: build.build_indicator(i, cfg, fetched, cache, data_date) for i in shown}
    curves, slope = build.build_curves(cfg, fetched, data_date)
    cb = build.build_central_banks(cfg, fetched, data_date, today)
    infl = build.build_inflation(cfg, fetched, today, http)
    events = build.scheduled_events(cfg, today, infl, cb)

    notices: list[str] = []
    eu, us = closures["europe"], closures["us"]
    status = "ok"
    if eu and us:
        status = "closed"
    elif eu:
        notices.append(f"Marchés européens fermés le {build.fr_date(data_date, False)} ({HOLIDAYS_FR.get(eu, eu)}).")
    elif us:
        notices.append(f"Marchés américains fermés le {build.fr_date(data_date, False)} ({HOLIDAYS_FR.get(us, us)}).")
    down = [ind["label"] for ind in inds.values() if ind["status"] == "unavailable"]
    if down:
        notices.append("Source indisponible ce matin pour : " + ", ".join(down) + " (dernière valeur connue affichée).")
        if status == "ok":
            status = "partial"
    if cb.get("fed", {}).get("status") == "unavailable":
        notices.append("Taux de la Fed indisponibles (source FRED).")
    if all(ind["status"] != "ok" for ind in inds.values()) and status != "closed":
        notices.append("Aucune nouvelle donnée pour la séance d'hier.")

    if status == "closed" or args.no_commentary:
        com = {"available": False, "error": "marchés fermés" if status == "closed" else "désactivé"}
    else:
        payload = commentary_payload(today, data_date, inds, curves, slope, cb, infl, events, notices)
        com = commentary.generate(cfg, payload, today, ROOT / "data" / "couts_claude.csv")

    essentiel = com.get("essentiel", []) if com.get("available") else []
    if status == "closed":
        hol = HOLIDAYS_FR.get(eu, eu)
        essentiel = [f"Marchés fermés le {build.fr_date(data_date, False)} ({hol}) : pas de nouvelles données ce matin."]

    data = {
        "meta": {
            "title": cfg["general"].get("titre", "Brief marchés"),
            "brief_date": today.isoformat(), "data_date": data_date.isoformat(),
            "generated_at": now_paris().isoformat(timespec="seconds"),
            "status": status, "notices": notices, "demo": False,
            "default_range": cfg["general"].get("periode_defaut", "3M"),
        },
        "essentiel": essentiel,
        "groups": [{"title": g["titre"], "ids": [i for i in g["indicateurs"] if i in inds]} for g in cfg["groupes"]],
        "indicators": inds, "curves": curves, "slope": slope, "central_banks": cb, "inflation": infl,
        "commentary": com,
        "footer_sources": [{"what": s["quoi"], "name": s["nom"], "url": s.get("url", "")} for s in cfg.get("sources_pied_de_page", [])],
    }
    site = Path(args.site)
    write_site(data, site, today, cfg["general"].get("titre_court", "Brief"))
    log.info("Site écrit dans %s", site)

    state.update({"last_brief_date": today.isoformat(), "last_data_date": data_date.isoformat(), "status": status})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    # Corps de la notification ntfy ; le workflow ajoute le topic (secret) et l'adresse de la page publiée.
    title = f"{cfg['general'].get('titre', 'Brief marchés')} · {build.fr_date(today)}"
    if status == "closed":
        notif = {"title": title, "message": essentiel[0], "tags": ["zzz"], "priority": 2,
                 "skip": not cfg["general"].get("notifier_jours_fermes", True)}
    else:
        msg = " ".join(_plain(s) for s in essentiel[:2])
        if not msg:
            parts = [f"{ind['label']} {fmt_level(ind, ind['last']['value'])} ({fmt_change(ind, ind['change'])})"
                     for ind in list(inds.values())[:4] if ind["last"]]
            msg = " · ".join(parts)
        if notices:
            msg += "\n⚠ " + notices[0]
        notif = {"title": title, "message": msg, "tags": ["chart_with_upwards_trend"], "priority": 3}
    Path(args.notification).write_text(json.dumps(notif, ensure_ascii=False), encoding="utf-8")
    gh_output(generated="true", status=status)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Génère le brief marchés du jour")
    p.add_argument("--force", action="store_true", help="génère même si ce n'est pas l'heure ou si c'est déjà fait")
    p.add_argument("--no-commentary", action="store_true", help="n'appelle pas Claude")
    p.add_argument("--config", default=str(ROOT / "config.yaml"))
    p.add_argument("--site", default=str(ROOT / "site"))
    p.add_argument("--notification", default=str(ROOT / "notification.json"))
    p.add_argument("--date", help="(tests) simule une autre date, format AAAA-MM-JJ")
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
