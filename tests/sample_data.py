"""Génère un jeu de données FICTIVES au format attendu par la page.

Sert à la maquette et aux tests : aucune de ces valeurs n'est réelle.
Usage : python tests/sample_data.py > /tmp/sample.json
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta

RNG = random.Random(42)
END = date(2026, 9, 30)          # date des données (clôture de la veille)
BRIEF = date(2026, 10, 1)        # date du brief


def business_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bridge(days: list[date], anchors: list[tuple[date, float]], vol: float) -> list[float]:
    """Pont brownien passant par des points d'ancrage (allure réaliste)."""
    vals = []
    a = sorted(anchors)
    for d in days:
        for (d0, v0), (d1, v1) in zip(a, a[1:]):
            if d0 <= d <= d1:
                span = (d1 - d0).days or 1
                w = (d - d0).days / span
                vals.append(v0 + (v1 - v0) * w)
                break
        else:
            vals.append(a[-1][1])
    # bruit en pont : marche aléatoire ramenée à zéro aux ancrages
    noise, cur = [], 0.0
    for _ in days:
        cur += RNG.gauss(0, vol)
        noise.append(cur)
    anchor_idx = [min(range(len(days)), key=lambda i: abs((days[i] - d).days)) for d, _ in a]
    adj = [0.0] * len(days)
    for i0, i1 in zip(anchor_idx, anchor_idx[1:]):
        for i in range(i0, i1 + 1):
            w = (i - i0) / max(1, i1 - i0)
            adj[i] = noise[i] - (noise[i0] * (1 - w) + noise[i1] * w)
    return [round(v + n, 4) for v, n in zip(vals, adj)]


def thin(days: list[date], vals: list[float]) -> dict:
    """Quotidien sur 13 mois, hebdomadaire au-delà (allège la page)."""
    cut = END - timedelta(days=400)
    t, v = [], []
    for d, x in zip(days, vals):
        if d >= cut or d.weekday() == 4:
            t.append(d.isoformat())
            v.append(x)
    return {"t": t, "v": v}


D5 = business_days(END - timedelta(days=5 * 365 + 10), END)


def Y(y, m, d):
    return date(y, m, d)


def rate_series(anchors, vol=0.025):
    return bridge(D5, anchors, vol)


de10 = rate_series([(D5[0], -0.20), (Y(2022, 10, 20), 2.40), (Y(2023, 10, 4), 2.98), (Y(2024, 9, 30), 2.12),
                    (Y(2025, 9, 30), 2.71), (Y(2026, 6, 15), 2.55), (END, 2.68)])
spread = [round(x, 1) for x in bridge(D5, [(D5[0], 38), (Y(2022, 10, 20), 55), (Y(2023, 10, 4), 57),
                                             (Y(2024, 5, 31), 48), (Y(2024, 6, 14), 80), (Y(2024, 12, 2), 88),
                                             (Y(2025, 9, 30), 80), (Y(2026, 6, 15), 75), (END, 74)], 0.9)]
fr10 = [round(d + sp / 100, 4) for d, sp in zip(de10, spread)]
us10 = rate_series([(D5[0], 1.48), (Y(2022, 10, 21), 4.22), (Y(2023, 10, 19), 4.98), (Y(2024, 9, 16), 3.62),
                    (Y(2025, 1, 14), 4.79), (Y(2025, 9, 30), 4.15), (END, 4.12)], vol=0.035)
de2 = rate_series([(D5[0], -0.70), (Y(2022, 10, 20), 2.00), (Y(2023, 7, 7), 3.30), (Y(2024, 9, 30), 2.07),
                   (Y(2025, 9, 30), 2.02), (Y(2026, 6, 15), 1.95), (END, 2.02)])
us2 = rate_series([(D5[0], 0.27), (Y(2022, 10, 21), 4.60), (Y(2023, 10, 18), 5.20), (Y(2024, 9, 25), 3.55),
                   (Y(2025, 9, 30), 3.60), (END, 3.55)], vol=0.03)
be10 = rate_series([(D5[0], 2.45), (Y(2022, 4, 21), 3.02), (Y(2023, 6, 1), 2.20), (Y(2025, 9, 30), 2.36),
                    (END, 2.31)], vol=0.015)
cac = bridge(D5, [(D5[0], 6520), (Y(2022, 9, 29), 5680), (Y(2023, 4, 24), 7570), (Y(2024, 5, 15), 8240),
                  (Y(2025, 4, 8), 6900), (Y(2025, 9, 30), 7895), (END, 8012.35)], 38)
spx = bridge(D5, [(D5[0], 4357), (Y(2022, 10, 12), 3577), (Y(2023, 12, 29), 4770), (Y(2025, 2, 19), 6144),
                  (Y(2025, 4, 8), 4982), (Y(2025, 9, 30), 6688), (END, 6905.20)], 22)
brent = bridge(D5, [(D5[0], 78.5), (Y(2022, 6, 8), 123.6), (Y(2023, 6, 12), 72.0), (Y(2024, 4, 5), 91.2),
                    (Y(2025, 5, 5), 60.2), (Y(2025, 9, 30), 67.0), (END, 66.85)], 0.9)
wti = [round(b - 3.4 + 0.6 * math.sin(i / 40), 2) for i, b in enumerate(brent)]
dubai = [round(b - 1.2 + 0.9 * math.sin(i / 25), 2) for i, b in enumerate(brent)]
eurusd = bridge(D5, [(D5[0], 1.158), (Y(2022, 9, 27), 0.962), (Y(2023, 7, 17), 1.124), (Y(2025, 1, 13), 1.022),
                     (Y(2025, 9, 30), 1.173), (END, 1.1742)], 0.0035)

# Le dernier point exact (évite les arrondis du pont brownien)
for s, v in ((de10, 2.68), (us10, 4.12), (de2, 2.02), (us2, 3.55), (be10, 2.31),
             (cac, 8012.35), (spx, 6905.20), (brent, 66.85), (eurusd, 1.1742)):
    s[-1] = v
de10[-2], us10[-2], de2[-2], us2[-2] = 2.65, 4.09, 2.03, 3.57
be10[-2], cac[-2], spx[-2], brent[-2], eurusd[-2] = 2.29, 7953.50, 6876.45, 67.90, 1.1729
wti[-1], wti[-2] = 63.10, 64.02
dubai[-1], dubai[-2] = 67.40, 68.15
spread[-1], spread[-2] = 74.0, 72.0
fr10[-1], fr10[-2] = 3.42, 3.37


def ind(id_, label, sub, kind, unit, dec, change, series, source, url, help_, status="ok", last_date=END,
        prev_date=None):
    days = D5
    prev_date = prev_date or days[-2]
    v_last, v_prev = series[-1], series[-2]
    chg = (v_last - v_prev) * (100 if change == "bp" and kind != "spread" else 1) if change == "bp" \
        else (v_last / v_prev - 1) * 100
    return {
        "id": id_, "label": label, "sub": sub, "kind": kind, "unit": unit, "decimals": dec,
        "change_mode": change, "status": status,
        "last": {"date": last_date.isoformat(), "value": v_last},
        "prev": {"date": prev_date.isoformat(), "value": v_prev},
        "change": round(chg, 4),
        "source": {"name": source, "url": url}, "help": help_,
        "series": thin(days, series),
    }


H = {
    "fr10": "Rendement de l'obligation d'État française à 10 ans sur le marché secondaire. Il monte quand le prix des OAT baisse. C'est la référence du coût d'emprunt de l'État et il se diffuse aux crédits immobiliers.",
    "de10": "Rendement du Bund à 10 ans, l'actif sans risque de référence de la zone euro. Il reflète surtout les anticipations sur la BCE, l'inflation attendue et la prime de terme.",
    "us10": "Rendement du Treasury à 10 ans, la référence mondiale des taux longs. Ses mouvements se transmettent souvent aux taux européens.",
    "spread_fr_de_10": "Écart entre les taux à 10 ans français et allemand, en points de base. C'est la prime exigée pour détenir de la dette française plutôt qu'allemande (risque budgétaire, politique, liquidité). S'il s'élargit, la France paie relativement plus cher.",
    "de2": "Rendement du Schatz allemand à 2 ans. Il est très sensible aux anticipations de taux de la BCE sur les deux prochaines années : c'est le thermomètre de ce que le marché attend de la BCE.",
    "us2": "Rendement du Treasury à 2 ans. Il suit de près ce que le marché attend de la Fed sur les deux prochaines années.",
    "cac40": "Indice des 40 principales capitalisations de Paris, à la clôture (hors dividendes). Des taux qui montent pèsent souvent sur les actions : ils réduisent la valeur actuelle des profits futurs et rendent les obligations plus attractives.",
    "spx": "Indice des 500 grandes entreprises américaines, pondéré par la capitalisation. Dominé par la technologie, il est sensible aux taux longs. Il clôture à 22 h heure de Paris.",
    "brent": "Prix du baril de pétrole de la mer du Nord (contrat à terme le plus proche), en dollars. Une hausse durable pèse sur l'inflation, puis sur les points morts et les taux.",
    "wti": "Prix du baril de pétrole américain (contrat à terme le plus proche), en dollars. Il suit en général le Brent, avec un écart lié au transport et aux stocks américains.",
    "dubai": "Prix du brut de Dubaï (évaluation Platts), en dollars par baril : la référence du pétrole du Moyen-Orient vendu vers l'Asie. Son écart avec le Brent renseigne sur l'équilibre entre l'offre du Golfe et la demande asiatique.",
    "eurusd": "Nombre de dollars pour un euro : une hausse signifie que l'euro s'apprécie. Il réagit à l'écart de taux entre zone euro et États-Unis. Un euro fort rend le pétrole moins cher en euros.",
    "be10_us": "Écart entre le Treasury 10 ans classique et le Treasury indexé sur l'inflation (TIPS). Il donne l'inflation moyenne anticipée par le marché sur 10 ans, à une prime de risque près. La Fed le surveille pour vérifier que les anticipations restent ancrées autour de 2 %.",
}

indicators = {
    "fr10": ind("fr10", "OAT 10 ans", "France", "rate", "%", 2, "bp", fr10, "Banque de France", "https://webstat.banque-france.fr", H["fr10"]),
    "de10": ind("de10", "Bund 10 ans", "Allemagne", "rate", "%", 2, "bp", de10, "Bundesbank", "https://www.bundesbank.de", H["de10"]),
    "us10": ind("us10", "Treasury 10 ans", "États-Unis", "rate", "%", 2, "bp", us10, "US Treasury", "https://home.treasury.gov", H["us10"]),
    "spread_fr_de_10": ind("spread_fr_de_10", "Spread OAT − Bund", "10 ans", "spread", "bp", 0, "bp", spread, "Calcul", "", H["spread_fr_de_10"]),
    "cac40": ind("cac40", "CAC 40", "Paris", "index", "", 2, "pct", cac, "Source de marché", "", H["cac40"]),
    "spx": ind("spx", "S&P 500", "New York", "index", "", 2, "pct", spx, "Source de marché", "", H["spx"]),
    "brent": ind("brent", "Brent", "$ / baril", "price", "$", 2, "pct", brent, "Source de marché", "", H["brent"]),
    "dubai": ind("dubai", "Dubai", "$ / baril", "price", "$", 2, "pct", dubai, "Source de marché (à confirmer)", "", H["dubai"]),
    "wti": ind("wti", "WTI", "$ / baril", "price", "$", 2, "pct", wti, "Source de marché", "", H["wti"],
               status="stale", last_date=Y(2026, 9, 29), prev_date=Y(2026, 9, 26)),
    "eurusd": ind("eurusd", "Euro / dollar", "EUR/USD", "fx", "", 4, "pct", eurusd, "BCE", "https://data.ecb.europa.eu", H["eurusd"]),
    "be10_us": ind("be10_us", "Point mort 10 ans", "États-Unis", "rate", "%", 2, "bp", be10, "FRED", "https://fred.stlouisfed.org/series/T10YIE", H["be10_us"],
                   last_date=Y(2026, 9, 29), prev_date=Y(2026, 9, 28)),
}
indicators["wti"]["status_note"] = "Source indisponible ce matin : dernière valeur connue."

groups = [
    {"title": "Taux souverains à 10 ans", "ids": ["fr10", "de10", "us10", "spread_fr_de_10"]},
    {"title": "Actions", "ids": ["cac40", "spx"]},
    {"title": "Pétrole", "ids": ["brent", "wti", "dubai"]},
    {"title": "Change et inflation anticipée", "ids": ["eurusd", "be10_us"]},
]

# --- Courbes ---
MATS = ["3M", "6M", "1A", "2A", "5A", "10A", "20A", "30A"]
base = {
    "fr": [1.95, 1.98, 2.02, 2.20, 2.66, 3.42, 4.05, 4.31],
    "de": [1.92, 1.94, 1.97, 2.02, 2.30, 2.68, 3.10, 3.26],
    "us": [3.92, 3.82, 3.68, 3.55, 3.71, 4.12, 4.66, 4.71],
}
shifts = {  # (1 sem, 1 mois, 1 an) : décalage court / long
    "fr": [(-0.02, -0.06), (0.04, -0.12), (0.10, -0.25)],
    "de": [(0.00, -0.05), (0.03, -0.10), (0.05, -0.15)],
    "us": [(0.03, -0.04), (0.12, 0.02), (0.55, 0.05)],
}


def shifted(vals, short, long):
    n = len(vals)
    return [round(v + short + (long - short) * i / (n - 1), 2) for i, v in enumerate(vals)]


curve_dates = [END, END - timedelta(days=7), Y(2026, 8, 31), Y(2025, 9, 30)]
curve_labels = ["30/09/2026", "1 semaine", "1 mois", "1 an"]
curves = {"maturities": MATS, "help": "Chaque point est le rendement d'une obligation d'État pour une durée donnée, de 3 mois à 30 ans. Comparer la courbe du jour à celles d'il y a une semaine, un mois et un an montre si ce sont les taux courts (anticipations de banque centrale) ou les taux longs (inflation attendue, prime de terme) qui ont bougé. L'axe horizontal n'est pas proportionnel aux durées.", "countries": []}
for cid, label, instr, src in (("fr", "France", "OAT et BTF", "Banque de France"),
                               ("de", "Allemagne", "Bund", "Bundesbank"),
                               ("us", "États-Unis", "Treasuries", "US Treasury")):
    snaps = [{"key": "j", "label": "Dernière", "date": END.isoformat(), "values": base[cid]}]
    for (s, l), d, lab, key in zip(shifts[cid], curve_dates[1:], curve_labels[1:], ["1s", "1m", "1a"]):
        snaps.append({"key": key, "label": lab, "date": d.isoformat(), "values": shifted(base[cid], s, l)})
    curves["countries"].append({"id": cid, "label": label, "instrument": instr, "source": {"name": src, "url": ""},
                                "status": "ok", "snapshots": snaps})
curves["countries"][0]["snapshots"][0]["values"][0] = None  # ex. maturité manquante

D2 = [d for d in D5 if d >= END - timedelta(days=730)]
i0 = len(D5) - len(D2)
slope = {"help": "Différence entre le taux à 10 ans et le taux à 2 ans, en points de base. Sous zéro, la courbe est inversée : le marché anticipe des baisses de taux, souvent associées à un ralentissement. Une pente qui remonte peut venir d'une baisse des taux courts ou d'une hausse des taux longs.",
         "series": {}}
fr2 = [d2 + 0.18 + 0.05 * math.sin(i / 30) for i, d2 in enumerate(de2)]
for cid, ten, two in (("fr", fr10, fr2), ("de", de10, de2), ("us", us10, us2)):
    slope["series"][cid] = {"t": [d.isoformat() for d in D2],
                            "v": [round((a - b) * 100, 1) for a, b in zip(ten[i0:], two[i0:])]}

# --- Banques centrales ---
fed_changes = [("2021-10-01", 0.00, 0.25), ("2022-03-17", 0.25, 0.50), ("2022-05-05", 0.75, 1.00),
               ("2022-06-16", 1.50, 1.75), ("2022-07-28", 2.25, 2.50), ("2022-09-22", 3.00, 3.25),
               ("2022-11-03", 3.75, 4.00), ("2022-12-15", 4.25, 4.50), ("2023-02-02", 4.50, 4.75),
               ("2023-03-23", 4.75, 5.00), ("2023-05-04", 5.00, 5.25), ("2023-07-27", 5.25, 5.50),
               ("2024-09-19", 4.75, 5.00), ("2024-11-08", 4.50, 4.75), ("2024-12-19", 4.25, 4.50),
               ("2025-09-18", 4.00, 4.25), ("2025-10-30", 3.75, 4.00), ("2025-12-11", 3.50, 3.75),
               ("2026-09-17", 3.25, 3.50)]
ecb_changes = [("2021-10-01", -0.50), ("2022-07-27", 0.00), ("2022-09-14", 0.75), ("2022-11-02", 1.50),
               ("2022-12-21", 2.00), ("2023-02-08", 2.50), ("2023-03-22", 3.00), ("2023-05-10", 3.25),
               ("2023-06-21", 3.50), ("2023-08-02", 3.75), ("2023-09-20", 4.00), ("2024-06-12", 3.75),
               ("2024-09-18", 3.50), ("2024-10-23", 3.25), ("2024-12-18", 3.00), ("2025-02-05", 2.75),
               ("2025-03-12", 2.50), ("2025-04-23", 2.25), ("2025-06-11", 2.00)]
central_banks = {
    "help": "La Fed fixe une fourchette cible pour le taux des fed funds (prêts interbancaires au jour le jour). La BCE pilote les taux courts par son taux de dépôt, qui rémunère les liquidités excédentaires des banques. La date de la prochaine réunion indique quand une nouvelle décision peut tomber.",
    "fed": {"label": "Fed", "name": "Fourchette des fed funds", "lower": 3.25, "upper": 3.50,
            "last_change": {"date": "2026-09-17", "bp": -25},
            "next_meeting": {"date": "2026-10-28", "label": "27-28 octobre 2026"},
            "source": {"name": "FRED (DFEDTARL, DFEDTARU)", "url": "https://fred.stlouisfed.org"},
            "series": {"t": [c[0] for c in fed_changes] + [END.isoformat()],
                       "lower": [c[1] for c in fed_changes] + [3.25],
                       "upper": [c[2] for c in fed_changes] + [3.50]}},
    "ecb": {"label": "BCE", "name": "Taux de dépôt", "value": 2.00,
            "last_change": {"date": "2025-06-11", "bp": -25},
            "next_meeting": {"date": "2026-10-29", "label": "28-29 octobre 2026"},
            "source": {"name": "BCE (Data Portal)", "url": "https://data.ecb.europa.eu"},
            "series": {"t": [c[0] for c in ecb_changes] + [END.isoformat()],
                       "v": [c[1] for c in ecb_changes] + [2.00]}},
}


# --- Inflation (mensuel, 3 ans) ---
def months(n_back: int) -> list[str]:
    out, y, m = [], 2026, 8
    for _ in range(n_back):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


M36 = months(36)


def monthly(anchors, vol):
    ds = [date(int(s[:4]), int(s[5:]), 1) for s in M36]
    return [round(v, 1) for v in bridge(ds, [(date(int(a[:4]), int(a[5:]), 1), v) for a, v in anchors], vol)]


infl = [
    {"id": "ea", "label": "Zone euro", "help": "Glissement annuel de l'IPCH (indice harmonisé, Eurostat). La sous-jacente exclut énergie, alimentation, alcool et tabac. La BCE vise 2 % à moyen terme et suit la sous-jacente pour juger de la persistance de l'inflation.",
     "next_release": {"date": "2026-10-01", "label": "Estimation rapide de septembre, aujourd'hui 11 h"},
     "source": {"name": "Eurostat", "url": "https://ec.europa.eu/eurostat"},
     "views": [{"key": "ipch", "label": "IPCH",
                "total": {"t": M36, "v": monthly([("2023-09", 4.3), ("2024-09", 1.7), ("2025-01", 2.5), ("2025-09", 2.2), ("2026-08", 2.1)], 0.12)},
                "core": {"t": M36, "v": monthly([("2023-09", 4.5), ("2024-09", 2.7), ("2025-09", 2.3), ("2026-08", 2.2)], 0.06)}}]},
    {"id": "fr", "label": "France", "help": "IPCH de la France (indice harmonisé, comparable à la zone euro), publié par l'Insee et Eurostat. L'IPC « national » cité dans la presse est en général un peu plus bas. La sous-jacente exclut énergie, alimentation, alcool et tabac.",
     "next_release": {"date": "2026-10-01", "label": "Estimation provisoire de septembre (Insee), aujourd'hui 8 h 45"},
     "source": {"name": "Eurostat / Insee", "url": "https://www.insee.fr"},
     "views": [{"key": "ipch", "label": "IPCH",
                "total": {"t": M36, "v": monthly([("2023-09", 5.7), ("2024-09", 1.4), ("2025-02", 0.9), ("2025-09", 1.1), ("2026-08", 1.3)], 0.12)},
                "core": {"t": M36, "v": monthly([("2023-09", 4.2), ("2024-09", 2.0), ("2025-09", 1.6), ("2026-08", 1.7)], 0.06)}}]},
    {"id": "us", "label": "États-Unis", "help": "Le CPI (BLS) mesure les prix payés par les ménages ; le PCE (BEA) couvre un panier plus large et c'est la mesure que la Fed cible à 2 %. La sous-jacente exclut alimentation et énergie. Le PCE est souvent un peu plus bas que le CPI, car le logement y pèse moins.",
     "next_release": {"date": "2026-10-14", "label": "CPI de septembre, 14 octobre"},
     "source": {"name": "FRED (BLS, BEA)", "url": "https://fred.stlouisfed.org"},
     "views": [{"key": "cpi", "label": "CPI",
                "total": {"t": M36, "v": monthly([("2023-09", 3.7), ("2024-09", 2.4), ("2025-04", 2.3), ("2025-09", 3.0), ("2026-08", 2.8)], 0.1)},
                "core": {"t": M36, "v": monthly([("2023-09", 4.1), ("2024-09", 3.3), ("2025-09", 3.0), ("2026-08", 2.9)], 0.05)}},
               {"key": "pce", "label": "PCE",
                "total": {"t": M36[:-1], "v": monthly([("2023-09", 3.4), ("2024-09", 2.1), ("2025-09", 2.8), ("2026-08", 2.5)], 0.08)[:-1]},
                "core": {"t": M36[:-1], "v": monthly([("2023-09", 3.6), ("2024-09", 2.7), ("2025-09", 2.9), ("2026-08", 2.7)], 0.05)[:-1]}}]},
]

commentary = {
    "available": True,
    "hier": "Les taux longs européens ont monté hier : l'OAT 10 ans gagne 5 bp à 3,42 % et le Bund 3 bp à 2,68 %, si bien que le spread OAT − Bund s'élargit à 74 bp après [la présentation du projet de budget](https://www.example.com/budget). Aux États-Unis, le 10 ans prend 3 bp à 4,12 % tandis que le 2 ans recule légèrement, ce qui pentifie la courbe. Les actions ont malgré tout progressé : CAC 40 +0,74 %, S&P 500 +0,42 %, portés par la technologie. Le Brent a perdu 1,5 % à 66,85 $ après [des chiffres de stocks américains plus élevés que prévu](https://www.example.com/stocks). L'euro s'est légèrement apprécié à 1,1742 $.",
    "implications": "La hausse des taux longs sans hausse des taux courts est un « bear steepening » : le marché ne change pas d'avis sur la BCE ou la Fed, mais réclame une prime de terme un peu plus élevée pour prêter à 10 ans. Côté France, l'élargissement du spread reflète un risque budgétaire spécifique, pas un mouvement de la zone euro. La baisse du pétrole va dans l'autre sens : elle modère l'inflation attendue (le point mort américain reste stable à 2,31 %), ce qui limite la hausse des taux. Que les actions montent malgré des taux plus hauts suggère que les investisseurs y voient surtout le signe d'une économie solide.",
    "agenda": [
        {"heure": "08:45", "pays": "FR", "evenement": "Inflation de septembre, estimation provisoire (Insee)"},
        {"heure": "10:50", "pays": "FR", "evenement": "Adjudication d'OAT à long terme (AFT)"},
        {"heure": "11:00", "pays": "EA", "evenement": "Inflation de septembre, estimation rapide (Eurostat)"},
        {"heure": "14:30", "pays": "US", "evenement": "Inscriptions hebdomadaires au chômage"},
        {"heure": "16:00", "pays": "US", "evenement": "Indice ISM manufacturier de septembre"},
    ],
    "sources": [
        {"titre": "Exemple de source : article sur le budget", "url": "https://www.example.com/budget"},
        {"titre": "Exemple de source : stocks de pétrole", "url": "https://www.example.com/stocks"},
    ],
}

essentiel = [
    "Les taux longs européens montent : l'OAT 10 ans gagne 5 bp à 3,42 % et le spread avec le Bund s'élargit à 74 bp.",
    "Les actions tiennent bon malgré la hausse des taux, avec un CAC 40 en progression de 0,74 %.",
    "À suivre aujourd'hui : l'inflation de septembre en France à 8 h 45 et en zone euro à 11 h.",
]

data = {
    "meta": {
        "title": "Brief marchés",
        "brief_date": BRIEF.isoformat(),
        "data_date": END.isoformat(),
        "generated_at": "2026-10-01T06:27:00+02:00",
        "status": "partial",
        "notices": ["WTI : source indisponible ce matin, dernière valeur connue affichée."],
        "demo": True,
        "archive_url": "archives/",
        "prev_url": "archives/2026-09-30.html",
    },
    "essentiel": essentiel,
    "groups": groups,
    "indicators": indicators,
    "curves": curves,
    "slope": slope,
    "central_banks": central_banks,
    "inflation": infl,
    "commentary": commentary,
    "footer_sources": [
        {"what": "Taux français (OAT, BTF)", "name": "Banque de France", "url": "https://webstat.banque-france.fr"},
        {"what": "Taux allemands", "name": "Bundesbank", "url": "https://www.bundesbank.de"},
        {"what": "Taux américains", "name": "US Treasury", "url": "https://home.treasury.gov"},
        {"what": "Actions, pétrole", "name": "Source de marché", "url": ""},
        {"what": "Euro / dollar, taux de dépôt", "name": "BCE", "url": "https://data.ecb.europa.eu"},
        {"what": "Fed, CPI, PCE, point mort", "name": "FRED", "url": "https://fred.stlouisfed.org"},
        {"what": "Inflation européenne", "name": "Eurostat", "url": "https://ec.europa.eu/eurostat"},
        {"what": "Commentaire", "name": "Claude (Anthropic), avec recherche web", "url": ""},
    ],
}

if __name__ == "__main__":
    print(json.dumps(data, ensure_ascii=False))
