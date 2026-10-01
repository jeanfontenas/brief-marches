"""Tests automatiques (sans réseau) : python -m pytest -q"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from brief import build, commentary, sources
from brief.gate import decide, read_general
from brief.render import render_page, write_site
from brief.store import Store

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parent.parent
PARIS = ZoneInfo("Europe/Paris")


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200

    def json(self):
        return json.loads(self.text)


class FakeHttp:
    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url, **kw):
        self.calls.append(url)
        for pattern, body in self.routes.items():
            if pattern in url:
                if isinstance(body, Exception):
                    raise body
                return FakeResponse(body)
        raise RuntimeError(f"URL inattendue : {url}")


# ------------------------------------------------------------------ portier (heure d'été / d'hiver)
@pytest.mark.parametrize("utc, expected", [
    ("2026-07-01T05:17", True),    # été : 7 h 17 à Paris
    ("2026-07-01T04:47", False),   # été : 6 h 47, trop tôt
    ("2026-01-14T06:17", True),    # hiver : 7 h 17 à Paris
    ("2026-01-14T05:47", False),   # hiver : 6 h 47, trop tôt
    ("2026-07-04T06:17", False),   # samedi
])
def test_gate_heure_paris(utc, expected):
    now = datetime.fromisoformat(utc + "+00:00").astimezone(PARIS)
    go, _ = decide(now, "08:00", 50, False, None, force=False)
    assert go is expected


def test_gate_deja_fait_pause_et_force():
    now = datetime(2026, 7, 1, 7, 30, tzinfo=PARIS)
    assert decide(now, "08:00", 50, False, "2026-07-01", False)[0] is False
    assert decide(now, "08:00", 50, True, None, False)[0] is False
    assert decide(now, "08:00", 50, True, "2026-07-01", True)[0] is True


def test_gate_lit_la_config():
    g = read_general((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert g["heure_cible"] == "08:00" and g["avance_minutes"] == 50 and g["en_pause"] is False


# ------------------------------------------------------------------ formats français
def test_formats():
    assert build.fr_num(3.4219, 2) == "3,42"
    assert build.fr_num(7964.51, 2) == "7\u202f964,51"
    assert build.fr_num(-0.5, 2) == "\u22120,50"
    assert build.fr_signed(5, 0) == "+5"
    assert build.fr_signed(-4, 0) == "\u22124"
    assert build.fr_signed(0.004, 2) == "0,00"
    assert build.fr_date(date(2026, 10, 1)) == "jeudi 1er octobre 2026"


# ------------------------------------------------------------------ sources (réponses réelles enregistrées)
def test_treasury_csv():
    http = FakeHttp({"daily_treasury_yield_curve": (FIX / "treasury.csv").read_text()})
    specs = [{"fournisseur": "treasury", "colonne": "10 Yr"}, {"fournisseur": "treasury", "colonne": "3 Mo"}]
    since = {sources.spec_key(s): date(2026, 9, 1) for s in specs}
    out = sources.fetch_treasury(http, specs, since, date(2026, 10, 1), real=False)
    assert out["treasury:10 Yr"][-1] == (date(2026, 9, 30), 5.29)
    assert out["treasury:3 Mo"][-1] == (date(2026, 9, 30), 4.20)


def test_bundesbank_csv_exclut_le_jour_meme():
    http = FakeHttp({"bundesbank": (FIX / "bundesbank.csv").read_text(encoding="utf-8-sig")})
    specs = [{"fournisseur": "bundesbank", "maturite": m} for m in ("R005X", "R10XX", "R30XX")]
    since = {sources.spec_key(s): date(2021, 9, 1) for s in specs}
    out = sources.fetch_bundesbank(http, specs, since, date(2026, 10, 1))
    assert out["bundesbank:R10XX"][-1] == (date(2026, 9, 30), 3.64)
    assert out["bundesbank:R005X"][0] == (date(2026, 9, 29), 2.79)


def test_ecb_mensuel():
    http = FakeHttp({"data-api.ecb.europa.eu": (FIX / "ecb_hicp.csv").read_text()})
    spec = {"fournisseur": "bce", "cle": "HICP/M.U2.N.000000.4D0.ANR"}
    out = sources.fetch_ecb(http, [spec], {sources.spec_key(spec): date(2026, 5, 1)}, date(2026, 10, 1))
    assert out["bce:HICP/M.U2.N.000000.4D0.ANR"][-1] == (date(2026, 8, 1), 3.2)


def test_yahoo_exclut_la_seance_en_cours():
    http = FakeHttp({"finance.yahoo.com": (FIX / "yahoo_fchi.json").read_text()})
    spec = {"fournisseur": "yahoo", "symbole": "^FCHI"}
    out = sources.fetch_yahoo(http, [spec], {"yahoo:^FCHI": date(2026, 9, 1)}, date(2026, 10, 1))
    dates = [d for d, _ in out["yahoo:^FCHI"]]
    assert dates[-1] == date(2026, 9, 30) and date(2026, 10, 1) not in dates


def test_une_source_en_panne_ne_bloque_pas_les_autres():
    http = FakeHttp({"finance.yahoo.com": RuntimeError("panne"),
                     "daily_treasury_yield_curve": (FIX / "treasury.csv").read_text()})
    specs = [{"fournisseur": "yahoo", "symbole": "^FCHI"}, {"fournisseur": "treasury", "colonne": "10 Yr"}]
    since = {sources.spec_key(s): date(2026, 9, 1) for s in specs}
    data, errors = sources.fetch_all(http, specs, since, date(2026, 10, 1))
    assert "treasury:10 Yr" in data and "yahoo:^FCHI" in errors


# ------------------------------------------------------------------ historique local
def test_store_fusion_et_reprise(tmp_path):
    st = Store(tmp_path)
    st.merge("x", [(date(2026, 9, 29), 1.0), (date(2026, 9, 30), 2.0)])
    st2 = Store(tmp_path)
    s = st2.merge("x", [(date(2026, 9, 30), 2.5), (date(2026, 10, 1), 3.0)])
    assert s == [(date(2026, 9, 29), 1.0), (date(2026, 9, 30), 2.5), (date(2026, 10, 1), 3.0)]
    assert st2.since("vide", date(2026, 10, 1), 5) < date(2021, 10, 1)


# ------------------------------------------------------------------ calculs
def _days(n, start=date(2021, 9, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fetched(series: dict, ok=None):
    f = build.Fetched()
    f.series = series
    f.ok = set(series) if ok is None else ok
    return f


CFG = {
    "general": {"historique_ans": 5},
    "indicateurs": {
        "oat10": {"nom": "OAT 10 ans", "unite": "%", "decimales": 2, "variation": "bp",
                  "sources": [{"fournisseur": "bdf", "serie": "A"}]},
        "bund10": {"nom": "Bund 10 ans", "unite": "%", "decimales": 2, "variation": "bp",
                   "sources": [{"fournisseur": "bundesbank", "maturite": "R10XX"}]},
        "spread": {"nom": "Spread", "unite": "bp", "decimales": 0, "variation": "bp",
                   "calcul": {"difference": ["oat10", "bund10"], "facteur": 100}},
        "cac": {"nom": "CAC 40", "unite": "", "decimales": 2, "variation": "pct",
                "sources": [{"fournisseur": "yahoo", "symbole": "^FCHI"}]},
    },
}


def test_indicateurs_variations_et_spread():
    days = _days(30, date(2026, 8, 20))
    f = _fetched({
        "bdf:A": [(d, 4.70 + 0.01 * i) for i, d in enumerate(days)],
        "bundesbank:R10XX": [(d, 3.60 + 0.005 * i) for i, d in enumerate(days)],
        "yahoo:^FCHI": [(d, 8000 + 10 * i) for i, d in enumerate(days)],
    })
    dd = days[-1]
    cache: dict = {}
    oat = build.build_indicator("oat10", CFG, f, cache, dd)
    spread = build.build_indicator("spread", CFG, f, cache, dd)
    cac = build.build_indicator("cac", CFG, f, cache, dd)
    assert oat["status"] == "ok" and oat["change"] == pytest.approx(1.0)
    assert spread["last"]["value"] == pytest.approx((4.99 - 3.745) * 100)
    assert spread["change"] == pytest.approx(0.5)
    assert cac["change"] == pytest.approx((8290 / 8280 - 1) * 100, abs=1e-3)


def test_statuts_ancien_et_indisponible():
    days = _days(10, date(2026, 9, 14))
    f = _fetched({"bdf:A": [(d, 4.7) for d in days[:-1]], "bundesbank:R10XX": [(d, 3.6) for d in days],
                  "yahoo:^FCHI": [(d, 8000.0) for d in days]}, ok={"bdf:A", "bundesbank:R10XX"})
    cache: dict = {}
    assert build.build_indicator("oat10", CFG, f, cache, days[-1])["status"] == "stale"
    assert build.build_indicator("cac", CFG, f, cache, days[-1])["status"] == "unavailable"
    assert build.build_indicator("spread", CFG, f, cache, days[-1])["status"] == "stale"


def test_allegement_des_series():
    days = _days(1300)
    out = build.thin([(d, 1.0) for d in days], days[-1], 5)
    assert 400 < len(out["t"]) < 600 and out["t"][-1] == days[-1].isoformat()


def test_banques_centrales_et_reunions():
    days = _days(60, date(2026, 7, 1))
    lo = [(d, 3.75 if d < date(2026, 9, 17) else 3.50) for d in days]
    hi = [(d, v + 0.25) for d, v in lo]
    cfg = {"banques_centrales": {
        "fed": {"nom": "Fed", "libelle": "x", "bas": {"fournisseur": "fred", "serie": "L"},
                "haut": {"fournisseur": "fred", "serie": "H"}, "reunions": ["2026-09-16", "2026-10-28"]},
        "bce": {"nom": "BCE", "libelle": "y", "taux": {"fournisseur": "bce", "cle": "FM/X"}, "reunions": ["2026-10-29"]}}}
    f = _fetched({"fred:L": lo, "fred:H": hi, "bce:FM/X": [(d, 2.5) for d in days]})
    cb = build.build_central_banks(cfg, f, days[-1], days[-1] + timedelta(days=1))
    assert cb["fed"]["lower"] == 3.5 and cb["fed"]["last_change"] == {"date": "2026-09-17", "bp": -25}
    assert cb["fed"]["next_meeting"]["label"] == "27-28 octobre 2026"
    assert cb["ecb"]["last_change"] is None


def test_adjudications_aft():
    assert any("long terme" in e for e in build.aft_auctions(date(2026, 10, 1)))   # 1er jeudi
    assert any("moyen terme" in e for e in build.aft_auctions(date(2026, 10, 15)))  # 3e jeudi
    assert any("BTF" in e for e in build.aft_auctions(date(2026, 10, 5)))           # lundi
    assert build.aft_auctions(date(2026, 10, 6)) == []


def test_jours_feries():
    assert build.market_closures(date(2026, 12, 25)) == {"europe": "Christmas Day", "us": "Christmas Day"}
    c = build.market_closures(date(2026, 4, 6))
    assert c["europe"] == "Easter Monday" and c["us"] is None


def test_inflation_glissement_annuel():
    idx = [(date(2025, m, 1), 100.0 + m) for m in range(1, 13)] + [(date(2026, m, 1), 103.0 + m) for m in range(1, 9)]
    out = build._monthly(idx, yoy=True)
    assert out[-1] == ("2026-08", round((111 / 108 - 1) * 100, 1))


# ------------------------------------------------------------------ commentaire
def test_extraction_json_et_nettoyage():
    raw = 'Voici :\n```json\n{"essentiel": ["a", "b", "c", "d"], "hier": "x [lien](https://ex.org)", ' \
          '"implications": "y", "agenda": [{"heure": "8h45", "pays": "fr", "evenement": "IPC"}], ' \
          '"sources": [{"titre": "ok", "url": "https://ex.org"}, {"titre": "ko", "url": "javascript:alert(1)"}]}\n```'
    obj = commentary.extract_json(raw)
    out = commentary.clean(obj, [{"titre": "cité", "url": "https://autre.org"}])
    assert out["essentiel"] == ["a", "b", "c"]
    assert [s["url"] for s in out["sources"]] == ["https://ex.org", "https://autre.org"]
    assert out["agenda"][0]["pays"] == "FR" and out["agenda"][0]["heure"] == "8h45"
    assert commentary.extract_json("pas de json") is None


def test_commentaire_sans_cle_ne_plante_pas(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = {"commentaire": {"actif": True, "modele": "claude-opus-5-5"}}
    out = commentary.generate(cfg, {}, date(2026, 10, 1), tmp_path / "c.csv")
    assert out["available"] is False


# ------------------------------------------------------------------ rendu
def test_rendu_echappe_les_donnees_et_ecrit_les_archives(tmp_path):
    data = json.loads(json.dumps(__import__("tests.sample_data", fromlist=["data"]).data))
    data["commentary"]["hier"] = "</script><script>alert(1)</script>"
    page = render_page(data)
    assert "</script><script>alert(1)" not in page and "\\u003c/script>" in page
    write_site(data, tmp_path, date(2026, 10, 1), "Brief")
    write_site(data, tmp_path, date(2026, 10, 2), "Brief")
    assert (tmp_path / "index.html").exists() and (tmp_path / "archives" / "2026-10-01.html").exists()
    idx = (tmp_path / "archives" / "index.html").read_text(encoding="utf-8")
    assert idx.index("2026-10-02") < idx.index("2026-10-01")
    assert re.search(r'"prev_url":"archives/2026-10-01.html"', (tmp_path / "index.html").read_text(encoding="utf-8"))


def test_commentaire_avec_reponse_simulee_du_sdk(monkeypatch, tmp_path):
    """Réponse construite avec les vrais types du SDK Anthropic : pause_turn, recherche web, citations."""
    import anthropic
    from anthropic.types.beta import BetaMessage

    final_json = json.dumps({"essentiel": ["Les taux montent.", "Le CAC recule.", "Inflation à 11 h."],
                             "hier": "Le Bund prend 4 bp [Reuters](https://www.reuters.com/x).",
                             "implications": "Prime de terme.", "agenda": [], "sources": []}, ensure_ascii=False)

    def msg(stop, content):
        return BetaMessage.model_validate({
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": stop, "stop_sequence": None, "content": content,
            "usage": {"input_tokens": 20000, "output_tokens": 3000, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0, "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0}}})

    paused = msg("pause_turn", [
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "Bund"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
            {"type": "web_search_result", "url": "https://www.reuters.com/x", "title": "Reuters",
             "encrypted_content": "abc", "page_age": None}]}])
    done = msg("end_turn", [
        {"type": "text", "text": "Je cherche.", "citations": None},
        {"type": "server_tool_use", "id": "srvtoolu_2", "name": "web_search", "input": {"query": "CAC"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_2", "content": []},
        {"type": "text", "text": final_json[:40], "citations": [
            {"type": "web_search_result_location", "url": "https://www.lesechos.fr/y", "title": "Les Échos",
             "encrypted_index": "z", "cited_text": "..."}]},
        {"type": "text", "text": final_json[40:], "citations": None}])

    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return paused if len(calls) == 1 else done

    class FakeClient:
        def __init__(self, **kw):
            self.beta = type("B", (), {"messages": FakeMessages()})()
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    out = commentary.generate(cfg, {"indicateurs": [{"niveau": "3,64 %"}]}, date(2026, 10, 1), tmp_path / "c.csv")
    assert out["available"] is True and out["essentiel"][0] == "Les taux montent."
    assert "https://www.lesechos.fr/y" in [s["url"] for s in out["sources"]]
    assert calls[0]["fallbacks"] == "default" and calls[0]["tools"][0]["type"] == "web_search_20260318"
    assert calls[1]["messages"][1]["role"] == "assistant"          # reprise après pause_turn
    assert out["cost_usd"] == pytest.approx(2 * (20000 * 4 / 1e6 + 3000 * 20 / 1e6 + 0.02))
    assert len((tmp_path / "c.csv").read_text().splitlines()) == 3   # en-tête + 2 appels


def test_fed_new_york_fourchette_cible():
    http = FakeHttp({"newyorkfed.org": (FIX / "nyfed.json").read_text()})
    specs = [{"fournisseur": "nyfed", "champ": "targetRateFrom"}, {"fournisseur": "nyfed", "champ": "targetRateTo"}]
    since = {sources.spec_key(s): date(2026, 9, 1) for s in specs}
    out = sources.fetch_nyfed(http, specs, since, date(2026, 10, 1))
    assert out["nyfed:targetRateFrom"][-1] == (date(2026, 9, 30), 3.75)
    assert out["nyfed:targetRateTo"][0] == (date(2026, 9, 15), 3.75)
    assert out["nyfed:targetRateTo"][-1] == (date(2026, 9, 30), 4.0)


def test_raison_lisible_si_la_cle_anthropic_echoue():
    import anthropic
    import httpx2
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError("invalid x-api-key", response=httpx2.Response(401, request=req), body=None)
    assert "expirée" in commentary.explain_error(err)
    assert "limite de dépense" in commentary.explain_error(RuntimeError("You have reached your specified API usage limits"))
