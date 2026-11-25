"""Live source discovery. Free services first; keyed services are optional.

For the most distinctive sentences of a submission we ask these services for documents
containing that wording, fetch their FULL text where it is openly available (HTML or
PDF), and index them as sources:

| Provider        | What                                            | Key            | Report label |
|-----------------|-------------------------------------------------|----------------|--------------|
| wikipedia       | Wikipedia articles (en, ur ...)                 | none           | Internet     |
| arxiv           | arXiv abstracts                                 | none           | Publication  |
| europepmc       | Europe PMC: full text of open-access papers     | none           | Publication  |
| openalex        | OpenAlex: 250M works, abstract + open-access PDF| optional (free)| Publication  |
| crossref        | Crossref: abstracts deposited by publishers     | none           | Publication  |
| semanticscholar | Semantic Scholar abstracts + open-access PDF    | optional (free)| Publication  |
| core            | CORE: full text of 30M+ open-access papers      | required (free)| Publication  |
| searxng         | your own SearXNG metasearch, then page fetch    | none (self-hosted) | Internet |
| brave           | Brave Search API, then page fetch               | required       | Internet     |
| google          | Google Programmable Search, then page fetch     | required       | Internet     |

Fetching obeys robots.txt, only goes to public IP addresses (no SSRF), follows at most
5 redirects (each one checked) and stops at MAX_PAGE_BYTES. Sentences of the submission
are sent to these services as search queries (that is how every web check works).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx

from engine.similarity.tokens import tokenize

USER_AGENT = "Mozilla/5.0 (compatible; HamzonicsBot/1.0; document similarity checker)"
MAX_PAGE_BYTES = 15 * 1024 * 1024
TIMEOUT = 12
PAGE_DEADLINE_S = 25  # whole download of one page/PDF
MIN_DOC_WORDS = 40

_STOPWORDS = frozenset(
    "the a an and or but of to in on at for with by from as is are was were be been being this that these those "
    "it its they them their we our you your he she his her not no can could would should may might will shall "
    "has have had do does did which who whom whose what when where why how than then there here also such into "
    "about over under between more most other some any all each very".split()
)


@dataclass(frozen=True)
class FoundDocument:
    url: str
    title: str
    text: str
    source_type: str  # "web" (Internet) | "corpus" (Publication)
    provider: str


class DocumentProvider(Protocol):
    name: str

    def find(self, phrase: str, limit: int) -> list[FoundDocument]: ...


def make_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False)


def _get(client: httpx.Client, url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response | None:
    """GET a known API (redirects allowed) with one polite retry on 429/503; None on any
    failure, so an outage of a free service never breaks a check."""
    for attempt in range(2):
        try:
            r = client.get(url, params=params, headers=headers, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if r.status_code in (429, 503) and attempt == 0:
            try:
                wait = float(r.headers.get("Retry-After", "2") or 2)
            except ValueError:
                wait = 2.0
            time.sleep(min(wait, 5))
            continue
        return r if r.status_code == 200 else None
    return None


def _strip_tags(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def _words(text: str) -> int:
    return len(text.split())


# ------------------------------------------------------------------ free providers


class WikipediaProvider:
    def __init__(self, lang: str = "en", client: httpx.Client | None = None) -> None:
        self.lang = lang
        self.name = f"wikipedia-{lang}"
        self.client = client or make_client()

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        api = f"https://{self.lang}.wikipedia.org/w/api.php"
        r = _get(self.client, api, {"action": "query", "list": "search", "srsearch": f'"{phrase}"',
                                    "srlimit": limit, "format": "json", "formatversion": 2})
        if r is None:
            return []
        out: list[FoundDocument] = []
        for hit in r.json().get("query", {}).get("search", [])[:limit]:
            page = _get(self.client, api, {"action": "query", "prop": "extracts", "explaintext": 1,
                                           "titles": hit["title"], "format": "json", "formatversion": 2})
            pages = page.json().get("query", {}).get("pages", []) if page is not None else []
            if pages and pages[0].get("extract"):
                title = pages[0]["title"]
                out.append(FoundDocument(
                    f"https://{self.lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                    title, pages[0]["extract"], "web", self.name))
        return out


class ArxivProvider:
    name = "arxiv"
    _ATOM = "{http://www.w3.org/2005/Atom}"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        r = _get(self.client, "https://export.arxiv.org/api/query",
                 {"search_query": f'abs:"{phrase}"', "max_results": limit})
        if r is None:
            return []
        out: list[FoundDocument] = []
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            return []
        for e in root.iter(f"{self._ATOM}entry"):
            url = (e.findtext(f"{self._ATOM}id") or "").strip()
            text = " ".join((e.findtext(f"{self._ATOM}summary") or "").split())
            title = " ".join((e.findtext(f"{self._ATOM}title") or "").split())
            if url and text:
                out.append(FoundDocument(url, title, text, "corpus", self.name))
        return out[:limit]


class EuropePmcProvider:
    """Searches titles, abstracts AND the full text of open-access papers; returns the
    full text (JATS XML) when the paper is open access, else the abstract."""

    name = "europepmc"
    API = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        r = _get(self.client, f"{self.API}/search",
                 {"query": f'"{phrase}"', "resultType": "core", "format": "json", "pageSize": limit})
        if r is None:
            return []
        out: list[FoundDocument] = []
        for item in r.json().get("resultList", {}).get("result", [])[:limit]:
            text = ""
            pmcid = item.get("pmcid")
            if pmcid and item.get("isOpenAccess") == "Y":
                x = _get(self.client, f"{self.API}/{pmcid}/fullTextXML")
                if x is not None:
                    text = jats_text(x.text)
            if _words(text) < MIN_DOC_WORDS:
                text = _strip_tags(item.get("abstractText") or "")
            if _words(text) < MIN_DOC_WORDS:
                continue
            url = (f"https://europepmc.org/article/PMC/{pmcid}" if pmcid
                   else f"https://europepmc.org/article/{item.get('source', 'MED')}/{item.get('id', '')}")
            out.append(FoundDocument(url, _strip_tags(item.get("title", "Europe PMC article")), text, "corpus", self.name))
        return out


def jats_text(xml: str) -> str:
    """Body paragraphs (and abstract) of a JATS article, without references and tables."""
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError:
        return ""
    parts: list[str] = []
    for tag in ("abstract", "body"):
        for sec in root.iter(tag):
            for el in sec.iter():
                if el.tag in ("p", "title"):
                    t = " ".join("".join(el.itertext()).split())
                    if t:
                        parts.append(t)
    return "\n\n".join(parts)


def _openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: list[tuple[int, str]] = [(i, w) for w, idx in inv.items() for i in idx]
    return " ".join(w for _, w in sorted(pos))


class OpenAlexProvider:
    """OpenAlex works search (title, abstract and full-text n-grams). Abstract always;
    with `fetch_fulltext` the open-access PDF / landing page is fetched too."""

    name = "openalex"

    def __init__(self, api_key: str = "", fetch_fulltext: bool = True, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.fetch_fulltext = fetch_fulltext
        self.client = client or make_client()

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        params = {"search": f'"{phrase}"', "per-page": limit,
                  "select": "id,doi,display_name,abstract_inverted_index,best_oa_location,primary_location,open_access"}
        if self.api_key:
            params["api_key"] = self.api_key
        r = _get(self.client, "https://api.openalex.org/works", params)
        if r is None:
            return []
        out: list[FoundDocument] = []
        for w in r.json().get("results", [])[:limit]:
            title = w.get("display_name") or "OpenAlex work"
            oa = w.get("best_oa_location") or {}
            landing = (w.get("primary_location") or {}).get("landing_page_url") or oa.get("landing_page_url")
            url = w.get("doi") or landing or w.get("id")
            text = ""
            if self.fetch_fulltext:
                for candidate in (oa.get("pdf_url"), oa.get("landing_page_url"), (w.get("open_access") or {}).get("oa_url")):
                    if candidate:
                        page = fetch_page_text(candidate, self.client)
                        if page is not None:
                            text, url = page[1], candidate
                            break
            if _words(text) < MIN_DOC_WORDS:
                text = _openalex_abstract(w.get("abstract_inverted_index"))
            if _words(text) >= MIN_DOC_WORDS and url:
                out.append(FoundDocument(url, title, text, "corpus", self.name))
        return out


class CrossrefProvider:
    name = "crossref"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        r = _get(self.client, "https://api.crossref.org/works",
                 {"query": phrase, "filter": "has-abstract:true", "rows": limit, "select": "DOI,title,abstract,URL"})
        if r is None:
            return []
        out: list[FoundDocument] = []
        for it in r.json().get("message", {}).get("items", [])[:limit]:
            text = _strip_tags(it.get("abstract") or "")
            if _words(text) >= MIN_DOC_WORDS:
                title = (it.get("title") or ["Crossref work"])[0]
                out.append(FoundDocument(it.get("URL") or f"https://doi.org/{it.get('DOI')}", title, text, "corpus", self.name))
        return out


class SemanticScholarProvider:
    name = "semanticscholar"

    def __init__(self, api_key: str = "", fetch_fulltext: bool = True, client: httpx.Client | None = None) -> None:
        self.headers = {"x-api-key": api_key} if api_key else None
        self.fetch_fulltext = fetch_fulltext
        self.client = client or make_client()

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        r = _get(self.client, "https://api.semanticscholar.org/graph/v1/paper/search",
                 {"query": phrase, "limit": limit, "fields": "title,abstract,url,openAccessPdf"}, self.headers)
        if r is None:
            return []
        out: list[FoundDocument] = []
        for p in r.json().get("data", [])[:limit]:
            text, url = "", p.get("url")
            pdf = (p.get("openAccessPdf") or {}).get("url")
            if self.fetch_fulltext and pdf:
                page = fetch_page_text(pdf, self.client)
                if page is not None:
                    text, url = page[1], pdf
            if _words(text) < MIN_DOC_WORDS:
                text = p.get("abstract") or ""
            if _words(text) >= MIN_DOC_WORDS and url:
                out.append(FoundDocument(url, p.get("title") or "Semantic Scholar paper", text, "corpus", self.name))
        return out


class CoreProvider:
    name = "core"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.client = client or make_client()

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        r = _get(self.client, "https://api.core.ac.uk/v3/search/works", {"q": f'"{phrase}"', "limit": limit}, self.headers)
        if r is None:
            return []
        out: list[FoundDocument] = []
        for w in r.json().get("results", [])[:limit]:
            text = w.get("fullText") or w.get("abstract") or ""
            url = w.get("downloadUrl") or (w.get("links") or [{}])[0].get("url") or f"https://core.ac.uk/works/{w.get('id')}"
            if _words(text) >= MIN_DOC_WORDS:
                out.append(FoundDocument(url, w.get("title") or "CORE work", text, "corpus", self.name))
        return out


# ------------------------------------------------------------------ web search


class _WebSearch:
    """Base: get result URLs for a phrase, then fetch each page (HTML or PDF).

    Counts searches that worked and searches that failed (blocked, CAPTCHA, rate limited,
    quota used up), so a report can say "Internet search was unavailable" instead of
    showing a misleading low score."""

    name = "web"
    is_web_search = True

    def __init__(self, client: httpx.Client | None = None) -> None:
        import threading

        self.client = client or make_client()
        self.ok = 0
        self.failed = 0
        self._lock = threading.Lock()

    def _record(self, success: bool) -> None:
        with self._lock:
            if success:
                self.ok += 1
            else:
                self.failed += 1

    def urls(self, phrase: str, limit: int) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    # Optional result cache, set by the caller: get(provider, phrase) -> urls | None; put(provider, phrase, urls)
    cache_get = None
    cache_put = None
    cache_hits = 0

    def cached_urls(self, phrase: str, limit: int) -> list[str]:
        if self.cache_get is not None:
            hit = self.cache_get(self.name, phrase)
            if hit is not None:
                with self._lock:
                    self.cache_hits += 1
                return hit[:limit]
        urls = self.urls(phrase, limit)
        if urls and self.cache_put is not None:  # only real answers are cached, never failures
            self.cache_put(self.name, phrase, urls)
        return urls

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        out: list[FoundDocument] = []
        for url in self.cached_urls(phrase, limit * 2):
            page = fetch_page_text(url, self.client)
            if page is not None:
                out.append(FoundDocument(url, page[0], page[1], "web", self.name))
            if len(out) >= limit:
                break
        return out


class SearxngProvider(_WebSearch):
    """Your OWN SearXNG instance (JSON format enabled)."""

    name = "searxng"

    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        super().__init__(client)
        self.base_url = base_url.rstrip("/")

    def urls(self, phrase: str, limit: int) -> list[str]:
        r = _get(self.client, f"{self.base_url}/search", {"q": f'"{phrase}"', "format": "json"})
        data = r.json() if r is not None else {}
        results = [res["url"] for res in data.get("results", []) if res.get("url")]
        # No results while engines report errors (CAPTCHA, 403, too many requests) = blocked,
        # not "nothing on the web".
        self._record(r is not None and (bool(results) or not data.get("unresponsive_engines")))
        return results[:limit]


class StaticKeys:
    """One fixed key (tests, or no admin-managed keys). Same interface as worker.key_pool.KeyPool."""

    def __init__(self, secret: str) -> None:
        self._key = _Key(None, secret) if secret else None

    def current(self):  # type: ignore[no-untyped-def]
        return self._key

    def record_use(self, key) -> None:  # type: ignore[no-untyped-def]
        pass

    def exhausted(self, key, reason: str) -> None:  # type: ignore[no-untyped-def]
        self._key = None

    def flush_usage(self) -> None:
        pass


@dataclass
class _Key:
    id: str | None
    secret: str


class SerperProvider(_WebSearch):
    """Google results through serper.dev (paid per search; 2,500 free at sign-up).

    `keys` is a key pool: when a key has no credits left (or is rejected) the pool drops
    it and the SAME search is repeated with the next key, so a check never fails because
    one key ran out."""

    name = "serper"
    paid = True

    def __init__(self, keys: "str | StaticKeys", client: httpx.Client | None = None) -> None:
        super().__init__(client)
        self.keys = StaticKeys(keys) if isinstance(keys, str) else keys

    def urls(self, phrase: str, limit: int) -> list[str]:
        for _ in range(50):  # at most one try per key
            key = self.keys.current()
            if key is None:
                self._record(False)  # no usable key left
                return []
            try:
                r = self.client.post("https://google.serper.dev/search", timeout=TIMEOUT,
                                     headers={"X-API-KEY": key.secret, "Content-Type": "application/json"},
                                     json={"q": f'"{phrase}"', "num": 10})
            except httpx.HTTPError:
                self._record(False)
                return []
            if r.status_code in (401, 402, 403):  # invalid key / no credits left: next key
                try:
                    reason = r.json().get("message") or r.text[:200]
                except ValueError:
                    reason = r.text[:200]
                self.keys.exhausted(key, f"HTTP {r.status_code}: {reason}")
                continue
            self.keys.record_use(key)
            self._record(r.status_code == 200)
            if r.status_code != 200:  # 429 too fast, 5xx outage: this search is lost, the key is fine
                return []
            return [x["link"] for x in r.json().get("organic", []) if x.get("link")][:limit]
        self._record(False)
        return []


class BraveProvider(_WebSearch):
    name = "brave"
    paid = True

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        super().__init__(client)
        self.headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}

    def urls(self, phrase: str, limit: int) -> list[str]:
        r = _get(self.client, "https://api.search.brave.com/res/v1/web/search",
                 {"q": f'"{phrase}"', "count": min(limit, 20)}, self.headers)
        self._record(r is not None)
        results = r.json().get("web", {}).get("results", []) if r is not None else []
        return [x["url"] for x in results if x.get("url")][:limit]


class GoogleCseProvider(_WebSearch):
    name = "google"
    paid = True

    def __init__(self, key: str, cx: str, client: httpx.Client | None = None) -> None:
        super().__init__(client)
        self.key, self.cx = key, cx

    def urls(self, phrase: str, limit: int) -> list[str]:
        r = _get(self.client, "https://www.googleapis.com/customsearch/v1",
                 {"key": self.key, "cx": self.cx, "q": f'"{phrase}"', "num": min(limit, 10)})
        self._record(r is not None)
        return [x["link"] for x in (r.json().get("items", []) if r is not None else []) if x.get("link")][:limit]


def build_providers(
    names: list[str],
    wikipedia_langs: list[str],
    searxng_url: str = "",
    *,
    openalex_key: str = "",
    semanticscholar_key: str = "",
    core_key: str = "",
    brave_key: str = "",
    google_key: str = "",
    google_cx: str = "",
    serper_key: "str | StaticKeys" = "",  # a key, or a key pool (worker.key_pool.KeyPool)
    fetch_fulltext: bool = True,
) -> list[DocumentProvider]:
    providers: list[DocumentProvider] = []
    for name in names:
        if name == "wikipedia":
            providers.extend(WikipediaProvider(lang) for lang in wikipedia_langs)
        elif name == "arxiv":
            providers.append(ArxivProvider())
        elif name == "europepmc":
            providers.append(EuropePmcProvider())
        elif name == "openalex":
            providers.append(OpenAlexProvider(openalex_key, fetch_fulltext))
        elif name == "crossref":
            providers.append(CrossrefProvider())
        elif name == "semanticscholar":
            providers.append(SemanticScholarProvider(semanticscholar_key, fetch_fulltext))
        elif name == "core" and core_key:
            providers.append(CoreProvider(core_key))
    if serper_key:
        providers.append(SerperProvider(serper_key))
    if searxng_url:
        providers.append(SearxngProvider(searxng_url))
    if brave_key:
        providers.append(BraveProvider(brave_key))
    if google_key and google_cx:
        providers.append(GoogleCseProvider(google_key, google_cx))
    return providers


def distinctive_sentences(text: str, sentences: list[tuple[int, int]], n: int = 8, max_words: int = 10) -> list[str]:
    """Search phrases from the sentences with the most long, non-stopword words, spread
    over the whole document (the best sentence of each part), in document order.
    Returned without quotes; providers add phrase syntax."""
    scored: list[tuple[int, int, str]] = []
    position: list[int] = []  # words before each scored sentence
    words_before = 0
    for idx, (s, e) in enumerate(sentences):
        words = text[s:e].split()
        start_word, words_before = words_before, words_before + len(words)
        toks = tokenize(text[s:e])
        if len(toks) < 8:
            continue
        rare = sum(1 for t in toks if len(t.norm) >= 6 and t.norm not in _STOPWORDS)
        snippet = " ".join(words[:max_words]).strip(" .,;:!?\"'“”()[]")
        snippet = re.sub(r"[\"“”\[\]()]", " ", snippet)
        snippet = re.sub(r"\s+\d{1,3}(?:\s*,\s*\d{1,3})*\s*$", "", snippet)  # trailing citation numbers
        scored.append((rare, -idx, " ".join(snippet.split())))
        position.append(start_word)
    if not scored or n <= 0:
        return []
    # Split the document into n parts of EQUAL WORD LENGTH and take the best sentence of
    # each part, so every stretch of the text is searched. (Equal sentence counts left
    # passages with long sentences unsearched: 6 of 10 copied web pages in a 4,600-word
    # test document got no search at all, 2026-11-24.)
    part_words = max(1, words_before / n)
    parts: dict[int, list[tuple[int, int, str]]] = {}
    for item, pos in zip(scored, position):
        parts.setdefault(min(n - 1, int(pos / part_words)), []).append(item)
    picks: list[tuple[int, int, str]] = [max(part, key=lambda x: (x[0], x[1])) for part in parts.values()]
    picks = sorted(picks, key=lambda x: (-x[0], -x[1]))[:n]
    seen: set[str] = set()
    out: list[str] = []
    for _, _, snippet in sorted(picks, key=lambda x: -x[1]):
        if snippet.lower() not in seen:
            seen.add(snippet.lower())
            out.append(snippet)
    return out


# ------------------------------------------------------------------ safe fetching


def is_public_url(url: str) -> bool:
    """Block SSRF: only http(s) to hosts that resolve exclusively to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except (socket.gaierror, UnicodeError, OSError):
        return False
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def robots_allows(url: str, client: httpx.Client) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _robots_cache:
        rp: urllib.robotparser.RobotFileParser | None = None
        try:
            r = client.get(f"{origin}/robots.txt", timeout=TIMEOUT, follow_redirects=True)
            if r.status_code < 400:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            rp = None
        if len(_robots_cache) > 5000:
            _robots_cache.clear()
        _robots_cache[origin] = rp
    rp = _robots_cache[origin]
    return True if rp is None else rp.can_fetch("HamzonicsBot", url)


def pdf_text(data: bytes) -> str:
    import pypdfium2

    from engine.pdfium_lock import PDFIUM_LOCK

    parts: list[str] = []
    with PDFIUM_LOCK:
        try:
            doc = pypdfium2.PdfDocument(data)
        except Exception:
            return ""
        try:
            for i in range(min(len(doc), 200)):
                page = doc[i]
                tp = page.get_textpage()
                parts.append(tp.get_text_range())
                tp.close()
                page.close()
        except Exception:
            pass  # damaged PDF: keep what was read
        finally:
            doc.close()
    text = "\n".join(parts)
    text = re.sub(r"-\n(?=[a-z])", "", text)  # hyphenated line breaks
    return re.sub(r"[ \t]*\r?\n[ \t]*", "\n", text).strip()


_INVISIBLE_TAGS = ("script", "style", "noscript", "template", "svg", "head", "iframe", "canvas", "select", "option")
_BLOCK_TAGS = frozenset("p div section article header footer nav aside main li ul ol h1 h2 h3 h4 h5 h6 tr td th "
                        "table dt dd dl blockquote pre figure figcaption form label button br hr address".split())


def visible_text(html: str) -> str:
    """All text a visitor can see, one block per line (no scripts, styles or hidden elements)."""
    import lxml.etree
    import lxml.html

    try:
        root = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return ""
    for el in root.xpath("//*[self::" + " or self::".join(_INVISIBLE_TAGS) + "]"
                         " | //*[@hidden] | //*[@aria-hidden='true']"
                         " | //*[contains(translate(@style,' ',''),'display:none')]"):
        el.drop_tree()
    lines: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        line = " ".join(" ".join(buf).split())
        if line:
            lines.append(line)
        buf.clear()

    for event, el in lxml.etree.iterwalk(root, events=("start", "end")):
        is_element = isinstance(el.tag, str)  # comments / processing instructions are not
        tag = el.tag.lower() if is_element else ""
        if event == "start":
            if tag in _BLOCK_TAGS:
                flush()
            if el.text and is_element:
                buf.append(el.text)
        else:
            if tag in _BLOCK_TAGS:
                flush()
            if el.tail:
                buf.append(el.tail)
    flush()
    # Drop consecutive duplicates (mobile + desktop copies of the same menu).
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


def fetch_page_text(url: str, client: httpx.Client | None = None) -> tuple[str, str] | None:
    """Return (title, main_text) of an HTML page or PDF, or None if not allowed / not
    reachable / no real text."""
    client = client or make_client()
    deadline = time.monotonic() + PAGE_DEADLINE_S
    for _ in range(6):  # the first request + at most 5 redirects, each one checked
        if not is_public_url(url) or not robots_allows(url, client):
            return None
        try:
            with client.stream("GET", url, timeout=TIMEOUT, follow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                ctype = r.headers.get("content-type", "").lower()
                if r.status_code != 200 or not ("html" in ctype or "pdf" in ctype or "xml" in ctype):
                    return None
                body = bytearray()
                for chunk in r.iter_bytes():
                    body.extend(chunk)
                    # A server that trickles bytes would never hit the read timeout.
                    if len(body) > MAX_PAGE_BYTES or time.monotonic() > deadline:
                        return None
                encoding = r.encoding or "utf-8"
        except httpx.HTTPError:
            return None
        break
    else:
        return None

    if body[:5] == b"%PDF-" or "pdf" in ctype:
        text = pdf_text(bytes(body))
        if _words(text) < MIN_DOC_WORDS:
            return None
        first = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 15), "")
        title = (first[:200] or urlparse(url).netloc)
        return title, text

    import trafilatura

    html = bytes(body).decode(encoding, errors="replace")
    # People copy everything they can see: headings, cards, FAQ questions, footers. Main-content
    # extraction alone dropped 40% of a business landing page (tested 2026-11-22), so the
    # source text is ALL visible text; the article extraction is the fallback.
    text = visible_text(html)
    if _words(text) < MIN_DOC_WORDS:
        text = trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True) or ""
    if _words(text) < MIN_DOC_WORDS:
        return None
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else urlparse(url).netloc)[:300]
    return title, text


__all__ = ["FoundDocument", "DocumentProvider", "build_providers", "distinctive_sentences", "fetch_page_text",
           "is_public_url", "pdf_text", "jats_text", "make_client"]
