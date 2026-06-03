"""Heuristic source ranking (deterministic, always-on, no LLM, no dependency).

Faithfully reproduces GPTR's SMALL-INPUT cheap-filter behavior (GPTR short-circuits
and SKIPS embeddings below ~8000 chars / max_results; at our scale — a handful of
sources per issue — we are always in that regime). We therefore do the same job
WITHOUT embeddings:

  1. URL dedup — collapse near-duplicate URLs (normalize scheme/host/path; strip
     trailing slash + tracking query params) so the same page counts once.
  2. Junk drop — sources with neither a title nor a url, or whose url is an obvious
     junk host (link shorteners), are removed.
  3. Relevance — issue-keyword overlap in the title (primary) + a recency/known-
     authority heuristic (source_type + quality) as the tie-break.
  4. Top-k — cap the survivors.

A FILTER, not a rewriter: surviving sources are returned as the SAME objects,
unmodified (same shape). Pure / deterministic — no wall-clock, no env reads.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from ..models import Source, SourceQuality, SourceType

# Hosts we treat as obvious junk (link shorteners / redirectors): a source whose
# only locator is one of these carries no verifiable primary content.
_JUNK_HOSTS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly"}

# Tracking query params stripped during URL normalization so utm-tagged dups
# collapse onto the canonical URL.
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_eid", "ref")

# Authority weight by source_type (higher = more authoritative primary-ish source).
_TYPE_WEIGHT = {
    SourceType.primary: 3,
    SourceType.standard: 3,
    SourceType.internal: 2,
    SourceType.secondary: 1,
    SourceType.marketing: 0,
}

# Quality weight (the source critic's judgement, if present).
_QUALITY_WEIGHT = {
    SourceQuality.high: 3,
    SourceQuality.medium: 2,
    SourceQuality.low: 1,
    SourceQuality.unknown: 1,
}

_WORD_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return {t for t in _WORD_RE.split((text or "").lower()) if len(t) > 2}


def normalize_url(url: str | None) -> str | None:
    """Canonicalize a URL for dedup: lowercase scheme+host, drop a trailing slash,
    drop tracking query params, drop the fragment. None passes through."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    scheme = (parts.scheme or "https").lower()
    host = (parts.netloc or "").lower()
    path = parts.path.rstrip("/")
    kept_q = [
        kv for kv in parts.query.split("&")
        if kv and not any(kv.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    query = "&".join(sorted(kept_q))
    return urlunsplit((scheme, host, path, query, ""))


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urlsplit(url).netloc or "").lower()
    except ValueError:
        return ""


def _is_junk(src: Source) -> bool:
    if not (src.title or "").strip() and not (src.url or "").strip():
        return True
    if _host(src.url) in _JUNK_HOSTS:
        return True
    return False


def _authority(src: Source) -> int:
    return _TYPE_WEIGHT.get(src.source_type, 1) + _QUALITY_WEIGHT.get(src.quality, 1)


def rank(sources: list[Source], *, issue_keywords: list[str],
         top_k: int = 5) -> list[Source]:
    """Return the deduped, junk-filtered, relevance-ranked top-k sources.

    Stable: ties keep input order (Python sort is stable). Sources are returned
    unmodified (filter, not rewriter).
    """
    if not sources:
        return []

    kw = {k.lower() for k in issue_keywords if k}

    # 1+2: junk drop + URL dedup (first occurrence of a canonical URL wins; a
    # source with no URL is kept and deduped by id).
    seen_urls: set[str] = set()
    survivors: list[Source] = []
    for s in sources:
        if _is_junk(s):
            continue
        norm = normalize_url(s.url)
        if norm is not None:
            if norm in seen_urls:
                continue
            seen_urls.add(norm)
        survivors.append(s)

    # 3: score = (keyword overlap, authority). Higher first; stable on ties.
    def _relevance(s: Source) -> int:
        if not kw:
            return 0
        return len(_tokenize(s.title) & kw)

    indexed = list(enumerate(survivors))
    indexed.sort(key=lambda it: (_relevance(it[1]), _authority(it[1]), -it[0]),
                 reverse=True)
    ordered = [s for _i, s in indexed]

    # 4: cap top-k.
    return ordered[: max(0, top_k)]
