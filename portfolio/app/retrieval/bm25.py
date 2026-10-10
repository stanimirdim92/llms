"""BM25 sparse vectors for hybrid retrieval (`HYBRID_SEARCH`), computed here rather than by a model.

Dense retrieval is weakest exactly where this corpus is densest: dataset names, model names,
version numbers and figures ("KILT-100w", "bge-large-en-v1.5", "152.9 ms"). An embedding maps
those near anything that looks similar; a term match finds the one passage that contains them.

Split the BM25 way Qdrant's own `Qdrant/bm25` model splits it: the **term-frequency** half lives
in the stored document vector (saturated by `K1`, normalised by length with `B`), and the **IDF**
half is applied by Qdrant at query time from the collection's statistics (`Modifier.IDF` on the
sparse vector), so it stays correct as documents are added without re-indexing anything.

Plain code, not `fastembed`: tokenising and counting is deterministic work (root rule 5), and the
library would add onnxruntime plus a Hugging Face download at first use, which is a cassette miss
in CI for the same reason Voyage's tokenizer was (`app/eval/replay.py`).
"""

from __future__ import annotations

import re
import zlib
from collections import Counter

from qdrant_client.models import SparseVector

K1 = 1.2
B = 0.75
AVG_DOC_TOKENS = 256
"""Expected chunk length in tokens for length normalisation. A fixed estimate, as in Qdrant's own
BM25 config (`avg_len`), not a collection statistic: chunks are capped at `chunk_max_tokens` (700),
so the spread is narrow and an exact average would barely move a score."""

_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-_/][a-z0-9]+)*")
"""Keeps compound identifiers whole (`bge-large-en-v1.5`, `2609.22100`, `0.875`), because the whole
string is the thing an exact-term query is looking for. Their parts are added separately below."""

_STOPWORD_TEXT = (
    "a an and are as at be by can do does did for from had has have how i if in into is it its of "
    "on or that the their them then there these they this to was were what when where which who "
    "whom why will with would you your my me we our us"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())
"""Mostly question words, and not for the usual reason. IDF is computed over *documents*, where
"what", "which" and "does" are rare -- so in a *question* they would score as distinctive terms and
pull in whichever chunk happens to contain them."""


def tokens(text: str) -> list[str]:
    """Lower-cased terms: each compound identifier, plus its parts, minus stopwords."""
    out: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        parts = re.split(r"[.\-_/]", token)
        candidates = [token, *parts] if len(parts) > 1 else [token]
        out.extend(t for t in candidates if t and t not in _STOPWORDS)
    return out


def _index(term: str) -> int:
    """A stable term id. `crc32`, not `hash()`: Python salts `hash()` per process, so the api, the
    worker and a later re-index would disagree about every term.
    """
    return zlib.crc32(term.encode()) & 0x7FFFFFFF


def _vector(weights: dict[int, float]) -> SparseVector:
    return SparseVector(indices=list(weights), values=list(weights.values()))


def document_vector(text: str) -> SparseVector:
    """BM25 term-frequency weights for one chunk. IDF is not here; Qdrant applies it."""
    terms = tokens(text)
    counts = Counter(_index(term) for term in terms)
    norm = K1 * (1 - B + B * len(terms) / AVG_DOC_TOKENS)
    return _vector({index: tf * (K1 + 1) / (tf + norm) for index, tf in counts.items()})


def query_vector(text: str) -> SparseVector:
    """Each distinct query term once, weight 1: the score is then the sum of matched terms' IDF x TF."""
    return _vector(dict.fromkeys((_index(term) for term in tokens(text)), 1.0))
