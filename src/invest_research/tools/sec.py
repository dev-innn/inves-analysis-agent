from __future__ import annotations

import hashlib
import random
import re
import threading
import time
from datetime import date
from urllib.parse import urlparse

import httpx

from ..schemas import Candidate, Source, utcnow


class TemporaryUpstreamError(RuntimeError):
    pass


class SecClient:
    _lock = threading.Lock()
    _next_request = 0.0
    _cache: dict[str, tuple[float, dict]] = {}

    def __init__(self, user_agent: str, transport: httpx.BaseTransport | None = None):
        if not user_agent or "@" not in user_agent:
            raise ValueError("SEC_USER_AGENT must include an organization and contact email")
        self.client = httpx.Client(headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=httpx.Timeout(30, connect=10), transport=transport, follow_redirects=False)

    def _get(self, url: str) -> httpx.Response:
        if urlparse(url).hostname not in {"www.sec.gov", "data.sec.gov"} or not url.startswith("https://"):
            raise ValueError("Only SEC HTTPS hosts are allowed")
        for attempt in range(3):
            with self._lock:
                now = time.monotonic()
                wait = max(0, self._next_request - now)
                type(self)._next_request = max(now, self._next_request) + 0.125
            if wait:
                time.sleep(wait)
            try:
                response = self.client.get(url)
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise TemporaryUpstreamError(str(exc)) from exc
                time.sleep((2**attempt) + random.random())
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == 2:
                    raise TemporaryUpstreamError(f"SEC HTTP {response.status_code}")
                delay = response.headers.get("Retry-After")
                time.sleep(min(float(delay), 30) if delay and delay.isdigit() else (2**attempt) + random.random())
                continue
            response.raise_for_status()
            return response
        raise TemporaryUpstreamError("SEC unavailable")

    def json(self, url: str) -> dict:
        with self._lock:
            cached = self._cache.get(url)
            if cached and time.monotonic() - cached[0] < (86_400 if url.endswith("company_tickers.json") else 900):
                return cached[1]
        data = self._get(url).json()
        with self._lock:
            self._cache[url] = (time.monotonic(), data)
        return data

    @staticmethod
    def _norm(value: str) -> str:
        value = re.sub(r"\b(inc|corp|corporation|company|co|ltd|plc)\b", "", value.lower())
        return re.sub(r"[^a-z0-9]", "", value)

    def candidates(self, company_name: str, ticker: str | None = None) -> list[Candidate]:
        data = self.json("https://www.sec.gov/files/company_tickers.json")
        entries = [Candidate(cik=int(v["cik_str"]), ticker=v["ticker"], legal_name=v["title"]) for v in data.values()]
        tick = (ticker or company_name).upper().strip()
        matches = [e for e in entries if e.ticker.upper() == tick]
        if matches:
            return matches
        query = self._norm(company_name)
        exact = [e for e in entries if self._norm(e.legal_name) == query]
        if exact:
            return exact[:10]
        return [e for e in entries if query and query in self._norm(e.legal_name)][:10]

    def submissions(self, cik: int) -> dict:
        return self.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")

    def company_facts(self, cik: int) -> dict:
        return self.json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")

    def filings(self, cik: int, as_of: date, max_per_form: int = 5) -> list[dict]:
        recent = self.submissions(cik)["filings"]["recent"]
        result = []
        counts = {"10-K": 0, "10-Q": 0}
        for i, form in enumerate(recent["form"]):
            if form not in counts or counts[form] >= max_per_form or recent["filingDate"][i] > as_of.isoformat():
                continue
            accession = recent["accessionNumber"][i]
            primary = recent["primaryDocument"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{primary}"
            result.append({"form": form, "accession": accession, "filed_at": recent["filingDate"][i], "url": url, "primary_document": primary})
            counts[form] += 1
        return result

    def filing_source(self, filing: dict) -> Source:
        return Source(source_id=f"sec-{filing['accession']}", type="sec_filing", title=f"SEC {filing['form']} {filing['filed_at']}", url=filing["url"], publisher="SEC", published_at=filing["filed_at"], accession=filing["accession"])

    def download_filing(self, url: str, max_bytes: int = 15_000_000) -> tuple[bytes, str]:
        response = self._get(url)
        content = response.content
        if len(content) > max_bytes:
            raise ValueError("Filing exceeds size limit")
        kind = "pdf" if content.startswith(b"%PDF-") else "html" if b"<html" in content[:2000].lower() or b"<xbrl" in content[:2000].lower() else "unknown"
        if kind == "unknown":
            raise ValueError("Unsupported filing content")
        return content, hashlib.sha256(content).hexdigest()
