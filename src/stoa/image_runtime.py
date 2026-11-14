"""Application inference over pixels and explicit tasks; benchmark labels stay out."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Callable

import cv2

from .answer import ABSTAIN_DECLINED, Answer, Evidence
from .assets import Drawing
from .detection_geometry import Detection, View, deduplicate, overlap, project, views
from .image_task import CountTask, interpret

PROMPT = """Inspect this image as a floor-plan drawing. Locate {description} across the entire supplied image.
Do not infer a count from typical homes, filenames, room counts, or expected answers.
Return JSON only with this schema:
{{"readable": true, "complete": true, "detections": [{{"box": [x0,y0,x1,y1], "uncertain": false}}], "notes": ""}}
Coordinates are relative to THIS supplied image: 0..1000, top-left origin, x1>x0 and y1>y0.
Each box must enclose one visible object. Report objects once. An empty list means no visible objects.
Set readable=false if this is not a legible floor plan. Set complete=false when you cannot examine the entire image or cannot reliably locate all requested objects.
Mark uncertain candidates uncertain=true. Do not invent boxes to satisfy a number. A cropped symbol at an image edge can be reported but should be marked uncertain if its identity is unclear.
"""


@dataclass
class Assessment:
    drawing: Drawing = field(repr=False)
    question: str
    status: str
    answer: Answer
    task: CountTask | None = None
    detections: tuple[Detection, ...] = ()
    requests: int = 0
    planned_requests: int = 0
    choices: tuple[str, ...] = ()

    def payload(self) -> dict:
        return {"drawing": self.drawing.metadata(), "question": self.question,
                "status": self.status, "answer": dataclasses.asdict(self.answer),
                "task": dataclasses.asdict(self.task) if self.task else None,
                "detections": [{"id": i, "box": d.box, "uncertain": d.uncertain} for i, d in enumerate(self.detections, 1)],
                "requests": self.requests, "planned_requests": self.planned_requests,
                "choices": self.choices, "reviewed": False}


def _declined(drawing, question, message, task=None, status="declined", choices=()):
    return Assessment(drawing, question, status,
                      Answer(None, "count", lane="vision", note=message, abstain=ABSTAIN_DECLINED),
                      task=task, choices=choices)


class ProviderUnavailable(RuntimeError):
    """A local capability is absent, before a provider request is attempted."""


def provider(view: View, task: CountTask) -> str:
    # Reuse the shared bounded provider transport from #29. This adapter sends
    # only canonical pixels and task semantics: no filename, source or labels.
    from .lanes import llm
    if not hasattr(llm, "settings"):
        raise ProviderUnavailable("The bounded provider transport from PR #29 is required before live inference")
    content = [{"type": "text", "text": PROMPT.format(description=task.description)},
               llm.image_part(view.png)]
    return llm.chat([{"role": "system", "content": "Locate objects from the supplied pixels. Never guess unavailable content."},
                     {"role": "user", "content": content}], max_tokens=4000)


def parse(reply: str, view: View) -> tuple[list[Detection], bool, bool]:
    text = reply.strip()
    if text.startswith("```") and text.endswith("```"):
        if "\n" not in text:
            raise ValueError("Detector output has an invalid code fence")
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Detector output is not valid JSON; no count can be established") from None
    if not isinstance(data, dict) or not isinstance(data.get("detections"), list):
        raise ValueError("Detector output lacks a detection list")
    if type(data.get("readable")) is not bool or type(data.get("complete")) is not bool:
        raise ValueError("Detector output must report image readability and coverage")
    if len(data["detections"]) > 500:
        raise ValueError("Detector reply exceeds the per-view response limit")
    detections = []
    for item in data["detections"]:
        if not isinstance(item, dict) or type(item.get("uncertain")) is not bool:
            raise ValueError("Detector output contains an invalid or unqualified candidate")
        detections.append(project(item.get("box"), view, item["uncertain"]))
    return detections, data["readable"], data["complete"]


def assess(drawing: Drawing, question: str, *, confirmation=None,
           detect: Callable[[View, CountTask], str] = provider,
           tile_edge=1400, overlap_pixels=200, max_requests=9) -> Assessment:
    interpretation = interpret(question, confirmation)
    if interpretation.task is None:
        return _declined(drawing, question, interpretation.message, status=interpretation.status, choices=interpretation.choices)
    task = interpretation.task
    if float(cv2.meanStdDev(drawing.pixels())[1].max()) < 0.5:
        return _declined(drawing, question, "The image appears blank; provide a legible floor plan", task)
    try:
        planned = views(drawing, tile_edge, overlap_pixels, max_requests)
    except ValueError as exc:
        return _declined(drawing, question, str(exc), task)
    result = _declined(drawing, question, "Image inspection incomplete", task)
    result.planned_requests = len(planned)
    detailed, overview = [], []
    problems = []
    for view in planned:
        result.requests += 1
        try:
            reply = detect(view, task)
        except ProviderUnavailable:
            result.requests -= 1
            problems.append("Image inspection is not configured on this server. You can still mark and review objects manually")
            break
        except Exception as exc:
            problems.append(f"{view.id}: {type(exc).__name__}: Provider request failed; check configuration, quota or request limits")
            break
        try:
            boxes, readable, complete = parse(reply, view)
        except (ValueError, TypeError, AttributeError) as exc:
            problems.append(f"{view.id}: invalid detector output: {exc}")
            break  # no automatic retry, and no partial count after failure
        if not readable or not complete:
            problems.append(f"{view.id}: image is unreadable or coverage is incomplete")
            if view.overview:
                overview.extend(boxes)
            else:
                detailed.extend(boxes)
            break
        if view.overview:
            overview.extend(boxes)
        else:
            detailed.extend(boxes)
    candidates = detailed if len(planned) > 1 else overview
    result.detections, ambiguous = deduplicate(candidates)
    if any(d.uncertain for d in [*overview, *detailed]):
        problems.append("The detector marked uncertain objects; review is required")
    if ambiguous:
        problems.append("Overlapping candidates cannot be deduplicated confidently")
    if len(planned) > 1 and any(not any(overlap(d.box, candidate.box)[1] >= 0.6 for candidate in result.detections) for d in overview):
        problems.append("Overview and detailed crops disagree; review candidate completeness")
    evidence = [Evidence(drawing.metadata()["url"], f"{task.target} {i} (unreviewed)", page=0, bbox=d.box)
                for i, d in enumerate(result.detections, 1)]
    if problems:
        result.answer.evidence = evidence
        result.answer.note = "; ".join(problems)
        return result
    result.status = "unreviewed"
    result.answer = Answer(len(result.detections), "count", evidence or [Evidence(drawing.metadata()["url"], "no objects proposed (unreviewed)", page=0)],
                           "vision", "Model-proposed count; boxes and self-reported coverage do not establish recall. Review before use")
    return result
