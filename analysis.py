import json
import math
import re
from collections import Counter
from itertools import combinations
from typing import Any

from openai import AuthenticationError, OpenAI

from config import get_secret


STOP_WORDS = {
    "about", "after", "also", "been", "being", "between", "both", "could", "does", "from", "have", "into",
    "more", "most", "other", "over", "same", "should", "some", "such", "than", "that", "their", "them",
    "there", "these", "they", "this", "those", "through", "using", "what", "when", "where", "which", "while",
    "with", "would", "your", "will", "www", "https", "http", "com", "readme", "project", "projects", "github",
}
CAPABILITY_TERMS = {
    "authentication & identity": {"auth", "authentication", "authorization", "oauth", "jwt", "session", "identity", "sso", "login", "password"},
    "API & web services": {"api", "http", "rest", "graphql", "websocket", "middleware", "router", "server", "endpoint", "request"},
    "data & storage": {"database", "storage", "sql", "postgres", "mysql", "redis", "cache", "vector", "search", "query", "data"},
    "messaging & events": {"message", "messaging", "queue", "kafka", "event", "events", "pubsub", "stream", "webhook"},
    "observability": {"logging", "metrics", "monitoring", "tracing", "telemetry", "observability", "alerts", "debug"},
    "deployment & infrastructure": {"docker", "kubernetes", "deploy", "deployment", "cloud", "terraform", "container", "scaling", "infrastructure"},
    "developer workflow": {"cli", "plugin", "sdk", "library", "framework", "testing", "configuration", "automation", "integration"},
}


def _symmetrize(raw: dict[str, set[str]]) -> dict[str, set[str]]:
    result = {category: set(neighbors) for category, neighbors in raw.items()}
    for category, neighbors in raw.items():
        for neighbor in neighbors:
            result.setdefault(neighbor, set()).add(category)
    return result


# Categories that typically compose well together even though they cover different concerns,
# e.g. an auth library is usually middleware *for* an API framework, not a competitor to it.
CAPABILITY_ADJACENCY = _symmetrize({
    "authentication & identity": {"API & web services", "developer workflow", "deployment & infrastructure"},
    "API & web services": {"data & storage", "messaging & events", "observability", "developer workflow", "deployment & infrastructure"},
    "data & storage": {"observability", "messaging & events", "deployment & infrastructure"},
    "messaging & events": {"observability", "deployment & infrastructure"},
    "observability": {"deployment & infrastructure"},
    "developer workflow": {"deployment & infrastructure"},
})

COMPOSABILITY_WEIGHTS = {"category": 0.55, "mention": 0.30, "similarity": 0.15}
REDUNDANCY_WEIGHTS = {"category": 0.6, "similarity": 0.4}
UNRELATED_THRESHOLD = 20
# S-TIER needs strong complementary focus AND evidence the projects reference each other
# (weights below make 75 unreachable without a mention); A-TIER is a solid complementary pair.
S_TIER_THRESHOLD = 75
A_TIER_THRESHOLD = 40
# Cosine similarity at which the similarity term maxes out. Complementary projects rarely
# share much vocabulary (median 0.02 on real READMEs), so this is a small tiebreaker only.
SIMILARITY_FULL_CREDIT = 0.10

# A capability area is a project's "primary" focus only if it holds at least this share of the
# README's capability-keyword hits (at most MAX_PRIMARY_CATEGORIES are kept). Counting any single
# keyword mention made nearly every README "about" API + auth + workflow.
PRIMARY_SHARE_MIN = 0.25
MAX_PRIMARY_CATEGORIES = 2


def local_ngram_counts(text: str) -> Counter:
    """Unigram + bigram term frequencies for TF-IDF.

    Bigrams are built on truly-adjacent raw words (before stopword filtering) so phrases like
    "rate limiting" survive as a unit, then dropped if either side is a stopword.
    """
    raw_words = [word.strip(".-") for word in re.findall(r"[a-z][a-z0-9+#.-]{2,}", text.lower())]
    raw_words = [word for word in raw_words if len(word) >= 3]
    unigrams = [word for word in raw_words if word not in STOP_WORDS]
    bigrams = [
        f"{first} {second}"
        for first, second in zip(raw_words, raw_words[1:])
        if first not in STOP_WORDS and second not in STOP_WORDS
    ]
    return Counter(unigrams + bigrams)


def compute_tfidf_vectors(term_counts: dict[str, Counter]) -> dict[str, dict[str, float]]:
    """repo -> sparse {term: tfidf_weight}, corpus = just the batch of repos being analyzed now."""
    num_docs = len(term_counts)
    document_frequency: Counter = Counter()
    for counts in term_counts.values():
        document_frequency.update(counts.keys())

    vectors = {}
    for repo, counts in term_counts.items():
        total_terms = sum(counts.values()) or 1
        vectors[repo] = {
            term: (frequency / total_terms) * (math.log((1 + num_docs) / (1 + document_frequency[term])) + 1)
            for term, frequency in counts.items()
        }
    return vectors


def cosine_similarity(vector_a: dict[str, float], vector_b: dict[str, float]) -> float:
    shared_terms = vector_a.keys() & vector_b.keys()
    dot_product = sum(vector_a[term] * vector_b[term] for term in shared_terms)
    norm_a = math.sqrt(sum(weight * weight for weight in vector_a.values()))
    norm_b = math.sqrt(sum(weight * weight for weight in vector_b.values()))
    return dot_product / (norm_a * norm_b) if norm_a and norm_b else 0.0


def top_shared_terms(vector_a: dict[str, float], vector_b: dict[str, float], limit: int = 6) -> list[str]:
    """Shared terms ranked by contribution to cosine similarity, for display."""
    shared_terms = vector_a.keys() & vector_b.keys()
    return sorted(shared_terms, key=lambda term: vector_a[term] * vector_b[term], reverse=True)[:limit]


def local_category_shares(counts: Counter) -> dict[str, float]:
    """Each capability area's share (0-1) of a README's capability-keyword hits."""
    hits = {category: sum(counts[term] for term in terms) for category, terms in CAPABILITY_TERMS.items()}
    total = sum(hits.values())
    return {category: count / total for category, count in hits.items() if count} if total else {}


def primary_categories(shares: dict[str, float]) -> set[str]:
    """The one or two capability areas a project is actually about."""
    ranked = sorted(shares, key=lambda category: (-shares[category], category))
    chosen = [category for category in ranked if shares[category] >= PRIMARY_SHARE_MIN][:MAX_PRIMARY_CATEGORIES]
    return set(chosen or ranked[:1])


def complementary_pairs(shares_a: dict[str, float], shares_b: dict[str, float]) -> dict[tuple[str, str], float]:
    """Adjacent primary areas that differ between the two projects, keyed (area_in_a, area_in_b).

    The value is how strongly *both* projects are focused there (the weaker of the two shares).
    Areas both projects share are competition, not complementarity, so they are excluded.
    """
    primary_a, primary_b = primary_categories(shares_a), primary_categories(shares_b)
    return {
        (area_a, area_b): min(shares_a[area_a], shares_b[area_b])
        for area_a in primary_a - primary_b
        for area_b in primary_b - primary_a
        if area_b in CAPABILITY_ADJACENCY.get(area_a, set())
    }


GENERIC_ALIASES = {
    "server", "client", "utils", "tools", "common", "library", "framework", "plugin", "plugins",
    "module", "modules", "service", "services", "backend", "frontend", "example", "examples",
    "starter", "template", "boilerplate", "middleware", "gateway", "platform", "toolkit",
}


def repo_aliases(repo: str) -> set[str]:
    """Names another README would use to refer to this repo. Deliberately conservative: bare
    names need 6+ characters and can't be generic words, since a false mention inflates a tier."""
    owner, _, name = repo.lower().partition("/")
    owner_stem = re.sub(r"[-.]?js$", "", owner)  # expressjs -> express
    aliases = {repo.lower(), f"github.com/{repo.lower()}", f"{owner_stem}-{name}"}
    if "-" in name:
        aliases.add(name)
    if len(name) >= 6 and name not in GENERIC_ALIASES:
        aliases.add(name)
    return aliases


def mentions(readme: str, repo: str) -> bool:
    """Whether `readme` refers to `repo` by one of its names (whole-word match)."""
    text = readme.lower()
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) for alias in repo_aliases(repo)
    )


def compute_composability_score(pairs: dict[tuple[str, str], float], similarity: float, mentioned: bool = False) -> int:
    """Strong focus on different-but-adjacent areas (an auth library and a web framework) earns
    most of the score; one README naming the other project is the evidence that lifts a pair to
    the top tier. A mention only counts for pairs that are already complementary, so a stray
    common word can't create a match on its own."""
    category_term = min(1.0, 2 * max(pairs.values())) if pairs else 0.0
    mention_term = 1.0 if (mentioned and pairs) else 0.0
    similarity_term = min(1.0, similarity / SIMILARITY_FULL_CREDIT)
    score = 100 * (
        COMPOSABILITY_WEIGHTS["category"] * category_term
        + COMPOSABILITY_WEIGHTS["mention"] * mention_term
        + COMPOSABILITY_WEIGHTS["similarity"] * similarity_term
    )
    return round(min(score, 100))


def compute_redundancy_score(primary_a: set[str], primary_b: set[str], similarity: float) -> int:
    """Rewards sharing the same primary focus plus similar README language: these projects likely
    compete on the same problem rather than combining."""
    union = primary_a | primary_b
    same_focus = len(primary_a & primary_b) / len(union) if union else 0
    score = 100 * (
        REDUNDANCY_WEIGHTS["category"] * same_focus
        + REDUNDANCY_WEIGHTS["similarity"] * similarity
    )
    return round(min(score, 100))


def classify_pair(composability_score: int, redundancy_score: int) -> str:
    if composability_score < UNRELATED_THRESHOLD and redundancy_score < UNRELATED_THRESHOLD:
        return "unrelated"
    return "composable" if composability_score >= redundancy_score else "redundant"


def classify_match_tier(composability_score: int, relationship: str) -> str:
    """Rarity-style tier for a pair, driven by how strong a composable match it is."""
    if relationship != "composable":
        return "COMPETING"
    if composability_score >= S_TIER_THRESHOLD:
        return "S-TIER MATCH"
    if composability_score >= A_TIER_THRESHOLD:
        return "A-TIER MATCH"
    return "SOLID MATCH"


def local_report(repositories: dict[str, str]) -> dict[str, Any]:
    """Estimate project relationships locally when an OpenAI key is unavailable."""
    ngram_counts = {repo: local_ngram_counts(readme) for repo, readme in repositories.items()}
    tfidf_vectors = compute_tfidf_vectors(ngram_counts)
    category_shares = {repo: local_category_shares(counts) for repo, counts in ngram_counts.items()}
    primaries = {repo: primary_categories(shares) for repo, shares in category_shares.items()}

    overlaps = []
    all_shared_categories: set[str] = set()
    all_composable_pairs: set[tuple[str, str]] = set()

    for repo_a, repo_b in combinations(repositories, 2):
        similarity = cosine_similarity(tfidf_vectors[repo_a], tfidf_vectors[repo_b])
        pairs = complementary_pairs(category_shares[repo_a], category_shares[repo_b])
        a_mentions_b = mentions(repositories[repo_a], repo_b)
        b_mentions_a = mentions(repositories[repo_b], repo_a)
        composability_score = compute_composability_score(pairs, similarity, a_mentions_b or b_mentions_a)
        redundancy_score = compute_redundancy_score(primaries[repo_a], primaries[repo_b], similarity)
        relationship = classify_pair(composability_score, redundancy_score)
        tier = classify_match_tier(composability_score, relationship)

        shared_categories = sorted(primaries[repo_a] & primaries[repo_b])
        all_shared_categories.update(shared_categories)

        if relationship == "unrelated":
            continue
        if relationship == "composable":
            all_composable_pairs.update(pairs)

        shared_terms = top_shared_terms(tfidf_vectors[repo_a], tfidf_vectors[repo_b])
        if relationship == "composable":
            sorted_pairs = sorted(pairs, key=lambda key: (-pairs[key], key))
            pairing_label = ", ".join(f"{a} ↔ {b}" for a, b in sorted_pairs)
            top_pairing_label = ", ".join(f"{a} ↔ {b}" for a, b in sorted_pairs[:2])
            evidence = (
                f"Complementary capability areas: {pairing_label}."
                if pairing_label
                else f"Related terms suggest compatible tooling: {', '.join(shared_terms) or 'limited evidence'}."
            )
            if pairing_label and (a_mentions_b or b_mentions_a):
                referrer, referred = (repo_a, repo_b) if a_mentions_b else (repo_b, repo_a)
                evidence += f" {referrer}'s README references {referred}, which suggests they already work together."
            next_step = (
                f"Use {repo_a} and {repo_b} together"
                + (f" — {top_pairing_label}." if top_pairing_label else " — their shared terms suggest compatible tooling.")
            )
        else:
            evidence = (
                f"Overlapping capability areas: {', '.join(shared_categories) or 'none'}. "
                f"Shared terms: {', '.join(shared_terms) or 'none'}."
            )
            next_step = (
                f"{repo_a} and {repo_b} likely compete on {', '.join(shared_categories[:2]) or 'similar functionality'} "
                "— pick one as the base before extending."
            )

        overlaps.append(
            {
                "repository_a": repo_a,
                "repository_b": repo_b,
                "composability_score": composability_score,
                "redundancy_score": redundancy_score,
                "relationship": relationship,
                "tier": tier,
                "evidence": evidence,
                "next_step": next_step,
            }
        )

    overlaps.sort(key=lambda item: max(item["composability_score"], item["redundancy_score"]), reverse=True)
    for rank, item in enumerate(overlaps, start=1):
        item["rank"] = rank

    composable_overlaps = [item for item in overlaps if item["relationship"] == "composable"]
    top_composable = composable_overlaps[0] if composable_overlaps else None
    avg_composability_score = (
        round(sum(item["composability_score"] for item in overlaps[:3]) / min(len(overlaps), 3)) if overlaps else 0
    )
    avg_redundancy_score = (
        round(sum(item["redundancy_score"] for item in overlaps[:3]) / min(len(overlaps), 3)) if overlaps else 0
    )

    project_summaries = [
        {
            "repository": repo,
            "primary_focus": "Main focus: " + ", ".join(sorted(primaries[repo])) if primaries[repo] else "No clear capability areas found.",
        }
        for repo in repositories
    ]

    summary = (
        f"Local analysis found {len(composable_overlaps)} project pair{'s' if len(composable_overlaps) != 1 else ''} "
        f"that look complementary and {len(overlaps) - len(composable_overlaps)} that look redundant, out of "
        f"{len(repositories)} projects compared. Composability rewards different-but-adjacent capability areas "
        "(e.g. auth + API); redundancy rewards matching capability areas and shared README language."
    )
    if top_composable:
        summary += f" Strongest pairing to build together: {top_composable['repository_a']} + {top_composable['repository_b']}."

    if top_composable:
        recommendation = top_composable["next_step"]
    elif overlaps:
        recommendation = overlaps[0]["next_step"]
    else:
        recommendation = "No strong relationships found in the README excerpts. Try repositories from the same domain or add more descriptive projects."

    return {
        "overlap_score": avg_composability_score,
        "avg_composability_score": avg_composability_score,
        "avg_redundancy_score": avg_redundancy_score,
        "summary": summary,
        "shared_capabilities": sorted(all_shared_categories) or ["No shared capability areas found"],
        "composable_pairings": [f"{a} ↔ {b}" for a, b in sorted(all_composable_pairs)] or ["No complementary capability areas found"],
        "recommendation": recommendation,
        "project_summaries": project_summaries,
        "overlaps": overlaps[:10],
    }


def get_api_key() -> str | None:
    """Read the key from the environment, then .streamlit/secrets.toml."""
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key or api_key.strip().lower() in {"your-api-key", "your-real-key-here", "sk-proj-your-key-here"}:
        return None
    return api_key.strip()


def analyze_overlap(repositories: dict[str, str], allow_openai: bool = True) -> dict[str, Any]:
    """allow_openai=False forces local scoring so README text is never sent to OpenAI."""
    api_key = get_api_key() if allow_openai else None
    if not api_key:
        return local_report(repositories)

    client = OpenAI(api_key=api_key)
    source_text = "\n\n".join(
        f"Project {index}: {repo}\nREADME excerpt:\n{readme}"
        for index, (repo, readme) in enumerate(repositories.items(), start=1)
    )
    prompt = f"""Analyze this set of software projects using only the README excerpts below.
Return an overall overlap score from 0 to 100, where 0 means the projects are unrelated and 100 means they are effectively duplicate projects.
Analyze every project. Identify the strongest shared functional or technical capabilities, rank the most important overlapping project pairs, and suggest a practical next step for the teams.
Use concrete evidence from the text. Do not invent features that are not present. Include at most 10 overlap pairs, ordered from strongest to weakest.

{source_text}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "overlap_report",
                    "strict": True,
                    "schema": {
                    "type": "object",
                    "properties": {
                        "overlap_score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "summary": {"type": "string"},
                        "shared_capabilities": {"type": "array", "items": {"type": "string"}},
                        "recommendation": {"type": "string"},
                        "project_summaries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "repository": {"type": "string"},
                                    "primary_focus": {"type": "string"},
                                },
                                "required": ["repository", "primary_focus"],
                                "additionalProperties": False,
                            },
                        },
                        "overlaps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "repository_a": {"type": "string"},
                                    "repository_b": {"type": "string"},
                                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                                    "reason": {"type": "string"},
                                },
                                "required": ["repository_a", "repository_b", "score", "reason"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["overlap_score", "summary", "shared_capabilities", "recommendation", "project_summaries", "overlaps"],
                    "additionalProperties": False,
                    },
                },
            },
            messages=[
                {"role": "system", "content": "You are an expert software architect analyzing codebases for duplicate functionality and project overlap."},
                {"role": "user", "content": prompt},
            ],
        )
    except AuthenticationError:
        return local_report(repositories)
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("The model returned an empty analysis.")
    return json.loads(content)
