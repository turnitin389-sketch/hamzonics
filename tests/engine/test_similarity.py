"""Phase 3 acceptance:
- a paragraph copied from a loaded Wikipedia article scores >= 90 %
- the same paragraph reworded by hand is still matched as paraphrase
- an original essay scores < 10 %
- excluding quotes lowers the score correctly
plus unit tests for winnowing, alignment, citations, scoring and web discovery."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from engine.similarity.align import align
from engine.similarity.check import check_similarity
from engine.similarity.citations import bibliography_start, build_context, citation_spans, group_for, quote_spans
from engine.similarity.fingerprint import WINDOW, K, fingerprints, gram_hashes, winnow
from engine.similarity.index import MemoryIndex, SourceDoc, build_entry
from engine.similarity.merge import Filters, RawMatch, round2, score
from engine.similarity.sentences import split_sentences
from engine.similarity.tokens import tokenize
from engine.similarity.web import (
    ArxivProvider,
    EuropePmcProvider,
    WikipediaProvider,
    build_providers,
    distinctive_sentences,
    is_public_url,
)
from tests import fixtures as fx

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "wikipedia" / "sample.jsonl"


def _torch_works() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:  # missing, or Windows DLL/runtime problem
        return False
    return True


needs_embedder = pytest.mark.skipif(not _torch_works(), reason="PyTorch cannot be loaded on this machine")


def _articles() -> dict[str, dict]:
    return {a["title"]: a for a in map(json.loads, CORPUS.read_text(encoding="utf-8").splitlines())}


ARTICLES = _articles()
AGRI = ARTICLES["Agriculture in Pakistan"]
COPIED = next(p for p in AGRI["text"].split("\n") if len(p.split()) > 70)

# Written by hand from COPIED: same facts, different words and sentence structure.
REWORDED = (
    "Pakistan's economy depends a lot on farming and its main crops, so agriculture is seen as its backbone. "
    "The Food and Agriculture Organization says that farming makes up about 23% of GDP and gives jobs to 37.4% "
    "of the country's workers. Roughly 47% of Pakistan's land is used for farming, and 82% of the farmed land "
    "gets irrigation. Wheat, rice, cotton and sugarcane are the main crops. The leading farming province is "
    "Punjab, where the main crops are wheat, rice and cotton. Most mango orchards are in the provinces of Sindh "
    "and Punjab, which makes Pakistan the fourth biggest mango producer in the world."
)

ORIGINAL_ESSAY = (
    "My grandfather has grown vegetables near Okara for forty years, and his notebook shows how the seasons "
    "have shifted. He writes down the first day the tomatoes flower and the last day he can sow spinach. "
    "In the nineteen eighties the spinach went in during early October, but now he waits until November "
    "because the soil stays hot for longer. Last summer a sudden storm flattened half of his maize, and the "
    "insurance agent never came to look at the damage. My cousins want to leave the farm and drive taxis in "
    "Lahore, which worries him more than the weather does. When I asked him what would help most, he did not "
    "mention money; he asked for a reliable forecast and a cold store in the village so that ripe produce does "
    "not rot while traders bargain over prices. I think his answer shows that small practical tools matter as "
    "much as big national plans."
)


@pytest.fixture(scope="module")
def corpus_index() -> MemoryIndex:
    index = MemoryIndex()
    for i, a in enumerate(ARTICLES.values()):
        index.add(SourceDoc(f"wiki-{i:02d}", "corpus", a["title"], a["text"], a["url"]), build_entry(a["text"], None))
    return index


@pytest.fixture(scope="module")
def embedder():  # type: ignore[no-untyped-def]
    from engine.similarity.semantic import get_embedder

    return get_embedder()


# ------------------------------------------------------------------ acceptance


def test_copied_wikipedia_paragraph_scores_90(corpus_index: MemoryIndex) -> None:
    res = check_similarity(COPIED, corpus_index)
    assert res.score.percent >= 90
    top = res.score.sources[0]
    assert corpus_index.get_source(top.source_key).title == "Agriculture in Pakistan"
    assert {m.match_type for m in res.matches} <= {"exact", "near"}


def test_original_essay_scores_below_10(corpus_index: MemoryIndex) -> None:
    assert check_similarity(ORIGINAL_ESSAY, corpus_index).score.percent < 10


def test_lightly_edited_copy_is_near_match(corpus_index: MemoryIndex) -> None:
    edited = COPIED.replace("considered", "regarded as").replace("approximately", "about")
    res = check_similarity(edited, corpus_index)
    assert res.score.percent >= 80
    assert "near" in {m.match_type for m in res.matches}


def test_excluding_quotes_lowers_score(corpus_index: MemoryIndex) -> None:
    first = COPIED.split(". ")[0] + "."  # copied sentence, put in quotation marks below
    rest = COPIED.split(". ", 2)[2]  # copied, NOT quoted
    text = f"{ORIGINAL_ESSAY}\n\nAs one source puts it, “{first}” (Food and Agriculture Organization, 2020). {rest}"
    res = check_similarity(text, corpus_index)
    groups = {m.group for m in res.matches}
    assert "cited_and_quoted" in groups

    quoted_words = sum(
        r.word_end - r.word_start for r in res.score.runs if res.matches[r.match_index].group == "cited_and_quoted"
    )
    without = score(res.matches, res.total_words, Filters(exclude_quotes=True))
    assert quoted_words >= len(first.split()) - 1
    assert without.matched_words == res.score.matched_words - quoted_words
    assert without.percent < res.score.percent
    assert without.percent == round2(100 * without.matched_words / res.total_words)


@needs_embedder
def test_reworded_paragraph_matched_as_paraphrase(embedder) -> None:  # type: ignore[no-untyped-def]
    index = MemoryIndex()
    for i, title in enumerate(["Agriculture in Pakistan", "Economy of Pakistan", "Climate change in Pakistan", "Cricket"]):
        a = ARTICLES[title]
        index.add(SourceDoc(f"w{i}", "corpus", title, a["text"], a["url"]), build_entry(a["text"], embedder))
    res = check_similarity(REWORDED, index, embedder)
    para = [m for m in res.matches if m.match_type == "paraphrase"]
    assert para, "reworded text was not matched"
    assert all(index.get_source(m.source_key).title == "Agriculture in Pakistan" for m in para)
    assert res.score.percent >= 50
    # and the original essay stays low with embeddings switched on
    assert check_similarity(ORIGINAL_ESSAY, index, embedder).score.percent < 10


@needs_embedder
def test_urdu_translation_matched_cross_language(embedder) -> None:  # type: ignore[no-untyped-def]
    index = MemoryIndex()
    a = ARTICLES["Agriculture in Pakistan"]
    index.add(SourceDoc("w", "corpus", a["title"], a["text"], a["url"]), build_entry(a["text"], embedder))
    urdu = "پنجاب ملک کا سب سے اہم زرعی صوبہ ہے، جہاں گندم، چاول اور کپاس اس کی بنیادی فصلیں ہیں۔"
    res = check_similarity(urdu, index, embedder)
    assert [m.match_type for m in res.matches] == ["crosslang"]


# ------------------------------------------------------------------ units


def test_winnowing_guarantee() -> None:
    hashes = gram_hashes(tokenize(fx.essay(2)))
    picked = set(winnow(hashes))
    # every window of WINDOW consecutive hashes contains a picked position
    for start in range(len(hashes) - WINDOW + 1):
        assert picked & set(range(start, start + WINDOW))
    fps = fingerprints(tokenize("a b c d e"))
    assert len(fps) == 1 and fps[0].char_start == 0 and fps[0].char_end == 9


def test_align_exact_and_case_insensitive() -> None:
    src = tokenize("Intro words here. " + COPIED + " Outro words.")
    q = tokenize(COPIED.upper())
    regions = align(q, src)
    assert len(regions) == 1 and regions[0].kind == "exact" and regions[0].words == len(q)


def test_align_ignores_short_overlap() -> None:
    assert align(tokenize("one two three four"), tokenize("one two three four")) == []  # < K words


def test_citation_detection() -> None:
    t = 'He said "water is life" (Khan, 2019). Smith et al. (2020) disagree [3].\n\nReferences\nKhan, A. (2019).'
    assert len(quote_spans(t)) == 1
    assert len(citation_spans(t)) == 3
    assert bibliography_start("Body text. " * 10 + "\nReferences\nKhan 2019") is not None
    assert bibliography_start("References\nat the very top") is None


def test_groups() -> None:
    # A citation counts for the sentence it is in and the sentence before it.
    t = (
        "Plain copied sentence here. “Quoted copied words here”. A filler sentence. "
        "Cited copied words (Ali, 2021). Next one."
    )
    ctx = build_context(t, split_sentences(t))
    s = t.index("Plain")
    assert group_for(ctx, s, s + 26) == "not_cited_or_quoted"
    q = t.index("Quoted")
    assert group_for(ctx, q, q + 24) == "missing_citation"
    c = t.index("Cited")
    assert group_for(ctx, c, c + 19) == "missing_quotations"


def _m(ws: int, we: int, key: str, kind: str = "exact", group: str = "not_cited_or_quoted") -> RawMatch:
    return RawMatch(ws, we, 0, 0, key, 0, 0, kind, group, 1.0)


def test_word_assignment_priority_and_filters() -> None:
    matches = [_m(0, 10, "b", "paraphrase"), _m(0, 6, "a"), _m(20, 30, "b")]
    sc = score(matches, 100)
    assert sc.matched_words == 20 and sc.percent == 20.0
    assert {s.source_key: s.words for s in sc.sources} == {"a": 6, "b": 14}  # exact beats paraphrase
    # Excluding source a gives its words to b's paraphrase match.
    sc2 = score(matches, 100, Filters(exclude_sources=frozenset({"a"})))
    assert sc2.matched_words == 20 and sc2.sources[0].source_key == "b"
    assert score(matches, 100, Filters(min_words=8)).matched_words == 20  # 6-word match dropped, b covers 0-10
    assert score([], 0).percent == 0.0
    assert round2(12.345) == 12.35 and round2(2 / 3 * 100) == 66.67


def test_distinctive_sentences_and_ssrf_guard() -> None:
    text = ORIGINAL_ESSAY
    qs = distinctive_sentences(text, split_sentences(text), n=3)
    assert len(qs) == 3 and all(len(q.split()) <= 10 and '"' not in q for q in qs)
    assert not is_public_url("http://127.0.0.1/admin")
    assert not is_public_url("http://localhost:8000/")
    assert not is_public_url("file:///etc/passwd")
    assert not is_public_url("http://169.254.169.254/latest/meta-data")


def _mock(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_wikipedia_provider_returns_full_article() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "key" not in str(request.url).lower()  # no API key anywhere
        if request.url.params.get("list") == "search":
            assert request.url.params["srsearch"] == '"major crops include wheat"'
            return httpx.Response(200, json={"query": {"search": [{"title": "Agriculture in Pakistan"}]}})
        return httpx.Response(200, json={"query": {"pages": [{"title": "Agriculture in Pakistan", "extract": AGRI["text"]}]}})

    docs = WikipediaProvider("en", _mock(handler)).find("major crops include wheat", 2)
    assert [d.title for d in docs] == ["Agriculture in Pakistan"]
    assert docs[0].url == "https://en.wikipedia.org/wiki/Agriculture_in_Pakistan"
    assert docs[0].source_type == "web" and docs[0].text == AGRI["text"]


def test_publication_providers_parse_responses() -> None:
    atom = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1</id>'
        "<title>T</title><summary>An abstract about wheat.</summary></entry></feed>"
    )
    arxiv = ArxivProvider(_mock(lambda r: httpx.Response(200, text=atom))).find("wheat", 2)
    assert arxiv[0].url == "http://arxiv.org/abs/1" and arxiv[0].source_type == "corpus"

    abstract = "Rice yields in Punjab rose after new irrigation schemes. " * 8
    pmc_json = {"resultList": {"result": [{"id": "9", "source": "MED", "title": "P", "abstractText": f"<p>{abstract}</p>"}]}}
    pmc = EuropePmcProvider(_mock(lambda r: httpx.Response(200, json=pmc_json))).find("rice", 2)
    assert pmc[0].text == abstract.strip() and pmc[0].url.endswith("/MED/9")

    # Open-access paper: the full text (JATS body) is used, not just the abstract.
    body = " ".join(["Storage temperature of medicines was recorded in every pharmacy."] * 10)
    oa_json = {"resultList": {"result": [{"id": "1", "pmcid": "PMC1", "isOpenAccess": "Y", "title": "OA", "abstractText": "short"}]}}
    jats = f"<article><front><abstract><p>Short abstract.</p></abstract></front><body><sec><title>Methods</title><p>{body}</p></sec></body><back><ref-list><ref>Ref 1</ref></ref-list></back></article>"

    def oa_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/fullTextXML"):
            return httpx.Response(200, text=jats)
        return httpx.Response(200, json=oa_json)

    full = EuropePmcProvider(_mock(oa_handler)).find("storage", 2)
    assert body in full[0].text and "Ref 1" not in full[0].text
    assert full[0].url == "https://europepmc.org/article/PMC/PMC1"


def test_openalex_and_crossref_parse_abstracts() -> None:
    from engine.similarity.web import CrossrefProvider, OpenAlexProvider

    words = "community pharmacies stored medicines above the recommended temperature in summer months".split()
    inv: dict[str, list[int]] = {}
    for i, w in enumerate(words * 4):
        inv.setdefault(w, []).append(i)
    oa_json = {"results": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "display_name": "Storage study",
                            "abstract_inverted_index": inv, "best_oa_location": None, "primary_location": None}]}
    docs = OpenAlexProvider(fetch_fulltext=False, client=_mock(lambda r: httpx.Response(200, json=oa_json))).find("storage", 2)
    assert docs[0].text == " ".join(words * 4) and docs[0].url == "https://doi.org/10.1/x"
    assert docs[0].source_type == "corpus"

    abstract = "<jats:p>" + " ".join(words * 4) + "</jats:p>"
    cr_json = {"message": {"items": [{"DOI": "10.1/y", "title": ["T"], "abstract": abstract, "URL": "https://doi.org/10.1/y"}]}}
    cr = CrossrefProvider(_mock(lambda r: httpx.Response(200, json=cr_json))).find("storage", 2)
    assert cr[0].text == " ".join(words * 4)


def test_pdf_text_and_jats() -> None:
    from engine.similarity.web import jats_text, pdf_text

    pdf = fx.make_pdf(Path(__import__("tempfile").mkdtemp()) / "x.pdf", [fx.essay(1)])
    assert "Punjab" in pdf_text(pdf.read_bytes()) or len(pdf_text(pdf.read_bytes()).split()) > 20
    assert jats_text("<article><body><p>A  b</p></body></article>") == "A b"

    # PDFium is not thread-safe: many threads reading PDFs at once must not crash the process.
    from concurrent.futures import ThreadPoolExecutor

    data = pdf.read_bytes()
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: pdf_text(data), range(64)))
    assert len(set(results)) == 1 and results[0]
    assert jats_text("not xml <") == ""


def test_visible_text_keeps_headings_and_drops_hidden() -> None:
    from engine.similarity.web import visible_text

    html = (
        "<html><head><title>T</title><style>.x{}</style></head><body>"
        "<nav><a href='/'>About Us</a><a>Contact</a></nav>"
        "<h1>The Dental Billing Company That Closes The Gap</h1>"
        "<div class='card'><p>Real-time insurance <b>verification</b> before every appointment.</p></div>"
        "<!-- secret comment --><script>var a = 1;</script>"
        "<div style='display: none'>hidden text</div><p hidden>also hidden</p>"
        "<details><summary>Should I outsource dental billing?</summary></details>"
        "</body></html>"
    )
    text = visible_text(html)
    assert "The Dental Billing Company That Closes The Gap" in text
    assert "Real-time insurance verification before every appointment." in text
    assert "Should I outsource dental billing?" in text
    for hidden in ("secret comment", "var a", "hidden text", "also hidden", ".x{}"):
        assert hidden not in text


def test_provider_outage_returns_nothing() -> None:
    down = _mock(lambda r: httpx.Response(500))
    for p in (WikipediaProvider("en", down), ArxivProvider(down), EuropePmcProvider(down)):
        assert p.find("anything", 2) == []


def test_build_providers_from_names() -> None:
    names = [p.name for p in build_providers(["wikipedia", "arxiv", "europepmc", "openalex", "crossref", "core"], ["en", "ur"])]
    # CORE needs a (free) key: without one it is skipped.
    assert names == ["wikipedia-en", "wikipedia-ur", "arxiv", "europepmc", "openalex", "crossref"]
    assert build_providers([], ["en"]) == []
    keyed = [p.name for p in build_providers([], ["en"], "http://searx:8080", brave_key="b", google_key="g", google_cx="c",
                                             serper_key="s")]
    assert keyed == ["serper", "searxng", "brave", "google"]


def test_serper_provider_parses_google_results_and_counts_failures() -> None:
    from engine.similarity.web import SerperProvider

    def ok(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.headers["X-API-KEY"] == "k"
        assert json.loads(request.content)["q"] == '"major crops include wheat"'
        return httpx.Response(200, json={"organic": [{"link": "https://a.example/1"}, {"link": "https://b.example/2"}]})

    p = SerperProvider("k", _mock(ok))
    assert p.urls("major crops include wheat", 5) == ["https://a.example/1", "https://b.example/2"]
    assert (p.ok, p.failed) == (1, 0) and p.paid

    no_credit = SerperProvider("k", _mock(lambda r: httpx.Response(403, json={"message": "Not enough credits"})))
    assert no_credit.urls("x", 5) == [] and (no_credit.ok, no_credit.failed) == (0, 1)


def test_paid_search_gets_fewer_phrases(app_env) -> None:  # type: ignore[no-untyped-def]
    from api.config import Settings
    from api.db import get_sessionmaker
    from worker.web_sources import discover_web_sources

    class Counter:
        def __init__(self, name: str, paid: bool) -> None:
            self.name, self.paid, self.calls = name, paid, 0

        def find(self, phrase: str, limit: int) -> list:
            self.calls += 1
            return []

    free, paid = Counter("free", False), Counter("serper", True)
    text = " ".join(f"Sentence number {i} talks about irrigation canals, groundwater depletion and wheat harvests."
                    for i in range(60))
    settings = Settings(secret_key="x" * 40, web_search_max_queries=24, paid_search_max_queries=6,  # type: ignore[call-arg]
                        paid_search_words_per_query=1000, paid_search_query_cap=60)
    with get_sessionmaker()() as db:
        discover_web_sources(db, text, split_sentences(text), settings, None, providers=[free, paid])  # type: ignore[arg-type]
    assert free.calls == 24 and paid.calls == 6  # 720 words / 1000 per query -> the minimum, 6


def test_paid_query_count_scales_with_length() -> None:
    from api.config import Settings
    from worker.web_sources import paid_query_count

    s = Settings(secret_key="x" * 40, paid_search_max_queries=12, paid_search_words_per_query=100,  # type: ignore[call-arg]
                 paid_search_query_cap=60)
    assert paid_query_count(300, s) == 12  # short documents: the minimum
    assert paid_query_count(4643, s) == 47  # one per 100 words
    assert paid_query_count(50000, s) == 60  # long documents: the cap


def test_distinctive_sentences_cover_every_stretch_of_text() -> None:
    # Ten 'sources' of different sentence lengths: equal-WORD parts give each one a phrase.
    blocks = []
    for i in range(10):
        length = 6 if i % 2 else 2  # sentences per block; long blocks have long sentences
        word = f"topic{i}alpha"
        blocks.append(" ".join(f"The {word} measurement number {j} describes extraordinary {word} conditions"
                               + (" with considerable additional explanatory material attached" * (3 if length == 2 else 0)) + "."
                               for j in range(length)))
    text = " ".join(blocks)
    phrases = distinctive_sentences(text, split_sentences(text), n=10)
    assert {next(i for i in range(10) if f"topic{i}alpha" in p) for p in phrases} == set(range(10))
