# Dataset preview overview (structure, questions, gotchas)

Date: 2026-11-13. Legend: **[V]** verified by reading or running code on the preview in this session; **[P]** stated by a primary file in the dataset (path given); **[U]** unverified.
Root = `~/Downloads/stoa/junction-dataset-preview/` (paths below are relative to it). All reads were read-only; Python ran with `-I` from a scratchpad outside the dataset (ezdxf 1.4.5, pymupdf, stdlib from the repo `.venv`). Complements `tooling-and-dataset.md`, which has the library-level detail; this note is the whole-dataset map.

## TL;DR

1. The preview is a 926-file sample (incl. 2 `.DS_Store`) of a ~14,000-drawing corpus; `questions.jsonl` has **7,990 questions over only 320 distinct files** (0 missing paths) **[V]**. 594 shipped files (all scans, all Swiss DXF/PNG, most opening_design) have no question **[V]**.
2. Questions exist for 5 of 9 sources: cubicasa5k 4,270, swiss_dwellings 2,358, ifc_models 1,049, ifc_bench 249, opening_design 64. habs, finna, europeana, wikimedia (all JPG/SVG scans, 374 jpg + 7 svg) have none **[V]**.
3. Three lanes cover ~99% of questions: CubiCasa PNG vision (53%), Swiss PDF (30%), IFC models and their floor PDFs (16%). Opening_design is a fourth, small, text-schedule-in-PDF lane (0.8%) **[V]**.
4. Every question is a bilingual pair (English plus the drawing's own language), so the "real" question count is about half **[V]**.
5. Several traps are baked in: whole-model questions attached to a one-floor PDF; Swiss questions point at the PDF only; 20 DWGs with no parser; schedule PDFs in `ft2`; free-form `text` answers with no stated grader (section 7).

## 1. README claims (`README.md`) **[P]**

- "About 14,000 construction drawings (PDF, DWG, DXF, IFC, SVG, PNG and JPEG scans) ... about 30 languages, with about 120,000 quantity-takeoff questions for roughly 40% of them." Non-commercial, Junction challenge.
- Layout: `data/<source>/<file>`, `data/<source>/LICENSE.md`, `questions.jsonl` with `{"path","question","answer","unit","type"}`.
- "Files with the same name and a different extension are the same drawing in another format." `ifc_models` floor plans `<model>_<level>.pdf` were rendered from `<model>.ifc`.
- `type` in count, area, length, volume, text, other. Scoring: counts exact; area/length/volume within 2%; text free-form. (`other` never occurs in the preview.) **[V]**
- Source table: cubicasa5k, swiss_dwellings, opening_design, ifc_models, ifc_bench, habs, finna, europeana, wikimedia with licences. Questions inherit the drawing's licence.
- Preview scale check: 7,990 questions / 320 files vs README's 120,000 / ~40% of 14,000 (~5,600 files): the preview is about 6.7% of the questions. Per-file density is far higher here (25 per file) than the README average (~21) only because the preview was built around questioned files **[V]**.

## 2. Folder layout and file counts **[V]**

Totals by extension: jpg 374, png 306, pdf 123, dxf 66, dwg 20, ifc 14, svg 10, md 10 (9 `LICENSE.md` + `README.md`), jsonl 1, `.DS_Store` 2.

| `data/` folder | files | types | questioned files | notes |
|---|---|---|---|---|
| `cubicasa5k` | 241 png (+LICENSE.md) | 187 `high_quality_architectural-N`, 41 `high_quality-N`, 13 `colorful-N` | 241 | Finnish plans; renamed files; CC BY-NC-SA (`cubicasa5k/LICENSE.md`) |
| `swiss_dwellings` | 65 dxf, 65 pdf, 65 png | triplets `siteS_bldgB_floorF.*` | 65 (PDF only) | rendered from Swiss Dwellings v3.0.0 geometry (`swiss_dwellings/LICENSE.md`) |
| `ifc_models` | 4 ifc, 3 pdf, 3 svg | see below | 6 (3 pdf, 3 ifc) | `LICENSE.md` says plans rendered with IfcOpenShell |
| `ifc_bench` | 5 ifc | IFC4 x3, IFC2X3 x2 | 5 | unchanged IFC-Bench v2 models, 64 MB largest (`hitos_arc.ifc`) |
| `opening_design` | 20 dwg, 1 dxf, 5 ifc, 55 pdf | original OpeningDesign repo folders kept (`Transfer/<date - note>/`, `Sheets - Current Set/`...) | 3 pdf | 17 project folders |
| `habs` | 92 jpg | HABS/HAER/HALS sheets, e.g. `al1159_sheet_00001.jpg`, max 2250 px | 0 | public domain |
| `finna` | 96 jpg | Helsinki archives, 66 named `hka.N_N.jpg` | 0 | CC BY 4.0 |
| `europeana` | 61 jpg | museum scans, 279 to 2250 px | 0 | per-file licence |
| `wikimedia` | 125 jpg, 7 svg | `<commons id>.jpg`; the SVGs have **no** IFC classes (0 `data-guid`) | 0 | per-file licence |

`ifc_models` contents: `bsc-clinic_clinic-plumbing.ifc` (IFC2X3, 54 MB), `bsc-esplanades_1807-ep-ar-v18.ifc` (IFC2X3, 12 MB) with `_plan-04-4-korrus.pdf/.svg`, `bsc-molio_molio-with-uris.ifc` (IFC2X3, 72 MB) with `_plan-02-klder.pdf/.svg`, `resbim-388_model.ifc` (IFC4, 2 KB), and `kit-fzk-haus_ac20-fzk-haus_plan-02-dachgeschoss.pdf/.svg` **whose `.ifc` is not shipped** **[V]**. `ifc_models/LICENSE.md` also says Duplex and Clinic get "no drawings rendered".

`opening_design` DWG/DXF/IFC: 20 DWG are scattered across `Transfer/*` and `Sports_Complex/Transfer/_Archive/*`; the one DXF is `Screened_in_Porch/Models & CAD/BIM/Linked - CAD & Data/Site plan.dxf`; IFCs include 3 of "FreeCAD roundtrip"/"bad IFC models - for autopsy only" type (`ULI-44_E_Mifflin-Suite_802/Models/bad IFC models - for autopsy only/...ifc`) **[V]**. PDFs: 55 files, 43 are 1 page, others 2 to 15 pages; 49 contain raster images, 6 have no extractable text, 4 have no vector paths (page 1 check) **[V]**.

Swiss PDFs, DXFs, PNGs are all 65/65 (same stems); all 65 PDFs are 1 page, vector, 0 images, text present **[V]**.

## 3. The question set (`questions.jsonl`)

### 3.1 Schema **[V]**
7,990 lines, all with exactly the keys `path, question, answer, unit, type`. 0 duplicate (path, question) pairs. `answer` is int (6,085), float (1,640) or str (265, the `text` type). `unit` is `count`, `m2` (1,590), `ft2` (9), `m` (16), `m3` (34), or `null` for text.

| type | n | unit |
|---|---|---|
| count | 6,076 | count |
| area | 1,599 | m2 (1,590), ft2 (9) |
| text | 265 | null |
| volume | 34 | m3 |
| length | 16 | m |

### 3.2 By source, file type, type **[V]**

| source | target file | type: n |
|---|---|---|
| cubicasa5k | `.png` | count 4,270 |
| swiss_dwellings | `.pdf` | count 1,614, area 744 |
| ifc_models | `.ifc` | area 692, count 93, volume 28, length 14 (= 827) |
| ifc_models | `.pdf` | area 154, count 60, volume 6, length 2 (= 222) |
| ifc_bench | `.ifc` | text 249 |
| opening_design | `.pdf` | count 39, text 16, area 9 |

(ifc_models total 1,049.) Paths per source: cubicasa 241 (each has 8 to 24 questions, mostly 10 to 24), swiss 65 (28 to 42 each), ifc_models 6, ifc_bench 5, opening_design 3.

### 3.3 Templates and one example per type **[V]**
Questions come in language pairs: English plus the drawing's language.

- **cubicasa5k count (12 EN templates, each with a Finnish twin):** windows (241 files), floors/storeys (241), WC seats (240), sinks (239; "double-bowl sink counts as one"), showers+bathtubs total (227), doors (176; "open doorways without a door leaf do not count"), bedrooms "(makuuhuone, usually marked MH)" (154), kitchens (161), bathrooms/washrooms (111), separate WC rooms (112), saunas (165), balconies (68). Example: `{"path":"data/cubicasa5k/colorful-11397.png","question":"How many windows are shown on this floor plan?","answer":13,"unit":"count","type":"count"}`. 496 of the 4,270 answers are 0 (saunas, balconies etc. absent), median 1, max 44.
- **swiss_dwellings count:** apartments (65), doors "interior and entrance together" (65), windows (65), toilets WC (65), washbasins (65), bathtubs (56), showers, "rooms labelled X" (e.g. `Pièce`). Each file's questions come in EN + one of de (22 files) / fr (22) / it (21). Example: `site1102_bldg2242_floor10281.pdf` "How many apartments (residential units) are shown on this floor plan?" = 2. Answer range 0 to 114 (20 zeros).
- **swiss_dwellings area:** total net area of all numbered indoor rooms (65), net area of apartment A/B/... "excluding balconies, loggias, terraces and other outdoor spaces" (~90), net area of room N, total area of rooms labelled "Pièce" etc. Example: same file, total net area = 193.49 m2. Range 1.51 to 1275.14 m2 (108 distinct EN/DE/FR/IT-normalised templates).
- **ifc_models count/area/length/volume:** per-level "doors/rooms/walls/columns/stairs/windows shown on the floor plan of 'N.korrus'" (13 doors templates etc.); per-room "net floor area of the room 'ELUTUBA+KÖÖK (57-1)' on '2.korrus', in m²" (Esplanades, Estonian twin "Kui suur on ruumi ..."); per-level "total length of all walls on 'N. Sal'" and "total net volume of all walls/slabs on ..." (Molio, Danish twin); one "total net side area of all walls on 'Dachgeschoss'" (FZK, type area); "How many sanitary fixtures are there in the model 'Medical-Dental Clinic - plumbing'?" = 119 (the only whole-model question on an `.ifc`). Example: `{"path":"data/ifc_models/bsc-molio_molio-with-uris.ifc",... "total length of all walls on 'N. Sal', in metres?","answer":222.79,"unit":"m"}`. Esplanades `.ifc` has 486 questions, Molio `.ifc` 340.
- **ifc_bench text (239 distinct templates):** free-form multi-line strings, e.g. "What is the building's type and its function?" -> `'Building Type: Office Building\n   Building Name: Buerogebaeude\n   Total Levels: 5 floors'` (`ifc_bench/ac20_arc.ifc`). Others: spaces per level with areas, largest room, MEP counts by system, software/IFC version. 30 of 249 answers are of the form "...not available in this model" / "not found" (abstention is a correct answer) **[V]**. `unit` is null.
- **opening_design (64):** all on sheet A-801 "Door and Finish Schedules & Wall Types" (41 questions), A-701 Restrooms (3) and CTR `A700 - SCHEDULES.pdf` (20). Count: "how many doors in the door schedule are door type A1 (swing door)?" (39); area in **ft2**: "area of room 101 (Fieldhouse) in the finish room schedule" = 29690 ft2 (9); text: width `'5\'-10 3/8"'`, hardware group `'19'`, `'3 rooms, 4541 SF'` (16).

## 4. How questions map to source files

| lane | question target | what the data actually contains | evidence |
|---|---|---|---|
| CubiCasa vision | `cubicasa5k/*.png` (raster only) | 241 PNG, 150x410 to 3375x1575 px; no SVG ground truth shipped; no vector route | folder listing **[V]**; `tooling-and-dataset.md` section 3 |
| Swiss vector | questions on `swiss_dwellings/*.pdf` only | DXF + PNG with the same stem exist but carry **no questions**; DXF is the cleaner source (layers `WALL, DOOR, WINDOW, ROOM_OUTLINE, ROOM_TEXT, FIXTURE, UNIT_OUTLINE, ANNOTATION`) | **[V]**, `tooling-and-dataset.md` 2.3 |
| IFC | `ifc_models/*.ifc` per-level and per-room; `ifc_bench/*.ifc` text | IFC files are the ground-truth source; SVG/PDF are renders | **[V]** |
| Floor-plan PDF of IFC | `ifc_models/*_plan-*.pdf` (3 files, 222 questions) | one level only, vector, text labels; SVG sibling has `class="Ifc*"` + `data-guid` | **[V]** |
| Schedule PDF | `opening_design` A-801, A-701, A700 | text-in-PDF tables, scale unknown, 49 PDFs in the folder carry raster images | **[V]** |

Findings against the teammate notes:

- **IFC-derived SVGs retain `data-guid` and `class`: confirmed on all 3 in this preview.** Counts: Esplanades 317 elements (146 `IfcWallStandardCase`, 60 `IfcSpace`, 53 `IfcWindow`, 42 `IfcDoor`), Molio 120 (51 `IfcRailing`, 27 `IfcWall`, 14 `IfcSpace`, 14 `IfcDoor`, **no IfcWindow**), FZK 49 (42 `IfcMember`, 2 `IfcSlab`, 2 `IfcWindow`, 2 `IfcWallStandardCase`). The "107" figure is a full-dataset number and cannot be checked from the preview **[V for 3/3]**. Note the 7 wikimedia SVGs are ordinary drawings with 0 `data-guid`.
- **Whole-model questions target floor PDFs: confirmed.** Questions "How many doors are there in the model ..." attach to the three `_plan-*.pdf` (Esplanades 211 doors/297 windows/285 rooms/846 walls; Molio 119/119/117/189; FZK 5/11/7/13), while the same PDFs show a single level (Esplanades 4.korrus: 42 doors, 60 rooms, 160 walls, 1 stair). Only one whole-model question points at an `.ifc` (clinic plumbing) **[V]**. A system that routes by file extension and answers from the PDF will give the per-floor number for a whole-model question. Detect "in the model" vs "on the floor plan of" in the question text.
- **Volume/length questions target PDFs: contradicted for the preview.** 42 of 50 volume/length questions target `.ifc` (Molio per-level walls/slabs); only 8 target PDFs (FZK 6: walls length 42.8 m, wall volume 15.202 m3, slab volume 52.992 m3; Molio Kaelder slab volume 277.334 m3 plus length/volume twins). FZK's are on the PDF only because its `.ifc` is not shipped, so those 6 are unanswerable by geometry from files in the preview **[V]**.
- **733/1040 Swiss DXFs lack explicit m2 area text:** the preview shows **42 of 65 DXFs (65%) have zero `m²` text** and only 23 have any; across the 65, 550 `m²` labels exist vs 1,618 numbered room labels (matches `tooling-and-dataset.md` 2.3: labels only for larger rooms). Same direction as 733/1040 (70%) **[V]**.

## 5. Per-folder detail on what is machine-readable **[V]**

- **swiss DXF:** all 65 are `AC1027`, `$INSUNITS`=6 (metres) **[V]**. Titles: 22 German "Massstab", 22 French "Échelle", 21 Italian "Scala" (annotation layer). The language of the room names and of the second question follows the same split.
- **opening_design DWG:** 20 files, 18 `AC1027` and 2 `AC1021` header bytes; sizes 75 KB to 10.8 MB. ezdxf cannot open DWG; needs ODA File Converter or LibreDWG, neither installed (see `tooling-and-dataset.md` 4.3). No question points at any DWG, so they are unscored **[V]**.
- **opening_design DXF:** `Site plan.dxf` is `AC1009`, `$INSUNITS` unset **[V]**.
- **IFC:** schema per file: ifc_bench `ac20`, `digital_hub`, `fantasy_office_building_3` IFC4; `duplex`, `hitos` IFC2X3; ifc_models clinic/esplanades/molio IFC2X3, `resbim-388` IFC4 (2 KB, trivial) **[V]**.

## 6. Gotchas

1. **Preview vs full corpus:** counts in team notes from the full set (107 SVGs, 1,040 DXFs) differ from the preview (3 IFC SVGs, 65 swiss DXFs + 1 other). Do not hard-code preview counts.
2. **Swiss questions never name the DXF.** To use the better DXF source, map `path` `.pdf` -> same stem `.dxf` (README rule) **[V]**.
3. **Whole-model vs per-floor ambiguity** on the three plan PDFs (section 4).
4. **FZK `.ifc` missing:** its 24 questions (PDF-targeted) include whole-model and volume/length ones that cannot be derived from files in the preview **[V]**.
5. **Units:** Swiss/IFC areas in m2; opening_design areas in **ft2** with feet-inch strings (`5'-10 3/8"`) in text answers. Scoring tolerance is 2% for area/length/volume.
6. **Level names are per-model and non-English:** `4.korrus` (Estonian), `N. Sal`/`Kaelder`/`Grundplan` (Danish), `Dachgeschoss` (German); casing varies in the same model (`N. Sal` vs `N. sal`, `Grundplan`) **[V]**.
7. **"Net" area semantics:** Swiss "net area of apartment A" excludes balcony/loggia/terrace; ifc_models room area comes from geometry (Esplanades spaces lack Qto) or Qto (Molio) per `tooling-and-dataset.md` 1.3.
8. **Free-form `text` answers (ifc_bench 249, opening_design 16):** README gives no grader; 30 ifc_bench answers are "not available" abstentions. Multi-line, indented, mixes numbers with prose.
9. **Labels vs rooms:** swiss questions like "rooms labelled 'Pièce'" depend on the assigned language of the drawing (`swiss_dwellings/LICENSE.md`: "room names in an assigned language (de, fr or it)").
10. **Duplicate-looking Finnish pairs in CubiCasa:** each question appears in EN and FI with the same answer (2,135 each) so scoring both doubles any systematic error **[V]**.
11. **Zero answers** are legitimate: 496 CubiCasa, 20 Swiss.
12. **`.DS_Store`** x2 in the tree; ignore.
13. **Untrusted data:** SVG/PDF/IFC content is attacker-controllable text; do not execute or `eval` anything from it.

## 7. What a QA system over this needs

1. **Router** by (source from path, question phrase), not just extension: `cubicasa5k` -> vision lane; `swiss_dwellings` -> DXF lane (swap `.pdf` to `.dxf`); `ifc_models`/`ifc_bench` `.ifc` -> IFC lane; `ifc_models` `*_plan-*.pdf` -> if question says "in the model" use the sibling `.ifc` (Esplanades, Molio) else floor SVG/PDF; `opening_design` PDFs -> schedule-table text extraction.
2. **IFC lane:** per-level queries by storey name; Qto sums where present, geometry footprints otherwise (Esplanades). Handle IFC2X3 and IFC4 and multilingual storey names. For `text` questions return the same structured prose style as the answers (`Level 1 (OG1) Spaces:\n Total spaces: 17\n Total area: 299.30 sq m`) and abstain when quantities are absent.
3. **Swiss lane:** DXF polylines per layer: door = 5-vertex DOOR polyline, window = 4-vertex WINDOW polyline, apartments = unique `Whg.`-style labels, room area by shoelace on the closed ROOM_OUTLINE containing the room-number text; do not depend on `m²` labels (42/65 DXFs have none). Fixtures (WC/washbasin/bathtub/shower) remain not decoded **[U]**; apartment net area (needs room-to-unit containment, outdoor exclusion by localised name) not tested **[U]**.
4. **CubiCasa lane:** vision model (or CubiCasa-trained segmenter) producing counts for 12 categories, plus Finnish room abbreviations (MH, KH, PH, WC); expect 0 as a common answer.
5. **Schedule lane (opening_design):** PDF text-position table parsing; handle ft/in strings and `ft2`.
6. **DWG:** needs a converter; unscored in the preview, but they are in the corpus.
7. **Scoring awareness:** exact for counts, 2% for the rest; mix of EN and local-language twins means one parser must be language-agnostic (question language only changes labels like "Pièce", level names).

## 8. Not verified

- The 120,000/14,000 full-corpus statistics, 107 SVGs and 733/1040 DXFs (preview only).
- Swiss PNG pixel dimensions (prior note says 2480x1753); `type: other` never appears.
- Whether the Junction grader uses an LLM judge for `text`.
- Any numeric correctness of answers beyond what `tooling-and-dataset.md` already reproduced.
