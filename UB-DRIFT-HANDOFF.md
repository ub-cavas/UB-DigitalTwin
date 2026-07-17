# UB-DigitalTwin lane-drift: handoff #3

## 0. 2026-07-16 desktop correction and candidate fix

**A candidate fix is now implemented, but it still needs one laptop run before this can be called
resolved.** `launch/autoware-carla-sumo.sh` now calls
`patch_and_build_autoware_centerpoint` before launch (default
`UB_AUTOWARE_PATCH_CENTERPOINT_CUDA=1`). On the first run for a container, it backports three
upstream fixes into the pinned Autoware source and rebuilds only `autoware_lidar_centerpoint`; a
marker caches the successful build for that container's lifetime. Recreating the container causes
the patch/build to run again. Set the variable to `0` only for an A/B comparison.

### The §8 OGM ranking is contradicted by desktop data

Desktop data has now been collected. There are **22 healthy desktop runs with `act>=2` and no CUDA
fault, and all 22 have exactly the same two OGM bounds errors**, including the same geometry:

```
start.x=581, start.y=157, cell_size.x=0, cell_size.y=143 size_x:300, size_y:300
```

The OGM error is therefore not a laptop-specific precursor. It is a reproducible startup artifact
on both machines and does not discriminate faulting from healthy runs. §9.1's occupancy-grid
disable experiment is no longer the top-ranked next step.

Source inspection also weakens the proposed mechanism. `updateOrigin()` calls
`copyMapRegionLaunch()` with `region_size_x=0`, which computes a zero-block launch; it then clears
the costmap and returns at the logged bounds check before the second copy. This path is defective
and worth fixing separately, but the observed path does not issue an out-of-bounds copy.

### §4 proved less than it claimed

Moving the reported error from CenterPoint's first checked CUDA call to Thrust's
`after reduction step 2` proves that asynchronous error reporting does not identify the exact
originating instruction. It **does not prove that CenterPoint is only a victim**. The latter message
maps directly to CenterPoint postprocessing's `thrust::count_if`; an earlier CenterPoint kernel can
fault asynchronously and be reported by either site.

The pinned container uses Autoware Universe commit `cbfbb146` (2025-03-23). Its CenterPoint source
predates three directly relevant upstream fixes:

1. [`53536dc4`](https://github.com/autowarefoundation/autoware_universe/commit/53536dc467afe1d9deead40a1c84d418b2576dec): clear the auxiliary/current point buffers before preprocessing.
2. [`cb14853a`](https://github.com/autowarefoundation/autoware_universe/commit/cb14853a63ae91b04e82aa1f2e0da54768e59ac6): create the CUDA stream before `initPtr()` performs its asynchronous shuffle-index
   upload, rather than switching streams afterward.
3. [`2e2d02f4`](https://github.com/autowarefoundation/autoware_universe/commit/2e2d02f4c384bd9a5a3211dbddc0061e0854005e): in `shufflePoints_kernel`, validate `src_idx` (the index actually read) instead of
   `dst_idx`.

The old first-inference path shuffles all 2,000,000 slots while most of the source buffer is
uninitialized logical data. Which values happen to be in those allocations is GPU/runtime
dependent, matching the machine sensitivity and the first-inference timing far better than OGM.
The launcher backport clears both buffers, orders initialization on the created stream, and rejects
shuffled source indices beyond the current point count.

### Desktop verification of the backport

The CenterPoint-only rebuild completed successfully in 22 seconds. A second invocation used the
cache. A time-bounded end-to-end desktop run `2026-07-16-20-55-31` produced:

```
Activation succeeded: 2
CenterPoint loaded:     1
cudaError / illegal:    0
OGM bounds errors:      2
pointcloud_container died: 0
```

It remained healthy through the 140-second verification window and was then stopped intentionally.
The `-11` exits recorded at the end are the known SIGINT teardown noise, not runtime failures.

### Decisive laptop verification

Run the normal entry point on the laptop with no special model override:

```bash
launch/autoware-carla-passive.sh
```

The first run should print the three patch messages and build `autoware_lidar_centerpoint`; later
runs should print `CenterPoint CUDA compatibility fixes are already built.` Scope the result to the
new e2e log directory and require all of the following:

```bash
grep -c 'Activation succeeded' <NEW_E2E_LOG>/launch.log                 # expect 2
grep -c -E 'cudaError|illegal memory|after reduction' <NEW_E2E_LOG>/launch.log  # expect 0
grep -c 'component_container_mt-1.*process has died' <NEW_E2E_LOG>/launch.log   # expect 0
```

Then reproduce the first turn. A clean startup without a clean turn would finally disprove the
assumed crash-to-drift link and require separate localization/control measurement.

**Supersedes handoff #2 (and #1 before it).** Read §2 first — it lists what #2 got *wrong*, because
#2's top-ranked next step is built on a misreading and would probably have misled you. Status:
**UNRESOLVED**, but four leads are now killed by measurement rather than argument, and one
long-ignored lead is now the prime suspect.

Repo `/home/oakley/UB-DigitalTwin`, branch `Launch-Script-Refactor`, HEAD `fd2cf23`.
Entry point: `launch/autoware-carla-passive.sh` → `autoware-carla-sumo.sh` → `launch/autoware/launch.sh`.

Everything in §3–§6 was measured on **2026-07-16, 18:31 and 19:56**, on the **laptop**. Two runs were
executed this session; all other numbers come from the 28 historical runs still inside `autoware_c`.

---

## 1. Machine naming — do not skip this

Call them **desktop** and **laptop**. Never "A"/"B". **Never identify them by hostname.**

| | desktop | laptop |
|---|---|---|
| GPU | RTX 5080, 16 GB, **compute cap 12.0** (Blackwell) | RTX 4070 **Laptop**, 8 GB, **compute cap 8.9** (Ada), driver 580.142 |
| chassis | desktop tower | Dell G16 7630 |
| prompt | `awsim@awsim-Dell-G16-7630` | `oakley@oakley-Dell-G16-7630` |
| behavior | **works** — reaches the goal | **drifts** out of lane after the first turn |

**Both hostnames say `Dell-G16-7630`** because the desktop was imaged from a laptop. Only the
username or `nvidia-smi` distinguishes them. This trap has burned **three** investigators. Verify:
`nvidia-smi --query-gpu=name,compute_cap --format=csv`

All work so far is **laptop-side only**. Nobody has ever collected desktop data (§9.5).

---

## 2. Corrections to handoff #2 — read before trusting anything it says

| #2 claim | verdict |
|---|---|
| §3 "Localization **activates** at ~12–16 s, i.e. **before** the crash. The crash lands at ~+23 s." | **BACKWARDS.** The crash lands at **+20 s**; `EKF/NDT Activation succeeded` fires at **+29 s**. Across **all 18** `act>=2` faulting runs the crash precedes activation by **8.7–12.2 s**, never once the reverse. §3's *conclusion* (NDT starved all drive) survives and is **strengthened** — the scan pipeline dies before it ever activates — but every timing argument in §3 is void. Notably "no human can engage inside 23 s" is now irrelevant: the crash isn't driving-triggered at all. |
| §3 "Simple VRAM exhaustion — partially [ruled out] ... VRAM is **not** cleanly excluded" | **NOW CLEANLY EXCLUDED, measured.** At the crash: **4832–5654 MiB of 8188 (59–69%)**, ~2.5 GB free. Run peak **7096 MiB (86.7%)** occurred **46 s BEFORE** the crash during CARLA's map load, with no fault. The highest-pressure moment of the run is not the moment it dies. |
| §3 / #1 §7.1 implication that `-quality-level=Low` might help | **Dead.** Follows from the above. CARLA at `Epic` settles at only **~3.3 GB** after map load (peaks ~5.9 GB *while* loading). Epic is not the problem. |
| §9.1 "`detection.launch.xml:74` defaults `switch/detector/lidar_dnn` to `false`; only DNN types flip it true" | **WRONG.** In `lidar` perception mode (the default) `switch/detector/lidar_dnn` is set **`true` unconditionally** — it never consults `lidar_detection_model_type`. See §7. |
| §9.1 "`clustering` ... routes to the rule-based Euclidean detector" | **WRONG.** `switch/detector/lidar_rule` is **already `true`** in `lidar` mode. `clustering` does not route *to* anything — it only **subtracts** the DNN. |
| §9.1 as the #1 next step | **Actively misleading — see §7.** It would remove the *tripwire*, not the origin. |
| §9.4 TensorRT engine cache | **Tested. Real defect found and fixed — but NOT the cause.** See §5. |
| §3 "the reported location is where the error was first *checked*, not where it *originated*" | **PROVEN, experimentally.** See §4. This is #2's best insight and it is now fact, not theory. |
| §2's framing "Bug B ... prime suspect [for the drift]" | Still plausible but **still not demonstrated**. Nobody has yet reproduced the *drift* and tied it to the crash. The crash→drift link remains inference. |

Handoff #2's Bug A analysis (§4), its traps (§6), and its corrections to #1 (§7) are **not** challenged
here and appear sound. Bug A's fix is confirmed working (§6).

---

## 3. The crash, measured precisely

Baseline run `2026-07-16-18-31-20`, e2e `t0 = 1784241080`:

```
*** Aborted at 1784241100                                        <- +20 s
[1784241109.055955088] [localization.util.pose_initializer]: EKF Activation succeeded   <- +29 s
[1784241109.056915956] [localization.util.pose_initializer]: NDT Activation succeeded   <- +29 s
[ERROR] [component_container_mt-1]: process has died [pid 26257, exit code -6, ...]
```

**The crash fires during startup, on centerpoint's first inferences — before localization is ever
live.** It is not triggered by driving, by engaging, or by a live EKF. Any hypothesis requiring the
vehicle to be moving, or requiring EKF/NDT to be publishing, is dead on arrival.

### VRAM trace at the crash (2 Hz `nvidia-smi`, correlated against `*** Aborted at`)

| t (rel. e2e t0) | VRAM used | % of 8188 |
|---|---|---|
| +14.8 s | 3452 MiB | 42.2% |
| +17.0 s | 4356 MiB | 53.2% |
| **+19.1 s** | **4832 MiB** | **59.0%**  ← crash |
| +19.7 s | 5592 MiB | 68.3% |
| +20.2 s | 5654 MiB | 69.1% |
| +23.4 s | 4161 MiB | 50.8% (container dead) |

Run peak: **7096 MiB (86.7%) at unix 1784241054** — 46 s earlier, during CARLA map load, no fault.
The 3397→5654 MiB ramp across +14.8→+20 s is TensorRT deserializing and allocating workspace.
**It faults while loading/first-inferencing, with ~2.5 GB to spare.**

---

## 4. PROVEN: the reported fault location is arbitrary

This is the most useful result of the session and it is an **experiment, not an inference**.

`centerpoint_trt.cpp#L178` is the **first `CHECK_CUDA_ERROR` inside `detect()`** — a `cudaMemsetAsync`
on the encoder input, the opening CUDA call of the inference path:

```cpp
bool CenterPointTRT::detect(...)
{
  is_num_pillars_within_range = true;
  CHECK_CUDA_ERROR(cudaMemsetAsync(              // <- L178, the first tripwire in the path
    encoder_in_features_d_.get(), 0, encoder_in_feature_size_ * sizeof(float), stream_));
```

Error 700 is sticky and context-wide, so the first *checked* call after **any** prior fault reports it.
Centerpoint deserializes its engine fine and is running inference — it is a **victim/reporter**.

**The proof:** after forcing a native TensorRT engine rebuild (§5), the fault **moved to a different
site** while everything else stayed identical:

```
before:  cudaErrorIllegalAddress (700)@.../autoware_lidar_centerpoint/lib/centerpoint_trt.cpp#L178
after:   after reduction step 2: cudaErrorIllegalAddress: an illegal memory access was encountered
```

`after reduction step 2` is the message shape of a **Thrust/CUB reduction**, not centerpoint's own
`CHECK_CUDA_ERROR`. Same corruption, different tripwire, same ~+20 s timing.

**⇒ `centerpoint_trt.cpp#L178` was never the origin.** Handoff #1's §6 was right all along; #1 and #2
both dismissed it. **Stop attributing this crash to centerpoint on the strength of a stack trace.**

**Practical consequence:** grep for `cudaErrorIllegalAddress` alone. Do **not** grep the L178 string —
it no longer appears.

---

## 5. TensorRT engine cache — real defect found and FIXED, but not the cause

Handoff #2 §9.4 was right that this was never checked, and right that it *couldn't* be checked by
Autoware: the sidecar `.json` was verified to contain **only** `{"Layers": [...], "Bindings": [...]}`
— **no GPU arch, no TRT version**. A foreign engine loads undetected.

**A genuinely bogus engine was found.** Forcing a native rebuild on the laptop's sm_89:

| engine | before | after native rebuild |
|---|---|---|
| `pts_voxel_encoder_centerpoint.engine` | **617,820 B** (Jul 5) | **17,962,820 B** (Jul 16) |
| `pts_backbone_neck_head_centerpoint.engine` | 11,946,556 B (Jul 5) | 12,140,076 B (Jul 16) |
| `pts_voxel_encoder_centerpoint_tiny.engine` | 18,107,540 B (Jun 15) | untouched |

**The anomaly was the opposite of what it looked like.** The *full* model's voxel-encoder engine was
**29× too SMALL**, not tiny being too large: a native build yields ~18 MB, matching the Jun 15 `_tiny`
engine. So the **Jun 15 engines were native; the Jul 5 full-model engine was foreign/corrupt.**
That defect is real and is **now permanently corrected on the laptop**.

**But the crash persisted.** Engine staleness is **not** the cause. (TensorRT did genuinely rebuild —
`[I] [TRT] Applying optimizations and building TensorRT CUDA engine` — costing ~3 min of startup.)

Recovery if ever needed (do **not** — the rebuilt engines are the correct ones):
- `*.stale` renames beside the originals — on the **host** bind mount, survive `docker compose down`
- `/root/autoware_data/lidar_centerpoint_engines_backup_20260716/` — **inside** the container, a
  `down` destroys it

---

## 6. Bug A (bridge tick-skipping) — fix confirmed working, still uncommitted

Handoff #2 §4's analysis holds. The fix is applied but **not committed** (`git status` shows
`CARLA/UB-API/util/carla_time_master.py`, `CARLA/docker-compose.yml`, `launch/carla/time_master.sh`).

Confirmed this session with `UB_CARLA_WALL_STEP` in effect: **`stalls=9`** and **`stalls=10`** on
`act=2` runs, versus the historical laptop range of **488–1347**. It works. It does **not** stop the
CUDA fault (both runs still `cuda_faults=1`), consistent with #2's own finding.

Proper fix remains back-pressure: `external_tick=False` exists in `carla_autoware.py` but is
unreachable because `launch/autoware/launch.sh:1078` hardcodes `external_tick:=True`.

---

## 7. Why the `clustering` test (#2's §9.1) is a trap

The env var is real (`launch/autoware-carla-sumo.sh:79`, default `centerpoint/centerpoint`) and is
passed explicitly on the ros2 command line (`launch/autoware/launch.sh:525-527`), so it *does* take
effect. And it *would* disable centerpoint. **But #2's stated mechanism is wrong, and the test result
would be misleading.**

**Actual mechanism** (verified by reading the files in the container):
1. `detection.launch.xml`, `lidar` mode branch, sets `switch/detector/lidar_dnn` = **`true`
   unconditionally** — the model type is never consulted. #2's "line 74 defaults it false" reads the
   stock default and misses that the mode branch overrides it.
2. The DNN group **is entered**. It includes `lidar_dnn_detector.launch.xml`, which dispatches on
   `if type=='transfusion' / 'centerpoint' / 'apollo'`. There is **no `clustering` branch** → the
   group resolves to a **no-op**.
3. `switch/detector/lidar_rule` is **already `true`** in `lidar` mode, so the rule detector runs
   either way. `clustering` only subtracts the DNN.

**Why the result would mislead:** per §4, centerpoint is the *tripwire*. Removing it removes the
thing that *checks* for the error, not the thing that *causes* it. Expect either a relocated fault or
a silent one while the corruption continues unchecked.

**This very likely explains handoff #2 §11's great mystery** — #1's report that *disabling the
detector made the drift **worse***, which was "backwards under every hypothesis on the table."
Under §4 it is exactly right: remove the fail-fast tripwire and the corruption propagates silently
instead of aborting the container. **Treat that as the leading explanation, not an anomaly.**

---

## 8. Prime suspect: `pointcloud_based_occupancy_grid_map`

Same process (`component_container_mt-1`), same CUDA context, and it logs a **real** out-of-bounds
with **garbage geometry** — `cell_size.x=0` is uninitialized/nonsense, not a mere indexing slip:

```
[ERROR] [pointcloud_based_occupancy_grid_map]: update coordinates are negative or out of bounds:
  start.x=581, start.y=157, cell_size.x=0, cell_size.y=143 size_x:300, size_y=300
```

**It precedes the CUDA fault in 27 of 29 faulting runs**, always **exactly 2 errors**, always
**2–133 ms before**, **never after**:

| run | OGM → fault |
|---|---|
| 15-27-02 | +2 ms |
| 17-20-37 | +2.5 ms |
| 18-31-20 (baseline this session) | +79 ms |
| 19-56-50 (after engine rebuild) | +19 ms |
| 17-30-23 | +133 ms |

**The 2 exceptions matter and must be explained**: `2026-07-16-15-15-32` and `2026-07-16-15-18-34`
CUDA-faulted with **`ogm_count=0`** — the OGM node loaded but logged no out-of-bounds. So OGM is
**not necessary** for the fault.

**Two readings, both live:**
- **(a) OGM is the origin** in most runs, and the 2 exceptions have a second origin; or
- **(b) common cause** — something produces garbage geometry that OGM *reports* on CPU (fast, logged)
  while the same garbage drives an out-of-range GPU write elsewhere (illegal address). The ~20–130 ms
  gap and the shared inputs (TF tree, pointcloud) fit this well.

Reading (b) is attractive because `cell_size.x=0` smells like corrupt/uninitialized input rather than
OGM's own arithmetic. **Determine which before building a fix.**

---

## 9. Next steps, ranked

1. **Disable the occupancy grid in `pointcloud_container` and see whether the fault vanishes or
   relocates.** This is the same relocation trick that made §4 decisive, and it cleanly separates
   readings (a) and (b) of §8. If the fault **vanishes** → OGM is the origin. If it **relocates
   again** → common cause; hunt what feeds both. Success metric is the **crash**, not the drift:
   ```bash
   docker exec autoware_c bash -c 'grep -c cudaErrorIllegalAddress <THIS_RUN_LOG>/launch.log'
   ```
2. **Explain the 2 zero-OGM runs** (`15-15-32`, `15-18-34`). They are the single strongest constraint
   on §8 and they are still sitting in the container, un-analysed. What config differed? Both are
   `act=2`, both faulted at ~+20 s.
3. **Find the garbage's source** (if §8 reading (b)). Both OGM and centerpoint's `detect()` consume
   the **TF tree** and the pointcloud. Handoff #1 §3.2's **dual `map→base_link` publisher** (bridge
   ground-truth vs EKF, no arbitration) remains **untouched by all three handoffs**. Caution: it is
   *not* a simple post-activation race — §3 proves the crash precedes activation by ~9 s, so if TF is
   involved the mechanism must work **before** EKF activates. Note
   `UB_AUTOWARE_CARLA_PUBLISH_SIMULATOR_TF=0` → vehicle never engages, so the bridge TF is
   load-bearing.
4. **Enumerate every CUDA consumer sharing `pointcloud_container`** and bisect: CUDA pointcloud
   preprocessor, occupancy grid, centerpoint. `compute-sanitizer` on that container would find the
   true origin directly if it can be made to run.
5. **Get desktop data — still never obtained after 3 handoffs.** Everything known is laptop-side.
   The container has been alive since 2026-07-05 with 11 days of in-place launcher patches:
   ```bash
   docker exec autoware_c bash -lc 'find /autoware/install -name "*.ub-original" | while read f; do l="${f%.ub-original}"; d=$(diff "$f" "$l"); [ -n "$d" ] && { echo "--- $l"; echo "$d"; }; done'
   nvidia-smi --query-gpu=name,compute_cap,memory.total,driver_version --format=csv
   docker exec autoware_c bash -c 'ls -la /root/autoware_data/lidar_centerpoint/'   # engine sizes! cf. §5
   ```
   Given §5, the desktop's engine sizes are now specifically interesting.
6. **Directly measure localization error** (requested by #1 §7.4 and #2 §9.6, still never done):
   NDT/EKF pose vs the bridge's CARLA ground-truth across the first turn. This is the only way to
   confirm the **crash → drift** link, which remains inference (§10).
7. **Commit the Bug A fix** (§6). It is verified and currently sitting uncommitted.

**Deprioritised, with reasons:** VRAM / `quality-level=Low` (§2, excluded by measurement);
engine cache (§5, tested, fixed, not the cause); `clustering` (§7, would mislead);
`centerpoint_tiny` (#2 tested it — still faults).

---

## 10. What is still NOT established

- **The crash → drift link.** Every handoff assumes it. Nobody has reproduced the drift and tied it to
  the crash. §6 of this doc shows Bug A's fix leaves the crash intact; nobody has shown the converse.
- **Why the laptop faults and the desktop never does, at the mechanism level.** Ada vs Blackwell,
  8 vs 16 GB, driver 580.142 vs unknown — all correlate, none proven. **VRAM capacity is now excluded
  as the trigger (§3), which makes this *harder*, not easier, to explain.**
- **The origin of the illegal access.** §4 proves where it *isn't*.
- Container ships `/usr/local/cuda-12.4` but `libnvinfer 10.8.0.43-1+cuda12.8`; same image digest on
  both machines (`sha256:6f7391ef42e2...`). Blackwell (sm_120) requires CUDA 12.8+, and the desktop
  works — still odd, still unexplained.

---

## 11. Measurement tooling and environment notes

**You can launch the stack from a non-interactive agent session without `sudo`.** All three DDS
sysctls already pass on the laptop and `lo` has multicast, so `launch/autoware/dds.sh:63-66` returns
early and never invokes `sudo`. Do **not** set `UB_AUTOWARE_HOST_CONFIG_DDS=0` to dodge the prompt —
it risks starving LiDAR and giving a **false negative on the crash**, the exact metric you're testing.

```bash
sysctl net.core.rmem_max net.ipv4.ipfrag_time net.ipv4.ipfrag_high_thresh   # need >=10485760, <=3, >=134217728
ip link show lo | grep -qw MULTICAST
```

Per-run health (only `act>=2` rows are meaningful):

```bash
docker exec autoware_c bash -c 'for f in /root/.ros/log/*/launch.log; do grep -q ekf_localizer "$f" 2>/dev/null || continue; n=$(basename $(dirname "$f") | cut -c1-19); a=$(grep -c "Activation succeeded" "$f"); w=$(grep -c "EKF period may be too slow" "$f"); c=$(grep -c "cudaErrorIllegalAddress" "$f"); echo "$n act=$a stalls=$w cuda=$c"; done'
```

VRAM correlation (the §3 method) — sample at 2 Hz with unix timestamps, then correlate against
`*** Aborted at <unix>`:

```bash
while true; do echo "$(date +%s.%N) $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)"; sleep 0.5; done > vram.log
```

---

## 12. Log-reading traps — every one has produced a wrong conclusion

1. **Each run writes TWO log dirs ~5 s apart** — the bridge (`autoware_carla_interface`) and
   `e2e_simulator` (hosts the EKF). `ls -dt /root/.ros/log/*/ | head -1` is **wrong**.
2. **Runs with `Activation succeeded = 0` never brought localization up.** They prove nothing.
3. **NEW: never glob `/root/.ros/log/*/launch.log` when testing a fresh run.** It matches **28
   historical runs** and will "find" a CUDA fault from hours ago within milliseconds. *I did this and
   briefly believed a run had crashed before Autoware had even started.* Scope by time:
   `find /root/.ros/log -maxdepth 1 -type d -newermt @<launch_unix>`
4. **`launch.log` column 1 is the log-flush time, not the event time.** Use bracketed internal
   timestamps or `*** Aborted at <unix>`. (Both agreed to within 50 ms in this session's runs, but
   don't rely on that.)
5. **`service_log_checker` logs ONLY errors.** You cannot recover engage timing from these logs.
6. **Exit `-11` after SIGINT is teardown noise. Exit `-6` is a real crash.**
7. **Do not grep `autonomous`** — it matches the map name and `autonomous_emergency_braking`.
8. **NEW: do not grep the `centerpoint_trt.cpp#L178` string.** Per §4 the site moved. Grep
   `cudaErrorIllegalAddress`.
9. **Logs live INSIDE the container.** `docker compose down` destroys them — this is how #1 lost its
   evidence and made its §6 permanently unverifiable. **`docker kill` / `docker stop` is safe**
   (containers were killed, not removed, at the end of this session; all 29 runs survive).
10. **NEW: `nohup`-ing the launcher makes the wrapper exit 0 immediately.** That is not the run
    finishing. Also `pgrep -f <pattern>` matches its **own** `bash -c` wrapper — it will report a
    process still alive after you killed it. Use `ps -eo pid,args | grep "[v]ram-sample"`.

---

## 13. My own errors — read before trusting §3–§8

1. **The VRAM hypothesis was mine, and it was wrong.** I went in confident that 8 GB vs 16 GB plus
   `-quality-level=Epic` was the whole story. The trace killed it (§3). It was still worth measuring —
   it is now excluded rather than merely doubted — but I should not have led with it.
2. **I fell into trap #3 above** within minutes of my first run, exactly the class of error #2's §8
   apologises for. The handoff warns about globs and I still globbed.
3. **I built a TF-race hypothesis and it made a falsifiable prediction — the crash should land
   *after* activation. It lands ~9 s *before*, in all 18 runs.** Hypothesis dead. The dual-TF lead
   itself survives (§9.3) but *not* in the post-activation form I proposed.
4. **I had the engine anomaly exactly backwards.** I flagged the 18 MB `_tiny` engine as
   suspiciously large; the rebuild proved the **617 KB full engine** was the bogus one (§5). I
   reasoned from "tiny should be smaller" instead of just rebuilding and looking.
5. **I never reproduced the drift**, only the crash. §10's first bullet is a gap I did not close.
6. Everything here is **laptop-only**. I added no desktop data — the same failure as #1 and #2.

---

## 14. Constraints from the user

- **No `G16-Integration` cherry-picks.** Fixes must work on `Launch-Script-Refactor`'s own terms —
  env vars and new code are fine.
- **Call the machines desktop and laptop**, never A/B.
