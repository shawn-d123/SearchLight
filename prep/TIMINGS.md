# Daytona fleet timings — MEASURED, Sun 30 Aug 2026

Person B. Measured against the live API, not estimated. Everything below is a
real number except the two rows explicitly marked *extrapolated*.

**Read the first section even if you read nothing else. It changes the plan.**

---

## 1. The fleet is 10 sandboxes, not 200

The account tier caps **total CPU at 10** and **total memory at 10 GiB**, across
all live sandboxes. Not per sandbox — total. So:

| worker size | max concurrent |
|---|---|
| `searchlight-worker`, 1 CPU / **2 GiB** | **5** |
| `searchlight-worker-1g`, 1 CPU / **1 GiB** | **10** |

We use the 1 GiB snapshot. A worker mmaps 33.7 MB of terrain and holds a few
thousand floats, so 1 GiB is nowhere near tight, and it doubles the fleet.
10 is the hard ceiling either way, because CPU caps at 10 as well.

```
DaytonaBadRequestError: Failed to create sandbox: Total memory limit
exceeded. Maximum allowed: 10GiB.
```

**This does not change the demo.** 200 hypotheses still run; they run in ~20
waves over 10 sandboxes instead of all at once. A sandbox is reused by
uploading a new `job.json`, which costs ~30 ms. Nobody can count sandboxes on
screen, and the fleet counter shows simulations, not machines.

**Say the real number on stage.** "Ten isolated machines, two hundred generated
scripts" is true and is a better sentence than a vague large number a judge
might probe.

---

## 2. Measured numbers

| | value | notes |
|---|---|---|
| Snapshot bake, 5 files, 33.7 MB | ~1.1 s | layers cached; first build is slower |
| Create **1** sandbox + upload runtime | **1.59 s** | |
| Create **10** sandboxes in parallel + upload runtime | **2.23 s** | 10/10, no failures |
| Dispatch 20 batches × 60 runs = **1,200 sims** | **1.59 s** | 1200/1200 ok |
| First batch back after dispatch | **0.55 s** | this is the beat that must land |
| Throughput | **~756 sims/s** | across 10 sandboxes |
| Codegen, 8 scripts in parallel (`gpt-5.4-mini`) | **4.3–7.5 s** | 8/8 compiled and ran |
| 12,000 sims (200 × 60) | *extrapolated* ~16 s | 20 waves of 10 |
| 60 codegen calls at 60-way concurrency | *extrapolated* ~8 s | |

Cost is negligible: 10 sandboxes alive for five minutes is well under a dollar
against $200 + $100 of credit.

---

## 3. Warm pools do not exist on this tier

```
NotFoundException (404): Cannot GET /api/warm-pools
```

`daytona.warm_pool` is in the SDK but the endpoint is not deployed for this
account. **There is no warm-pool measurement to report, because there is no
warm pool.**

It does not matter. Cold-starting the *entire* fleet takes 2.23 s, and the demo
does not pay even that:

> **Acquire the fleet when the app loads, hold it, dispatch when you press run.**
> First trajectories are on screen 0.55 s after the keypress.

`fleet.acquire()` sets `auto_stop_interval=0`. Without it the fleet quietly
auto-stops on the idle timeout between setup and the pitch, and the first
dispatch becomes ten machines resuming while the room watches a still map.

---

## 4. Three traps that cost real time

1. **Concurrent execs on ONE sandbox collide.** Firing 12 dispatches at 5
   sandboxes returns bare `Failed to execute command` with no detail and lost
   300 of 720 runs. Each sandbox owns a lane and works it sequentially;
   parallelism comes from the number of sandboxes. Fixed in `fleet.run_all()`.

2. **Deleting a sandbox does not free quota immediately.** A create straight
   after a delete fails with `Total CPU limit exceeded` while 0 sandboxes are
   listed. Do not thrash create/delete — acquire once and reuse.

3. **`Image.add_local_file` is broken on Windows** in daytona 0.207.0.
   `compute_archive_base_path` strips the drive letter but keeps backslashes,
   so the Dockerfile gets `COPY Users\masca\...` and the Linux builder eats
   each backslash as an escape:

   ```
   failed to compute cache key: "/UsersmascaOneDriveDocuments...meta.json": not found
   ```

   `ensure_snapshot()` chdirs into `data/` and adds files by **bare filename** —
   no separators, nothing to mangle. Do not "tidy" that back to absolute paths.

   A failed build also leaves a snapshot record in `ERROR` state that blocks the
   name, and deletion is async — `ensure_snapshot()` polls until the name frees.

---

## 5. How to reproduce

```bash
python orchestrator/fleet.py --build-snapshot        # bake terrain, 1 GiB
python orchestrator/fleet.py --smoke                 # 1 sandbox, end to end
python orchestrator/fleet.py --n 10 --hypotheses 20 --runs 60
python worker/run_local.py                           # no sandbox, no keys
python orchestrator/codegen.py --run                 # one generated script
```
