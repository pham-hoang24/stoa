"""Explicit application count tasks. No expected answers or benchmark metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CountTask:
    target: str  # window or door_leaf
    scope: str = "whole_image"

    def __post_init__(self):
        if self.target not in ("window", "door_leaf") or self.scope != "whole_image":
            raise ValueError("Unsupported object or image scope")

    @property
    def description(self):
        return ("each visible window symbol" if self.target == "window" else
                "each visible door leaf, including separate leaves of double doors; exclude empty openings")


@dataclass(frozen=True)
class Interpretation:
    task: CountTask | None
    status: str
    message: str = ""
    choices: tuple[str, ...] = ()


def interpret(question: str, confirmation: str | None = None) -> Interpretation:
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        return Interpretation(None, "declined", "Enter a count question of at most 2,000 characters")
    text = re.sub(r"\s+", " ", question.casefold()).strip()
    if re.search(r"area|length|width|height|square|m²|metres?|meters?|feet|inches", text):
        return Interpretation(None, "declined", "Physical measurements need calibrated scale and supported geometry; this mode counts visible doors or windows")
    if re.search(r"\b(?:left|right|upper|lower|upstairs|downstairs|only|except|excluding|interior|exterior)\b|\broom\s+\w+|\b(?:first|second|ground|third) floor\b", text):
        return Interpretation(None, "declined", "This mode counts the whole uploaded image. Crop the desired scope into a new PNG for a scoped count")
    if not re.search(r"\b(?:count|number|many|mark|find|locate|show)\b", text):
        return Interpretation(None, "declined", "Ask to count or mark visible doors or windows")
    door = bool(re.search(r"\bdoors?\b|\bdoor leaves\b", text))
    window = bool(re.search(r"\bwindows?\b", text))
    if not door and not window:
        return Interpretation(None, "declined", "Initial support is visible window symbols and door leaves")
    if re.search(r"\b(?:with|without|whose|that|which|north|south|east|west|sliding|fire-rated|entrance|than|bedroom|kitchen|bathroom|garage|basement|attic)\b", text):
        return Interpretation(None, "declined", "Object-property filters are not supported; ask for all visible windows or door leaves")
    target = r"(?:door leaves|door leaf|doors?|windows?)"
    modifiers = r"(?:(?:me|all|every|each|the|visible|drawn)\s+)*"
    command = re.search(r"\b(?:many|count|mark|find|locate|show|number of)\s+" + modifiers + target + r"\b", text)
    if not command:
        return Interpretation(None, "declined", "Ask to count all visible windows or door leaves; subtype filters are not supported")
    # Reject unrecognized suffixes rather than silently drop a second object,
    # condition, or scope. The model receives only a canonical whole-image task.
    tail = text[command.end():]
    join = r"(?:\s+(?:and|or)\s+" + modifiers + target + r")*"
    clause = r"(?:\s+(?:are there|are visible|can you see|do you see))?"
    location = r"(?:\s+(?:in|on|within)\s+(?:(?:this|the|a|an|uploaded|entire|whole|current|given|provided|attached)\s+)*(?:floor\s+)?(?:plan|drawing|image|picture|png|blueprint))?"
    if not re.fullmatch(join + clause + location + clause + r"(?:\s+please)?[?.!]*", tail):
        return Interpretation(None, "declined", "That condition or target is not supported. Ask for all visible windows or door leaves across the image")
    for location in re.finditer(r"\b(?:in|on|within)\s+(.+)", text):
        if not re.match(r"(?:(?:this|the|a|an|uploaded|entire|whole|current|given|provided|attached)\s+)*(?:floor\s+)?(?:plan|drawing|image|picture|png|blueprint)\b", location[1]):
            return Interpretation(None, "declined", "Use the whole uploaded image, or upload a crop of the desired scope")
    choices = tuple(t for t, present in (("door_leaf", door), ("window", window)) if present)
    if confirmation is not None and confirmation not in choices:
        return Interpretation(None, "declined", "The confirmed object must match the question")
    if re.search(r"\b(?:openings?|assemblies)\b", text) and door:
        return Interpretation(None, "declined", "Door openings/assemblies and individual leaves are different counts. Ask for door leaves to use this detector")
    if confirmation:
        return Interpretation(CountTask(confirmation), "ready")
    if door and window:
        return Interpretation(None, "clarification_required", "Count door leaves or windows? Select one object at a time", choices)
    if door and not re.search(r"\bleaves\b|\bleaf\b", text):
        return Interpretation(None, "clarification_required", "Count each door leaf? Double doors contribute two leaves; empty openings are excluded", ("door_leaf",))
    return Interpretation(CountTask("door_leaf" if door else "window"), "ready")
