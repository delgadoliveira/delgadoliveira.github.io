#!/usr/bin/env python3
"""Refresh the reading lists backing /reading/.

Sources everything from the Hugging Face papers API, which is faster and more
reliable than the arXiv Atom endpoint and additionally exposes community
attention (upvotes) and linked code repositories.

Two distinct jobs, deliberately kept separate:

  1. Curated backbone - a hand-picked list of arXiv IDs per track. Metadata is
     always fetched, never transcribed, so titles and authors cannot drift or be
     invented.
  2. Discovery - a candidate pool built from the daily "hot" feed plus targeted
     searches, then filtered by an explicit keyword model. HF's own relevance
     ranking is noisy, so the scoring below does the real selection work and the
     rules stay visible in source.

Standard library only. Run: python scripts/fetch_papers.py
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HF = "https://huggingface.co/api"
UA = "delgadoliveira.github.io reading-list refresh (+https://github.com/delgadoliveira)"
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reading" / "papers.json"

# Minimum keyword score for a discovered paper to appear at all.
MIN_SCORE = 9
MAX_RECENT_PER_TRACK = 6

# A paper must look like it is about language models / agents at all. The daily
# feed is dominated by vision and video work that otherwise trips generic terms
# such as "instruction", "memory", or "rubric".
ANCHORS = (
    "language model", "llm", "large language", "agent", "chatbot", "gpt",
    "transformer", "prompt", "reasoning", "retrieval", "nlp", "dialogue",
    "instruction following", "tool use", "rlhf", "alignment",
)

# Off-domain markers. These do not disqualify on their own, but they subtract
# from the relevance score so that a vision paper needs overwhelming on-topic
# evidence to surface in a track about agent methodology.
NEGATIVE = {
    "image restoration": 10, "super-resolution": 10, "segmentation": 8,
    "svg": 8, "video generation": 10, "image generation": 8, "diffusion model": 6,
    "robot manipulation": 8, "manipulation policy": 8, "speech": 6, "audio": 6,
    "medical imaging": 8, "point cloud": 10, "3d scene": 8, "autonomous driving": 8,
    "text-to-image": 10, "text-to-video": 10, "rendering": 6, "depth estimation": 10,
}

TRACKS = [
    {
        "id": "evaluation",
        "title": "Evaluation and measurement",
        "blurb": (
            "How to tell whether an agent is actually good: benchmark construction, "
            "automated judges and their calibration against human labels, and the "
            "failure modes of compressing a complex experience into one number."
        ),
        "curated": [
            {
                "id": "2306.05685",
                "establishes": (
                    "A strong model judge can reach roughly the same agreement with human "
                    "raters that humans reach with each other on open-ended preference "
                    "comparisons."
                ),
                "unsettled": (
                    "Validity. The same paper documents position, verbosity and "
                    "self-enhancement bias, so agreeing with a crowd is not evidence that "
                    "the judge measures the property you actually care about."
                ),
            },
            {
                "id": "2310.06770",
                "establishes": (
                    "Evaluation can be execution-verified against real repository issues "
                    "and their tests, instead of graded by another model."
                ),
                "unsettled": (
                    "What the score means. Pass rates mix genuine capability with issue "
                    "specification quality and with whether the right files were retrieved."
                ),
            },
            {
                "id": "2407.10817",
                "establishes": (
                    "Autoraters trained across many human-judgment datasets generalise to "
                    "unseen evaluation tasks better than general-purpose models prompted "
                    "as judges."
                ),
                "unsettled": (
                    "Transfer to a specific product rubric, which usually resembles "
                    "nothing in the training mixture."
                ),
            },
            {
                "id": "2406.12045",
                "establishes": (
                    "Single-run success overstates reliability. Its pass^k metric shows "
                    "consistency degrading sharply across repeated trials of the same task."
                ),
                "unsettled": (
                    "Realism, since the user is simulated. The reliability finding survives "
                    "that caveat, and is the reason to report variance rather than a mean."
                ),
            },
            {
                "id": "2308.03688",
                "establishes": (
                    "How differently one agent performs across eight distinct environments."
                ),
                "unsettled": (
                    "How to aggregate. Averaging heterogeneous environments yields a number "
                    "that moves for reasons you cannot attribute to anything actionable."
                ),
            },
        ],
        "queries": [
            "LLM as a judge evaluation",
            "agent benchmark evaluation",
            "evaluating language model agents",
        ],
        "keywords": {
            "judge": 4, "evaluat": 3, "benchmark": 3, "metric": 3, "rubric": 4,
            "annotat": 2, "human preference": 3, "calibrat": 3, "reliability": 2,
            "leaderboard": 3, "assessment": 2, "grading": 3, "meta-evaluation": 4,
        },
    },
    {
        "id": "skills",
        "title": "Agent skills, tools, and action",
        "blurb": (
            "What an agent can actually do: reasoning-and-acting loops, tool and "
            "function calling, self-correction, and the architectures that turn a "
            "model into a system that executes real work."
        ),
        "curated": [
            {
                "id": "2210.03629",
                "establishes": (
                    "Interleaving reasoning with external actions beats either alone, and "
                    "grounding steps in retrieved observations reduces fabrication."
                ),
                "unsettled": (
                    "Cost. Every step adds tokens and latency, which compounds once the "
                    "loop runs many times per task."
                ),
            },
            {
                "id": "2302.04761",
                "establishes": (
                    "A model can learn when to call a tool in a self-supervised way, kept "
                    "only when the call measurably reduces loss."
                ),
                "unsettled": (
                    "Scaling to large or changing tool inventories. The tool set here is "
                    "small and fixed."
                ),
            },
            {
                "id": "2303.11366",
                "establishes": (
                    "Verbal self-critique carried across attempts improves success without "
                    "updating any weights."
                ),
                "unsettled": (
                    "Where the gain comes from. It needs a reliable success signal to "
                    "reflect against, which is precisely what production tasks lack."
                ),
            },
            {
                "id": "2308.08155",
                "establishes": (
                    "A concrete pattern for composing several conversing agents with "
                    "defined human-in-the-loop points."
                ),
                "unsettled": (
                    "Whether multiple agents beat one well-prompted agent on a given task. "
                    "The framework does not answer that; only an experiment does."
                ),
            },
        ],
        "queries": [
            "LLM agent tool use",
            "function calling agent framework",
            "multi-agent collaboration language model",
            "computer use agent",
        ],
        "keywords": {
            "tool use": 4, "tool-use": 4, "function call": 4, "agent": 2,
            "multi-agent": 3, "planning": 3, "react": 2, "self-correct": 3,
            "reflection": 2, "workflow": 2, "computer use": 4, "orchestrat": 2,
            "skill": 3, "api call": 3, "trajector": 2,
        },
    },
    {
        "id": "prompting",
        "title": "Prompt and context engineering",
        "blurb": (
            "How the request and its surrounding context shape behavior: structured "
            "reasoning, decomposition, retrieval, long-context effects, and how "
            "sensitive results are to the way a task is phrased."
        ),
        "curated": [
            {
                "id": "2201.11903",
                "establishes": (
                    "Eliciting intermediate steps improves reasoning tasks, and the effect "
                    "depends strongly on model scale."
                ),
                "unsettled": (
                    "Faithfulness. The stated reasoning is not necessarily the computation "
                    "that produced the answer, so it cannot be read as an explanation."
                ),
            },
            {
                "id": "2005.11401",
                "establishes": (
                    "Retrieval lets knowledge be updated without retraining, and lets an "
                    "answer be attributed to a source."
                ),
                "unsettled": (
                    "Retrieval quality itself, which becomes the dominant error term as "
                    "soon as generation is competent."
                ),
            },
            {
                "id": "2307.03172",
                "establishes": (
                    "Position inside the context window changes accuracy: relevant material "
                    "placed in the middle is used least."
                ),
                "unsettled": (
                    "The remedy. But it does mean long-context claims should be tested by "
                    "position rather than assumed uniform."
                ),
            },
            {
                "id": "2203.11171",
                "establishes": (
                    "Sampling several reasoning paths and taking the majority beats a "
                    "single greedy decode."
                ),
                "unsettled": (
                    "Whether it is worth it. The gain is bought with k times the inference "
                    "cost, making this a deployment decision rather than a modelling one."
                ),
            },
        ],
        "queries": [
            "prompt engineering large language models",
            "chain of thought reasoning",
            "retrieval augmented generation context",
            "long context language model",
        ],
        "keywords": {
            "prompt": 4, "chain-of-thought": 4, "chain of thought": 4,
            "in-context": 3, "context window": 3, "long context": 3,
            "retrieval": 3, "rag": 2, "decomposition": 2, "reasoning": 2,
            "few-shot": 3, "instruction": 2, "context engineering": 5,
        },
    },
    {
        "id": "experimentation",
        "title": "Experimentation, safety, and rollout",
        "blurb": (
            "Moving from a promising prototype to a change that is defensible in "
            "production: online experiments, alignment and guardrails, reward "
            "hacking, and the risks that only appear once real users are exposed."
        ),
        "curated": [
            {
                "id": "2212.08073",
                "establishes": (
                    "Explicit written principles plus model feedback can substitute for "
                    "human harm labels when training for harmlessness."
                ),
                "unsettled": (
                    "Who writes the principles. That is where the actual value judgements "
                    "sit, and the method does not make them for you."
                ),
            },
            {
                "id": "2203.02155",
                "establishes": (
                    "Alignment to instructions beats raw scale on human preference: a 1.3B "
                    "model was preferred over 175B GPT-3."
                ),
                "unsettled": (
                    "Whose preferences. The paper is explicit that it aligns to a small "
                    "group of labellers, not to any general notion of helpfulness."
                ),
            },
            {
                "id": "2209.13085",
                "establishes": (
                    "A formal account of when optimising a proxy diverges from the true "
                    "objective, with a proof that the conditions for non-hackability are "
                    "highly restrictive."
                ),
                "unsettled": (
                    "Detection in practice. That restrictiveness is the argument for "
                    "reporting guardrail metrics alongside the target metric, not instead "
                    "of reasoning about the proxy."
                ),
            },
        ],
        "queries": [
            "online controlled experiment",
            "reward hacking alignment",
            "guardrails deployment language model safety",
        ],
        "keywords": {
            "a/b test": 5, "online experiment": 5, "controlled experiment": 5,
            "reward hack": 5, "guardrail": 4, "deployment": 3, "rollout": 4,
            "alignment": 3, "safety": 2, "red team": 3, "production": 2,
            "causal": 3, "treatment effect": 5, "goodhart": 5, "specification gaming": 5,
        },
    },
]

# Non-arXiv essays. Each was read before inclusion; notes are descriptive.
ESSAYS = [
    {
        "title": "The Proxy Trap",
        "author": "Milad Shokouhi",
        "venue": "LinkedIn",
        "url": "https://www.linkedin.com/pulse/proxy-trap-milad-shokouhi-xtfae/",
        "track": "evaluation",
        "note": (
            "Argues that metric science has made real progress on proxy gaming and proxy "
            "quality, while two other traps stay comparatively underexamined: an aggregation "
            "trap, where an average hides consequential differences beneath it, and an "
            "optimization trap, where the measurement system quietly constrains which product "
            "changes get considered at all. The concern sharpens as agents automate the "
            "optimization loop, because it becomes possible to climb a hill very efficiently "
            "without asking whether it is the right hill."
        ),
    },
    {
        "title": "Changing How We Build",
        "author": "Charles Lamanna",
        "venue": "LinkedIn",
        "url": "https://www.linkedin.com/pulse/changing-how-we-build-charles-lamanna-xpitc/",
        "track": "experimentation",
        "note": (
            "A first-hand account of reorganizing engineering work around agentic coding. The "
            "durable point for evaluation: the bottleneck moves rather than disappears, landing "
            "on deciding what matters and verifying whether what was built is genuinely good. "
            "It also resists inventing AI-specific KPIs, arguing that counting inputs such as "
            "lines of code says almost nothing, and that the outcome metrics that mattered "
            "before AI remain the right test."
        ),
    },
]


def _ssl_context() -> ssl.SSLContext:
    """Prefer an explicit CA bundle; some managed machines lack a usable store."""
    bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("HF_CA_BUNDLE")
    if not bundle:
        try:
            import certifi

            bundle = certifi.where()
        except ImportError:
            bundle = None
    return ssl.create_default_context(cafile=bundle)


_CTX = _ssl_context()


def get_json(path: str, params: dict | None = None, attempts: int = 4):
    url = f"{HF}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    delay, last = 4, None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=45, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                return None
            if exc.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
        if attempt < attempts:
            print(f"    retry {attempt} in {delay}s ({last})", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    print(f"    giving up on {path}: {last}", file=sys.stderr)
    return None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize(record: dict) -> dict | None:
    """Flatten an HF paper record (daily/search item or direct paper object)."""
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else record
    arxiv_id = paper.get("id")
    title = clean(record.get("title") or paper.get("title"))
    if not arxiv_id or not title:
        return None
    summary = clean(record.get("summary") or paper.get("summary"))
    authors = [clean(a.get("name")) for a in (paper.get("authors") or []) if a.get("name")]
    published = (record.get("publishedAt") or paper.get("publishedAt") or "")[:10]
    return {
        "id": arxiv_id,
        "title": title,
        "authors": authors[:5],
        "author_count": len(authors),
        "summary": summary[:400].rstrip() + ("…" if len(summary) > 400 else ""),
        "published": published,
        "upvotes": paper.get("upvotes") or 0,
        "github": paper.get("githubRepo") or "",
        "github_stars": paper.get("githubStars") or 0,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "hf_url": f"https://huggingface.co/papers/{arxiv_id}",
    }


def score(paper: dict, keywords: dict) -> int:
    """Title matches count double; the model is intentionally simple and inspectable."""
    title = paper["title"].lower()
    summary = paper["summary"].lower()
    total = 0
    for term, weight in keywords.items():
        if term in title:
            total += weight * 2
        elif term in summary:
            total += weight
    for term, penalty in NEGATIVE.items():
        if term in title:
            total -= penalty * 2
        elif term in summary:
            total -= penalty
    return total


def in_domain(paper: dict) -> bool:
    blob = (paper["title"] + " " + paper["summary"]).lower()
    return any(a in blob for a in ANCHORS)


def main() -> int:
    print("fetching daily (hot) papers…")
    daily_raw = get_json("/daily_papers", {"limit": 100}) or []
    pool: dict[str, dict] = {}
    for rec in daily_raw:
        item = normalize(rec)
        if item:
            item["hot"] = True
            pool[item["id"]] = item
    print(f"  pool from daily feed: {len(pool)}")

    for track in TRACKS:
        for q in track["queries"]:
            results = get_json("/papers/search", {"q": q}) or []
            added = 0
            for rec in results[:40]:
                item = normalize(rec)
                if item and item["id"] not in pool:
                    item.setdefault("hot", False)
                    pool[item["id"]] = item
                    added += 1
            print(f"  search {track['id']!r} {q!r}: +{added}")
            time.sleep(1)

    print(f"candidate pool: {len(pool)}")

    curated_ids = {entry["id"] for t in TRACKS for entry in t["curated"]}
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Hugging Face papers API",
        "min_score": MIN_SCORE,
        "tracks": [],
        "essays": ESSAYS,
    }

    # Assign each discovered paper to its single best-fitting track.
    assignment: dict[str, tuple[str, int]] = {}
    for item in pool.values():
        if item["id"] in curated_ids or not in_domain(item):
            continue
        best_track, best_score = None, 0
        for track in TRACKS:
            s = score(item, track["keywords"])
            if s > best_score:
                best_track, best_score = track["id"], s
        if best_track and best_score >= MIN_SCORE:
            assignment[item["id"]] = (best_track, best_score)

    for track in TRACKS:
        print(f"track: {track['id']}")
        curated = []
        for entry in track["curated"]:
            arxiv_id = entry["id"]
            data = get_json(f"/papers/{arxiv_id}")
            if not data:
                print(f"  ! curated id not resolved: {arxiv_id}", file=sys.stderr)
                continue
            item = normalize(data)
            if item:
                # Metadata is fetched; the two notes are the editorial layer and are
                # the only hand-written content in the feed.
                item["establishes"] = entry["establishes"]
                item["unsettled"] = entry["unsettled"]
                curated.append(item)
            time.sleep(0.5)

        recent = [
            dict(pool[pid], score=sc)
            for pid, (tid, sc) in assignment.items()
            if tid == track["id"]
        ]
        # Relevance first. Community attention is a tie-breaker, not the ranking.
        recent.sort(
            key=lambda p: (p["score"], p.get("upvotes", 0), p["published"]),
            reverse=True,
        )
        recent = recent[:MAX_RECENT_PER_TRACK]

        print(f"  curated={len(curated)} recent={len(recent)}")
        payload["tracks"].append(
            {
                "id": track["id"],
                "title": track["title"],
                "blurb": track["blurb"],
                "curated": curated,
                "recent": recent,
            }
        )

    total_curated = sum(len(t["curated"]) for t in payload["tracks"])
    if total_curated == 0:
        print("refusing to write a feed with no curated papers", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total_recent = sum(len(t["recent"]) for t in payload["tracks"])
    print(f"wrote {OUT} (curated={total_curated}, recent={total_recent})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
