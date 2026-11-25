# Competitor research (November 2026)

What the main checkers offer, where Hamzonics stands, and what is still missing.
Figures come from the linked pages; most accuracy numbers are vendor claims or
blog tests with different methods, so treat them as rough.

## The market

| Product | Who it is for | Similarity | AI detection | Notes |
| --- | --- | --- | --- | --- |
| **Turnitin** | Universities (HEC licenses it for ~115 Pakistani institutions) | Huge web + publisher + student-paper database | Yes; separate AI report; no score shown under 20 %; "AI bypasser" (humanizer) detection added for English in 2025–26 | Institutional, quote-only pricing; individuals are pointed to iThenticate (about $125 per paper in one listing) |
| **Copyleaks** | Enterprise, multilingual | Yes | Yes; claims 30+ languages; led one test on edited AI text | Paid |
| **Originality.ai** | Publishers / SEO | Yes | Yes; strong on raw AI text, drops a lot on paraphrased text in one test | Per-word pricing |
| **GPTZero** | Individual teachers, free tier | Limited | Yes; per-sentence view; higher false-positive figures in some studies | Freemium |
| **Scribbr** | Students | Uses Turnitin's database | Separate tool | Paid per document |
| **Check Plagiarism / CheckForPlag / DrillBit** | South Asia | Claim Urdu and other regional languages | Varies | Weekly or yearly plans |

## Where Hamzonics is already different (built and tested)

1. **Urdu first.** Urdu word counting with diacritics, Urdu sentence ends (۔ ؟),
   Urdu Wikipedia as a live source, Urdu reference headings (حوالہ جات, کتابیات),
   and a multilingual embedding model for Urdu ↔ English translation matching
   (code done; test pending PyTorch on the dev PC).
2. **Integrity flags most tools do not show:** look-alike letters, invisible
   characters, white/background-coloured text, tiny text and off-page text are found,
   counted, cleaned, and listed with locations, in DOCX and PDF. Real Urdu, Russian
   and Greek text is not falsely flagged.
3. **Transparent scoring.** Every match is labelled exact / near / paraphrase /
   translation and grouped (not cited or quoted, missing quotations, missing
   citation, cited and quoted, bibliography). Filters recompute the score instantly.
4. **Verifiable PDF.** Every page has the submission ID, page X of Y and a QR code;
   anyone can upload a PDF on the verify page and see if it is the genuine report.
5. **Free to run.** No API keys or paid services: open corpora, free live sources
   (Wikipedia en/ur, arXiv, Europe PMC) and your own repository of submissions.
6. **Privacy controls.** "Do not store my document" opt-out; files never leave the
   server except the short search phrases sent to the live sources.

## Honest gaps (what free cannot match)

- **Coverage.** Turnitin compares against billions of web pages, paid journal
  content and tens of millions of student papers. A free system only sees open
  corpora, free APIs and its own repository. It grows with every opted-in
  submission and every corpus you load, but it will miss copying from sources it has
  never seen. The report says this on the disclaimer page.
- **General web search without keys.** The only key-less option is a self-hosted
  SearXNG instance, which scrapes Google/Bing and may break their terms. It is
  built in but **off** by default; enabling it is your decision.
- **AI-writing accuracy** has to be measured on our own test set (Phase 6) before
  any number is shown. Turnitin claims about 1 % document-level false positives;
  we must reach that on Pakistani student essays before switching AI scores on.

## Roadmap to beat them where it counts (Pakistan, students, Urdu, price)

| Priority | Item | Phase |
| --- | --- | --- |
| 1 | AI-writing detection with the 20 % rule and calibration on Pakistani essays | 5–6 |
| 2 | Humanizer / AI-paraphrase sub-score | 6 |
| 3 | Code similarity (Dolos) for programming students | 7 |
| 4 | Clients, credits (1 check = 1 credit), JazzCash/Easypaisa receipt approval, frozen identical results | 8 |
| 5 | Deploy with HTTPS, backups, health checks | 9 |
| later | Load full Urdu Wikipedia and a larger English Wikipedia/arXiv snapshot; Urdu UI; block-quote detection; Crossref DOI check | – |

## Sources

- [Quetext: most reliable AI content detector 2026](https://www.quetext.com/blog/most-reliable-ai-content-detector-2026)
- [UmanWrite: AI detector comparison 2026](https://www.umanwrite.com/blog/ai-detector-comparison-2026)
- [StudySolutions: Turnitin vs GPTZero vs Originality vs Copyleaks](https://www.studysolutions.app/blog/ai-detector-comparison-2026)
- [Paper Checker: AI detector accuracy comparison 2026](https://hub.paper-checker.com/blog/ai-detector-comparison-guide-2026/)
- [Turnitin guide: AI writing detection capabilities](https://guides.turnitin.com/hc/en-us/articles/28477544839821-Turnitin-s-AI-writing-detection-capabilities)
- [Turnitin blog: AI bypassers](https://www.turnitin.ca/blog/what-are-ai-bypassers-why-should-educators-care)
- [THE Journal: Turnitin bypasser detection](https://thejournal.com/articles/2025/09/02/new-turnitin-bypasser-detection-feature-helps-identify-use-of-ai-humanizer-tools.aspx)
- [iThenticate guide: AI writing in the Similarity Report](https://guides.ithenticate.com/hc/en-us/articles/27835303398541-AI-writing-detection-in-the-new-enhanced-Similarity-Report-view)
- [SAU: HEC plagiarism policy](https://sau.edu.pk/?p=1211)
- [Dental Tribune: HEC plagiarism prevention service extension](https://pk.dental-tribune.com/news/hec-gets-extension-for-plagiarism-prevention-service)
- [SourceForge: Check Plagiarism](https://www.sourceforge.net/software/product/Check-Plagiarism)
- [OpenAlex docs: rate limits and authentication](https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication)
- [SearXNG self-hosted test](https://apiserpent.com/blog/searxng-self-hosted-serp-api-tested)
