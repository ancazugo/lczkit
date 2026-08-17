# Validation

::: lczkit.validation
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

Agreement reported lczexplore-style — per-class figures and a sparse confusion matrix, never a
single accuracy number.

!!! danger "Validate against labelled ground truth, not against another model"

    `lcz_v3.tif` is an estimate carrying its own error. Measuring against it compares two models
    and reports the disagreement as `lczkit`'s error. Where labelled polygons exist — So2Sat
    LCZ42, WUDAPT — **those are the reference** and `lcz_v3` is a secondary comparator.
    `reference_file` is recorded on every report, because "the reference" naming a role instead
    of a file is how both of this project's reference mix-ups stayed invisible.

Three things any per-city figure needs stated beside it:

- **Its ceiling.** Agreement between `lcz_v3` and labelled polygons on the same cells bounds what
  a comparison against `lcz_v3` can score. Ceilings range 22.8% (Mumbai) to 83.2% (Rio).
- **Built-class agreement, separately**, with the natural-class share alongside. An overall figure
  dominated by trivially-classified water says nothing about the classifier.
- **The label reproducibility.** Two independent expert label sets over the same ground agree at a
  median 79.9% across sixteen cities, ranging 26.3% (Cairo — *below* its own 52.1% majority-class
  baseline) to 96.3% (Paris). Where two references disagree, no classifier can agree with both.

!!! warning "Never report '% of ceiling'"

    Vancouver scores 41.8% against a 36.7% ceiling — 114%. The comparator is another estimator,
    not an upper bound. Report raw agreement and ceiling side by side, or their difference.

::: lczkit.validation.agreement

## Confusion axes

Two different instruments, and they must not be conflated:

- **Height axis** — 1↔2↔3 and 4↔5↔6. Compactness fixed, height band varies. Pairs with
  `height_completeness`.
- **Compactness axis** — 1↔4, 2↔5, 3↔6. Height fixed, building surface fraction varies. Pairs
  with footprint coverage and unit definition.

**Only pair-normalised lift against a composition-preserving null is reported.** The raw share
cannot compare the two: the height axis affords six pairs to compactness's three, so a null that
never looks at the data awards height 3.9× more error on affordance alone.

## Weighted accuracy

`OA_w` and its class-similarity matrix, from Bechtel, Demuzere & Stewart (2020) — the metric that
makes per-class figures comparable to published LCZ maps. Reported beside plain `OA`, never
instead of it.

::: lczkit.validation.similarity

## References

::: lczkit.validation.labelled

::: lczkit.validation.reference

::: lczkit.validation.wudapt

## Uncertainty

Spatial-**block** bootstrap, not cell-wise. So2Sat patches are 320 m on a 100 m stride, so a
city's labelled cells are one correlated sheet and resampling cells would report an interval far
too narrow.

::: lczkit.validation.uncertainty

## Parameter ranges

::: lczkit.validation.ranges
