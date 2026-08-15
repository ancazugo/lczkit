# docs/references

Reference literature for `lczkit`. **This README is committed; the PDFs are not.**

`lczkit` is an independent implementation of the LCZ mapping approach, built from the published
literature rather than from existing source code. GeoClimate is LGPL-3.0 and UMEP is GPL-3.0;
this package is permissively licensed, so the papers below — not those codebases — are the
source of every algorithm and every threshold.

## Rules

1. **PDFs are gitignored.** Publisher licensing, not size. Never `git add` a PDF here.
2. **Never quote more than a short phrase** from a paper into code comments, docstrings, or
   documentation. Paraphrase and cite the DOI.
3. **`tables/` beats the PDFs for numbers.** Transcribed tables are hand-checked, cheap to
   read, and immune to PDF table-extraction errors. Use them for any numeric lookup.
4. **If a source you need is missing, say so and stop.** Do not reconstruct a Tier 1 numeric
   range from memory. A plausible-looking wrong threshold is the worst failure mode this
   package has, because nothing will crash — the map will just be quietly wrong.

## Populating this folder

PDFs are obtained manually. Resolve each DOI at `https://doi.org/<DOI>`. Everything marked
**OA** below is open access and freely downloadable.

Filename convention — lowercase, underscores, no spaces:

```
firstauthor_year_shortname.pdf

stewart_2012_lcz.pdf
bernard_2024_geoclimate_lcz.pdf
kanda_2013_roughness.pdf
```

Layout:

```
docs/references/
├── README.md          # committed
├── references.bib     # committed
├── tables/            # committed — transcribed numeric tables
├── datasets/          # gitignored — product manuals
├── papers/            # gitignored — paper pdfs
└── *.pdf              # gitignored
```

`references.bib` is committed and should stay in sync with the tables below. It doubles as the
bibliography for the eventual methods paper.

---

## Tier 1 — authoritative numbers

Read these directly. Do not infer their contents.

| File | Citation | DOI | Access | Phase | What to read |
|---|---|---|---|---|---|
| `stewart_2012_lcz.pdf` | Stewart & Oke (2012), *BAMS* 93(12), 1879–1900 | `10.1175/BAMS-D-11-00019.1` | paywalled | 6 | The table of geometric and surface-cover properties per LCZ class — SVF, aspect ratio, building surface fraction, impervious/pervious fraction, height of roughness elements, terrain roughness class, admittance, albedo. **Transcribed in `tables/`; use that.** |
| `stewart_2014_ucp.pdf` | Stewart, Oke & Krayenhoff (2014), *Int. J. Climatol.* 34(4), 1062–1080 | `10.1002/joc.3746` | paywalled | 6 | Refined per-class UCP values derived from observations and modelling. Only needed if used in preference to the 2012 ranges. |
| `bernard_2024_geoclimate_lcz.pdf` | Bernard et al. (2024), *GMD* 17, 2077–2107 | `10.5194/gmd-17-2077-2024` | **OA** | 2, 5, 6 | RSU partitioning rules; the 14 urban canopy parameters and their definitions; the normalisation scheme and distance-to-prototype classification producing primary, secondary and uniqueness. The core methodological reference. |
| `bernard_2022_heights.pdf` | Bernard et al. (2022), *GMD* 15, 7505–7532 | `10.5194/gmd-15-7505-2022` | **OA** | 3 | Estimating missing building heights from morphology. Also the evidence for why height completeness must be reported. |
| `demuzere_2022_global_lcz.pdf` | Demuzere et al. (2022), *ESSD* 14, 3835–3873 | `10.5194/essd-14-3835-2022` | **OA** | 6 | Integer coding convention (1–10 built, 11–17 for A–G), the standard colour table, and the validation target dataset. |
| `bechtel_2020_weighted_accuracy.pdf` | Bechtel, Demuzere & Stewart (2020), *Remote Sens.* 12(11), 1769 | `10.3390/rs12111769` | **OA** | 6 | The weighted accuracy `OA_w` and the LCZ class-similarity matrix it weights the confusion matrix with. **Transcribed in `tables/`; use that.** The file holds the similarity matrix *and* its complement — `OA_w` uses the similarity one, and substituting the other inverts the measure without raising. |
| `davenport_2000_roughness.pdf` | Davenport et al. (2000), AMS 12th Conf. Applied Climatology | — | conference paper | 5 | The terrain roughness class lookup. **Transcribed in `tables/`.** |

## Tier 2 — deferred algorithms

Present ahead of need, so the context exists when SVF and roughness come off the deferred list.

| File | Citation | DOI | Access | What to read |
|---|---|---|---|---|
| `bernard_2018_svf.pdf` | Bernard et al. (2018), *Climate* 6(3), 60 | `10.3390/cli6030060` | **OA** | Vector ray-launching SVF. **The preferred route for this package** — no DSM required, composes with the existing vector pipeline. |
| `lindberg_2010_svf.pdf` | Lindberg & Grimmond (2010), *Climate Research* 42, 177–183 | `10.3354/cr00882` | **OA** | Raster SVF from urban DEMs; what UMEP implements. Alternative to the above. |
| `zaksek_2011_svf.pdf` | Zakšek, Oštir & Kokalj (2011), *Remote Sensing* 3(2), 398–415 | `10.3390/rs3020398` | **OA** | Cheaper raster SVF approximation. |
| `macdonald_1998_roughness.pdf` | Macdonald, Griffiths & Hall (1998), *Atmos. Environ.* 32(11), 1857–1864 | `10.1016/S1352-2310(97)00403-2` | paywalled | z₀ and z_d from plan area and frontal area index. The classic formulation. |
| `kanda_2013_roughness.pdf` | Kanda et al. (2013), *Boundary-Layer Meteorol.* 148, 357–377 | `10.1007/s10546-013-9818-x` | paywalled | Improved z₀/z_d using height standard deviation and maximum. **Preferred over Macdonald here**, since real cities are heterogeneous. |
| `grimmond_1999_aerodynamic.pdf` | Grimmond & Oke (1999), *J. Appl. Meteorol.* 38, 1262–1292 | `10.1175/1520-0450(1999)038<1262:APOUA>2.0.CO;2` | **OA** | Framing and comparison of morphometric roughness methods. |

## Tier 3 — methodology and context

| File | Citation | DOI / ID | Access | Phase | What to read |
|---|---|---|---|---|---|
| `majer_2026_lcz_morphometrics.pdf` | Majer & Fleischmann, arXiv | `arXiv:2603.00132` | **OA** | 1 | **Supplementary D is effectively the Phase 1 cleaning spec** — geometry validity, overlap handling, small-building absorption, cross-layer topology. Supplementary A is a morphometrics menu. The negative result on morphometrics-only prediction is the reason this package prioritises height quality over parameter count. |
| `fleischmann_2019_momepy.pdf` | Fleischmann (2019), *JOSS* 4(43), 1807 | `10.21105/joss.01807` | **OA** | 2, 5 | momepy overview. |
| `fleischmann_2026_neatnet.pdf` | Fleischmann et al. (2026), *CEUS* 123, 102354 | `10.1016/j.compenvurbsys.2025.102354` | **OA** | 1 | Parameter-free street network simplification. Why dual carriageways and roundabouts must be collapsed before enclosure generation. |
| `arribasbel_2022_tessellation.pdf` | Arribas-Bel & Fleischmann (2022), *Habitat International* 128, 102641 | `10.1016/j.habitatint.2022.102641` | **OA** | 2 | Enclosed tessellation and barrier logic. |
| `quan_2021_gis_lcz_review.pdf` | Quan & Bansal (2021), *Building & Environment* 196, 107791 | `10.1016/j.buildenv.2021.107791` | paywalled | 6 | How threshold choices are made in practice across the GIS-based LCZ literature. |
| `bechtel_2015_wudapt.pdf` | Bechtel et al. (2015), *IJGI* 4(1), 199–219 | `10.3390/ijgi4010199` | **OA** | — | WUDAPT Level 0 protocol. Context for what this package is an alternative to. |
| `demuzere_2021_lcz_generator.pdf` | Demuzere, Kittner & Bechtel (2021), *Front. Environ. Sci.* 9, 637455 | `10.3389/fenvs.2021.637455` | **OA** | — | LCZ Generator; the imagery-based baseline. |
| `fonte_2019_osm_lcz.pdf` | Fonte et al. (2019), *Urban Climate* 28, 100456 | `10.1016/j.uclim.2019.100456` | paywalled | — | Using OSM to enhance LCZ maps. |
| `huang_2023_lcz_review.pdf` | Huang et al. (2023), *RSE* 292, 113573 | `10.1016/j.rse.2023.113573` | paywalled | — | Broad LCZ mapping review. |
| `gousseff_lczexplore.pdf` | Gousseff et al., lczexplore | `10.5281/zenodo.7646866` | **OA** | 6 | The agreement-metric reporting format Phase 6 mirrors. |
| `zhu_2020_so2sat_lcz42.pdf` | Zhu et al. (2020), *IEEE GRSM* 8(3), 76–89 | `10.1109/MGRS.2020.2964708` | paywalled | 6.7 | **The primary validation reference**, not a deferred training set. How the labels were drawn and by whom, and the patch sampling geometry — 320 m patches on a 100 m stride, which is why `lczkit.validation.labelled` anchors a label on the patch centre rather than overlaying it areally. Covers 52 cities; Berlin is one, Rotterdam is not. |

## Tier 4 — dataset documentation (`datasets/`)

Class definitions here become **config values**. Read them rather than assuming.

| File | Source | Phase | What to read |
|---|---|---|---|
| `datasets/esa_worldcover_v200_pum.pdf` | ESA WorldCover v200 Product User Manual (Zanaga et al.) | 4 | The 11 class codes and their definitions. **Transcribed in `tables/`, together with this project's mapping decisions.** |
| `datasets/lang_2023_canopy_height.pdf` | Lang et al. (2023), *Nat. Ecol. Evol.* 7, 1778–1789, `10.1038/s41559-023-02206-6` | 4 | ETH 10 m global canopy height — resolution, uncertainty, known biases in dense urban areas. |
| `datasets/ghsl_built_h_documentation.pdf` | GHSL GHS-BUILT-H technical documentation (Pesaresi et al., JRC) | 3 | What the 100 m height product actually measures, and its uncertainty. Matters because it is the tier-2 height fallback. |
| `datasets/overture_schema_<version>.pdf` | Overture Maps schema reference — buildings, transportation, base | 1 | Field definitions for `height`, `num_floors`, `sources`, `subtype`, `class`. Pin the schema version in the filename. |

## Deferred-tier sources

Fetch when the corresponding deferred feature is picked up.

| Citation | DOI | For |
|---|---|---|
| Kamath et al. (2024), *Sci. Data* 11, 886 | `10.1038/s41597-024-03719-w` | UT-GLOBUS height tier |
| Zhu et al. (2025), *ESSD* 17, 6647 | `10.5194/essd-17-6647-2025` | GlobalBuildingAtlas height tier |
| Milojevic-Dupont et al. (2020), *PLOS ONE* 15(12), e0242010 | `10.1371/journal.pone.0242010` | ML height imputation |
| Demuzere et al. (2022), *JOSS* 7(76), 4432 | `10.21105/joss.04432` | W2W / WRF export |

---

## `tables/` — transcribed numeric tables

Hand-transcribed, hand-checked, committed, diffable. **These are the authority for numeric
lookups**, not the PDFs.

| File | Source | Notes |
|---|---|---|
| `tables/stewart_oke_2012_properties.md` | Stewart & Oke (2012) | One row per LCZ class; explicit `min`/`max` columns; explicit null where a property is undefined for a class. Ranges deliberately overlap between adjacent classes — do not "fix" this. |
| `tables/davenport_roughness_classes.md` | Davenport et al. (2000) | Eight roughness classes with z₀ values. |
| `tables/esa_worldcover_classes.md` | ESA WorldCover v200 PUM | Class codes, plus this project's mapping to pervious / impervious / tree / water, **with the reasoning for each borderline decision recorded inline**. |
| `tables/lcz_class_similarity.md` | Bechtel et al. (2020) | The 17x17 class similarity matrix, its complement, and the `OA_w` formula. Values are k/12 rounded to two decimals. **Two matrices with identical headers** — parse by section heading, not by header row. |
| `tables/stewart_2014_ucp.md` | Stewart et al. (2014) | Only if the refined values are used in preference to the 2012 ranges. |

The LCZ integer codes and colour table are **not transcribed** — they ship as data files with
`lczexplore` and `LCZ4r` and with the global map metadata. Fetch programmatically rather than
copying hex values by hand.

Each table file must carry a header comment recording: source citation, DOI, which table or
page it came from, transcription date, and who checked it.

## Open TODO

Table and figure numbers are deliberately omitted above, since they should be confirmed
against the actual PDFs rather than assumed. Fill them into the "What to read" column on first
read of each Tier 1 paper.