# LCZ integer codes and colour table

Demuzere et al. (2022), *ESSD* 14, 3835-3873, `10.5194/essd-14-3835-2022` — the integer coding
convention and colour table used by the global LCZ map and by the LCZ Generator.

**Provenance of the colours.** Transcribed from the GDAL colormap embedded in the published
raster (`lcz_v3.tif`, band 1) rather than from the paper, because the raster *is* the shipped
product and a colormap read is not subject to PDF table-extraction error. Alpha is 255 for every
class and 0 for value 0, which the product uses as nodata.

**Class names** are Stewart & Oke's, from `stewart_oke_2012_properties.md` in this directory.

| Code | LCZ | Class name | Colour |
| ---: | :--- | :--- | :--- |
| 1 | LCZ 1 | Compact high-rise | `#8c0000` |
| 2 | LCZ 2 | Compact midrise | `#d10000` |
| 3 | LCZ 3 | Compact low-rise | `#ff0000` |
| 4 | LCZ 4 | Open high-rise | `#bf4d00` |
| 5 | LCZ 5 | Open midrise | `#ff6600` |
| 6 | LCZ 6 | Open low-rise | `#ff9955` |
| 7 | LCZ 7 | Lightweight low-rise | `#faee05` |
| 8 | LCZ 8 | Large low-rise | `#bcbcbc` |
| 9 | LCZ 9 | Sparsely built | `#ffccaa` |
| 10 | LCZ 10 | Heavy industry | `#555555` |
| 11 | LCZ A | Dense trees | `#006a00` |
| 12 | LCZ B | Scattered trees | `#00aa00` |
| 13 | LCZ C | Bush, scrub | `#648525` |
| 14 | LCZ D | Low plants | `#b9db79` |
| 15 | LCZ E | Bare rock or paved | `#000000` |
| 16 | LCZ F | Bare soil or sand | `#fbf7ae` |
| 17 | LCZ G | Water | `#6a6aff` |

Codes 1-10 are the built types and 11-17 the natural types (Stewart & Oke's A-G). Value 0 is
nodata and has no class.

**Version note.** The copy read for this transcription is `lcz_v3.tif`, version 3 of the global
map. The 2022 ESSD paper describes an earlier version. The coding convention and colour table are
unchanged between them, but a run manifest records the file it actually validated against
separately from the citation.
