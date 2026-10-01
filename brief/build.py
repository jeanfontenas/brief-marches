"""Assemble les données de la page : indicateurs, courbes, banques centrales, inflation."""
from __future__ import annotations

import calendar
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

import holidays

from .sources import fetch_all, fetch_eurostat_flash_dates, spec_key
from .store import Series, Store
from .util import Http, log

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def fr_date(d: date, weekday: bool = True) -> str:
    day = "1er" if d.day == 1 else str(d.day)
    return (f"{JOURS[d.weekday()]} " if weekday else "") + f"{day} {MOIS[d.month - 1]} {d.year}"


def fr_num(v: float, dec: int) -> str:
    s = f"{abs(v):,.{dec}f}".replace(",", " ").replace(".", ",")
    return ("−" if v < 0 and any(c in s for c in "123456789") else "") + s


def fr_signed(v: float, dec: int) -> str:
    s = fr_num(abs(v), dec)
    return s if not any(c in s for c in "123456789") else ("+" if v > 0 else "−") + s


def value_at(s: Series, d: date, max_gap_days: int = 6) -> tuple[date, float] | None:
    """Dernière valeur à la date d ou avant (dans une limite de max_gap_days)."""
    if not s:
        return None
    i = bisect_right(s, (d, float("inf"))) - 1
    if i < 0 or (d - s[i][0]).days > max_gap_days:
        return None
    return s[i]


def thin(s: Series, end: date, years: int) -> dict:
    """Quotidien sur 13 mois, hebdomadaire au-delà : allège la page sans perdre l'allure."""
    start = end - timedelta(days=365 * years + 7)
    cut = end - timedelta(days=400)
    t, v, last_week = [], [], None
    s = [(d, x) for d, x in s if start <= d <= end]
    for i, (d, x) in enumerate(s):
        wk = d.isocalendar()[:2]
        is_last_of_week = i + 1 == len(s) or s[i + 1][0].isocalendar()[:2] != wk
        if d >= cut or is_last_of_week:
            if d < cut and wk == last_week:
                continue
            t.append(d.isoformat())
            v.append(round(x, 4))
            last_week = wk
    return {"t": t, "v": v}


@dataclass
class Fetched:
    series: dict[str, Series] = field(default_factory=dict)   # historique complet après fusion
    ok: set[str] = field(default_factory=set)                  # clés téléchargées avec succès ce matin
    errors: dict[str, str] = field(default_factory=dict)


def collect_specs(cfg: dict) -> list[dict]:
    specs: list[dict] = []
    used = set()
    for g in cfg["groupes"]:
        used.update(g["indicateurs"])
    inds = cfg["indicateurs"]
    stack = list(used)
    while stack:  # dépendances des indicateurs calculés
        i = stack.pop()
        calc = inds.get(i, {}).get("calcul")
        if calc:
            for dep in calc["difference"]:
                if dep not in used:
                    used.add(dep)
                    stack.append(dep)
    for i in used:
        specs.extend(inds.get(i, {}).get("sources", []))
    for c in cfg["courbes"]["pays"].values():
        specs.extend(c["points"].values())
    cb = cfg["banques_centrales"]
    specs += [cb["fed"]["bas"], cb["fed"]["haut"], cb["bce"]["taux"]]
    for reg in cfg["inflation"]:
        for m in reg["mesures"]:
            specs += [m["totale"], m["sous_jacente"]]
    return specs


def download(cfg: dict, store: Store, http: Http, today: date) -> Fetched:
    specs = collect_specs(cfg)
    years = int(cfg["general"].get("historique_ans", 5))
    since = {spec_key(s): store.since(spec_key(s), today, years) for s in specs}
    data, errors = fetch_all(http, specs, since, today)
    f = Fetched(errors=errors)
    for s in specs:
        k = spec_key(s)
        if k in data and data[k]:
            f.series[k] = store.merge(k, data[k])
            f.ok.add(k)
        else:
            f.series[k] = store.load(k)
            if k not in errors:
                errors[k] = "aucune donnée"
    for k, e in errors.items():
        log.warning("Source en échec %s : %s", k, e)
    return f


# ---------------------------------------------------------------- Indicateurs
def indicator_series(ind_id: str, cfg: dict, f: Fetched, cache: dict) -> tuple[Series, bool, str]:
    """Renvoie (série, téléchargée_ce_matin, nom_de_source)."""
    if ind_id in cache:
        return cache[ind_id]
    ind = cfg["indicateurs"][ind_id]
    if "calcul" in ind:
        a_id, b_id = ind["calcul"]["difference"]
        fac = float(ind["calcul"].get("facteur", 1))
        a, a_ok, _ = indicator_series(a_id, cfg, f, cache)
        b, b_ok, _ = indicator_series(b_id, cfg, f, cache)
        bd = dict(b)
        s = [(d, (x - bd[d]) * fac) for d, x in a if d in bd]
        res = (s, a_ok and b_ok, "Calcul")
    else:
        best: tuple[Series, bool, str] | None = None
        for spec in ind["sources"]:
            k = spec_key(spec)
            s = f.series.get(k, [])
            cand = (s, k in f.ok, k.split(":")[0])
            if not s:
                continue
            if best is None or (cand[1] and not best[1]) or (cand[1] == best[1] and s[-1][0] > best[0][-1][0]):
                best = cand
        res = best or ([], False, "")
    cache[ind_id] = res
    return res


SOURCE_NAMES = {"yahoo": "Yahoo Finance", "treasury": "US Treasury", "treasury_reel": "US Treasury",
                "bundesbank": "Bundesbank", "bdf": "Banque de France", "bce": "BCE", "fred": "FRED",
                "Calcul": "Calcul"}


def build_indicator(ind_id: str, cfg: dict, f: Fetched, cache: dict, data_date: date) -> dict:
    ind = cfg["indicateurs"][ind_id]
    s, fetched, src = indicator_series(ind_id, cfg, f, cache)
    s = [(d, v) for d, v in s if d <= data_date]
    unit = ind.get("unite", "")
    out = {
        "id": ind_id, "label": ind["nom"], "sub": ind.get("sous_titre", ""), "unit": unit,
        "decimals": int(ind.get("decimales", 2)), "change_mode": ind.get("variation", "pct"),
        "help": ind.get("aide", ""), "source": {"name": SOURCE_NAMES.get(src, src), "url": ""},
        "status": "ok", "last": None, "prev": None, "change": None, "series": {"t": [], "v": []},
    }
    if not s:
        out["status"] = "unavailable"
        return out
    (d1, v1) = s[-1]
    out["last"] = {"date": d1.isoformat(), "value": round(v1, 6)}
    if len(s) >= 2:
        d0, v0 = s[-2]
        out["prev"] = {"date": d0.isoformat(), "value": round(v0, 6)}
        if out["change_mode"] == "bp":
            out["change"] = round((v1 - v0) * (1 if unit == "bp" else 100), 4)
        else:
            out["change"] = round((v1 / v0 - 1) * 100, 4) if v0 else None
    if not fetched:
        out["status"] = "unavailable"
    elif d1 < data_date:
        out["status"] = "stale"
    out["series"] = thin(s, d1, int(cfg["general"].get("historique_ans", 5)))
    return out


# ---------------------------------------------------------------- Courbes
def curve_series(cfg: dict, f: Fetched) -> dict[str, dict[str, Series]]:
    out = {}
    for cid, c in cfg["courbes"]["pays"].items():
        out[cid] = {m: f.series.get(spec_key(spec), []) for m, spec in c["points"].items()}
    return out


def build_curves(cfg: dict, f: Fetched, data_date: date) -> tuple[dict, dict]:
    mats = cfg["courbes"]["maturites"]
    cs = curve_series(cfg, f)
    countries = []
    for cid, c in cfg["courbes"]["pays"].items():
        pts = cs[cid]
        ref = pts.get("10A") or next((v for v in pts.values() if v), [])
        ref = [(d, v) for d, v in ref if d <= data_date]
        snaps, status = [], "ok"
        if not ref:
            status = "unavailable"
        else:
            last = ref[-1][0]
            targets = [("j", "Dernière", last), ("1s", "1 semaine", last - timedelta(days=7)),
                       ("1m", "1 mois", _minus_months(last, 1)), ("1a", "1 an", _minus_months(last, 12))]
            for key, label, td in targets:
                vals, d_used = [], None
                for m in mats:
                    hit = value_at(pts.get(m, []), td) if m in pts else None
                    vals.append(round(hit[1], 4) if hit else None)
                    if hit and m == "10A":
                        d_used = hit[0]
                if any(v is not None for v in vals):
                    snaps.append({"key": key, "label": label, "date": (d_used or td).isoformat(), "values": vals})
            keys_ok = [spec_key(s) in f.ok for s in c["points"].values()]
            if not all(keys_ok):
                status = "partial"
        countries.append({"id": cid, "label": c["nom"], "instrument": c.get("instrument", ""),
                          "source": {"name": c.get("source", ""), "url": ""}, "status": status, "snapshots": snaps})
    slope = {"help": cfg["courbes"].get("pente_aide", ""), "series": {}}
    for cid in cfg["courbes"]["pays"]:
        ten, two = dict(cs[cid].get("10A", [])), cs[cid].get("2A", [])
        start = data_date - timedelta(days=731)
        s = [(d, (ten[d] - v) * 100) for d, v in two if d in ten and start <= d <= data_date]
        slope["series"][cid] = {"t": [d.isoformat() for d, _ in s], "v": [round(x, 1) for _, x in s]}
    return {"maturities": mats, "help": cfg["courbes"].get("aide", ""), "countries": countries}, slope


def _minus_months(d: date, n: int) -> date:
    y, m = d.year, d.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


# ---------------------------------------------------------------- Banques centrales
def _changes(s: Series) -> Series:
    """Ne garde que les points où le taux change (plus le premier et le dernier)."""
    out: Series = []
    for d, v in s:
        if not out or abs(v - out[-1][1]) > 1e-9:
            out.append((d, v))
    if s and out[-1][0] != s[-1][0]:
        out.append(s[-1])
    return out


def _meeting_label(d: date) -> str:
    first = d - timedelta(days=1)
    if first.month == d.month:
        return f"{first.day}-{d.day} {MOIS[d.month - 1]} {d.year}"
    return f"{first.day} {MOIS[first.month - 1]}-{d.day} {MOIS[d.month - 1]} {d.year}"


def _next_meeting(dates: list[str], today: date) -> dict | None:
    for s in sorted(dates):
        d = date.fromisoformat(s)
        if d >= today:
            return {"date": d.isoformat(), "label": _meeting_label(d) + (" (décision aujourd'hui)" if d == today else "")}
    return None


def build_central_banks(cfg: dict, f: Fetched, data_date: date, today: date) -> dict:
    cb = cfg["banques_centrales"]
    years_ago = data_date - timedelta(days=365 * 5 + 7)
    out: dict = {"help": cb.get("aide", "")}
    fed, ecb = cb["fed"], cb["bce"]
    lo = [(d, v) for d, v in f.series.get(spec_key(fed["bas"]), []) if d <= data_date]
    hi = [(d, v) for d, v in f.series.get(spec_key(fed["haut"]), []) if d <= data_date]
    if lo and hi:
        his = dict(hi)
        ch = _changes([(d, v) for d, v in lo if d in his])
        last_change = next((ch[i] for i in range(len(ch) - 1, 0, -1) if abs(ch[i][1] - ch[i - 1][1]) > 1e-9), None)
        prev_val = None
        if last_change:
            i = ch.index(last_change)
            prev_val = ch[i - 1][1]
        pts = [(d, v) for d, v in ch if d >= years_ago]
        if ch and (not pts or pts[0][0] > years_ago):
            before = [p for p in ch if p[0] < years_ago]
            if before:
                pts.insert(0, (years_ago, before[-1][1]))
        out["fed"] = {
            "label": fed["nom"], "name": fed["libelle"], "lower": lo[-1][1], "upper": his[lo[-1][0]],
            "last_change": ({"date": last_change[0].isoformat(), "bp": round((last_change[1] - prev_val) * 100)}
                            if last_change else None),
            "next_meeting": _next_meeting(fed["reunions"], today),
            "series": {"t": [d.isoformat() for d, _ in pts], "lower": [v for _, v in pts],
                       "upper": [his.get(d, v + 0.25) for d, v in pts]},
            "status": "ok" if spec_key(fed["bas"]) in f.ok else "unavailable",
        }
    else:
        out["fed"] = {"label": fed["nom"], "name": fed["libelle"], "status": "unavailable",
                      "next_meeting": _next_meeting(fed["reunions"], today)}
    e = [(d, v) for d, v in f.series.get(spec_key(ecb["taux"]), []) if d <= data_date]
    if e:
        ch = _changes(e)
        last_change = next((i for i in range(len(ch) - 1, 0, -1) if abs(ch[i][1] - ch[i - 1][1]) > 1e-9), None)
        pts = [(d, v) for d, v in ch if d >= years_ago]
        before = [p for p in ch if p[0] < years_ago]
        if before:
            pts.insert(0, (years_ago, before[-1][1]))
        out["ecb"] = {
            "label": ecb["nom"], "name": ecb["libelle"], "value": e[-1][1],
            "last_change": ({"date": ch[last_change][0].isoformat(),
                             "bp": round((ch[last_change][1] - ch[last_change - 1][1]) * 100)} if last_change else None),
            "next_meeting": _next_meeting(ecb["reunions"], today),
            "series": {"t": [d.isoformat() for d, _ in pts], "v": [v for _, v in pts]},
            "status": "ok" if spec_key(ecb["taux"]) in f.ok else "unavailable",
        }
    else:
        out["ecb"] = {"label": ecb["nom"], "name": ecb["libelle"], "status": "unavailable",
                      "next_meeting": _next_meeting(ecb["reunions"], today)}
    return out


# ---------------------------------------------------------------- Inflation
def _monthly(s: Series, yoy: bool) -> list[tuple[str, float]]:
    by_month = {(d.year, d.month): v for d, v in s}
    out = []
    for (y, m), v in sorted(by_month.items()):
        if yoy:
            base = by_month.get((y - 1, m))
            if not base:
                continue
            v = (v / base - 1) * 100
        out.append((f"{y:04d}-{m:02d}", round(v, 1)))
    return out


def _last_business_day(y: int, m: int) -> date:
    d = date(y, m, calendar.monthrange(y, m)[1])
    fr = holidays.country_holidays("FR", years=y)
    while d.weekday() >= 5 or d in fr:
        d -= timedelta(days=1)
    return d


def _next_release(pub: dict | list | None, label: str, today: date, http: Http | None) -> dict | None:
    if pub is None:
        return None
    if isinstance(pub, list):
        dates = sorted(date.fromisoformat(x) for x in pub)
        nxt = next((d for d in dates if d >= today), None)
        return {"date": nxt.isoformat(), "label": label} if nxt else {"date": None, "label": "date à compléter dans config.yaml"}
    auto = pub.get("automatique")
    label = pub.get("libelle", label)
    listed = sorted(date.fromisoformat(x) for x in pub.get("dates", []))
    nxt = next((d for d in listed if d >= today), None)
    if nxt:
        return {"date": nxt.isoformat(), "label": label}
    if auto == "eurostat_flash" and http is not None:
        try:
            nxt = next((d for d in fetch_eurostat_flash_dates(http) if d >= today), None)
            if nxt:
                return {"date": nxt.isoformat(), "label": label}
        except Exception as e:  # noqa: BLE001
            log.warning("Calendrier Eurostat indisponible : %s", e)
    if auto in ("insee_fin_de_mois", "eurostat_flash"):
        d = _last_business_day(today.year, today.month)
        if d < today:
            y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            d = _last_business_day(y, m)
        return {"date": d.isoformat(), "label": label + " (date estimée)"}
    return None


def build_inflation(cfg: dict, f: Fetched, today: date, http: Http | None) -> list[dict]:
    out = []
    start = f"{today.year - 3:04d}-{today.month:02d}"
    for reg in cfg["inflation"]:
        views = []
        for m in reg["mesures"]:
            view = {"key": m["nom"].lower(), "label": m["nom"]}
            ok = True
            for part in ("totale", "sous_jacente"):
                spec = m[part]
                s = _monthly(f.series.get(spec_key(spec), []), bool(spec.get("glissement_annuel")))
                s = [(t, v) for t, v in s if t >= start]
                view["total" if part == "totale" else "core"] = {"t": [t for t, _ in s], "v": [v for _, v in s]}
                ok = ok and spec_key(spec) in f.ok
            view["status"] = "ok" if ok else "unavailable"
            if "publications" in m:
                view["next_release"] = _next_release(m["publications"], m.get("libelle", m["nom"]), today, http)
            views.append(view)
        item = {"id": reg["id"], "label": reg["nom"], "help": reg.get("aide", ""),
                "source": {"name": reg.get("source", ""), "url": ""}, "views": views}
        if "publications" in reg:
            item["next_release"] = _next_release(reg["publications"], "", today, http)
        out.append(item)
    return out


# ---------------------------------------------------------------- Calendrier des marchés
def market_closures(d: date) -> dict:
    eu = holidays.financial_holidays("ECB", years=d.year)   # jours de fermeture TARGET ≈ Euronext
    us = holidays.financial_holidays("NYSE", years=d.year)
    return {"europe": eu.get(d), "us": us.get(d)}


def aft_auctions(today: date) -> list[str]:
    """Règle indicative des adjudications de l'AFT (calendrier officiel : aft.gouv.fr)."""
    out = []
    if today.weekday() == 0:
        out.append("Adjudication de BTF (AFT), 14 h 50 (règle indicative)")
    if today.weekday() == 3:
        nth = (today.day - 1) // 7 + 1
        if nth == 1 and today.month != 8:
            out.append("Adjudication d'OAT à long terme (AFT), 10 h 50 (règle indicative)")
        if nth == 3 and today.month not in (8, 12):
            out.append("Adjudications d'OAT à moyen terme (10 h 50) et d'OAT indexées (11 h 50) (AFT, règle indicative)")
    return out


def scheduled_events(cfg: dict, today: date, infl: list[dict], cb: dict) -> list[str]:
    ev = []
    for key in ("fed", "ecb"):
        nm = cb.get(key, {}).get("next_meeting")
        if nm and nm.get("date") == today.isoformat():
            ev.append(f"Décision de politique monétaire : {cb[key]['label']} (aujourd'hui)")
    for reg in infl:
        for item in [reg.get("next_release")] + [v.get("next_release") for v in reg["views"]]:
            if item and item.get("date") == today.isoformat():
                ev.append(f"Inflation {reg['label']} : {item['label']}")
    if cfg.get("agenda", {}).get("adjudications_aft"):
        ev += aft_auctions(today)
    return ev
