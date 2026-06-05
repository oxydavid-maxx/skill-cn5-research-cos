"""P9 §B — fetch a web-found doc/PDF and extract it (so public datasheets get READ, not just
search-snippeted). Deterministic; the LLM does not decide here."""
from __future__ import annotations
import logging, os, urllib.request
from pathlib import Path
from .doc_extract import extract_doc
logger = logging.getLogger("cn5_research_cos.retrieval")

_DOC_EXT = (".pdf",)


def is_doc_url(url: str | None) -> bool:
    if not url:
        return False
    path = url.split("?", 1)[0].lower()
    return any(path.endswith(ext) for ext in _DOC_EXT)


def _download(url: str, dest: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # noqa: S310
        f.write(r.read())
    return dest


def fetch_and_extract(url: str, *, base_dir: str = "runs", run_id: str = "_docs") -> tuple[str, str]:
    """Download a doc URL into the reference store + extract. Returns (text, backend); ("","none") on failure."""
    try:
        d = Path(base_dir) / run_id / "reference" / "fetched"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / (os.path.basename(url.split("?", 1)[0]) or "doc.pdf")
        _download(url, dest)
        return extract_doc(str(dest))
    except Exception as e:  # noqa: BLE001 - visible gap, never raise into the loop
        logger.warning("fetch_and_extract failed for %s: %s: %s", url, type(e).__name__, e)
        return "", "none"
