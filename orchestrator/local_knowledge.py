"""The Parallel research pass -- the third grounding layer.

Statistical priors say how far people travel (ISRID). Terrain says what ground
is walkable. Neither says where people go wrong HERE: which drainage subjects
mistakenly descend from Marshall Gulch, which junctions are genuinely confusing,
which routes look shorter on a map than they are. That is what a Pima County
search planner knows and a generic model does not.

    python orchestrator/local_knowledge.py          # writes data/local_knowledge.json

RUN THIS ONCE, BEFORE THE DEMO, AND COMMIT THE RESULT. Never call it live.

1. It is a failure point on stage. A live web call mid-pitch can hang,
   rate-limit or return nothing, at the exact moment nothing can go wrong.
2. It is latency in the worst possible place. The research pass sits BEFORE the
   fan-out, so a slow call means the map sits still while you talk, and the
   simulation explosion is the beat that has to land the instant you press run.
3. It is the same query every run. Repeating it wastes budget and changes nothing.

If `data/local_knowledge.json` is missing or empty, hypothesis generation
proceeds on terrain and statistics alone and NOTHING BREAKS. That path is the
one that was built first.

Say "local knowledge is cached" in four words if it comes up. Nobody blinks at
a cached research pass. They blink at a stalled demo.
"""
from __future__ import annotations

import argparse, json, sys, time
from datetime import datetime, timezone

from settings import DATA, key

SEARCH_URL = "https://api.parallel.ai/v1/search"
REGION = "Santa Catalina Mountains, Arizona"

OBJECTIVE = (
    "Find documented search-and-rescue incidents, ranger advisories and trip "
    "reports for the Santa Catalina Mountains near Tucson, Arizona, that say "
    "where hikers actually get lost: which trails and drainages people "
    "mistakenly descend, which junctions are confusing, which routes are longer "
    "or harder than they look, and where subjects have been found.")

QUERIES = [
    "Santa Catalina Mountains hiker lost search and rescue incident report",
    "Mount Lemmon Marshall Gulch hiker lost wrong drainage",
    "Pima County Sheriff search and rescue Catalina Mountains missing hiker found",
    "Sabino Canyon Ventana Canyon hikers lost trail junction confusing",
    "Catalina Mountains hiking trip report took wrong turn descended wrong canyon",
]

DISTILL_MODEL = "gpt-5.4"

DISTILL_SYSTEM = ("You extract locally-specific search-and-rescue knowledge "
                  "from web excerpts. You answer with JSON only.")

DISTILL_PROMPT = """Below are web search excerpts about hiking and search-and-rescue \
in the {region}.

Extract findings that would help predict WHERE a lost hiker in this range actually
goes. Each finding must be specific to this place -- a named trail, drainage,
canyon, junction or ridge -- and must be supported by the excerpts.

Reject anything generic ("hikers should carry water", "people get lost when tired").
A finding that would be true of any mountain range anywhere is worthless here; the
whole point of this pass is knowledge a generic model does not have.

Return JSON:
{{"findings": [{{"claim": ..., "label": ..., "url": ..., "confidence": 0.0-1.0}}]}}

- `claim`: one sentence, naming the specific feature.
- `label`: a short human citation for the source, e.g. "Pima County SAR incident
  report, 2019" or the publication and year. It is shown on screen under the
  hypothesis, so keep it short and readable.
- `url`: the source URL from the excerpts, verbatim. Never invent one.
- `confidence`: how well the excerpts support the claim.

At most 10 findings, best first. If the excerpts support nothing specific,
return {{"findings": []}} -- an empty result is correct and safe, and is much
better than a plausible invention.

EXCERPTS
{excerpts}"""


def search(api_key, timeout=120):
    import httpx
    r = httpx.post(SEARCH_URL,
                   headers={"x-api-key": api_key,
                            "Content-Type": "application/json"},
                   json={"objective": OBJECTIVE, "search_queries": QUERIES},
                   timeout=timeout)
    r.raise_for_status()
    return r.json()


def format_excerpts(results, limit=25):
    out = []
    for res in (results or [])[:limit]:
        exc = res.get("excerpts") or []
        text = " ".join(e if isinstance(e, str) else str(e) for e in exc)
        out.append("- {} <{}>\n  {}".format(
            res.get("title", "untitled"), res.get("url", ""), text[:1200]))
    return "\n".join(out)


def distill(excerpts, model=DISTILL_MODEL):
    from codegen import client
    r = client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": DISTILL_SYSTEM},
                  {"role": "user",
                   "content": DISTILL_PROMPT.format(region=REGION,
                                                    excerpts=excerpts)}],
        response_format={"type": "json_object"},
        timeout=180)
    return json.loads(r.choices[0].message.content).get("findings", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "local_knowledge.json"))
    ap.add_argument("--model", default=DISTILL_MODEL)
    ap.add_argument("--dry-run", action="store_true",
                    help="search only, print results, write nothing")
    args = ap.parse_args()

    t0 = time.perf_counter()
    print("Parallel search: {} queries...".format(len(QUERIES)))
    data = search(key("PARALLEL_API_KEY"))
    results = data.get("results") or []
    print("  {} results in {:.1f}s".format(len(results), time.perf_counter() - t0))
    for r in results[:8]:
        print("   - {}  <{}>".format((r.get("title") or "")[:70], r.get("url")))

    if args.dry_run:
        return 0

    excerpts = format_excerpts(results)
    if not excerpts.strip():
        print("no excerpts; writing an empty file (hypotheses fall back to "
              "terrain + statistics, which is a supported path)")
        findings = []
    else:
        print("distilling with {}...".format(args.model))
        findings = distill(excerpts, model=args.model)

    # Never let an invented URL through: it would appear on screen as a citation.
    urls = {r.get("url") for r in results}
    kept = [f for f in findings if f.get("url") in urls]
    if len(kept) != len(findings):
        print("  dropped {} finding(s) whose URL was not in the search results"
              .format(len(findings) - len(kept)))

    out = {"generated_at": datetime.now(timezone.utc).isoformat(
               timespec="seconds").replace("+00:00", "Z"),
           "region": REGION,
           "source": "Parallel Search API, cached. Not called at demo time.",
           "n_results": len(results),
           "findings": kept}

    from pathlib import Path
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nwrote {} with {} finding(s)".format(args.out, len(kept)))
    for f in kept:
        print("  [{:.2f}] {}".format(f.get("confidence", 0), f.get("claim", "")))
        print("         {}  {}".format(f.get("label"), f.get("url")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
