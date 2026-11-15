"""Independent PNG annotation/scoring workflow; labels never enter inference.

init creates unlabelled cases and an offline annotation page. run accepts only
explicit independent manual annotations, uses a bounded request budget, and
reports count/localization/abstention metrics without inventing an accuracy goal.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import time
from collections import deque
from pathlib import Path

from .assets import DrawingError, from_path
from .detection_geometry import overlap
from .image_review import validate_boxes
from .image_runtime import assess


def initialize(folder: Path, project: str, split: str) -> dict:
    if not folder.is_dir() or not project.strip() or split not in ("dev", "test"):
        raise ValueError("Choose an image folder, a project/design group and dev/test split")
    cases, seen = [], set()
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        drawing = from_path(path)
        if drawing.id in seen:
            continue
        seen.add(drawing.id)
        for target in ("window", "door_leaf"):
            cases.append({"drawing": str(path.resolve()), "digest": drawing.id,
                          "project": project.strip(), "split": split, "target": target,
                          "boxes": None, "annotator": "", "label_origin": "independent_manual"})
    if not cases:
        raise ValueError("No PNG drawings found")
    return {"version": 1, "cases": cases}


def validate_manifest(manifest: dict):
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("cases"), list):
        raise ValueError("Expected a version-1 annotation manifest")
    projects, pixels, keys = {}, {}, set()
    validated = []
    for case in manifest["cases"]:
        if not isinstance(case, dict):
            raise ValueError("Invalid annotation case")
        project, split, target = case.get("project"), case.get("split"), case.get("target")
        if not isinstance(project, str) or not project.strip() or split not in ("dev", "test") or target not in ("window", "door_leaf"):
            raise ValueError("Every case needs a project/design group, split and target")
        if project in projects and projects[project] != split:
            raise ValueError("A project/design cannot appear in both dev and test")
        projects[project] = split
        if case.get("label_origin") != "independent_manual" or not isinstance(case.get("annotator"), str) or not case["annotator"].strip():
            raise ValueError("Independent manual annotations need an identified annotator; model-assisted corrections are not held-out labels")
        if not isinstance(case.get("drawing"), str):
            raise ValueError("Every case needs an image path")
        drawing = from_path(case["drawing"])
        if drawing.id != case.get("digest"):
            raise ValueError("An annotated drawing has changed; review its labels again")
        if drawing.id in pixels and pixels[drawing.id] != (project, split):
            raise ValueError("Identical pixels cannot be relabelled into another project or split")
        pixels[drawing.id] = project, split
        key = drawing.id, target
        if key in keys:
            raise ValueError("Duplicate image/target case")
        keys.add(key)
        boxes = validate_boxes(case.get("boxes"), drawing.width, drawing.height)
        validated.append((case, drawing, boxes))
    return validated


def match_boxes(predicted, reference, threshold=0.5):
    """Maximum-cardinality one-to-one matching; a greedy first match can be wrong."""
    if not 0 < threshold <= 1:
        raise ValueError("IoU threshold must be in (0, 1]")
    adjacent = [[j for j, expected in sorted(enumerate(reference), key=lambda item: -overlap(box, item[1])[0])
                 if overlap(box, expected)[0] >= threshold] for box in predicted]
    owners = {}

    def augment(root):
        queue, parents = deque([root]), {}
        while queue:
            i = queue.popleft()
            for j in adjacent[i]:
                if j in parents:
                    continue
                parents[j] = i
                if j in owners:
                    queue.append(owners[j])
                    continue
                # Reverse the alternating path without recursion on dense plans.
                while True:
                    previous = next((right for right, left in owners.items() if left == parents[j]), None)
                    owners[j] = parents[j]
                    if previous is None:
                        return True
                    j = previous
        return False

    true_positive = sum(augment(i) for i in range(len(predicted)))
    return true_positive, len(predicted) - true_positive, len(reference) - true_positive


def config_stamp() -> dict:
    """Provider settings a report was produced under, so two reports can be compared fairly. Never includes a key."""
    from .lanes.llm import DEFAULT_BASE, DEFAULT_MAX_REQUESTS, DEFAULT_MODEL
    from .providers import configuration
    c = configuration(DEFAULT_MODEL, DEFAULT_BASE, DEFAULT_MAX_REQUESTS)
    return {k: c[k] for k in ("provider", "model", "fallback_provider", "timeout_seconds")}


def compare(before: dict, after: dict) -> dict:
    """Metric deltas between two reports, refusing mismatched splits or case sets."""
    if before.get("split") != after.get("split"):
        raise ValueError("Reports use different splits")
    key = lambda r: (r["drawing"], r["target"])
    if {key(r) for r in before["records"]} != {key(r) for r in after["records"]}:
        raise ValueError("Reports cover different cases; deltas would be meaningless")
    metrics = ("exact_count_accuracy", "precision", "recall", "abstentions", "inspection_requests")
    delta = {m: None if before[m] is None or after[m] is None else after[m] - before[m] for m in metrics}
    return {"split": before["split"], "cases": before["cases"], "delta": delta,
            "config_before": before.get("config"), "config_after": after.get("config")}


def run(manifest: dict, *, split="test", limit=5, request_budget=10, detect=None):
    if limit < 1 or not 1 <= request_budget <= 100:
        raise ValueError("Choose a positive case limit and a request budget from 1 to 100")
    cases = [(case, drawing, boxes) for case, drawing, boxes in validate_manifest(manifest) if case["split"] == split][:limit]
    if not cases:
        raise ValueError("No independently annotated cases in the requested split")
    from .lanes.llm import usage
    usage_before = usage() if detect is None else None
    records, requests = [], 0
    true_positive = false_positive = false_negative = exact = answered = 0
    for case, drawing, reference in cases:
        question = "Count all visible windows" if case["target"] == "window" else "Count all visible door leaves"
        start = time.perf_counter()
        if requests >= request_budget:
            records.append({"drawing": drawing.id, "project": case["project"], "target": case["target"],
                            "expected_count": len(reference), "predicted_count": None, "note": "evaluation request budget exhausted", "requests": 0})
            false_negative += len(reference)
            continue
        options = {"max_requests": min(9, request_budget - requests)}
        if detect is not None:
            options["detect"] = detect
        # No reference boxes, expected counts, filenames or project identities
        # cross this call boundary. Inference receives pixels + canonical task.
        assessment = assess(drawing, question, **options)
        requests += assessment.requests
        accepted = assessment.answer.value is not None
        predicted = [d.box for d in assessment.detections] if accepted else []
        tp, fp, fn = match_boxes(predicted, reference)
        true_positive += tp
        false_positive += fp
        false_negative += fn
        answered += accepted
        exact += accepted and assessment.answer.value == len(reference)
        records.append({"drawing": drawing.id, "project": case["project"], "target": case["target"],
                        "expected_count": len(reference), "predicted_count": assessment.answer.value,
                        "proposed_boxes": [d.box for d in assessment.detections], "status": assessment.status,
                        "note": assessment.answer.note, "requests": assessment.requests,
                        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2), "tp": tp, "fp": fp, "fn": fn})
    n = len(records)
    return {"config": config_stamp() if detect is None else None, "split": split, "cases": n, "answered": answered, "abstentions": n - answered,
            "exact_count_matches": exact, "exact_count_accuracy": exact / n,
            "precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else None,
            "recall": true_positive / (true_positive + false_negative) if true_positive + false_negative else None,
            "tp": true_positive, "fp": false_positive, "fn": false_negative,
            "inspection_requests": requests, "request_budget": request_budget,
            "provider_usage_before": usage_before, "provider_usage_after": usage() if detect is None else None,
            "model_proposals_are_unreviewed": True, "records": records}


def annotation_page(manifest: dict) -> str:
    images = {}
    for case in manifest["cases"]:
        drawing = from_path(case["drawing"])
        images[drawing.id] = "data:image/png;base64," + base64.b64encode(drawing.png).decode()
    template = Path(__file__).with_name("image_annotations.html").read_text()
    content = json.dumps({"manifest": manifest, "images": images}).replace("<", "\\u003c")
    return template.replace("/*ANNOTATION_DATA*/null", content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("folder", type=Path)
    init.add_argument("--project", required=True)
    init.add_argument("--split", choices=("dev", "test"), default="test")
    init.add_argument("--output", required=True, type=Path)
    evaluate = sub.add_parser("run")
    evaluate.add_argument("manifest", type=Path)
    evaluate.add_argument("--split", choices=("dev", "test"), default="test")
    evaluate.add_argument("--limit", type=int, default=5)
    evaluate.add_argument("--max-requests", type=int, default=10)
    evaluate.add_argument("--output", required=True, type=Path)
    diff = sub.add_parser("compare")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare(json.loads(args.before.read_text()), json.loads(args.after.read_text())), indent=2))
        elif args.command == "init":
            manifest = initialize(args.folder, args.project, args.split)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(manifest, indent=2))
            html = args.output.with_suffix(".html")
            html.write_text(annotation_page(manifest))
            print(f"Unlabelled cases: {len(manifest['cases'])}. Open {html} and draw independent annotations; no model calls were made.")
        else:
            # A process-level cap protects callers of the shared transport too.
            os.environ["STOA_LLM_MAX_REQUESTS"] = str(min(args.max_requests, int(os.environ.get("STOA_LLM_MAX_REQUESTS", args.max_requests))))
            report = run(json.loads(args.manifest.read_text()), split=args.split, limit=args.limit, request_budget=args.max_requests)
            args.output.write_text(json.dumps(report, indent=2))
            print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2))
            print("Observed model proposals on the supplied annotation set; no generalization or semantic completeness is implied.")
    except (ValueError, DrawingError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
