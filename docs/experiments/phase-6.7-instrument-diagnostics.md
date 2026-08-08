# Phase 6.7 — instrument diagnostics

**Result: the reference was the biggest single instrument error. Measured against hand-labelled
So2Sat polygons instead of `lcz_v3.tif`, Berlin goes 24.3% → 40.9%, against a ceiling of 53.2% —
the agreement `lcz_v3` itself reaches on those cells. The residual against a real reference is
12.3 points, not 26.**

Two further results, both of which change what to do next:

- **`is_planar_enforced` is now `True`.** The cause was three footprint pairs whose overlap had
  collapsed to zero area, which `geoplanar.trim_overlaps` cannot clear because its `difference` is
  a no-op on them. Cost of the fix: 4.5×10⁻⁵ m² of 3.13 km².
- **The dominant error axis inverts under a real reference.** Against `lcz_v3` the height axis
  carried 31.8% of Berlin's disagreement and compactness 25.8%. Against the labels it is
  **compactness 55.2%, height 17.0%**. Phase 6.6 promoted height estimation to the top of the
  candidate list on evidence taken against the wrong reference; that ranking does not stand.

Reproduce the fixture figures with `uv run --active python scripts/unit_scale_experiment.py`
(offline). Numbers below are run `20260808T084045Z`; the Phase 6.6 comparison is run
`20260807T233734Z`, recorded in [phase-6.6-footprint-attrition.md](phase-6.6-footprint-attrition.md).

Nothing was tuned. Ranges, weights, the LCZ 10 rule and the height cascade are untouched — every
change in the headline figure above comes from measuring against a different reference, and the
figure against `lcz_v3` is unchanged at 24.3%.

---

## 1. The real reference, and the ceiling

### The data, and why the label is anchored on a point

So2Sat LCZ42 v4 holds hand-labelled patches for 52 cities. Berlin is one; **Rotterdam is not** —
Amsterdam, 60 km away, is the nearest. So Berlin carries the ceiling and Rotterdam stays on
`lcz_v3` with that stated, exactly as CLAUDE.md anticipated.

The patches are 320 m squares sampled on a **100 m stride**, so they overlap each other heavily.
Inside the Berlin fixture bbox: 473 patches, 48.4 km² of patch area over a **7.1 km² union**, 16,560
overlapping pairs. An areal overlay would count the same ground up to nine times under labels that
need not agree, and the resulting majority would describe the sampling density rather than the city.

Anchoring each label on its patch **centre** removes that entirely, and is exact at the scale
lczkit validates on — the So2Sat patch grid and `GridUnits` are both aligned to the local UTM origin
at 100 m:

| | measured |
|---|---:|
| patches over the fixture bbox | 473 |
| centres falling inside a grid cell | 438 |
| distinct cells labelled | **438** |
| cells receiving two labels | **0** |
| centres ambiguous between cells | **0** |

`tests/test_validation_labelled.py` asserts this rather than assuming it, so a future fixture that
breaks the alignment fails there instead of quietly degrading a headline.

### The ceiling: 53.2%

`lcz_v3.tif` scored as if it were a run, against the labels, on the same 432 cells:

| | agreement | n |
|---|---:|---:|
| **`lcz_v3` vs So2Sat labels** | **53.2%** | 432 |
| — reference LCZ 2 | 63.7% | 331 |
| — reference LCZ 5 | 18.8% | 101 |

Where it goes wrong is systematic, not scattered. `lcz_v3` calls 64 of the true-LCZ-2 cells **LCZ 1**
and 30 of the true-LCZ-5 cells LCZ 1 — it reads Berlin Mitte as compact high-rise. It also puts 32
true-LCZ-2 cells in LCZ 4 and 27 true-LCZ-5 cells in LCZ 4.

**Every previous figure in this project was measured against that.** The 50–60% band lczkit was
being held to is a band `lcz_v3` does not itself clear here.

### Berlin re-reported

Same run, same cells, two references:

| arm | vs So2Sat labels | vs `lcz_v3` | description |
|---|---:|---:|---|
| A | **40.9%** | 24.3% | 100 m grid, `buildings_area` — the pipeline |
| B | **45.4%** | 28.4% | enclosures, projected to the grid |
| C | 40.9% | 24.3% | 100 m grid, raw Overture footprints (control) |
| — | *53.2% (ceiling)* | — | `lcz_v3` itself |

All 432 compared cells are built, so the built-class figure and the overall figure coincide here —
there is no water inflating anything.

Per class, arm A against the labels: **LCZ 2 43.7% (n=332), LCZ 5 32.1% (n=106)**. lczkit is better
than `lcz_v3` on LCZ 5 (32.1% against 18.8%) and worse on LCZ 2 (43.7% against 63.7%).

**A and C remain identical**, which is the Phase 6.6 regression test: no footprint area is being
lost again.

### The axis inversion

Share of all disagreement carried by each axis, arm A, same run, two references:

| reference | height axis (1↔2↔3, 4↔5↔6) | compactness axis (1↔4, 2↔5, 3↔6) |
|---|---:|---:|
| `lcz_v3` | 31.8% | 25.8% |
| **So2Sat labels** | **17.0%** | **55.2%** |

This is the finding with the most consequence. Phase 6.6 saw error move onto the height axis after
the footprints were restored and read that as evidence that height estimation was now the binding
constraint. Against real labels the picture is the opposite: more than half of lczkit's Berlin
disagreement is **2↔5**, compactness held against height — the axis that diagnoses footprint
coverage and unit definition, not the height cascade.

The height-axis share that Phase 6.6 measured was largely `lcz_v3`'s own LCZ 1 over-assignment
being attributed to lczkit.

**Bounded by what the labels cover.** These 438 cells hold only LCZ 2 and LCZ 5, so the compactness
axis is reachable through a single pair (2↔5) while the height axis is reachable through four
(2→1, 2→3, 5→4, 5→6). The inversion is therefore *not* an artefact of the compactness axis having
more ways to fire — it has fewer. But a two-class reference cannot rule out that a wider extent
would rebalance them, which is what §4 is for.

---

## 2. `is_planar_enforced` — cause and fix

Pre-existing, out of scope for 6.6, and blocking here because `momepy.enclosures()` requires a
planar input and the A/B decision rests on enclosure quality.

**The cause is three footprint pairs, on Berlin only.** After `resolve_overlaps` they satisfy the
`overlaps` predicate — `relate` gives `212111212`, a two-dimensional interior intersection — while
`intersection()` returns a MultiLineString of **area exactly 0.0**. `geoplanar.trim_overlaps` clears
overlaps with a plain `difference`, which on a zero-area overlap returns its input unchanged, so the
pairs survive any number of passes. Rotterdam was already planar.

What does not work, tried before settling:

| attempt | result |
|---|---|
| iterating `trim_overlaps` to a fixed point | no change after 5 passes |
| `shapely.set_precision`, grid 1e-9 … 1e-2 | fixes at most one of the three; coarse grids create new overlaps |
| `shapely.difference(grid_size=…)`, 1e-9 … 1e-2 | fixes one of three at 1e-6, none elsewhere |
| **subtracting a 1 µm buffer of the other polygon** | **clears all three** |

The buffer forces a genuine re-noding of the shared boundary, which a plain `difference` on
collinear-but-mismatched vertices does not. `enforce_planarity` runs it to a fixed point, trimming
the **larger** of each pair to match `trim_overlaps(strategy="largest")`.

| | Berlin | Rotterdam |
|---|---:|---:|
| residual pairs | 3 | 0 |
| passes to converge | 2 | 0 |
| area removed | **4.5×10⁻⁵ m²** | 0 |
| as a share of the layer | 1.4×10⁻⁹ % | — |
| `is_planar_enforced` after | **True** | **True** |

It runs **last** among the topo operations, after `absorb_small_buildings`: absorb dissolves, and a
dissolve can reintroduce the artefact, so the invariant has to be established after the last thing
that can break it.

**One decision the spec did not cover.** `eps_m = 1e-6` is a module constant, not a `CleaningConfig`
field. CLAUDE.md's "thresholds go in config" rule is aimed at domain parameters — a road half-width,
a storey height — where a different city warrants a different value. A one-micrometre geometric
tolerance is a floating-point remedy: nothing about a city would make another value right, and
exposing it would invite tuning a number that has no meaning to tune. Flagged rather than assumed.

---

## 3. Rotterdam's LCZ 8

CLAUDE.md's query: for cells the reference calls LCZ 8, is BSF inside the published 30–50%?

**Answer: outside, and not footprint loss.** Arms A and C are numerically identical, so cleaning is
removing nothing. On the 224 cells the reference calls LCZ 8, area-weighted:

| | Rotterdam | Berlin (n=29) |
|---|---:|---:|
| median BSF | **0.126** | 0.148 |
| inside published 0.30–0.50 | 12.5% | 31.0% |
| at or above 0.30 | 21.9% | 34.5% |
| BSF exactly zero | **10.7%** | 3.4% |
| cells holding no building at all | **10.7%** | 3.4% |

### Separating the two readings

The deciles are the instrument. Rotterdam, area-weighted:

```
0.000  0.000  0.007  0.037  0.067  0.126  0.180  0.225  0.319  0.447  0.985
```

This is not a distribution that is uniformly low. It spans essentially the full range: a fifth of
the area sits at or above 0.30 and the top decile reaches 0.985 — solid shed. The bottom fifth is
literally zero. **That is the bimodal signature of a fabric alternating large sheds with open
apron**, not the flat low distribution that would indicate the reference painting LCZ 8 over open
ground.

### The enclosure comparison does not support the scale reading, and one half of it is not usable

Measuring the same class on enclosures was meant to test the scale hypothesis directly. It had to
be area-weighted first — enclosures carrying a reference class of LCZ 8 have a *median* area of
0.12 ha in Rotterdam, so a count-weighted median reads 0.000 and describes slivers. Area-weighted:

| | grid (100 m) | enclosures |
|---|---:|---:|
| Berlin, median BSF | 0.148 | 0.319 |
| Berlin, share in range | 31.0% | 46.4% |
| Berlin, area covered | 0.29 km² | **0.15 km²** |
| Rotterdam, median BSF | 0.126 | 0.175 |
| Rotterdam, share in range | 12.5% | **4.3%** |
| Rotterdam, area covered | 2.24 km² | 2.76 km² |

**Berlin's half of this is a selection effect, not a result.** A unit enters either set when its
own majority reference class is LCZ 8, and the two selections need not agree — Berlin's enclosure
set covers half the ground its cells do, and consists mostly of small enclosures in dense fabric,
which have high BSF for reasons that have nothing to do with LCZ 8. The 0.319 is not the same
ground reaching the published range at a larger unit size; it is different ground.

**Rotterdam's half is usable and points the other way.** There the two sets cover comparable area
(2.76 km² against 2.24 km²), and moving to enclosures *lowers* the share inside the published range,
from 12.5% to 4.3%. The median rises but the distribution does not move into the band. Enclosures do
not recover LCZ 8 here.

The covered area is now recorded in the diagnostic beside both figures, so this comparison can be
checked rather than assumed. Its absence is what made the Berlin number look like a result.

### Interpretation

Rotterdam is both things at once, and the split is partly measurable. A tenth of the cells the
reference calls LCZ 8 hold **no building whatsoever**; "large low-rise" with zero buildings is not a
unit-size artefact, and those cells are the reference being coarser than the ground. The remainder
shows the bimodal signature, and lczkit's predictions for the set are what that produces: **53 cells
to LCZ 15 (bare rock or paved)** and 42 to LCZ 9 (sparsely built) — the apron half of the fabric,
correctly described at 100 m and mislabelled relative to a patch-scale reference.

What the evidence does **not** support is that a larger unit fixes it: the one comparison covering
like ground says the opposite. So the reading is that a 100 m cell describes port fabric accurately
and the reference describes it at patch scale, and that the two disagree for reasons no unit size
available here reconciles.

This cannot be closed further from Rotterdam alone, because Rotterdam has no labelled coverage. The
clean route, deliberately not taken here as it is a fourth measurement this phase did not ask for:
**Amsterdam has 206 labelled LCZ 10 patches and 850 LCZ 8 patches, including Westpoort.**

---

## 4. The wider Berlin extent

The committed fixture's 438 labelled cells carry only LCZ 2 and LCZ 5 — both midrise, so the
compactness axis is a single pair and most of the height axis is untestable. Enough to measure a
ceiling; not enough to decide anything about the classifier.

`scripts/berlin_wide_validation.py` runs the same three arms over 16×16 km of Berlin. Window sizes
were measured before one was picked:

| half-width | extent | labelled cells | classes |
|---|---|---:|---|
| 6 km | 12×12 km | 2715 | 2, 5, 6, 8, A, B |
| **8 km** | **16×16 km** | **3584** | **2, 4, 5, 6, 8, A, B, D** |

It reads `DATA_DIR` and the network, so it is not a fixture and CI cannot run it. Rasters are
clipped into the run directory; the only write under `input/` is Overture's own new cache entry.

**Runtime is the binding constraint, and it is `neatnet`.** The Overture pull for 256 km² takes
under a minute (34 MB of footprints). Street simplification does not: at the time of writing the
16×16 km run had spent **2½ hours** inside `neatify_singletons` / `_best_link` without reaching the
arms, and the 12×12 km run 1½ hours. The committed 9 km² fixture cleans in about a minute, so this
is markedly superlinear in extent rather than 28× the work.

That is a finding in itself, and it bears on Phase 7 and on any real city run: **`clean_vectors` as
it stands does not scale to a whole city on one core.** Nothing in CLAUDE.md's plan has needed it to
until now, and it is not this phase's job to fix — but the A/B decision at metropolitan scale is
gated on it, not on the classifier.

**Both runs were left in flight rather than killed**; they write `berlin_wide_validation.json` and
`berlin_medium_validation.json` into their run directories when they land. The A/B recommendation
below therefore rests on the fixture-scale evidence, and is stated as provisional for that reason.

---

## 5. A vs B — the evidence, and a provisional recommendation

| | arm A (grid) | arm B (enclosures) |
|---|---:|---:|
| Berlin, vs labels | 40.9% | **45.4%** |
| Berlin, vs `lcz_v3` | 24.3% | **28.4%** |
| Berlin, LCZ 2 vs labels | 43.7% | **49.7%** |
| Berlin, LCZ 5 vs labels | 32.1% | 32.1% |
| Berlin, compactness-axis share | 55.2% | **49.0%** |
| Rotterdam, built vs `lcz_v3` | **3.1%** | 2.2% |
| Rotterdam, overall vs `lcz_v3` | **42.3%** | 42.0% |

**B leads on Berlin against real labels, by 4.5 points, and the lead is in the right place** — it
comes entirely from LCZ 2 (49.7% against 43.7%) with LCZ 5 unchanged, and it lowers the compactness
axis' share of disagreement from 55.2% to 49.0%. That is what a better-sized unit should do to the
axis that diagnoses unit size, and it is now measured against labels rather than against `lcz_v3`.

**B still trails on Rotterdam**, on both the built figure and overall, and Rotterdam has no labels
to check that against.

**Provisional recommendation: do not adopt enclosures yet.** Two things are missing and both are
cheap relative to the change:

1. The class-diverse extent. Berlin's labelled cells are LCZ 2 and LCZ 5 only, so B's entire
   measured lead lives in one class of one city. §4 exists to widen that and has not landed.
2. Rotterdam's disagreement is unexplained rather than tolerated. §3 shows its enclosures moving
   LCZ 8 *further* out of the published range on like ground, which is a reason B loses there, not
   merely an observation that it does.

The Phase 6.5 rejection of the scale hypothesis stays reopened, not reversed. What has changed since
6.6 is that B's lead is now visible against ground truth and with a planar topology layer underneath
it — the two conditions CLAUDE.md set for reconsidering. What has not changed is that one city and
two classes is a thin basis for changing the package's unit of computation.

---

## 6. What this changes

**The residual is 12.3 points against a real reference, not 26 against a literature band.** lczkit
reaches 77% of what `lcz_v3` reaches on the same ground, and beats it outright on LCZ 5.

Candidate causes, **re-ranked on this phase's evidence**:

1. **Unit definition and footprint coverage.** The compactness axis carries 55.2% of Berlin's
   disagreement against real labels, and arm B leads arm A by 4.5 points there. This was third
   before and is now first.
2. **The metric's missing dimensions.** SVF carries weight 4 of Bernard's 21.5 and is unapplied;
   `FB` holds ~47% of a metric never meant to be dominated by it. Unchanged in position.
3. **Height estimation.** Demoted. It carried 31.8% of disagreement against `lcz_v3` and 17.0%
   against the labels; most of that share was `lcz_v3`'s own LCZ 1 over-assignment.

**The reference ceiling is no longer a candidate cause — it is a measured quantity**, and every
residual is now stated against it. `RunManifest` carries it in `reference_ceiling`, beside
`validation_ground_truth` and `validation`, as three separate fields; the harness writes it per
fixture into its own run record. (There is no pipeline runner assembling a manifest end to end yet
— the CLI is deferred — so the harness JSON is where a reader finds the number today.)

Range recalibration remains blocked, and nothing in weights, prototype ranges, the LCZ 10 rule or
the height cascade was touched.
