"""Outils communs : dates (heure de Paris), HTTP, journalisation."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

PARIS = ZoneInfo("Europe/Paris")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 brief-marches/1.0")

log = logging.getLogger("brief")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def now_paris() -> datetime:
    return datetime.now(PARIS)


def previous_business_day(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


class Http:
    """Session HTTP avec en-tête navigateur, délai et nouvelles tentatives."""

    def __init__(self, timeout: float = 45.0, retries: int = 3):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*"})
        self.timeout = timeout
        self.retries = retries

    def get(self, url: str, **kw) -> requests.Response:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.s.get(url, timeout=self.timeout, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                return r
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status is not None and status < 500 and status != 429:
                    break  # erreur définitive (404, 403…) : inutile de réessayer
                time.sleep(2 * (attempt + 1))
        assert last is not None
        raise last

    def post(self, url: str, **kw) -> requests.Response:
        r = self.s.post(url, timeout=self.timeout, **kw)
        r.raise_for_status()
        return r
