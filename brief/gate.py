"""Décide s'il faut générer le brief maintenant (bibliothèque standard uniquement, donc très rapide).

GitHub Actions lance le workflow plusieurs fois chaque matin (heures en UTC). Ce script compare
l'heure de Paris à l'heure cible de config.yaml : le premier créneau qui tombe après
« heure_cible − avance_minutes » génère le brief, les suivants ne font rien. Le passage à
l'heure d'été ou d'hiver est ainsi géré automatiquement.

Usage : python -m brief.gate [--force]   (écrit go=true/false pour GitHub Actions)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def decide(now: datetime, heure_cible: str, avance_minutes: int, en_pause: bool,
           last_brief_date: str | None, force: bool) -> tuple[bool, str]:
    if force:
        return True, "lancement manuel"
    if en_pause:
        return False, "en pause (config.yaml : en_pause: true)"
    if now.weekday() >= 5:
        return False, "week-end"
    if last_brief_date == now.date().isoformat():
        return False, "brief déjà publié aujourd'hui"
    h, m = (int(x) for x in heure_cible.split(":"))
    start = now.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(minutes=avance_minutes)
    if now < start:
        return False, f"trop tôt (démarrage à partir de {start:%H:%M}, heure de Paris)"
    return True, "c'est l'heure"


def read_general(text: str) -> dict:
    """Lecture minimale de la section « general » de config.yaml (sans dépendance)."""
    def grab(name: str, default: str) -> str:
        m = re.search(rf"^\s+{name}:\s*\"?([^\"#\n]+?)\"?\s*(?:#.*)?$", text, re.M)
        return m.group(1).strip() if m else default
    return {"heure_cible": grab("heure_cible", "08:00"), "avance_minutes": int(grab("avance_minutes", "50")),
            "en_pause": grab("en_pause", "false").lower() == "true"}


def main() -> int:
    force = "--force" in sys.argv
    g = read_general((ROOT / "config.yaml").read_text(encoding="utf-8"))
    state_path = ROOT / "data" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    now = datetime.now(ZoneInfo("Europe/Paris"))
    go, why = decide(now, g["heure_cible"], g["avance_minutes"], g["en_pause"], state.get("last_brief_date"), force)
    print(f"{now:%Y-%m-%d %H:%M} (Paris) : {'génération' if go else 'rien à faire'} ({why})")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"go={'true' if go else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
