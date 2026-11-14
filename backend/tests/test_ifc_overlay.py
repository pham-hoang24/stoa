"""Projection evidence through the same router/CLI used by the viewer."""
from pathlib import Path

import ifcopenshell
import pymupdf
import pytest

from stoa import cli, data, viewer
from stoa.lanes import llm


@pytest.fixture
def drawing(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(viewer, "ROOT", tmp_path)

    def unexpected(*args, **kwargs):
        pytest.fail("Verified IFC counts must not call an LLM")
    monkeypatch.setattr(llm, "answer", unexpected)
    folder = tmp_path / "data" / "ifc_models"
    folder.mkdir(parents=True)
    model = ifcopenshell.file(schema="IFC4")
    walls = [model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name=f"Wall {i}")
             for i in range(3)]
    model.write(str(folder / "test.ifc"))
    svg = folder / "test_plan-01-ground.svg"

    def write(body=None, path=svg, pdf=True):
        if body is None:
            body = (f'<g class="IfcWall" data-guid="{walls[0].GlobalId}">'
                    '<rect x="30" y="40" width="20" height="10"/></g>'
                    '<g transform="translate(10,5)">'
                    f'<g class="IfcWall" data-guid="{walls[1].GlobalId}">'
                    '<path d="M80 60 L100 60 L100 70 L80 70 Z"/></g></g>'
                    '<g class="IfcWall" data-guid="unrelated-product">'
                    '<rect x="50" y="60" width="10" height="10"/></g>')
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="150pt" height="75pt" '
                        'viewBox="10 20 200 100">' + body + '</svg>')
        if pdf:
            with pymupdf.open(path) as doc:
                path.with_suffix(".pdf").write_bytes(doc.convert_to_pdf())

    write()
    return folder, walls, write


def ask(path="data/ifc_models/test_plan-01-ground.pdf"):
    return cli.ask(path, "How many walls are there in the model 'Test model'?")


@pytest.mark.parametrize("ext", ["pdf", "svg", "ifc"])
def test_full_inventory_survives_partial_view(drawing, ext):
    folder, walls, _ = drawing
    path = f"data/ifc_models/test_plan-01-ground.{ext}" if ext != "ifc" else "data/ifc_models/test.ifc"
    a = ask(path)
    assert a["value"] == 3
    evidence = {e["global_id"]: e for e in a["evidence"]}
    assert set(evidence) == {w.GlobalId for w in walls}
    assert len(a["evidence"]) == 3
    assert "visible geometry=2/3" in a["note"]
    assert "1 contributing elements without visible geometry" in a["note"]
    for wall in walls[:2]:
        e = evidence[wall.GlobalId]
        assert e["file"] == "data/ifc_models/test_plan-01-ground.pdf"
        assert e["page"] == 0 and e["bbox"]
        assert "IFC source=test.ifc" in e["label"]
    off_view = evidence[walls[2].GlobalId]
    assert off_view["file"].endswith("test.ifc")
    assert off_view["bbox"] is None and off_view["page"] is None
    assert "not present in displayed view" in off_view["label"]


def test_svg_viewbox_offset_and_nested_transform_use_page_points(drawing):
    _, walls, _ = drawing
    evidence = {e["global_id"]: e for e in ask()["evidence"]}
    assert evidence[walls[0].GlobalId]["bbox"] == pytest.approx((15, 15, 30, 22.5))
    assert evidence[walls[1].GlobalId]["bbox"] == pytest.approx((60, 33.75, 75, 41.25))


@pytest.mark.parametrize("shape", [
    '<path d="M130 60 A10 10 0 1 0 150 60 A10 10 0 1 0 130 60"/>',
    '<circle cx="140" cy="60" r="10"/>',
])
def test_curved_geometry_has_complete_bounds(drawing, shape):
    _, walls, write = drawing
    write(f'<g data-guid="{walls[0].GlobalId}">{shape}</g>')
    e = next(e for e in ask()["evidence"] if e["global_id"] == walls[0].GlobalId)
    assert e["bbox"] == pytest.approx((90, 22.5, 105, 37.5), abs=0.01)


def test_multiple_fragments_union_without_duplicating_inventory(drawing):
    _, walls, write = drawing
    write(f'<g data-guid="{walls[0].GlobalId}"><rect x="30" y="40" width="20" height="10"/></g>'
          f'<g data-guid="{walls[0].GlobalId}"><rect x="60" y="40" width="10" height="10"/></g>')
    a = ask()
    e = next(e for e in a["evidence"] if e["global_id"] == walls[0].GlobalId)
    assert e["bbox"] == pytest.approx((15, 15, 45, 22.5))
    assert a["value"] == 3 and len(a["evidence"]) == 3


def test_selected_drawing_is_not_replaced_with_another_floor(drawing):
    folder, walls, write = drawing
    write(f'<g data-guid="{walls[2].GlobalId}"><rect x="30" y="40" width="20" height="10"/></g>',
          folder / "test_plan-02-upper.svg")
    a = ask("data/ifc_models/test_plan-02-upper.pdf")
    visible = [e for e in a["evidence"] if e["bbox"]]
    assert len(visible) == 1 and visible[0]["global_id"] == walls[2].GlobalId
    assert a["value"] == 3


def test_svg_only_boxes_use_svg_rendered_page_coordinates(drawing):
    folder, walls, _ = drawing
    (folder / "test_plan-01-ground.pdf").unlink()
    a = ask("data/ifc_models/test_plan-01-ground.svg")
    e = next(e for e in a["evidence"] if e["global_id"] == walls[0].GlobalId)
    assert e["file"].endswith(".svg") and e["page"] == 0
    assert e["bbox"] == pytest.approx((15, 15, 30, 22.5))


@pytest.mark.parametrize("name", ["test_section-east-west", "test_elevation-east"])
def test_selected_section_or_elevation_resolves_the_same_model(drawing, name):
    folder, walls, write = drawing
    write(path=folder / f"{name}.svg")
    a = ask(f"data/ifc_models/{name}.pdf")
    assert a["value"] == 3 and "visible geometry=2/3" in a["note"]
    assert {e["global_id"] for e in a["evidence"]} == {w.GlobalId for w in walls}
    assert all(e["file"].endswith(f"{name}.pdf") for e in a["evidence"] if e["bbox"])


@pytest.mark.parametrize("failure", ["missing", "malformed", "viewport"])
def test_projection_failure_keeps_verified_count_and_ids(drawing, failure):
    folder, walls, _ = drawing
    if failure == "missing":
        (folder / "test_plan-01-ground.svg").unlink()
    elif failure == "malformed":
        (folder / "test_plan-01-ground.svg").write_text("not XML")
    else:
        with pymupdf.open() as doc:
            doc.new_page(width=300, height=300)
            doc.save(folder / "test_plan-01-ground.pdf")
    a = ask()
    assert a["value"] == 3 and "overlay unavailable" in a["note"]
    assert {e["global_id"] for e in a["evidence"]} == {w.GlobalId for w in walls}
    assert all(e["bbox"] is None and e["file"].endswith("test.ifc") for e in a["evidence"])


def test_geometry_outside_viewport_is_not_claimed_visible(drawing):
    _, walls, write = drawing
    write(f'<g data-guid="{walls[0].GlobalId}"><rect x="2000" y="40" width="20" height="10"/></g>')
    a = ask()
    e = next(e for e in a["evidence"] if e["global_id"] == walls[0].GlobalId)
    assert a["value"] == 3 and e["bbox"] is None
    assert "no visible geometry" in e["label"] and "visible geometry=0/3" in a["note"]


def test_cache_refreshes_when_retained_svg_changes(drawing):
    _, walls, write = drawing
    assert "visible geometry=2/3" in ask()["note"]
    write(f'<g data-guid="{walls[2].GlobalId}"><rect x="30" y="40" width="20" height="10"/></g>')
    a = ask()
    visible = [e for e in a["evidence"] if e["bbox"]]
    assert len(visible) == 1 and visible[0]["global_id"] == walls[2].GlobalId


def test_viewer_resolves_source_and_renders_box_in_the_same_coordinates(drawing):
    e = next(e for e in ask()["evidence"] if e["bbox"])
    path = viewer._safe(e["file"])
    assert path and path.name == "test_plan-01-ground.pdf"
    png, zoom = viewer.render(path)
    pix = pymupdf.Pixmap(png)
    assert zoom == 2 and (pix.width, pix.height) == (300, 150)
    x0, y0, x1, y1 = e["bbox"]
    # The center of the returned overlay is inside the rendered black object.
    assert max(pix.pixel(int((x0 + x1) * zoom / 2), int((y0 + y1) * zoom / 2))[:3]) < 20


def test_real_floor_pdf_maps_42_of_211_whole_model_doors(monkeypatch):
    if not (data.ROOT / "questions.jsonl").exists():
        pytest.skip("dataset not available")
    monkeypatch.setattr(cli, "ROOT", data.ROOT)
    monkeypatch.setattr(viewer, "ROOT", data.ROOT)
    path = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18_plan-04-4-korrus.pdf"
    if not (data.ROOT / path).exists():
        pytest.skip("preview floor view not available")
    a = cli.ask(path, "How many doors are there in the model 'Maleva tänav 18 korterelamu (Esplanades example model)'?")
    assert a["value"] == 211 and len(a["evidence"]) == 211
    assert len({e["global_id"] for e in a["evidence"]}) == 211
    visible = [e for e in a["evidence"] if e["bbox"]]
    assert len(visible) == 42 and "visible geometry=42/211" in a["note"]
    source = viewer._safe(visible[0]["file"])
    assert source and source.name == Path(path).name
    with pymupdf.open(source) as doc:
        for e in visible:
            assert e["page"] == 0
            assert pymupdf.Rect(e["bbox"]) in doc[0].rect


def test_full_dataset_section_retains_whole_model_count(monkeypatch):
    root = data.ROOT.resolve().parent / "junction-dataset"
    path = "data/ifc_models/bimspeed-warmond_ar_section-north-south.pdf"
    if not (root / path).exists():
        pytest.skip("full dataset section not available")
    monkeypatch.setattr(data, "ROOT", root)
    monkeypatch.setattr(cli, "ROOT", root)
    a = cli.ask(path, "How many walls are there in the model 'BIM-Speed Warmond demo site (baseline)'?")
    assert a["value"] == 353 and len(a["evidence"]) == 353
    assert len({e["global_id"] for e in a["evidence"]}) == 353
    assert sum(bool(e["bbox"]) for e in a["evidence"]) == 17
    assert "visible geometry=17/353" in a["note"]
