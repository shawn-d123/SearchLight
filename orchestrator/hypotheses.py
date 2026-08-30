"""One model call before the fan-out proposes hypotheses for THIS incident.

Without this the hypothesis list is the five family names from
`data/priors.json` -- generic categories that apply to any lost hiker anywhere,
and a fair judge can say the model is only writing short numpy loops. With it,
the model reads a real terrain summary and proposes behaviours that exist
because of this landscape.

**Family weights still come from `data/priors.json`.** The model proposes
variations WITHIN published categories; it does not invent the statistical
structure. A returned hypothesis whose family is not one of the five is
dropped. That is what keeps the ISRID grounding intact, which is the whole
basis of the project.

    python orchestrator/hypotheses.py --n 12
"""
from __future__ import annotations

import math

import numpy as np

import argparse, json, os, sys, time

from settings import DATA, key, load_case
from terrain_summary import summarise

HYPOTHESIS_MODEL = os.environ.get("SEARCHLIGHT_HYPOTHESIS_MODEL", "gpt-5.4")

SYSTEM = ("You are a search-and-rescue planner. You reason about where a "
          "specific missing person plausibly went on specific ground, and you "
          "answer with JSON only.")

PROMPT = """A person is missing. Propose {n} distinct hypotheses about what they did.

SUBJECT
{subject}

CONDITIONS
Last contact {elapsed_min:.0f} minutes ago. {conditions}

TERRAIN AROUND THE LAST KNOWN POINT
{terrain}
{local}
FAMILIES â€” every hypothesis must be tagged with exactly one of these, spelled
exactly as written. These are published ISRID behaviour categories and their
weights are fixed; you are proposing variations WITHIN them, not new ones.

{families}

Return JSON: {{"hypotheses": [{{"family": ..., "description": ..., "rationale": ...}}]}}

- `description`: one sentence, plain English, what the person did. It goes on
  screen in front of an audience, so name real features from the terrain summary
  above â€” the drainage, the ridge, the direction, the trail. "Followed the
  drainage south-east from the junction, path of least resistance on tiring
  legs" is right. "Route travelling behaviour" is useless.
- `rationale`: one sentence on why this ground makes that plausible. Cite a
  number from the summary.
- Spread them across the families roughly in proportion to the weights, and make
  them genuinely different from each other â€” different directions, different
  terrain features. {n} near-identical hypotheses are worth one.
{local_rule}
JSON only."""


def load_priors():
    return json.loads((DATA / "priors.json").read_text())


def load_local_knowledge():
    """The cached Parallel pass. Missing or empty is FINE and expected --
    hypothesis generation proceeds on terrain and statistics alone."""
    p = DATA / "local_knowledge.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()).get("findings", []) or []
    except Exception:
        return []


def _families_block(families):
    return "\n".join("  {:<20} weight {:.2f}".format(k, v)
                     for k, v in sorted(families.items(), key=lambda x: -x[1]))


def build_prompt(case, terrain_text, n, families, findings):
    if findings:
        local = ("\nDOCUMENTED LOCAL KNOWLEDGE â€” real incidents and advisories "
                 "for this range:\n" +
                 "\n".join("  - {} [{}]".format(f.get("claim", ""),
                                                f.get("label", "source"))
                           for f in findings[:8]) + "\n")
        local_rule = ("- Where a hypothesis is grounded in one of the documented "
                      "findings above, add \"source_label\" with that finding's "
                      "label verbatim.\n")
    else:
        local, local_rule = "", ""

    # The intake payload carries age, experience, clothing and injuries. They
    # are not decoration: "experienced" and "no injuries" both argue against the
    # staying-put family, and the model should see them rather than a category.
    s = case.get("subject") or {}
    bits = ["{}, category {}".format(case.get("subject_name", "unknown"),
                                     case.get("subject_category", "hiker"))]
    for label, k in (("age", "age"), ("experience", "experience"),
                     ("clothing", "clothing"), ("injuries", "injuries")):
        if s.get(k):
            bits.append("{} {}".format(label, s[k]))
    lk = case.get("last_known") or {}
    if lk.get("place"):
        bits.append("last seen at {}".format(lk["place"]))
    subject = "; ".join(bits) + ". Terrain {}.".format(
        case.get("terrain", "Mountainous"))

    return PROMPT.format(
        n=n, subject=subject,
        elapsed_min=case.get("last_contact_s_ago", 4320) / 60.0,
        conditions=case.get("conditions", "Clear, daylight."),
        terrain=terrain_text, local=local, local_rule=local_rule,
        families=_families_block(families))


def generate(case, n=12, model=HYPOTHESIS_MODEL, oai=None, data_dir=None):
    """Returns (hypotheses, error). On any failure returns the fixed-family
    fallback and an error string -- the demo never depends on this call."""
    priors = load_priors()
    families = priors["families"]
    facts, terrain_text = summarise(*case["ipp"], data_dir=data_dir)
    findings = load_local_knowledge()

    if oai is None:
        from codegen import client
        oai = client()

    raw, err = None, None
    try:
        r = oai.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user",
                       "content": build_prompt(case, terrain_text, n,
                                               families, findings)}],
            response_format={"type": "json_object"},
            timeout=120)
        raw = json.loads(r.choices[0].message.content)["hypotheses"]
    except Exception as e:
        err = "{}: {}".format(type(e).__name__, e)[:200]

    if not raw:
        return fallback_hypotheses(case, n, families), (err or "empty response")

    by_label = {f.get("label"): f for f in findings}
    out = []
    for h in raw:
        fam = (h.get("family") or "").strip()
        if fam not in families:
            continue  # cannot map to a published family -> drop it
        item = {
            "family": fam,
            "description": (h.get("description") or fam).strip(),
            "rationale": (h.get("rationale") or "").strip(),
            "weight": families[fam],
        }
        finding = by_label.get(h.get("source_label"))
        if finding:
            item["source"] = {"kind": "local",
                              "label": finding.get("label"),
                              "url": finding.get("url")}
        else:
            item["source"] = {"kind": "terrain"}
        out.append(item)

    if not out:
        return fallback_hypotheses(case, n, families), "no mappable families"
    return out, None


def fallback_hypotheses(case, n, families=None):
    """Fixed families, no model. The demo survives on this alone."""
    families = families or load_priors()["families"]
    order = sorted(families.items(), key=lambda x: -x[1])
    out = []
    for i in range(n):
        fam, w = order[i % len(order)]
        out.append({"family": fam,
                    "description": fam.replace("_", " ").capitalize(),
                    "rationale": "", "weight": w,
                    "source": {"kind": "statistical"}})
    return out


# Search horizon as a multiple of elapsed time. A subject missing 72 minutes
# is not found 72 minutes from the IPP -- the published quantiles describe the
# EVENTUAL find distance, and the search must cover where they could be by the
# time teams arrive. Calibrated so the simulated median matches the published
# p50; see prep/check_calibration.py.
DURATION_SCALE = 3.2
MIN_DURATION_S = 900.0
MAX_DURATION_S = 12 * 3600.0


def _load_priors():
    try:
        return json.loads((DATA / "priors.json").read_text())
    except Exception:
        return None


def _duration_sigma(priors):
    """Lognormal sigma implied by the published p95/p50 distance ratio.

    For a lognormal, p95/p50 = exp(1.645 * sigma).
    """
    q = priors["distance_km"]
    return math.log(max(1.05, q["p95"] / max(q["p50"], 1e-6))) / 1.645


def expand(hyps, case, total_runs=12000, dt_seed=1000, priors=None,
           duration_scale=DURATION_SCALE):
    """Attach the per-sandbox run counts and the CONTRACT.md section 4 fields.

    `n_runs` is derived so the totals hold whatever the fleet size turns out to
    be -- the account tier caps sandboxes at 10, so hypotheses run in waves and
    the run count per hypothesis is what keeps 12,000 sims 12,000 sims.
    """
    per = max(1, round(total_runs / max(1, len(hyps))))

    # DURATIONS ARE SAMPLED, NOT FIXED. Every hypothesis previously walked for
    # exactly case["last_contact_s_ago"], so every walker covered the same
    # ground, every endpoint landed on the same radius, and the field collapsed
    # into a single blob -- measured field_area_pct 1.8% with one zone holding
    # 96% of the mass. That is not a tighter search area, it is a lost degree
    # of freedom.
    #
    # Spread comes from the published quantiles: sigma is derived from the
    # p95/p50 ratio in data/priors.json, so the simulated distance distribution
    # reproduces the evidence base rather than contradicting it. This is what
    # makes "the same published statistics" a statement of fact.
    priors = priors if priors is not None else _load_priors()
    elapsed = float(case.get("last_contact_s_ago", 4320))
    rng = np.random.default_rng(dt_seed)
    if priors:
        sigma = _duration_sigma(priors)
        base = elapsed * duration_scale
        durations = np.clip(base * rng.lognormal(0.0, sigma, len(hyps)),
                            MIN_DURATION_S, MAX_DURATION_S)
    else:
        durations = np.full(len(hyps), elapsed)

    out = []
    for i, h in enumerate(hyps):
        out.append(dict(h,
                        hypothesis_id="h_{:05d}".format(i),
                        start=case["ipp"],
                        duration_s=int(durations[i]),
                        n_runs=per,
                        seed_base=dt_seed * (i + 1)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--model", default=HYPOTHESIS_MODEL)
    ap.add_argument("--fallback", action="store_true", help="no model call")
    args = ap.parse_args()

    case = load_case()
    findings = load_local_knowledge()
    print("local knowledge: {} finding(s){}".format(
        len(findings), "" if findings else "  (proceeding on terrain + stats)"))

    t0 = time.perf_counter()
    if args.fallback:
        hyps, err = fallback_hypotheses(case, args.n), None
    else:
        hyps, err = generate(case, n=args.n, model=args.model)
    print("{} hypotheses in {:.2f}s{}".format(
        len(hyps), time.perf_counter() - t0,
        "   ERROR: " + err if err else ""))
    print()
    for h in hyps:
        print("  [{:<18} w={:.2f}] {}".format(h["family"], h["weight"],
                                              h["description"]))
        if h.get("rationale"):
            print("      {}".format(h["rationale"]))
        if h.get("source", {}).get("kind") == "local":
            print("      source: {}".format(h["source"]["label"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
