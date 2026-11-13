# Tooling and dataset research (quantity takeoff over drawings)

Date: 2026-11-13. Legend: **[V]** verified by running code on the dataset preview in this session; **[P]** stated by a primary source (URL given); **[U]** unverified or secondary.
Scratch scripts live outside the repo; all dataset reads used `python -I`. Versions used: ezdxf 1.4.5, PyMuPDF 1.27-era (`pymupdf`), ifcopenshell 0.9.0.post1.

## TL;DR (what to build on)

1. **swiss_dwellings: use the DXF (or PDF) vectors, not OCR/vision.** Layers are `WALL, DOOR, WINDOW, ROOM_OUTLINE, ROOM_TEXT, FIXTURE, UNIT_OUTLINE, ANNOTATION`. Heuristics below reproduce ground truth on all 65 preview floors: doors 65/65, windows 65/65, apartments 65/65, per-room net area 129/129 (within 2%) **[V]**.
2. **ifc_models floor-plan PDF/SVG:** the SVG carries `class="IfcWall|IfcSpace|IfcDoor..."`, `data-name`, `data-guid` per element **[V]**. The PDF has only vectors + text labels, no IFC class. For the IFC itself, ground truth matches `Qto` sums for walls (Molio) and geometry footprint sums for spaces (Esplanades) **[V]**.
3. **PDF library licence trap:** PyMuPDF is AGPL-3.0 / commercial dual-licensed **[P: package METADATA]**. ezdxf is MIT, IfcOpenShell is LGPL-3.0-or-later.
4. **DWG:** ezdxf cannot read DWG itself; needs ODA File Converter (non-commercial/community licence, not installed here) or LibreDWG (GPLv3, source build). Neither is installed on this machine **[V]**. 20 DWG files in `opening_design` (headers AC1027/AC1021) will need conversion.

---

## 1. IfcOpenShell: area, wall length, net volume per storey

### 1.1 Two sources of numbers
| Source | What it is | When to trust |
|---|---|---|
| `Qto_*BaseQuantities` (IFC4) / `BaseQuantities` (IFC2X3) property sets read with `ifcopenshell.util.element.get_psets(el, qtos_only=True)` | Values written by the authoring tool | Only if present. Absent in many models |
| Geometry derived: `ifcopenshell.geom.create_shape` + `ifcopenshell.util.shape.get_volume / get_footprint_area / get_side_area` | Computed from the tessellated geometry | When no Qto, or Qto is custom/rounded |

- `get_psets(element, psets_only=False, qtos_only=False, should_inherit=True, verbose=False)`: returns `{pset_name: {prop: value, 'id': ...}}`; inherits from the type unless `should_inherit=False`. Source: IfcOpenShell `util/element.py` https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/src/ifcopenshell-python/ifcopenshell/util/element.py **[P]**.
- `get_decomposition(element, is_recursive=True)`: "all subelements ... based on the spatial decomposition hierarchy. This includes all subspaces and elements contained in subspaces, parts of an aggregate, all openings, all fills of any openings..." (same file) **[P]**. Therefore filter by `is_a(...)` after calling it on an `IfcBuildingStorey`.
- Shape helpers (https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/src/ifcopenshell-python/ifcopenshell/util/shape.py **[P]**):
  - `get_volume(geometry)`: "total internal volume ... Volumes of non-manifold geometry will be unpredictable"; returns m3.
  - `get_footprint_area(geometry, axis="Z", direction=None)`: "projected surface area visible from along an axis", typically used for footprint areas.
  - `get_side_area(geometry, axis="Y", direction=None, angle=90.0)`: actual (not projected) area of surfaces visible from an axis, e.g. one side of a wall.
  - `get_total_edge_length`, `get_area`, `get_max_side_area` also exist.
- Unit scale: `ifcopenshell.util.unit.calculate_unit_scale(ifc_file, unit_type="LENGTHUNIT")` returns the factor "ifc_project_length * unit_scale = si_meters" (unit.py, same repo) **[P]**.

### 1.2 What the Qto names mean (buildingSMART definitions)
buildingSMART's own web pages returned HTTP 403 to automated fetch here, so definitions below are read from the property-set templates bundled inside the IfcOpenShell wheel (`ifcopenshell/util/schema/Pset_IFC4X3.ifc`, generated from the buildingSMART IFC4.3 psd) **[P via bundled copy]**:
- `Qto_SpaceBaseQuantities.NetFloorArea`: "Sum of all net usable floor areas. It excludes the area covered by elements inside the space (columns, inner walls, built-in...)". `GrossFloorArea` "Includes the area covered by elements inside the space ... and excludes the area covered by wall claddings".
- `Qto_WallBaseQuantities.Length`: "Along center line (even if different to the wall path)". `NetSideArea`: "area ... as viewed by an elevation view of the middle plane ... does take into account all object modifications (such as openings)". `NetVolume`: "taking into account possible processing features (cut-outs...)".
- `Qto_SlabBaseQuantities`: `GrossArea`/`NetArea` "Only given, if the element is prismatic"; `NetVolume` as above.
- IFC2X3 uses `BaseQuantities` (not `Qto_`) and tool-specific sets (`ArchiCADQuantities`, `Component Quantities`).

### 1.3 What reproduces this dataset's ground truth **[V]**
| Question | Model | Reproduced by |
|---|---|---|
| "total length of all walls on 'Grundplan'" = 185.129 m | `bsc-molio_molio-with-uris.ifc` (IFC2X3, ArchiCAD) | Sum of `BaseQuantities.Length` over `IfcWall` in `get_decomposition(storey)` gives raw 185129.313, which is **millimetres** (length unit scale 0.001); divide by 1000 |
| "net side area of all walls" = 505.175 m2 | same | Sum of `BaseQuantities.NetSideArea` = 505.175 (already m2, no scaling) |
| "net volume of all walls" = 177.896 m3 | same | Sum of `BaseQuantities.NetVolume` = 177.896 (already m3) |
| "total net floor area of all rooms on '1.korrus'" = 870.29 m2 | `bsc-esplanades_1807-ep-ar-v18.ifc` (IFC2X3, ArchiCAD, mm) | **No Qto on any IfcSpace.** Sum over 50 spaces of `ifcopenshell.util.shape.get_footprint_area(create_shape(settings, space).geometry)` = 870.29 exactly |
| counts on '1.korrus' / '2.korrus' | same | `get_decomposition(storey)` filtered by type: 1.korrus doors 46, rooms 50, columns 37, stairs 1; 2.korrus walls 156 (all match questions). Whole-model "walls 846" = `len(f.by_type("IfcWall"))` which includes subtype `IfcWallStandardCase` (747 of them) |
| ac20_arc (IFC-Bench) | IFC4 | Has full `BaseQuantities` on spaces: `NetFloorArea` 23.9008 etc. |

### 1.4 Pitfalls (observed unless marked)
- **Units differ per quantity type**: ArchiCAD IFC2X3 files have length in mm but area/volume quantities already in m2/m3 **[V]**. Use the `IfcUnitAssignment` per type (`ifcopenshell.util.unit.calculate_unit_scale(f, "AREAUNIT")` etc.), do not blindly apply the length scale.
- `create_shape` returns metres regardless of file units when using default settings (footprint sum matched an mm file) **[V]**.
- `create_shape` raises `RuntimeError: Failed to process shape` for products whose first representation is a 2D `Axis`/`Curve2D` (seen on Molio walls) **[V]**. Select the "Body" representation context (`settings` + `iterator` with context filter) or wrap in try/except.
- Esplanades `AR_Ruum.120_Pindala` is a string with comma decimal and one decimal ("28,9"): rounded and unusable for the 2% tolerance **[V]**.
- `Component Quantities` on Esplanades walls is an `IfcPhysicalComplexQuantity` (nested dict via `get_psets`), not a flat Qto **[V]**.
- Some models (duplex_arc) have no quantities on walls/slabs/doors at all and only a `GSA Space Areas` set on spaces **[V]**. Geometry fallback required.
- Elements can belong to a storey via aggregation (`IfcRelAggregates`) or containment; `get_decomposition` handles both, `get_container` returns only the direct container.
- `get_volume` of non-manifold meshes is unreliable [P, docstring]; slab volumes with openings may differ from Qto `NetVolume` [U, not tested].
- Storey names are localized (Estonian "1.korrus", Danish "Grundplan", German "Dachgeschoss"). Match by name from the question; not by elevation.

---

## 2. Swiss Dwellings: data model and how the drawings map

Primary sources: Zenodo record https://zenodo.org/records/7788422 (v3.0.0, CC BY 4.0), column docs https://zenodo.org/records/7215005, and the derived benchmark paper MSD https://arxiv.org/abs/2407.10121 (PDF could not be text-extracted by the fetch tool; paper content below is **[U]**). No standalone Swiss Dwellings paper was found; the Zenodo record is the primary description.

### 2.1 Published data **[P]**
- "over 45,000 apartments (about 370,000 rooms) in roughly 3,100 buildings"; area accuracy QA "within 5% (median deviation 1.2%)" (Zenodo 7788422).
- `geometries.csv` columns: `apartment_id, site_id, building_id, floor_id, plan_id, unit_id, area_id, unit_usage, entity_type, entity_subtype, geometry, elevation, height` (Zenodo 7788422; descriptions from 7215005).
  - `geometry`: WKT "in meters" in a per-site local coordinate system (+y north, +x east).
  - `entity_type` in {area, separator, opening, feature}; `entity_subtype` examples: WALL, LIVING_ROOM, ROOM, LIVING_DINING, BATHROOM, KITCHEN, BALCONY, LOGGIA. Full enumeration is only inside the zip (not inspected) **[U]**.
  - `unit_usage` in {RESIDENTIAL, COMMERICAL [sic], PUBLIC, JANITOR}. "Unit" = residential/commercial/public/janitor part of a building; public parts include staircases. "Feature" = sinks, toilets, bathtubs (showers mentioned in prose).
  - `apartment_id` is unique only per site; v3.0.0 re-digitized some apartments so IDs changed.
- Rooms ("areas") are polygons; net area is the polygon area **[V]** (see 2.3): there is no separate area column.

### 2.2 The challenge's files (LICENSE.md in the dataset)
"the PDF, DXF and PNG drawings were rendered by us from the published geometry. We added the drawing style, room and unit numbers, room names in an assigned language (de, fr or it), door swings and the title block." Same stem = same drawing in 3 formats (README.md). 65 floors x {dxf, pdf, png}. Question stems exist in EN/DE/FR/IT.

### 2.3 Concrete structure (inspected 65 DXF + 3 PDF + PNG headers) **[V]**
**DXF** (version AC1027, `$INSUNITS`=6 metres, extents header unset (1e20), so compute extents yourself):
- Layers: `0, Defpoints, WALL, DOOR, WINDOW, ROOM_OUTLINE, ROOM_TEXT, FIXTURE, ANNOTATION, UNIT_OUTLINE`. Blocks only `_ARCHTICK, _CLOSEDFILLED, _CLOSEDBLANK` (dimension arrows); **no INSERT blocks for doors/windows/fixtures**. Entity types present: LWPOLYLINE, TEXT, CIRCLE, ARC, HATCH only.
- `ROOM_OUTLINE`: closed/open LWPOLYLINEs, many tiny (<0.2 m2) artefacts. Room polygon = closed LWPOLYLINE containing the room-number TEXT insertion point; shoelace area matches the answer within 2% for **129/129** "net floor area of room X" questions (script chk3).
- `ROOM_TEXT`: per room three TEXT entities in order: name (e.g. `Zimmer`), number (`2.01`; basement `U1.15`), and area label (`15.61 m²`) **only for larger rooms** (area labels missing for 84/129 queried rooms, so do not rely on label text; compute polygon area). Apartment tag `Whg. A` (de), other languages use other prefixes. Unique `Whg.`-style labels = apartment count: 65/65 correct, whereas counting `UNIT_OUTLINE` polylines gave 55/65 (it includes non-residential units) **[V]**.
- `UNIT_OUTLINE`: one LWPOLYLINE per unit (not always closed). Area of a unit outline is not the "net apartment area" asked (that is the sum of its rooms excluding balcony/loggia/terrace): **[U]**, not tested.
- `DOOR`: each door = one 5-vertex LWPOLYLINE (leaf) + one 2-vertex polyline + one ARC (swing). Door count = number of 5-vertex DOOR polylines: **65/65** correct. (Arc counting gave 37/65: double/entrance doors lack arcs.)
- `WINDOW`: 4-vertex LWPOLYLINE per window + 2-vertex lines; windows = count of 4-vertex polylines: **65/65**.
- `FIXTURE`: 2-pt lines, 4-pt polylines, 48-pt and 69-pt polylines (curved basins/tubs), small CIRCLEs (r=0.08 etc.). Mapping of shapes to WC/washbasin/bathtub/shower **not decoded** [U]. In floor9385 the answers were 4 WC, 4 washbasins, 4 bathtubs, so vertex count 48/69 polylines (8 and 4) plausibly = basins/tubs [U].
- `WALL`: LWPOLYLINE + HATCH (wall fill).
- `ANNOTATION`: title text ("Grundriss 2. OG", "Massstab 1:200 (A3) · Masse in Metern", source credit). Title gives floor label and scale.
**PDF** (A3 landscape 1190.55 x 841.89 pt, produced by Matplotlib 3.11 pdf backend): 100% vector, no images, 536 drawing paths and 176 text words on floor9385; text is real text (name, number, `15.61 m²`, `Whg. A`). Room polygons are filled paths (fills white / grey 0.69 walls / light grey) with no layer or class metadata (no OCG) **[V]**. Page-to-metre scale must come from the scale note ("Massstab 1:200 (A3)") or by regression against labelled areas **[U for generality]**.
**PNG** (2480x1753 or 1753x2480, RGBA): raster of the same drawing; no embedded metadata checked beyond size **[V]**. Use PDF/DXF whenever the stem exists (same-name files; README).
**Question types seen** (7990 questions in preview file overall; swiss 1614 count + 744 area): apartments count; rooms labelled X; doors; windows; WC; washbasins; bathtubs; showers; net area of room N; net area of apartment A (excluding balconies, loggias, terraces and other outdoor spaces); total net area of rooms labelled X; total net area of all numbered indoor rooms (excluding outdoor spaces, shafts and voids).

---

## 3. CubiCasa5K

- Primary: repo https://github.com/CubiCasa/CubiCasa5k and paper https://arxiv.org/abs/1904.01920 (Kalervo, Ylioinas, Haikio, Karhu, Kannala, 2019): "5000 samples annotated into over 80 floorplan object categories" with "dense polygon annotations" **[P]**. README does not describe the SVG schema; the loader source does.
- Annotation is one `model.svg` per plan (`floortrans/loaders/svg_loader.py`: `self.svg_file_name = '/model.svg'`) **[P]**. Parsing in `floortrans/loaders/svg_utils.py` `get_labels`: `<g id="Wall">`, `<g id="Window">`, `<g id="Door">` polygons; fixtures are `<g class="FixedFurniture ...">`; rooms are `<g class="Space ...">` **[P]**.
- Class tables in `floortrans/loaders/house.py` **[P]**: `all_icons` has 52 entries (index): Window 1, Door 2, BaseCabinet 3, Bathtub 6, BathtubRound 7, CornerSink 14, DoubleSink 16, DoubleSinkRight 17, RoundSink 28, Shower 32, ShowerCab 33, ShowerScreen 34, ShowerScreenRoundLeft/Right 35/36, SideSink 37, Sink 38, Toilet 39, Urinal 40, WaterTap 42, WashingMachine 47, Dishwasher 49, ShowerPlatform 51, etc. `all_rooms` has about 80 entries (Alcove, Attic, Bath, Bedroom, Closet, Kitchen, ...). The training subset `icons_selected` collapses all sink variants to one class (6), Toilet = 5, both bathtub variants = 9, and maps Shower* to None, i.e. showers are dropped from the 11-icon training set. So the challenge's questions "sinks (double-bowl counts as one)", "showers and bathtubs in total" are not the model classes 1:1 **[P + inference]**.
- The dataset preview has **PNG only** (241 files, `colorful-*.png`, etc.); no SVG ground truth is shipped, and questions (Finnish and English) include doors ("open doorways without a door leaf do not count"), windows, WC seats, sinks, showers+tubs, floors, bedrooms/kitchens/bathrooms by Finnish abbreviation (MH, KH, ...) **[V]**. Expect to need vision/OCR; no vector route.
- Licence in challenge README: CC BY-NC-SA 4.0 (non-commercial). I did not read the repo LICENSE **[U]**.

---

## 4. ezdxf and PyMuPDF

### 4.1 ezdxf (MIT; https://ezdxf.readthedocs.io/en/stable/index.html **[P]**)
- Reads/writes DXF R12 to R2018; R13/R14 read-only (upgraded to R2000). **DWG: only through the `odafc` add-on** (docs index) **[P]**.
- Filter: `msp.query('LWPOLYLINE[layer=="DOOR"]')`, `msp.groupby(dxfattrib="layer")`; `e.dxftype()`, `e.dxf.layer`, `e.dxf.get(name, default)` (https://ezdxf.readthedocs.io/en/stable/tutorials/getting_data.html **[P]**).
- Block inserts: `msp.query('INSERT')`; `insert.dxf.name`, `.dxf.insert`; `Insert.mcount` ("MINSERT processing is required if mcount > 1"), `multi_insert()`, `virtual_entities()` (transformed block content without exploding), `explode()`, `block()`, `matrix44()`, `attribs` (docstrings of installed ezdxf 1.4.5 **[V]**; web page for INSERT returned 404). **Count each MINSERT as `mcount`, not 1** **[inference from docstring]**. Nested blocks need recursive traversal **[U]**.
- Text with position: TEXT `.dxf.insert`, `.dxf.text`, `.dxf.height`; MTEXT `.text`, `.dxf.insert` (+ `plain_text()`); bbox via `ezdxf.bbox.extents(entities)` (installed docstring **[V]**).
- Areas: polygon area from `LWPOLYLINE.get_points()` (shoelace, ensure `closed`), or `ezdxf.math.is_point_in_polygon_2d` for point-in-room. HATCH boundary paths also hold polygons **[U]**.
- Units: check `doc.units` (swiss: 6 = metre) and `$INSUNITS`. Real-world CAD (`opening_design`) is mostly inches/feet **[U]**.
- DWG to DXF: `from ezdxf.addons import odafc; odafc.is_installed(); doc = odafc.readfile('x.dwg')`; `odafc.convert(src, dest, version='R2018', audit=True)`. Needs ODA File Converter on PATH (`unix_exec_path` config) or Windows default path; docs warn executing external app is a security issue; on Linux may need `xvfb`, on macOS no known way to hide GUI (https://ezdxf.readthedocs.io/en/stable/addons/odafc.html **[P]**).

### 4.2 PyMuPDF (AGPL-3.0 or Artifex commercial; licence from installed package METADATA **[V]**)
- `page.get_drawings()` returns a list of path dicts with keys `items` (tuples with codes `"l"` line, `"c"` Bezier curve, `"re"` rect, `"qu"` quad), `fill`, `color`, `rect`, `closePath`, `width`, `dashes`, `even_odd`, `opacity`, `lineCap`, `lineJoin` (https://pymupdf.readthedocs.io/en/latest/recipes-drawing-and-graphics.html **[P]**). The docs page I read does not mention a `layer` key; the Page page was too large to read fully. "it will always return all paths", incl. clipped/hidden ones **[P]**.
- `page.get_text("words")` gives `(x0,y0,x1,y1,word,block,line,wordno)` tuples with bbox; `get_text("dict")`/`"rawdict"` give spans with bbox/font/size (used for highlight per docs; keys **[U]** beyond observed `words`, which I used **[V]**). `page.find_tables()` returns tables with `bbox, cells, extract(), to_markdown(), to_pandas(), header, row_count, col_count` **[P]**. On the A-801 door-schedule PDF `find_tables()` found 0 tables **[V]**, so schedule parsing needs word-position clustering.
- Coordinates are PDF points, y down. Scale: ifc_models PDFs carry scale text ("Maßstab 1:100") and a 200 mm-wide page for FZK (566.93 pt = 200 mm) **[V]**; area_m2 = pt_area x (0.352778 mm/pt)^2 x scale^2 / 1e6.
- Native alternatives: `pdfplumber`, `pypdfium2`, `pdfminer.six` (permissive licences) **[U]**.

### 4.3 DWG converters
| Tool | Licence/availability | Notes |
|---|---|---|
| ODA File Converter | Closed-source, ODA "Community User Agreement" (09-2025): limited, non-exclusive, non-transferable, revocable licence; may not be resold or distributed as part of a commercial app; commercial rights via paid membership (https://www.opendesign.com/files/2025-09/ODA%20Community%20User%20Agreement%2009-2025.pdf, via search snippet; full text not read **[U]**). Download page lists Linux x64 (glibc>=2.28; RPM/DEB/AppImage), macOS 13+ (Apple Silicon and Intel), Windows 10+ and mentions "60-day free trial" (https://www.opendesign.com/guestfiles/oda_file_converter **[P]**). Whether the download is still free is **[U]**. | CLI: source dir, target dir, input filter, output version, recursive flag, audit flag |
| LibreDWG | GPLv3+ (https://github.com/LibreDWG/libredwg README **[P]**) | "can read all DWG versions, just some very advanced R2010+ objects fail"; `dwg2dxf` ~90% coverage; `dwg2SVG` handles only some entities; no brew mention, build from source (autogen/configure/make) |
| Not installed here | `ODAFileConverter`, `dwg2dxf`, `dwgread` not on PATH **[V]** | |
Dataset facts: `opening_design` has 20 `.dwg` (AC1027/AC1021 headers **[V]**), 1 `.dxf` and its questions target PDFs (door schedule on sheet A-801) rather than DWG. Practical consequence: DWG conversion is likely low value for scoring in the preview; the PDF text of the A-801 sheet answers its 39 count questions **[inference; see section 6]**.

---

## 5. IFC-Bench v2

- Dataset card https://huggingface.co/datasets/sylvainhellin/ifc-bench **[P]**: columns `id, question, ground_truth, ifc_model (filename without .ifc), project, category (1-4)`; 1,027 QA pairs, 37 IFC models, 21 projects; fixed eval split `questions/eval-split-hellin2026.csv` (514 test). Categories: 1 Direct Information Retrieval (152), 2 Computational Aggregation (569), 3 Geometric/Spatial Computation (112), 4 Incomplete Information (194), adapted from Solihin and Eastman (2015). Licence CC BY 4.0, some models GPL-3 (4351, ettenheim_gis, hitos, samuel_macalister_sample_house). v1: https://github.com/sylvainHellin/ifc-bench (CSV, 105 QA pairs, superseded).
- Judging, from the paper (Hellin et al., arXiv 2605.01698, https://arxiv.org/abs/2605.01698; text read from the PDF) **[P]**: LLM-as-judge. Judge sees "the original question, the ground-truth answer, the system's answer, and the full execution trace" and rates **binary criteria** (faithfulness, completeness, transparency, relevance; a fifth criterion exists but I read only four used for accuracy). Aggregate accuracy requires all four true (deliberately conservative). Category 1 needs grounding in BIM data only; category 4 allows stated assumptions. Abstention ("Information not found in BIM model") is tracked separately. Judge agreement reported Krippendorff alpha 0.70-1.00 vs human experts 0.32-0.57. There is **no numeric tolerance rule** in that protocol; judge is an LLM. The companion framework paper ("Evaluating AI Systems for BIM Information Retrieval...") was not read **[U]**.
- In this challenge: `ifc_bench` questions are `type: "text"`, free-form multi-line answers (e.g. "Building Type: Office Building ... Total Levels: 5 floors", per-level room lists with areas such as "Keller: 17 spaces, 438.1 sq m"); README says "text answers are free-form". How the Junction organizers grade text answers is **not documented** in the README **[U]**. 249 text questions on 5 ifc_bench files in the preview. The answer text suggests aggregates computed from `NetFloorArea`-style Qto (ac20 level total 438.1 = sum of space areas) **[V partially: sample]**.

---

## 6. Dataset inspection summary (preview at ~/Downloads/junction-dataset-preview, 926 files, 7,990 questions)

Question count by source/type: cubicasa5k count 4270; swiss_dwellings count 1614, area 744; ifc_models area 846, count 153, volume 34, length 16; ifc_bench text 249; opening_design count 39, text 16, area 9. habs/finna/europeana/wikimedia are scanned JPGs (wikimedia also 7 SVGs) with no questions in the preview's questions.jsonl (counted by path prefix); not examined further **[U]**.

| Source | Files inspected | Machine-readable structure found |
|---|---|---|
| swiss_dwellings | site1000_bldg2082_floor9385 (dxf+pdf+png), plus counts across all 65 dxf, 3 PDFs | See 2.3. DXF layers per class; PDF vector + text; polygons yield areas; no INSERT blocks; text labels in 3 languages |
| ifc_models PDF | `kit-fzk-haus_..._dachgeschoss.pdf` (566.9x394.6 pt, 59 paths, 49 words, title says scale 1:100 and "Schnitthöhe 1.20 m über Geschossebene" (cut height)), `bsc-molio_..._klder.pdf` (1356x1198 pt, 198 paths, 106 words, 14 light-blue filled space polygons, labels like "Depot / Rum nr. K08") | Vector only. Space polygons identifiable by fill colour (0.89,0.93,0.97); room names + numbers as text; no IFC class/GUID in PDF |
| ifc_models SVG | fzk dachgeschoss, molio klder, esplanades 4-korrus | `<g class="IfcSpace|IfcWall|IfcDoor|IfcStair|IfcColumn|IfcRailing|IfcFurnishingElement|IfcMember" data-name=".." data-guid="..">` with `<path d>` in mm-ish drawing units (width="200.0mm", viewBox in same units). Molio: 27 IfcWall, 14 IfcSpace, 14 IfcDoor, 4 IfcStair, 2 IfcColumn, 51 IfcRailing groups; 33 `<text>` **[V]**. Easy to count but note that windows were not drawn as a class in molio SVG (only IfcDoor) while the question asks doors count 14 on Kælder = 14 IfcDoor groups **[V]** |
| ifc_models IFC | esplanades (IFC2X3, 12 MB, 285 spaces, 846 walls, 211 doors, 297 windows), molio (IFC2X3, 74 MB), clinic-plumbing, resbim-388 (2.5 KB, trivial), fzk IFC absent (only its PDF/SVG ship) | See 1.3. Spaces lack Qto in Esplanades; walls have BaseQuantities in Molio |
| ifc_bench IFC | ac20_arc (IFC4, 5 storeys, 82 spaces, 121 walls, 77 doors, 206 windows, full BaseQuantities + ArchiCADQuantities), duplex_arc (IFC2X3, Solibri-optimised, no wall/door Qto, `GSA Space Areas` on spaces) | Rich psets; storeys named in German/English |
| opening_design | Sheets A-801 PDF (Sports Complex, 3024x2160 pt, 1,885 words, 8,950 vector paths, 8 images, Ghostscript-produced), Site plan.dxf (AC1009; layers `0, Defpoints`; 9 INSERTs of blocks like `RECTANGLE033`, `DWIRE`; no door/window blocks), 3 DWG headers | Schedule table is text-positioned, no table structure detected by `find_tables()` (0 tables). DXF here has named blocks but generic, not door/window. Questions: door counts by type (A1 14, A2 1, B1 9, ...), counted from schedule rows |
| cubicasa5k | PNG only (241) | Raster; no SVG supplied |

Answers to the briefing's explicit questions:
- *Does the swiss_dwellings PDF have vector room polygons and text labels?* Yes: vector paths (536 on the examined file) and real text for name, number, area (for larger rooms), apartment letter **[V]**. Rooms are not tagged by layer in PDF; DXF carries the layers.
- *Do DXF files have named blocks for doors/windows?* swiss_dwellings: no (geometry is raw polylines/arcs/circles per layer; only 3 dimension-tick blocks). opening_design `Site plan.dxf`: blocks exist but are generic names, not door/window **[V]**.

## 7. Open items / not verified
- buildingSMART IFC documentation site returned HTTP 403, so Qto definitions came from IfcOpenShell's bundled copy.
- ezdxf INSERT doc page (404) and the full PyMuPDF Page reference (too long for the fetch tool): API facts there are from installed docstrings or runtime behaviour.
- Swiss Dwellings entity_subtype full enumeration; FIXTURE shape to WC/sink/tub/shower mapping; apartment net-area rule (needs room-to-unit assignment, e.g. by containment in `UNIT_OUTLINE`); outdoor room names ("Balkon", "Loggia", "Terrasse" in de/fr/it) for exclusion.
- ODA File Converter current licence/availability; CubiCasa repo LICENSE; Junction's grader for `text` answers.
- Slab/wall-volume questions on ifc_models other than Molio walls (e.g. FZK slabs 52.992 m3) were not reproduced (FZK IFC not in preview).
