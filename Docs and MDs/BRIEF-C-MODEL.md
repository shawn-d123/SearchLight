# PERSON C — aggregation, validation, pitch (Shawn)

**Read `CONTRACT.md` first.** You own the maths, the number in the pitch, and the pitch itself.

You did the design thinking, so you will be interrupted constantly. This is the piece where knowing the design matters most and interruption costs least.

---

## What already exists from last night

Do not rebuild any of this.

| Asset | State |
|---|---|
| `data/cases.csv` | 131 Arizona cases, 109 usable after filters |
| `data/bbox.json` | Santa Catalinas, 45.3 × 42.1 km |
| `data/priors.json` | Derived quantiles, **holdout set excluding the 6 validation cases** |
| `data/*.npy` | Four terrain arrays, 33.7 MB |
| `model/score.py` | Rossmo's R, verified |
| `model/ring_model.py` | The baseline, verified |
| `model/field.py` | `field_area_pct` implemented. `build_field` / `apply_evidence` are signatures only |
| `mocks/` | Six payloads, validated against the contract |

**Your build today is `build_field` and `apply_evidence`, then the validation run.**

---

## The numbers, and which one you say out loud

| Number | What it is |
|---|---|
| **0.761** | Ring baseline on the 6 validation cases. **This is the pitch number** |
| 0.711 (CI 0.643–0.779) | Ring baseline on all 109. Harness verification |
| 0.78 (CI 0.74–0.82) | Published, 376 different cases. **Never quote as your comparison** |
| 9.55 km | Derived p95, the ring radius on screen |

Comparing your six-case result to a published figure from a different sample is the first thing a judge who reads the paper would attack. Your own baseline on your own cases is unimpeachable.

---

## Aggregation

```python
build_field(trajectory_batches, bounds, resolution, accumulator=None) -> (grid, accumulator)
apply_evidence(trajectory_batches, evidence) -> (filtered, field_dict)
```

**Incremental, not one-shot.** B streams batches while the fleet is still working, so keep a running accumulator and add each batch's Gaussian splats. Emit roughly every second with a `progress` value.

**Normalise against a fixed ceiling or a heavily smoothed running maximum.** Renormalising to 0..1 on every update makes the field pulse and flicker as the max shifts.

Kernel density over run endpoints, weighted by family prior. A manual Gaussian splat onto the grid is usually faster than `scipy.stats.gaussian_kde` and easier to control the bandwidth on.

**Zones:** local maxima, top two shown on screen, probability mass integrated around each.

**Two grids.** 256×256 for the frontend, 5001×5001 for scoring. Same function, different resolution. The scoring grid is 25 million floats and never touches the WebSocket.

**Evidence filter:** `{lat, lon, t, radius_m, reliability}`. Keep a run if it passed within `radius_m` of that point inside a time window around `t`. Renormalise, rebuild. Report the counts honestly — the drop from total to consistent is a demo beat.

---

## Validation — 15:00, and never cut it

**6 cases, ~50 sandboxes each.** Scoped so it fits after integration. Say "six real historical cases" in the pitch.

Run the real pipeline per case, produce a 5001×5001 grid, score with `model/score.py`, average.

**Report whichever way it falls.** A model that scores 0.6 and says so is worth more than one that scores nothing and shows a tick. Beat 0.761 and you have a headline. Miss it and you have a finding, plus a far better answer to the inevitable question than silence.

**Do not tune until it looks right.** If the number is bad, the honest sentence is that six cases is a small sample with a wide interval and the ring baseline computed identically gives 0.761.

---

## Timeline

| Time | Target |
|---|---|
| 10:30 | Contract lock, 15 min |
| 10:45 | `build_field` working on `mocks/trajectories.json` |
| 11:30 | Grid encoding correct, A can render it |
| 12:30 | Zones, `field_area_pct` wired |
| 13:30 | Evidence filter |
| 14:00 | **Intake screens** — see below. Cut this first if validation is at risk |
| 14:30 | **Integration** |
| 15:00 | **Validation run** |
| 16:00 | Number into the pitch |
| 16:20 | First clean rehearsal |

---

## Intake — you build this, 14:00

Two states in **the same Next.js app** as the map. Not a separate application, not Lovable — the landing screen reuses the terrain canvas and everything shares the panels, type and palette. Same corner registration ticks as the rail.

**The call.** Live transcription via the browser **Web Speech API**, not Whisper. Word by word, no upload, no round trip. Whisper needs record-upload-wait, which kills the effect.

**The transcript is texture. The extraction is the hero.** The room will be loud at 5pm and recognition will mangle words. Build so that does not matter: an imperfect transcript still yields a correct report because a model pulls the fields out of it. If it garbles something and the card still populates correctly, say so — that reads as robustness rather than luck.

**Mandatory fallback:** a key that types `mocks/transcript.txt` at speaking pace. If the mic fails, *"the room's too loud, here's the recorded version"* and carry on. Nobody minds.

**The report.** Header shows `INCIDENT SL-2084` and keeps it all demo. Three panels — SUBJECT, LAST KNOWN, ASSESSMENT — per `CONTRACT.md` §8. **Fields populate one at a time as extraction returns**, not all at once. That staggering is the visual payoff of the transcription. Then one button: **BEGIN SEARCH**.

`ring_radius_m` comes from `data/priors.json` keyed on the extracted category. **Derived, not extracted.** The model reads the call; the statistics come from ISRID. Say that if asked.

### What you say into the microphone

> *"I need to report a missing person. My friend Alex Morgan went hiking on the Marshall Gulch trail in the Catalinas this morning. He's twenty-four, experienced hiker, been out there before. He was going to call me when he reached the top but I haven't heard from him since about ten past six. His phone's going straight to voicemail so I think the battery's dead. He was wearing a red jacket and he had no injuries when he set off."*

Every detail drives something visible: the trailhead sets the IPP, the time sets elapsed duration, "experienced hiker" selects the ISRID category and therefore the priors and ring radius, "no injuries" lowers the staying-put weight, "phone dead" explains the absence of GPS before anyone asks, and **"red jacket" sets up the witness sighting at 0:50 so the payoff lands.**

Rehearse it at the pace you will actually speak. Nothing in it is decoration.

### Cut order

**This is the first thing to go if the validation run is at risk.** Validation is worth more than the opening. If it goes, the demo starts at `briefing` with the case pre-loaded and loses nothing structural.

---

## The pitch — 90 seconds

**−0:30** *(if intake is in)* Landing, beam sweeping the terrain. Press report, speak the call, watch the fields populate.
*"That's a 999 call. Everything on this card came out of it."*

**0:00** Terrain, last known point, ring already drawn.
*"A hiker went missing in the Santa Catalinas 72 minutes ago. This ring is how search areas are drawn today. Published statistics, applied as a circle."*

**0:12** *"The statistics are good. The circle is the problem. People follow trails, go downhill, stop at water."* Run.

**0:18** Paths spread, field begins accumulating, fleet counter climbing.
*"Every sandbox takes one hypothesis from the published strategy categories, writes its own movement model, and runs it against the real landscape."*

**0:35** Field settles into the drainages.
*"Same statistics. [FIELD AREA]% of the area."*

**0:50** Witness report. Apply. Field collapses.
*"[N] simulations. [M] are consistent with that sighting."* Ring unchanged.

**1:05** *"The ring didn't move, because a ring can't respond to evidence."*

**1:12** Validation.
*"Six real historical cases from the Santa Catalinas. Known last seen point, known find location. The ring model scores 0.761 on those cases. We score [X]."*

**1:25** Hold on ring and field side by side.
*"Don't search everywhere. Search where they could be."*

**Bracketed numbers stay blank until the real run.** Do not rehearse a field area figure — the mocks show 26.4% from a random walk and the terrain-aware number will differ.

---

## Two sentences that belong in the validation beat

These answer "how do we know your numbers mean anything" before anyone asks:

> Our ring implementation scores 0.711 across all 109 usable cases, with a confidence interval overlapping the published 0.78. That verifies the harness.

> And we derived the distance quantiles from the case coordinates independently. They land within 3% of Koester's published hiker figures without ever opening the book.

The second is the strongest thing you have and it is not obvious. It independently corroborates the whole extraction chain.

---

## The prior-art answer, rehearsed until automatic

> Search and rescue already uses probability models. Koester's ISRID holds over 145,000 cases and teams draw distance rings from it. We're not replacing that. We're running the same statistics through terrain instead of a circle.

Being caught unaware of the prior art would be fatal. Citing it first makes you the person who did the reading.

---

## Weaknesses — state them before anyone finds them

- Six validation cases is a small sample. The interval is wide. Say so
- Arizona had the highest variance of the three regions in the published study, and model differences were not statistically significant there. **Do not claim significance**
- Terrain cost functions are hand-tuned, not fitted
- One subject category, one search area, one weather condition
- The evidence filter treats witness reports as reliable. Real ones often are not
- **This is decision support that surfaces hypotheses, not a probability oracle.** A system directing rescuers informs a human decision. It never replaces one

---

## Demo integrity

- Warm the fleet during the team before you
- Cache model outputs and **say so in four words**. Nobody blinks at that. They blink at a suspiciously fast live call
- Put slow stages under your talking. Nothing happens in silence
- The fallback video is a capture of the first clean rehearsal, labelled as a fallback if used
- **Never present cached output as live** — the judge-picks-a-relay style interaction cannot be faked, and neither can this
- Laptop plugged in. Test on an external display at venue resolution
