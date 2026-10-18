"""BM25 search with date filtering. Pure Python so it runs air-gapped with no
embedding service. An embedding re-ranker can sit on top where one is
authorized; lexical search is the floor, and it's easy to explain to a
records officer why a document matched."""

import math
import re
from collections import Counter

from .corpus import Document

STOPWORDS = set("""a an and any are as at be by copies copy all for from have i in including
into is it its me my of on or our please provide record records regarding related relating
request requesting such that the their them this to under was were with would documents
document information concerning about pertaining fga want need like see showing""".split())

# Small, auditable synonym table. In production this comes from the agency's
# records taxonomy, not from a model.
SYNONYMS = {
    "internet": ["broadband"], "broadband": ["internet"],
    "awards": ["award", "selection", "selected", "awarded"], "award": ["awards", "selection"],
    "audit": ["oig", "improper"], "oig": ["audit", "inspector"],
    "cyber": ["security", "phishing", "incident"], "hack": ["phishing", "compromised", "incident"],
    "breach": ["incident", "compromised", "phishing"],
    "match": ["cost-share"], "cost-share": ["match"],
    "budget": ["justification", "appropriations"],
    "contract": ["vendor", "procurement"], "vendor": ["contract"],
    "travel": ["itinerary", "visit", "schedule"],
    "water": ["wastewater", "drinking"],
    "complaint": ["complain", "rejected"],
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower()) if t not in STOPWORDS]


def expand(terms: list[str]) -> list[str]:
    out = list(terms)
    for t in terms:
        out += SYNONYMS.get(t, [])
    return out


class Index:
    def __init__(self, docs: list[Document], k1: float = 1.4, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(d.title + " " + d.title + " " + d.body)) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / len(self.len)
        df = Counter(t for c in self.tf for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 5, years: tuple[int, int] | None = None,
               min_score: float = 0.5) -> list[tuple[Document, float, list[str]]]:
        terms = expand(tokenize(query))
        results = []
        for doc, tf, length in zip(self.docs, self.tf, self.len):
            if years and not (years[0] <= doc.year <= years[1]):
                continue
            score, matched = 0.0, []
            for t in set(terms):
                f = tf.get(t, 0)
                if not f:
                    continue
                matched.append(t)
                score += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg))
            if score >= min_score:
                results.append((doc, round(score, 3), sorted(matched)))
        results.sort(key=lambda r: -r[1])
        return results[:k]
