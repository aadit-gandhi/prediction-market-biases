"""Small polite HTTP helper with retry/backoff for public APIs."""
from __future__ import annotations

import time

import requests

HEADERS = {"User-Agent": "pm-bias-research/0.1 (student research project)"}


def get_json(url: str, params: dict | None = None, retries: int = 6, pause: float = 0.25):
    """GET a JSON endpoint, backing off on HTTP 429 / transient 5xx errors."""
    for attempt in range(retries):
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        time.sleep(pause)  # be gentle with rate limits
        return r.json()
    raise RuntimeError(f"Too many failed attempts for {url}")
