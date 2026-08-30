"""The building-height cascade: fill every footprint's height, and say how well.

Overture solves footprint coverage; it does not solve height. The answer here is a graded
cascade — per-building `height`, `height_source` and `height_confidence` — plus per-unit
`height_completeness` and the full tier distribution, so that "90% surveyed heights" and
"90% coarse raster fallback" are distinguishable in the output. They produce the same LCZ label
with very different trustworthiness.
"""
