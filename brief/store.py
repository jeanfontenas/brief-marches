"""Historique local des séries (data/history/*.csv).

Chaque série téléchargée est fusionnée ici chaque jour. Cela sert à :
- garder la dernière valeur connue quand une source échoue ;
- construire l'historique des sources qui ne donnent que la dernière valeur ;
- ne télécharger que les derniers jours une fois l'historique constitué.
"""
from __future__ import annotations

import csv
import re
from datetime import date, timedelta
from pathlib import Path

Series = list[tuple[date, float]]


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("_")


class Store:
    def __init__(self, folder: Path, keep_years: int = 7):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.keep_years = keep_years
        self._cache: dict[str, Series] = {}

    def path(self, key: str) -> Path:
        return self.folder / f"{_safe(key)}.csv"

    def load(self, key: str) -> Series:
        if key in self._cache:
            return self._cache[key]
        p = self.path(key)
        out: Series = []
        if p.exists():
            with p.open(newline="", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) >= 2 and row[0] != "date":
                        try:
                            out.append((date.fromisoformat(row[0]), float(row[1])))
                        except ValueError:
                            continue
        out.sort()
        self._cache[key] = out
        return out

    def merge(self, key: str, new: Series) -> Series:
        """Fusionne de nouvelles valeurs (les nouvelles remplacent les anciennes à date égale)."""
        cur = dict(self.load(key))
        for d, v in new:
            cur[d] = v
        if not cur:
            return []
        cutoff = max(cur) - timedelta(days=365 * self.keep_years + 30)
        merged = sorted((d, v) for d, v in cur.items() if d >= cutoff)
        with self.path(key).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "valeur"])
            for d, v in merged:
                w.writerow([d.isoformat(), repr(round(v, 6))])
        self._cache[key] = merged
        return merged

    def since(self, key: str, today: date, years: int, overlap_days: int = 15) -> date:
        """Date à partir de laquelle télécharger : tout l'historique si vide, sinon les derniers jours."""
        s = self.load(key)
        full = today - timedelta(days=365 * years + 40)
        if len(s) < 20 or s[0][0] > full + timedelta(days=60) or (today - s[-1][0]).days > 120:
            return full
        return s[-1][0] - timedelta(days=overlap_days)
