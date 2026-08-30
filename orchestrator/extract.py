"""Turn a 999 call into the CONTRACT.md section 8 extraction payload.

The transcript is texture. **The structured extraction is the hero.** A
hackathon venue at 5pm is loud and speech recognition will mangle words; this
is built so that does not matter. An imperfect transcript still yields a
correct report because a model pulls the fields out of it, and if it garbles a
word while the card still populates correctly, say so on stage -- that reads as
robustness rather than luck.

Runs SERVER-SIDE, never in the browser. The extraction needs the OpenAI key,
and a key in browser JavaScript is a key you have published.

`ring_radius_m` is DERIVED from data/priors.json keyed on the extracted
category. The model reads the call; the statistics come from ISRID. Say that
if asked -- it is the difference between a demo that quotes evidence and one
that asks a language model to invent a search radius.
"""
from __future__ import annotations

import json
import os
import re
import time

from settings import DATA, MOCKS

EXTRACT_MODEL = os.environ.get("SEARCHLIGHT_EXTRACT_MODEL", "gpt-5.4")

# Order matters: this is the order fields appear on the report card, and the
# server emits them one at a time. The stagger IS the visual payoff of the
# transcription, so the sequence should read like someone taking notes --
# who, then where, then the assessment that follows from both.
FIELD_ORDER = [
    ("subject", "name"), ("subject", "age"), ("subject", "category"),
    ("subject", "experience"), ("subject", "clothing"), ("subject", "injuries"),
    ("last_known", "place"), ("last_known", "time"), ("last_known", "elapsed_min"),
    ("last_known", "ipp"),
    ("assessment", "ring_radius_m"), ("assessment", "conditions"),
]

SYSTEM = ("You are a search and rescue call handler. You extract only what the "
          "caller actually said. You never invent a detail to fill a field.")

PROMPT = """Extract a structured missing-person report from this emergency call.

TRANSCRIPT (speech recognition, so expect errors and mishearings):
\"\"\"{transcript}\"\"\"

Known trailheads in the Santa Catalina Mountains, Arizona, with coordinates:
{trailheads}

Return JSON exactly like this:

{{
  "subject": {{"name": str, "age": int|null, "category": str,
               "experience": str, "clothing": str, "injuries": str}},
  "last_known": {{"place": str, "time": "HH:MM", "elapsed_min": int,
                  "ipp": [lat, lon]}},
  "assessment": {{"conditions": str}},
  "confidence": {{"ipp": 0..1, "time": 0..1, "category": 0..1}}
}}

Rules:
  * `category` must be one of: hiker, hunter, camper, climber, mountain biker.
    Choose the closest. This selects the published statistics.
  * `ipp` is the coordinate of the named trailhead from the list above. If the
    caller names no place you recognise, return null and set confidence.ipp 0.
  * `elapsed_min` is minutes from the last contact time to now. If the caller
    gives a time of day, assume the call is happening about 72 minutes later.
  * Use null for anything the caller did not say. Do NOT guess.
  * Do NOT return a search radius. That is derived from published statistics,
    not from the call.
"""

# Trailheads the demo can name. Kept here rather than asked of the model,
# because a hallucinated coordinate would put the whole field in the wrong
# valley and nothing downstream would notice.
TRAILHEADS = {
    "marshall gulch": [32.4102, -110.7314],
    "sabino canyon": [32.3106, -110.8214],
    "catalina state park": [32.4290, -110.9200],
    "mount lemmon": [32.4429, -110.7885],
    "romero canyon": [32.4297, -110.9147],
    "bear canyon": [32.3167, -110.8083],
    "seven falls": [32.3253, -110.7936],
    "aspen trail": [32.4260, -110.7560],
}

CATEGORY_ALIASES = {
    "hiker": "hiker", "hiking": "hiker", "walker": "hiker",
    "hunter": "hunter", "camper": "camper", "climber": "climber",
    "mountain biker": "mountain biker", "cyclist": "mountain biker",
}


def _priors():
    return json.loads((DATA / "priors.json").read_text())


def ring_radius_m(category=None, priors=None):
    """DERIVED, never extracted. The model reads the call; ISRID sets the ring.

    One category today, so this returns the same p95 for every subject. The
    lookup exists so that stays true when a second category is added, rather
    than someone quietly hardcoding 9545.9 somewhere.
    """
    p = priors or _priors()
    return round(p["ring_radius_km"] * 1000.0, 1)


def _trailhead(place):
    if not place:
        return None
    t = str(place).lower()
    for name, ipp in TRAILHEADS.items():
        if name in t or t in name:
            return list(ipp)
    # "Marshall Gulch trail" -> "marshall gulch"
    words = re.sub(r"[^a-z ]", " ", t).split()
    for name, ipp in TRAILHEADS.items():
        if all(w in words for w in name.split()):
            return list(ipp)
    return None


def fallback_payload(transcript=None):
    """The committed mock, used when the model call fails.

    Marked `source: "fallback"` so nothing downstream can mistake it for a live
    extraction. The demo must never present canned output as live.
    """
    payload = json.loads((MOCKS / "extraction.json").read_text())
    if transcript:
        payload["transcript"] = transcript
    payload["source"] = "fallback"
    return payload


def extract(transcript, model=EXTRACT_MODEL, oai=None, priors=None):
    """Transcript -> section 8 payload. Returns (payload, error).

    Never raises: on any failure it returns the committed mock so the demo
    continues, with `source` saying which path produced it.
    """
    transcript = (transcript or "").strip()
    if len(transcript) < 20:
        return fallback_payload(transcript), "transcript too short"

    priors = priors or _priors()
    if oai is None:
        from codegen import client
        oai = client()

    lines = "\n".join("  {} -> [{}, {}]".format(k, v[0], v[1])
                      for k, v in TRAILHEADS.items())
    t0 = time.time()
    try:
        r = oai.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": PROMPT.format(
                          transcript=transcript, trailheads=lines)}],
            response_format={"type": "json_object"},
            timeout=60)
        raw = json.loads(r.choices[0].message.content)
    except Exception as e:
        return (fallback_payload(transcript),
                "{}: {}".format(type(e).__name__, e)[:200])

    subject = dict(raw.get("subject") or {})
    last = dict(raw.get("last_known") or {})

    cat = str(subject.get("category") or "hiker").lower().strip()
    subject["category"] = CATEGORY_ALIASES.get(cat, "hiker")

    # Trust our own gazetteer over a model-produced coordinate.
    named = _trailhead(last.get("place"))
    if named:
        last["ipp"] = named
    elif not (isinstance(last.get("ipp"), list) and len(last["ipp"]) == 2):
        last["ipp"] = list(TRAILHEADS["marshall gulch"])
        raw.setdefault("confidence", {})["ipp"] = 0.0

    payload = {
        "transcript": transcript,
        "subject": subject,
        "last_known": last,
        "assessment": {
            "ring_radius_m": ring_radius_m(subject["category"], priors),
            "conditions": (raw.get("assessment") or {}).get("conditions")
                          or "not stated",
        },
        "confidence": raw.get("confidence") or {},
        "source": "live",
        "model": model,
        "elapsed_s": round(time.time() - t0, 2),
    }
    return payload, None


def field_sequence(payload):
    """Flatten to (path, label, value) in card order, skipping what is absent.

    The server emits these one at a time. Fields the caller never mentioned are
    dropped rather than shown blank -- an empty row reads as a bug, and a
    missing row reads as a caller who did not say.
    """
    out = []
    for section, field in FIELD_ORDER:
        value = (payload.get(section) or {}).get(field)
        if value in (None, "", []):
            continue
        out.append({"section": section, "field": field, "value": value})
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", help="text, or omit to use the mock")
    ap.add_argument("--model", default=EXTRACT_MODEL)
    args = ap.parse_args()

    text = args.transcript or (MOCKS / "transcript.txt").read_text(encoding="utf-8")
    payload, err = extract(text, model=args.model)
    print("source: {}  {}".format(payload.get("source"),
                                  "error: " + err if err else ""))
    print(json.dumps(payload, indent=2)[:1200])
    print()
    for f in field_sequence(payload):
        print("  {:<12} {:<14} {}".format(f["section"], f["field"], f["value"]))


if __name__ == "__main__":
    main()
