# Matrix of LCZ weighted accuracy

Bechtel, B., Demuzere, M., & Stewart, I. D. (2020). "A Weighted Accuracy Measure for Land Cover Mapping: Comment on Johnson et al. …" Remote Sensing 12(11), 1769. 10.3390/rs12111769 — OA

## Dissimilarity matrix of LCZ classes

| LCZ | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | A | B | C | D | E | F | G |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.00 | 0.08 | 0.17 | 0.33 | 0.42 | 0.50 | 0.42 | 0.25 | 0.58 | 0.25 | 0.67 | 0.75 | 0.92 | 1.00 | 0.75 | 1.00 | 1.00 |
| 2 | 0.08 | 0.00 | 0.08 | 0.42 | 0.33 | 0.42 | 0.33 | 0.17 | 0.58 | 0.17 | 0.58 | 0.67 | 0.75 | 0.92 | 0.67 | 0.92 | 0.92 |
| 3 | 0.17 | 0.08 | 0.00 | 0.50 | 0.42 | 0.33 | 0.25 | 0.08 | 0.42 | 0.08 | 0.50 | 0.58 | 0.67 | 0.83 | 0.58 | 0.83 | 0.83 |
| 4 | 0.33 | 0.42 | 0.50 | 0.00 | 0.08 | 0.17 | 0.25 | 0.50 | 0.25 | 0.42 | 0.50 | 0.42 | 0.50 | 0.67 | 0.92 | 0.67 | 0.67 |
| 5 | 0.42 | 0.33 | 0.42 | 0.08 | 0.00 | 0.08 | 0.17 | 0.33 | 0.17 | 0.33 | 0.42 | 0.33 | 0.50 | 0.58 | 0.83 | 0.58 | 0.58 |
| 6 | 0.50 | 0.42 | 0.33 | 0.17 | 0.08 | 0.00 | 0.08 | 0.25 | 0.08 | 0.25 | 0.33 | 0.25 | 0.33 | 0.42 | 0.75 | 0.50 | 0.50 |
| 7 | 0.42 | 0.33 | 0.25 | 0.25 | 0.17 | 0.08 | 0.00 | 0.33 | 0.17 | 0.33 | 0.25 | 0.33 | 0.42 | 0.58 | 0.83 | 0.58 | 0.58 |
| 8 | 0.25 | 0.17 | 0.08 | 0.50 | 0.33 | 0.25 | 0.33 | 0.00 | 0.25 | 0.08 | 0.58 | 0.50 | 0.58 | 0.75 | 0.50 | 0.67 | 0.67 |
| 9 | 0.58 | 0.58 | 0.42 | 0.25 | 0.17 | 0.08 | 0.17 | 0.25 | 0.00 | 0.33 | 0.42 | 0.33 | 0.25 | 0.42 | 0.67 | 0.42 | 0.42 |
| 10 | 0.25 | 0.17 | 0.08 | 0.42 | 0.33 | 0.25 | 0.33 | 0.08 | 0.33 | 0.00 | 0.58 | 0.50 | 0.58 | 0.75 | 0.50 | 0.67 | 0.67 |
| A | 0.67 | 0.58 | 0.50 | 0.50 | 0.42 | 0.33 | 0.25 | 0.58 | 0.42 | 0.58 | 0.00 | 0.08 | 0.17 | 0.33 | 0.58 | 0.33 | 0.33 |
| B | 0.75 | 0.67 | 0.58 | 0.42 | 0.33 | 0.25 | 0.33 | 0.50 | 0.33 | 0.50 | 0.08 | 0.00 | 0.08 | 0.25 | 0.50 | 0.25 | 0.25 |
| C | 0.92 | 0.75 | 0.67 | 0.50 | 0.50 | 0.33 | 0.42 | 0.58 | 0.25 | 0.58 | 0.17 | 0.08 | 0.00 | 0.17 | 0.42 | 0.17 | 0.17 |
| D | 1.00 | 0.92 | 0.83 | 0.67 | 0.58 | 0.42 | 0.58 | 0.75 | 0.42 | 0.75 | 0.33 | 0.25 | 0.17 | 0.00 | 0.25 | 0.08 | 0.08 |
| E | 0.75 | 0.67 | 0.58 | 0.92 | 0.83 | 0.75 | 0.83 | 0.50 | 0.67 | 0.50 | 0.58 | 0.50 | 0.42 | 0.25 | 0.00 | 0.25 | 0.25 |
| F | 1.00 | 0.92 | 0.83 | 0.67 | 0.58 | 0.50 | 0.58 | 0.67 | 0.42 | 0.67 | 0.33 | 0.25 | 0.17 | 0.08 | 0.25 | 0.00 | 0.08 |
| G | 1.00 | 0.92 | 0.83 | 0.67 | 0.58 | 0.50 | 0.58 | 0.67 | 0.42 | 0.67 | 0.33 | 0.25 | 0.17 | 0.08 | 0.25 | 0.08 | 0.00 |

## Similarity matrix of LCZ classes

**This is the matrix the metric uses.** Element-wise `1 - dissimilarity`, verified cell for cell.

| LCZ | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | A | B | C | D | E | F | G |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.00 | 0.92 | 0.83 | 0.67 | 0.58 | 0.50 | 0.58 | 0.75 | 0.42 | 0.75 | 0.33 | 0.25 | 0.08 | 0.00 | 0.25 | 0.00 | 0.00 |
| 2 | 0.92 | 1.00 | 0.92 | 0.58 | 0.67 | 0.58 | 0.67 | 0.83 | 0.42 | 0.83 | 0.42 | 0.33 | 0.25 | 0.08 | 0.33 | 0.08 | 0.08 |
| 3 | 0.83 | 0.92 | 1.00 | 0.50 | 0.58 | 0.67 | 0.75 | 0.92 | 0.58 | 0.92 | 0.50 | 0.42 | 0.33 | 0.17 | 0.42 | 0.17 | 0.17 |
| 4 | 0.67 | 0.58 | 0.50 | 1.00 | 0.92 | 0.83 | 0.75 | 0.50 | 0.75 | 0.58 | 0.50 | 0.58 | 0.50 | 0.33 | 0.08 | 0.33 | 0.33 |
| 5 | 0.58 | 0.67 | 0.58 | 0.92 | 1.00 | 0.92 | 0.83 | 0.67 | 0.83 | 0.67 | 0.58 | 0.67 | 0.50 | 0.42 | 0.17 | 0.42 | 0.42 |
| 6 | 0.50 | 0.58 | 0.67 | 0.83 | 0.92 | 1.00 | 0.92 | 0.75 | 0.92 | 0.75 | 0.67 | 0.75 | 0.67 | 0.58 | 0.25 | 0.50 | 0.50 |
| 7 | 0.58 | 0.67 | 0.75 | 0.75 | 0.83 | 0.92 | 1.00 | 0.67 | 0.83 | 0.67 | 0.75 | 0.67 | 0.58 | 0.42 | 0.17 | 0.42 | 0.42 |
| 8 | 0.75 | 0.83 | 0.92 | 0.50 | 0.67 | 0.75 | 0.67 | 1.00 | 0.75 | 0.92 | 0.42 | 0.50 | 0.42 | 0.25 | 0.50 | 0.33 | 0.33 |
| 9 | 0.42 | 0.42 | 0.58 | 0.75 | 0.83 | 0.92 | 0.83 | 0.75 | 1.00 | 0.67 | 0.58 | 0.67 | 0.75 | 0.58 | 0.33 | 0.58 | 0.58 |
| 10 | 0.75 | 0.83 | 0.92 | 0.58 | 0.67 | 0.75 | 0.67 | 0.92 | 0.67 | 1.00 | 0.42 | 0.50 | 0.42 | 0.25 | 0.50 | 0.33 | 0.33 |
| A | 0.33 | 0.42 | 0.50 | 0.50 | 0.58 | 0.67 | 0.75 | 0.42 | 0.58 | 0.42 | 1.00 | 0.92 | 0.83 | 0.67 | 0.42 | 0.67 | 0.67 |
| B | 0.25 | 0.33 | 0.42 | 0.58 | 0.67 | 0.75 | 0.67 | 0.50 | 0.67 | 0.50 | 0.92 | 1.00 | 0.92 | 0.75 | 0.50 | 0.75 | 0.75 |
| C | 0.08 | 0.25 | 0.33 | 0.50 | 0.50 | 0.67 | 0.58 | 0.42 | 0.75 | 0.42 | 0.83 | 0.92 | 1.00 | 0.83 | 0.58 | 0.83 | 0.83 |
| D | 0.00 | 0.08 | 0.17 | 0.33 | 0.42 | 0.58 | 0.42 | 0.25 | 0.58 | 0.25 | 0.67 | 0.75 | 0.83 | 1.00 | 0.75 | 0.92 | 0.92 |
| E | 0.25 | 0.33 | 0.42 | 0.08 | 0.17 | 0.25 | 0.17 | 0.50 | 0.33 | 0.50 | 0.42 | 0.50 | 0.58 | 0.75 | 1.00 | 0.75 | 0.75 |
| F | 0.00 | 0.08 | 0.17 | 0.33 | 0.42 | 0.50 | 0.42 | 0.33 | 0.58 | 0.33 | 0.67 | 0.75 | 0.83 | 0.92 | 0.75 | 1.00 | 0.92 |
| G | 0.00 | 0.08 | 0.17 | 0.33 | 0.42 | 0.50 | 0.42 | 0.33 | 0.58 | 0.33 | 0.67 | 0.75 | 0.83 | 0.92 | 0.75 | 0.92 | 1.00 |

## OA_w formula

From the same paper. `w` is the **similarity** matrix above, never the dissimilarity one.

$$
W_A = \frac{1}{N} \sum_{ij} w_{ij} c_{ij}
$$

- `w_ij` — similarity between reference class *i* and predicted class *j*, from the second table.
  One on the diagonal, in [0, 1) off it.
- `c_ij` — confusion-matrix entry: units whose reference is *i* and whose prediction is *j*.
- `N` — sample size, `sum(c_ij)`.

**Why the similarity matrix and not the other one.** Bechtel et al. derive the weighted accuracy as
a *generalisation* of overall accuracy: plain OA is already a Hadamard product of the confusion
matrix with a weight matrix of ones on the diagonal and zeros off it, which is itself a similarity
metric — every class fully similar to itself and fully dissimilar to every other. Relaxing the
off-diagonal zeros to partial similarities gives partial credit for a near-miss. So `OA_w` reduces
to `OA` exactly when `w` is the identity, and that reduction is the first thing to test.

Substituting the dissimilarity matrix inverts the measure: a perfect map would score 0.00 and a map
confusing LCZ 1 with LCZ G would score 1.00. It would not crash, and every cross-city comparison
would rank backwards, so the two tables are labelled rather than left to be inferred from context.

Worked values, from the tables above:

| classification | `W_A` with similarity | with dissimilarity (wrong) |
|---|---:|---:|
| every unit correct | **1.00** | 0.00 |
| every unit 1 predicted as 2 (adjacent) | 0.92 | 0.08 |
| every unit 1 predicted as G (opposite) | 0.00 | 1.00 |

**Precision of the transcription.** Every value is `k/12` rounded to two decimals — 0.08 is 1/12,
0.92 is 11/12. `lczkit.validation.agreement` parses these printed two-decimal values rather than
reconstructing twelfths, so the table stays the authority and the code cannot drift from it.