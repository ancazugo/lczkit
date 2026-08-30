# Validation

::: lczkit.validation
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

Agreement between a run's labels and a reference set, reported in the style of the `lczexplore`
package — per-class figures and a sparse confusion matrix, never a single accuracy number.

Terms used throughout this page are defined in the [glossary](../glossary.md): *ceiling*, *overall
accuracy*, *built-class agreement* and the two *confusion axes*.

!!! danger "Validate against labelled ground truth, not against another model"

    `lcz_v3.tif` — the Demuzere global LCZ map, derived from satellite imagery — is an estimate
    carrying its own error. Measuring against it compares two models and reports the disagreement
    as `lczkit`'s error. Where hand-drawn polygons exist — So2Sat LCZ42, a labelled benchmark set
    over 51 cities, and WUDAPT, the community-contributed World Urban Database and Access Portal
    Tools — **those are the reference** and `lcz_v3` is a secondary comparator.
    `reference_file` is recorded on every report: "the reference" names a role, and the three
    that can fill it disagree by up to 18 points, so a figure that does not say which file produced
    it cannot be read.

Three things any per-city figure needs stated beside it:

- **Its ceiling.** How well `lcz_v3` itself agrees with the hand-drawn polygons on the same cells.
  That bounds what any map can score against `lcz_v3`, and it varies enormously: 22.8% in Mumbai,
  83.2% in Rio.
- **Built-class agreement, separately**, with the natural-class share alongside. An overall figure
  dominated by trivially-classified water says nothing about the classifier.
- **The label reproducibility.** Two independent expert label sets over the same ground agree at a
  median 79.7% across twenty-eight cities, ranging 26.3% (Cairo — *below* what a constant predictor
  scores there, 52.1%) to 97.7% (Istanbul). Where two references disagree, no classifier can agree
  with both, so this is a floor under every residual reported here.

!!! warning "Never report '% of ceiling'"

    Vancouver scores 41.8% against a 36.7% ceiling — 114%. The comparator is another estimator,
    not an upper bound. Report raw agreement and ceiling side by side, or their difference.

::: lczkit.validation.agreement

## Confusion axes

Two different ways a label can be wrong, and they diagnose different things, so they must not be
conflated:

- **Height axis** — confusions between 1↔2↔3 and between 4↔5↔6. Compactness is fixed and the
  height band varies, so this tracks the quality of the height data. Read it beside
  `height_completeness`.
- **Compactness axis** — confusions between 1↔4, 2↔5 and 3↔6. Height is fixed and building surface
  fraction varies, so this tracks how completely the footprints were captured and how the units
  were drawn.

**Only pair-normalised lift against a composition-preserving null is reported.** The raw share
cannot compare the two: the height axis affords six pairs to compactness's three, so a null that
never looks at the data awards height 3.9× more error on affordance alone.

## Weighted accuracy

Plain **overall accuracy** (`OA`) counts a unit right only if its label matches the reference
exactly. **Weighted overall accuracy** (`OA_w`) gives partial credit according to how similar the
two classes are, using the class-similarity matrix of Bechtel, Demuzere & Stewart (2020) — so
calling a compact midrise an open midrise scores most of a point, while calling it water scores
near zero.

`OA_w` above `OA` therefore says the map is landing in *neighbouring* classes rather than at
random. That is a real and useful thing to know, and it is **not** an accuracy figure. It is
reported beside `OA` and never instead of it.

::: lczkit.validation.similarity

## References

::: lczkit.validation.labelled

::: lczkit.validation.reference

::: lczkit.validation.wudapt

## Uncertainty

Confidence intervals come from a spatial-**block** bootstrap — resampling contiguous blocks of
cells rather than individual cells. So2Sat patches are 320 m across on a 100 m grid, so neighbouring
cells frequently carry the same label from the same patch: a city's labelled cells are one
correlated sheet, and resampling them individually would report an interval far too narrow.

::: lczkit.validation.uncertainty

## Parameter ranges

::: lczkit.validation.ranges
