"""Téléchargement des séries, un fournisseur par fonction.

Chaque « spec » de config.yaml (ex. {fournisseur: yahoo, symbole: "^FCHI"}) a une clé
unique (ex. "yahoo:^FCHI") qui sert aussi de nom de fichier d'historique.
Toutes les fonctions renvoient {clé: [(date, valeur), ...]} et lèvent une exception
en cas d'échec : l'appelant garde alors la dernière valeur connue.
"""
from __future__ import annotations

import csv
import io
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .store import Series
from .util import Http, log

BUNDESBANK_KEY = "BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.{mat}.R.A.A._Z._Z.A"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
WEBSTAT = "https://webstat.banque-france.fr/api/explore/v2.1/catalog/datasets"


def spec_key(spec: dict) -> str:
    f = spec["fournisseur"]
    ident = {
        "yahoo": spec.get("symbole"),
        "treasury": spec.get("colonne"),
        "treasury_reel": spec.get("colonne"),
        "bundesbank": spec.get("maturite"),
        "bdf": spec.get("serie"),
        "bce": spec.get("cle"),
        "fred": spec.get("serie"),
    }.get(f)
    if not ident:
        raise ValueError(f"Source mal décrite dans config.yaml : {spec}")
    return f"{f}:{ident}"


def _num(s: str) -> float | None:
    s = (s or "").strip()
    if s in ("", ".", "N/A", "NA", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- Yahoo Finance
def fetch_yahoo(http: Http, specs: list[dict], since: dict[str, date], today: date) -> dict[str, Series]:
    out: dict[str, Series] = {}
    end = int(datetime.combine(today + timedelta(days=1), datetime.min.time()).timestamp())
    for spec in specs:
        key = spec_key(spec)
        start = int(datetime.combine(since[key], datetime.min.time()).timestamp())
        sym = spec["symbole"]
        err: Exception | None = None
        for host in ("query1", "query2"):
            try:
                r = http.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"period1": start, "period2": end, "interval": "1d", "events": "history"})
                res = r.json()["chart"]["result"][0]
                tz = ZoneInfo(res["meta"].get("exchangeTimezoneName") or "UTC")
                closes = res["indicators"]["quote"][0]["close"]
                vals: dict[date, float] = {}
                for t, c in zip(res.get("timestamp") or [], closes):
                    if c is None:
                        continue
                    d = datetime.fromtimestamp(t, tz).date()
                    if d >= today:  # séance en cours : pas encore une clôture
                        continue
                    vals[d] = float(c)
                out[key] = sorted(vals.items())
                err = None
                break
            except Exception as e:  # noqa: BLE001 - on essaie l'autre serveur
                err = e
        if err:
            raise_later(out, key, err)
    return out


def raise_later(out: dict, key: str, err: Exception) -> None:
    out.setdefault("__errors__", {})[key] = f"{type(err).__name__}: {err}"


# ------------------------------------------------------------- US Treasury
def fetch_treasury(http: Http, specs: list[dict], since: dict[str, date], today: date, real: bool) -> dict[str, Series]:
    kind = "daily_treasury_real_yield_curve" if real else "daily_treasury_yield_curve"
    start_year = min(since[spec_key(s)] for s in specs).year
    cols = {spec_key(s): s["colonne"] for s in specs}
    acc: dict[str, dict[date, float]] = defaultdict(dict)
    for year in range(start_year, today.year + 1):
        r = http.get(TREASURY_URL.format(year=year, kind=kind))
        rows = list(csv.DictReader(io.StringIO(r.text)))
        for row in rows:
            d = datetime.strptime(row["Date"], "%m/%d/%Y").date()
            if d >= today:
                continue
            for key, col in cols.items():
                v = _num(row.get(col, ""))
                if v is not None:
                    acc[key][d] = v
    return {k: sorted(v.items()) for k, v in acc.items()}


# ------------------------------------------------------------- Bundesbank
def fetch_bundesbank(http: Http, specs: list[dict], since: dict[str, date], today: date) -> dict[str, Series]:
    mats = [s["maturite"] for s in specs]
    start = min(since[spec_key(s)] for s in specs)
    key = BUNDESBANK_KEY.format(mat="+".join(mats))
    r = http.get(f"https://api.statistiken.bundesbank.de/rest/data/{key}",
                 params={"format": "csv", "lang": "en", "startPeriod": start.isoformat()})
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    col_of: dict[str, int] = {}
    for i, h in enumerate(header):
        for m in mats:
            if h.endswith(f".A604.{m}.R.A.A._Z._Z.A"):
                col_of[f"bundesbank:{m}"] = i
    acc: dict[str, list] = defaultdict(list)
    for row in rows[1:]:
        if not row or len(row[0]) != 10 or not row[0][:4].isdigit():
            continue
        d = date.fromisoformat(row[0])
        if d >= today:
            continue
        for k, i in col_of.items():
            v = _num(row[i]) if i < len(row) else None
            if v is not None:
                acc[k].append((d, v))
    missing = [m for m in mats if f"bundesbank:{m}" not in col_of]
    if missing:
        log.warning("Bundesbank : maturités absentes de la réponse : %s", missing)
    return dict(acc)


# ------------------------------------------------------------- Banque de France
def fetch_bdf(http: Http, specs: list[dict], since: dict[str, date], today: date) -> dict[str, Series]:
    api_key = os.environ.get("BDF_API_KEY", "").strip()
    out: dict[str, Series] = {}
    if api_key:
        try:
            out = _bdf_with_key(http, specs, since, today, api_key)
        except Exception as e:  # noqa: BLE001
            log.warning("Banque de France (API avec clé) en échec, repli sans clé : %s", e)
            out = {}
    missing = [s for s in specs if spec_key(s) not in out]
    if missing:
        out.update(_bdf_without_key(http, missing, today))
    return out


def _bdf_with_key(http: Http, specs, since, today, api_key) -> dict[str, Series]:
    keys = [s["serie"] for s in specs]
    start = min(since[spec_key(s)] for s in specs)
    where = "(" + " or ".join(f'series_key="{k}"' for k in keys) + f") and time_period_end>=date'{start.isoformat()}'"
    r = http.get(f"{WEBSTAT}/observations/exports/json",
                 params={"select": "series_key,time_period_end,obs_value", "where": where},
                 headers={"Authorization": f"Apikey {api_key}"})
    acc: dict[str, list] = defaultdict(list)
    for rec in r.json():
        v = rec.get("obs_value")
        if v is None:
            continue
        d = date.fromisoformat(str(rec["time_period_end"])[:10])
        if d < today:
            acc[f"bdf:{rec['series_key']}"].append((d, float(v)))
    if not acc:
        raise RuntimeError("réponse vide")
    return {k: sorted(v) for k, v in acc.items()}


def _bdf_without_key(http: Http, specs, today) -> dict[str, Series]:
    """Sans clé, le catalogue public donne les deux dernières valeurs : l'historique se construit jour après jour."""
    out: dict[str, Series] = {}
    for s in specs:
        ds = s["serie"].lower().replace(".", "-")
        meta = http.get(f"{WEBSTAT}/{ds}").json()["metas"]["custom"]
        last = date.fromisoformat(meta["series_last_time_period_date"][:10])
        vals = [_num(x) for x in str(meta["series_last_two_obs_values"]).split(",")]
        pts: Series = []
        if len(vals) == 2 and vals[0] is not None:
            # Date de l'avant-dernière valeur inconnue : on suppose le jour ouvré précédent.
            prev = last - timedelta(days=1)
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            pts.append((prev, vals[0]))
        if vals and vals[-1] is not None:
            pts.append((last, vals[-1]))
        out[spec_key(s)] = [(d, v) for d, v in pts if d < today]
    return out


# ------------------------------------------------------------- BCE
def fetch_ecb(http: Http, specs: list[dict], since: dict[str, date], today: date) -> dict[str, Series]:
    out: dict[str, Series] = {}
    for spec in specs:
        key = spec_key(spec)
        flow, series = spec["cle"].split("/", 1)
        try:
            r = http.get(f"https://data-api.ecb.europa.eu/service/data/{flow}/{series}",
                         params={"format": "csvdata", "detail": "dataonly", "startPeriod": since[key].isoformat()[:7]})
            pts = []
            for row in csv.DictReader(io.StringIO(r.text)):
                v = _num(row.get("OBS_VALUE", ""))
                tp = row.get("TIME_PERIOD", "")
                if v is None or not tp:
                    continue
                d = date.fromisoformat(tp if len(tp) == 10 else tp + "-01")
                if len(tp) == 10 and d >= today:
                    continue
                pts.append((d, v))
            out[key] = sorted(pts)
        except Exception as e:  # noqa: BLE001
            raise_later(out, key, e)
    return out


# ------------------------------------------------------------- FRED
def fetch_fred(http: Http, specs: list[dict], since: dict[str, date], today: date) -> dict[str, Series]:
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("clé FRED_API_KEY absente (secret GitHub à ajouter)")
    out: dict[str, Series] = {}
    for spec in specs:
        key = spec_key(spec)
        try:
            r = http.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": spec["serie"], "api_key": api_key, "file_type": "json",
                                 "observation_start": since[key].isoformat()})
            pts = []
            for o in r.json().get("observations", []):
                v = _num(o.get("value", ""))
                d = date.fromisoformat(o["date"])
                if v is not None and d < today:
                    pts.append((d, v))
            out[key] = pts
        except Exception as e:  # noqa: BLE001
            raise_later(out, key, RuntimeError(str(e).replace(api_key, "***")))
    return out


# ------------------------------------------------------------- Répartiteur
def fetch_all(http: Http, specs: list[dict], since: dict[str, date], today: date) -> tuple[dict[str, Series], dict[str, str]]:
    """Télécharge toutes les specs, regroupées par fournisseur. Renvoie (données, erreurs)."""
    by_provider: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for s in specs:
        k = spec_key(s)
        if k not in seen:
            seen.add(k)
            by_provider[s["fournisseur"]].append(s)
    data: dict[str, Series] = {}
    errors: dict[str, str] = {}
    calls = {
        "yahoo": lambda sp: fetch_yahoo(http, sp, since, today),
        "treasury": lambda sp: fetch_treasury(http, sp, since, today, real=False),
        "treasury_reel": lambda sp: fetch_treasury(http, sp, since, today, real=True),
        "bundesbank": lambda sp: fetch_bundesbank(http, sp, since, today),
        "bdf": lambda sp: fetch_bdf(http, sp, since, today),
        "bce": lambda sp: fetch_ecb(http, sp, since, today),
        "fred": lambda sp: fetch_fred(http, sp, since, today),
    }
    for provider, sp in by_provider.items():
        if provider not in calls:
            for s in sp:
                errors[spec_key(s)] = f"fournisseur inconnu : {provider}"
            continue
        try:
            res = calls[provider](sp)
            errors.update(res.pop("__errors__", {}))
            data.update(res)
            for s in sp:
                k = spec_key(s)
                if k not in data and k not in errors:
                    errors[k] = "aucune donnée renvoyée"
        except Exception as e:  # noqa: BLE001 - une source en panne ne doit pas tout bloquer
            for s in sp:
                errors[spec_key(s)] = f"{type(e).__name__}: {str(e)[:300]}"
        log.info("Source %-13s : %d série(s) OK, %d en échec", provider,
                 sum(1 for s in sp if spec_key(s) in data), sum(1 for s in sp if spec_key(s) in errors))
    return data, errors


def fetch_eurostat_flash_dates(http: Http) -> list[date]:
    """Dates des estimations rapides d'inflation de la zone euro (calendrier officiel Eurostat, iCal)."""
    r = http.get("https://ec.europa.eu/eurostat/o/calendars/eventsIcal", params={"theme": 0, "category": 0, "lang": "en"})
    text = r.text.replace("\r\n ", "").replace("\n ", "")
    out = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        summary = next((l.split(":", 1)[1] for l in block.splitlines() if l.startswith("SUMMARY")), "")
        start = next((l.split(":", 1)[1] for l in block.splitlines() if l.startswith("DTSTART")), "")
        if "flash estimate inflation euro area" in summary.lower() and len(start) >= 8:
            out.append(date(int(start[:4]), int(start[4:6]), int(start[6:8])))
    return sorted(set(out))

