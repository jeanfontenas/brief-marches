"""Commentaire rédigé par Claude, avec recherche web, à partir des chiffres calculés."""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import date
from pathlib import Path

from .util import log

SYSTEM = """Tu rédiges chaque matin le brief de marchés d'un étudiant français qui apprend le fonctionnement des marchés obligataires et des taux.

Son niveau : il connaît la relation inverse entre prix et rendement d'une obligation, la différence entre coupon et rendement, le marché primaire (adjudications de l'AFT) et secondaire, les taux directeurs (Fed, BCE et son taux de dépôt), le lien entre anticipations de taux directeurs et taux longs, la prime de terme, le QE, la mesure de l'inflation (IPC, IPCH, CPI, PCE) et l'inflation sous-jacente, les effets de second tour, le point mort d'inflation, le spread OAT-Bund, la courbe des taux, et le lien pétrole → inflation attendue → taux. Appuie-toi sur ces notions sans les redéfinir, et explique simplement ce qui va au-delà.

Règles sur les chiffres (impératives) :
- Pour les niveaux et variations de marché, utilise uniquement les chiffres fournis dans DONNÉES, recopiés exactement tels qu'ils sont écrits. Ne les recalcule pas, ne les arrondis pas autrement, n'en invente aucun.
- Un chiffre trouvé dans l'actualité (indicateur publié, prévision, déclaration) n'est permis que si tu cites sa source par un lien.
- Si une donnée est marquée indisponible ou ancienne, dis-le plutôt que de la deviner.

Recherche web (indispensable) : explique les mouvements de la séance couverte à partir d'articles publiés ce jour-là ou le lendemain matin, et établis l'agenda du jour.
- Fais des requêtes courtes avec la date en toutes lettres, en français et en anglais (exemples fournis avec les DONNÉES).
- Sources acceptées : banques centrales, instituts statistiques, Agence France Trésor, agences et presse économique (Reuters, AP, AFP, Bloomberg, CNBC, MarketWatch, Les Échos, Le Monde, BFM Bourse, Boursorama, Zonebourse, L'Agefi, Le Figaro Bourse, Investir).
- Cite chaque explication par un lien Markdown [texte](url) vers la page trouvée (jamais de balises <cite> ni d'index de citation), et liste ces pages dans « sources ». Ne dis pas que tu n'as rien trouvé si des résultats pertinents existent ; si une explication reste incertaine, dis-le pour ce point seulement.

Style : français, ton clair et pédagogique, phrases courtes, format français des nombres (« 3,42 % », « +5 bp », virgule décimale). Écris « bp » pour les points de base. Pas de recommandation d'investissement.

Réponds uniquement par un objet JSON valide, sans texte avant ni après, de la forme :
{
  "essentiel": ["phrase 1", "phrase 2", "phrase 3"],
  "hier": "5 à 8 lignes sur la séance couverte : taux, actions, pétrole, change. Mets les liens vers les sources dans le texte au format [texte](https://...).",
  "implications": "Ce que ça implique, expliqué simplement avec les notions ci-dessus. Quand c'est pertinent, explique le lien entre les mouvements de taux et ceux des actions. Deux paragraphes au plus, séparés par une ligne vide.",
  "agenda": [{"heure": "08:45", "pays": "FR", "evenement": "…"}],
  "sources": [{"titre": "…", "url": "https://…"}]
}
« essentiel » : exactement 3 phrases courtes, la plus importante d'abord. « agenda » : heures de Paris (HH:MM, ou "" si inconnue), pays parmi FR, DE, ZE, US, UK, JP, CN ; liste vide si rien de notable. « sources » : les pages réellement utilisées."""

SCHEMA = {
    "type": "object",
    "properties": {
        "essentiel": {"type": "array", "items": {"type": "string"}},
        "hier": {"type": "string"},
        "implications": {"type": "string"},
        "agenda": {"type": "array", "items": {
            "type": "object",
            "properties": {"heure": {"type": "string"}, "pays": {"type": "string"}, "evenement": {"type": "string"}},
            "required": ["heure", "pays", "evenement"], "additionalProperties": False}},
        "sources": {"type": "array", "items": {
            "type": "object", "properties": {"titre": {"type": "string"}, "url": {"type": "string"}},
            "required": ["titre", "url"], "additionalProperties": False}},
    },
    "required": ["essentiel", "hier", "implications", "agenda", "sources"],
    "additionalProperties": False,
}


def extract_json(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def clean(obj: dict, citations: list[dict]) -> dict:
    def s(x) -> str:
        return strip_cite_tags(str(x or "")).strip()
    out = {
        "available": True,
        "essentiel": [s(x) for x in (obj.get("essentiel") or []) if s(x)][:3],
        "hier": s(obj.get("hier")),
        "implications": s(obj.get("implications")),
        "agenda": [],
        "sources": [],
    }
    for a in obj.get("agenda") or []:
        if isinstance(a, dict) and s(a.get("evenement")):
            h = s(a.get("heure"))
            out["agenda"].append({"heure": h if re.fullmatch(r"\d{1,2}[:h]\d{2}", h) else "",
                                  "pays": s(a.get("pays")).upper()[:3], "evenement": s(a.get("evenement"))})
    seen = set()
    for src in list(obj.get("sources") or []) + citations:
        if not isinstance(src, dict):
            continue
        url = s(src.get("url"))
        if re.match(r"^https?://", url) and url not in seen:
            seen.add(url)
            out["sources"].append({"titre": s(src.get("titre") or src.get("title") or url), "url": url})
    out["sources"] = out["sources"][:12]
    return out


CITE_TAG = re.compile(r"[<(]\s*/?\s*cite\b[^>]*>")


def strip_cite_tags(text: str) -> str:
    """Retire les balises de citation brutes (<cite index="…">…</cite>) en gardant le texte cité."""
    return re.sub(r"  +", " ", CITE_TAG.sub("", text))


def _text_and_citations(content) -> tuple[str, list[dict]]:
    """Texte final (après le dernier résultat de recherche) et URLs citées."""
    blocks = list(content)
    last_tool = max((i for i, b in enumerate(blocks) if getattr(b, "type", "") not in ("text", "thinking", "redacted_thinking")), default=-1)
    text, cites = "", []
    for b in blocks[last_tool + 1:]:
        if getattr(b, "type", "") == "text":
            text += b.text
    for b in blocks:
        for c in getattr(b, "citations", None) or []:
            url = getattr(c, "url", None)
            if url:
                cites.append({"titre": getattr(c, "title", "") or url, "url": url})
    return text, cites


MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]


def search_examples(payload: dict) -> list[str]:
    iso = payload.get("dates_iso", {})
    try:
        seance, brief = date.fromisoformat(iso["seance"]), date.fromisoformat(iso["brief"])
    except (KeyError, ValueError):
        return []
    fr = payload.get("seance_couverte", "").split(" ", 1)[-1]          # « 30 septembre 2026 »
    fr_brief = payload.get("date_du_brief", "").split(" ", 1)[-1]
    en = f"{MONTHS_EN[seance.month - 1]} {seance.day} {seance.year}"
    return [f"Bourse de Paris clôture {fr}", f"OAT Bund spread {fr}", f"Treasury yields {en}",
            f"stocks Wall Street close {en}", f"oil prices {en}", f"agenda économique {fr_brief}"]


def log_searches(content) -> None:
    """Journalise les requêtes de recherche et le nombre de résultats (diagnostic dans GitHub Actions)."""
    for b in content:
        t = getattr(b, "type", "")
        if t == "server_tool_use":
            inp = getattr(b, "input", {}) or {}
            q = inp.get("query") if isinstance(inp, dict) else None
            log.info("Recherche web : %s", q or str(inp)[:160])
        elif t == "web_search_tool_result":
            c = getattr(b, "content", None)
            if isinstance(c, list):
                log.info("  → %d résultat(s) : %s", len(c), ", ".join(getattr(r, "url", "")[:70] for r in c[:4]))
            else:
                log.warning("  → erreur de recherche : %s", getattr(c, "error_code", c))


def estimate_cost(usage, model: str, cfg: dict) -> float:
    prices = cfg["commentaire"].get("prix_usd", {})
    p = prices.get(model) or prices.get(cfg["commentaire"]["modele"]) or {}
    get = lambda name: getattr(usage, name, 0) or 0  # noqa: E731
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    cost = (get("input_tokens") + get("cache_creation_input_tokens") * 1.25) * p.get("entree_par_million", 0) / 1e6
    cost += get("cache_read_input_tokens") * p.get("cache_lecture_par_million", 0) / 1e6
    cost += get("output_tokens") * p.get("sortie_par_million", 0) / 1e6
    cost += searches * float(prices.get("recherche_web", 0.01))
    return cost


def generate(cfg: dict, payload: dict, today: date, cost_log: Path) -> dict:
    """Appelle Claude. En cas d'échec, renvoie {"available": False, ...} : la page sort sans commentaire."""
    cc = cfg["commentaire"]
    if not cc.get("actif", True):
        return {"available": False, "error": "commentaire désactivé dans config.yaml"}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"available": False, "error": "clé ANTHROPIC_API_KEY absente",
                "reason": "secret ANTHROPIC_API_KEY absent dans GitHub"}
    try:
        import anthropic
    except ImportError:
        return {"available": False, "error": "module anthropic non installé"}

    headers = {}
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):  # utile seulement pour une clé non rattachée à un espace de travail
        headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    client = anthropic.Anthropic(timeout=600.0, max_retries=2, default_headers=headers or None)
    model = cc.get("modele", "claude-opus-5-5")
    user = ("DONNÉES (chiffres officiels du brief, à recopier tels quels) :\n"
            + json.dumps(payload, ensure_ascii=False, indent=1)
            + "\n\nExemples de requêtes pour ce brief : " + "; ".join(f"« {q} »" for q in search_examples(payload))
            + "\n\nRédige le brief de ce matin au format JSON demandé.")
    messages: list = [{"role": "user", "content": user}]
    tools = [{"type": "web_search_20260318", "name": "web_search",
              "max_uses": int(cc.get("recherches_web_max", 5)),
              "user_location": {"type": "approximate", "city": "Paris", "country": "FR", "timezone": "Europe/Paris"}}]
    if not cc.get("filtrage_dynamique", False):
        # Recherche « directe » : les résultats et les citations reviennent tels quels (sources fiables dans la page).
        tools[0]["allowed_callers"] = ["direct"]
    else:
        tools[0]["response_inclusion"] = "excluded"
    if cc.get("domaines_exclus"):
        tools[0]["blocked_domains"] = list(cc["domaines_exclus"])
    # Cache automatique : les tours internes de la recherche web relisent le même début de conversation à 10 % du prix.
    params = dict(model=model, max_tokens=int(cc.get("max_tokens", 16000)), system=SYSTEM, tools=tools,
                  output_config={"effort": cc.get("effort", "medium")}, cache_control={"type": "ephemeral"})
    total_cost, use_fallbacks = 0.0, True
    try:
        for _ in range(4):  # la recherche web peut renvoyer « pause_turn » : on relance la suite du tour
            try:
                if use_fallbacks:
                    resp = client.beta.messages.create(messages=messages, betas=["server-side-fallback-2026-07-01"],
                                                       fallbacks="default", **params)
                else:
                    resp = client.messages.create(messages=messages, **params)
            except anthropic.BadRequestError as e:
                if use_fallbacks and "fallback" in str(e).lower():
                    log.warning("Paramètre de repli refusé, nouvel essai sans : %s", e)
                    use_fallbacks = False
                    continue
                raise
            c = estimate_cost(resp.usage, model, cfg)
            total_cost += c
            _log_cost(cost_log, today, model, resp.usage, c)
            if resp.stop_reason == "pause_turn":
                messages = [messages[0], {"role": "assistant", "content": resp.content}]
                continue
            break
        if resp.stop_reason == "refusal":
            return {"available": False, "error": "le modèle a décliné la demande"}
        log_searches(resp.content)
        text, cites = _text_and_citations(resp.content)
        obj = extract_json(text)
        if obj is None:
            log.warning("Réponse non JSON, tentative de mise en forme")
            obj = _repair(client, model, text, cfg, cost_log, today)
        if obj is None:
            return {"available": False, "error": "réponse illisible"}
        out = clean(obj, cites)
        out["model"] = getattr(resp, "model", model)
        out["cost_usd"] = round(total_cost, 4)
        check_numbers(out, payload)
        log.info("Commentaire généré (%s), coût estimé : %.3f $", out["model"], total_cost)
        return out
    except Exception as e:  # noqa: BLE001 - la page doit sortir quoi qu'il arrive
        log.error("Commentaire indisponible : %s: %s", type(e).__name__, e)
        return {"available": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "reason": explain_error(e)}


def explain_error(e: Exception) -> str:
    """Raison courte, en français, affichée sur la page et dans la notification."""
    name, text = type(e).__name__, str(e).lower()
    if "usage limit" in text or "spend_limit" in text or "credit balance" in text:
        return "limite de dépense ou crédit Anthropic épuisé (console Anthropic > Billing)"
    if name == "AuthenticationError":
        return "clé Anthropic refusée : expirée ou supprimée ? (à recréer, puis mettre à jour le secret ANTHROPIC_API_KEY)"
    if name == "PermissionDeniedError":
        return "clé Anthropic sans autorisation suffisante"
    if "workspace" in text:
        return "clé Anthropic non rattachée à un espace de travail (recréer la clé sur « Default »)"
    if name in ("APIConnectionError", "APITimeoutError", "InternalServerError", "RateLimitError"):
        return "service Anthropic momentanément indisponible"
    return "erreur inattendue (voir les journaux GitHub Actions)"


def _repair(client, model, text, cfg, cost_log, today) -> dict | None:
    resp = client.messages.create(
        model=model, max_tokens=8000, output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": "Mets ce brief au format JSON demandé, sans rien changer au texte ni aux chiffres :\n\n" + text}])
    _log_cost(cost_log, today, model, resp.usage, estimate_cost(resp.usage, model, cfg))
    text2 = next((b.text for b in resp.content if b.type == "text"), "")
    return extract_json(text2)


def _log_cost(path: Path, today: date, model: str, usage, cost: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "modele", "tokens_entree", "tokens_cache_lus", "tokens_sortie", "recherches_web", "cout_usd_estime"])
        w.writerow([today.isoformat(), model, getattr(usage, "input_tokens", 0), getattr(usage, "cache_read_input_tokens", 0) or 0,
                    getattr(usage, "output_tokens", 0), searches, f"{cost:.4f}"])


NUM_RE = re.compile(r"[+−-]?\d[\d   ]*(?:,\d+)?\s?(?:%|bp|\$)")


def check_numbers(out: dict, payload: dict) -> None:
    """Signale dans les journaux les chiffres de marché du commentaire absents des DONNÉES (contrôle, pas de blocage)."""
    allowed = set()
    blob = json.dumps(payload, ensure_ascii=False)
    for m in NUM_RE.finditer(blob):
        allowed.add(_norm(m.group()))
    text = " ".join(out["essentiel"]) + " " + out["hier"] + " " + out["implications"]
    text_wo_links = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    unknown = sorted({m.group().strip() for m in NUM_RE.finditer(text_wo_links) if _norm(m.group()) not in allowed})
    if unknown:
        log.warning("Chiffres du commentaire absents des données (à vérifier, peuvent venir des sources citées) : %s", unknown)


def _norm(s: str) -> str:
    return re.sub(r"[\s  +]", "", s).replace("−", "-").lstrip("-")
