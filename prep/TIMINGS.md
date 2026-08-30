# Daytona fleet timings — measured 30 Aug 2026

Measured against the live API with `orchestrator/fleet.py`, at the real demo
shape: 200 hypotheses × 60 seeds = 12,000 simulations.

---

## The finding that changes the plan

**The account caps at 10 GiB of sandbox memory in total.**

The `searchlight-worker` snapshot requests 2 GiB, so the hard ceiling is
**5 concurrent sandboxes**, not the 200 the spec plans for.

```
COLD provision: 50 requested -> 5 created, 45 failed
first error: DaytonaBadRequestError: Failed to create sandbox:
             Total memory limit exceeded. Maximum allowed: 10GiB.
```

This is exactly the number the spec said to measure before the day, and it is
40× smaller than the plan assumed. Everything below is measured at the real
ceiling rather than the hoped-for one.

### The ceiling is 10, and 10 is achievable

Memory is not the only cap. Halving the snapshot to 1 GiB doubles the fleet to
10, at which point a SECOND limit binds:

```
requested 14 @1GiB -> 10 created in 2.4s, 4 refused
Total CPU limit exceeded. Maximum allowed: 10.
```

Both limits are 10 -- 10 GiB of memory and 10 vCPU -- so at 1 vCPU per sandbox
**10 concurrent is the hard ceiling regardless of memory**. There is no
configuration on this tier that reaches 200.

`sl-worker-1g` (1 vCPU / 1 GiB) is built and is the snapshot to use. It is
strictly better than the 2 GiB one: twice the fleet, same result.

| snapshot | memory | concurrent | 200 hypotheses | rate |
|---|---|---|---|---|
| `searchlight-worker` | 2 GiB | 5 | 13.7 s | 877 sims/s |
| **`sl-worker-1g`** | **1 GiB** | **10** | **9.3 s** | **1,289 sims/s** |

Both produce `field_area_pct` 14.6%, so halving memory costs nothing.

### What still works

The demo runs fine. Five sandboxes are reused across the 200 hypotheses:

| Stage | Time |
|---|---|
| Cold provision, 5 sandboxes in parallel | **2.5 s** |
| Dispatch 200 hypotheses → 12,000 sims | **13.7 s** |
| Teardown | 0.1 s |
| **Total wall clock** | **16.2 s** |

877 simulations/second. 11,478 of 12,000 runs returned `ok`; zero fell back to
local execution. Resulting `field_area_pct` 14.6%, identical to the local run,
so the sandbox path and the local path agree.

Single-sandbox latency, measured separately: **create 0.87 s, upload 0.90 s,
run 0.55 s.** That create time matches the ~742 ms figure in the independent
benchmark the spec cites.

---

## What this means for the pitch

**Do not say "200 sandboxes" while 5 are running.** The fleet counter is the
only thing on screen proving real machines are working, and a judge who asks
to see the dashboard will see five.

Three honest options:

1. **Say the real number.** "Five isolated sandboxes, each writing and running
   its own movement model, 12,000 simulations in fourteen seconds." That is a
   true and impressive sentence, and 877 sims/s is a good number.
2. **Upgrade the account** if the tier allows it. The error message says
   "upgrade your ... to increase concurrency limits". That is a spend decision
   and a time risk on the day.
3. **Use the 1 GiB snapshot.** Already done -- `sl-worker-1g` doubles the
   fleet to 10 and cuts the run to 9.3 s. This is free and there is no reason
   not to. It does not get you past 10.

**The architecture argument is unchanged either way.** It needs ephemeral
isolated compute at scale, and the honest caveat in the spec already says "not
this specific vendor". A capacity ceiling on a free tier is not an argument
against the design.

---

## Reproducing

```bash
python prep/daytona_ctl.py status      # what exists, what it is costing
python prep/daytona_ctl.py snapshots   # available images
python prep/daytona_ctl.py clean       # kill everything tagged searchlight
```

Cost at these scales is negligible — the 50-sandbox attempt above was about
$0.02 in practice — but **idle sandboxes bill by the second and nothing on
screen tells you they are up.** Run `status` after any interrupted run.

### A real incident worth recording

An early fleet run crashed *after* creating sandboxes (a `set` of unhashable
`Sandbox` objects), leaving 5 running with no handle on them. They were found
and deleted in under a minute because every sandbox is created with a
`searchlight` label and `daytona_ctl.py clean` filters on it. Cost: ~$0.014.

That is why the label and the reaper exist, and why `fleet.py` also registers
an `atexit` sweep.

---

## Building a snapshot on Windows — two traps

1. **`add_local_file` / `add_local_dir` mangle path separators.** Passing
   `data/meta.json` produced `/datameta.json` and the build failed on a missing
   ref; `prep/_snapshot_data` became `/prep_snapshot_data`. Stage the files in
   a **top-level directory whose name contains no separator** and pass that.
   `_snapdata/` exists for this.
2. **A failed build still occupies the name**, and `snapshot.delete()` is
   async, so an immediate rebuild under the same name hits
   `DaytonaConflictError`. Either wait, or build under a new name.
