"""Bounded, source-only IFC text queries; None means the template is unsupported.

An Answer whose value is None means a recognized request lacks source data or
has ambiguous scope. The IFC caller must decline it, rather than ask an LLM
to invent the missing attribute. No benchmark answers or model identities are
consulted. Areas use explicit net quantity records, never inferred room uses.
"""
from __future__ import annotations

import collections
import functools
import math
import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as ue
import ifcopenshell.util.unit as uu

from ..answer import Answer, Evidence
from ..qparse import norm, quoted


@functools.lru_cache(maxsize=4)
def _open(path: str, mtime: int, size: int):
    return ifcopenshell.open(path)


def _present(value, name="") -> bool:
    return value is not None and str(value).strip().casefold() not in {
        "", "unknown", "undefined", "not defined", "n/a", "$", name.casefold(),
    }


def _reply(path, value, method, entities=(), reason=""):
    entities = {e.id(): e for e in entities}.values()
    evidence = [Evidence(str(path), f"{e.is_a()} #{e.id()}; {method}",
                         global_id=getattr(e, "GlobalId", None)) for e in entities]
    if not evidence:
        evidence = [Evidence(str(path), method)]
    return Answer(value, evidence=evidence, lane="ifc",
                  note=f"IFC text; method={method}" + (f"; {reason}" if reason else ""))


def _software(f, path):
    apps = f.by_type("IfcApplication")
    if not any(_present(app.ApplicationFullName) for app in apps) and not _present(f.header.file_name.originating_system):
        return _reply(path, None, "IFC header and IfcApplication attributes", apps,
                      "authoring software is not available")
    lines = [f"IFC Schema: {f.schema_identifier}",
             f"Originating system: {f.header.file_name.originating_system}",
             f"Preprocessor: {f.header.file_name.preprocessor_version}",
             f"Timestamp: {f.header.file_name.time_stamp}"]
    lines.extend(f"File description: {v}" for v in f.header.file_description.description)
    for app in apps:
        developer = app.ApplicationDeveloper.Name if app.ApplicationDeveloper else None
        lines.append(f"Application: {app.ApplicationFullName}; Version: {app.Version}; Developer: {developer}")
    return _reply(path, "\n".join(lines), "IFC header and IfcApplication attributes", apps)


def _identity(f, path, text):
    buildings = f.by_type("IfcBuilding")
    if len(buildings) != 1:
        return _reply(path, None, "IfcBuilding attributes", buildings,
                      "building scope is absent or ambiguous")
    building = buildings[0]
    usage = ue.get_psets(building).get("Pset_BuildingCommon", {}).get("OccupancyType")
    usage = usage if _present(usage, "OccupancyType") else building.ObjectType
    needs_usage = bool(re.search(r"type|usage|function|use\b|occupancy", text))
    if needs_usage and not _present(usage):
        return _reply(path, None, "IfcBuilding.ObjectType / Pset_BuildingCommon.OccupancyType",
                      buildings, "building usage is not available; no usage inferred from names or spaces")
    projects, sites = f.by_type("IfcProject"), f.by_type("IfcSite")
    lines = []
    for e in projects:
        lines.extend(f"Project {key}: {getattr(e, key)}" for key in ("Name", "LongName") if _present(getattr(e, key)))
    if not _present(building.Name) and not _present(building.LongName):
        return _reply(path, None, "IfcBuilding.Name / LongName", buildings, "building name is not available")
    lines.append(f"Building Name: {building.Name or building.LongName}")
    if _present(usage):
        lines.append(f"Building Usage: {usage}")
    if re.search(r"location|situated|site", text):
        if len(sites) != 1 or not _present(sites[0].Name):
            return _reply(path, None, "IfcSite attributes", sites, "site scope or location is unavailable")
        site = sites[0]
        lines.append(f"Site Name: {site.Name}")
        for key in ("RefLatitude", "RefLongitude"):
            v = getattr(site, key)
            if v is not None:
                lines.append(f"{key}: {v}")
    return _reply(path, "\n".join(lines), "explicit project/building/site attributes", [*projects, building, *sites])


def _levels(f, path):
    levels = sorted(f.by_type("IfcBuildingStorey"), key=lambda e: (e.Elevation or 0, e.GlobalId))
    if not levels:
        return _reply(path, None, "IfcBuildingStorey inventory", reason="no storey records available")
    lines = [f"Number of Levels: {len(levels)} (all explicit storey records, including empty storeys)"]
    scale = uu.calculate_unit_scale(f)
    for level in levels:
        elevation = f"{level.Elevation * scale:g} m" if level.Elevation is not None else "not available"
        lines.append(f"{level.Name or level.GlobalId}: elevation {elevation}")
    return _reply(path, "\n".join(lines), "IfcBuildingStorey.Name/Elevation, project length units", levels)


def _space_scope(f, text):
    levels = f.by_type("IfcBuildingStorey")
    names = quoted(text)
    if names:
        matches = [e for e in levels if any(norm(n) in (norm(e.Name or ""), norm(e.LongName or "")) for n in names)]
        return matches if len(names) == len(matches) == 1 else None
    matches = [e for e in levels if e.Name and re.search(r"(?<!\w)" + re.escape(norm(e.Name)) + r"(?!\w)", text)]
    if len(matches) == 1:
        return matches
    if matches:
        return None
    if re.search(r"by (?:building )?(?:level|floor)|per (?:level|floor)|(?:all|each|every).*(?:levels|floors|storeys)|names of all", text):
        return levels
    return None


def _spaces(f, path, text):
    from .ifc import _qto

    levels = _space_scope(f, text)
    if not levels:
        return _reply(path, None, "named storey lookup", reason="space scope unresolved; use an exact storey name or all levels")
    needs_area = "area" in text
    entities, lines, missing = [], [], []
    all_ids = set()
    for level in sorted(levels, key=lambda e: (e.Elevation or 0, e.GlobalId)):
        spaces = sorted((e for e in ue.get_decomposition(level) if e.is_a("IfcSpace")),
                        key=lambda e: (e.Name or "", e.GlobalId))
        entities.append(level)
        entities.extend(spaces)
        all_ids.update(e.GlobalId for e in spaces)
        lines.append(f"{level.Name or level.GlobalId}: {len(spaces)} spaces")
        total = 0.0
        for space in spaces:
            label = f"{space.Name or space.GlobalId}: {space.LongName or '(unnamed)'}"
            if needs_area:
                value = _qto(space, ("NetFloorArea", "NetFootprintArea"), "AREAUNIT")
                if value is None or not math.isfinite(value) or value < 0:
                    missing.append(space.GlobalId)
                    label += "; net area unavailable"
                else:
                    total += value
                    label += f"; {value:.2f} m2"
            lines.append(label)
        if needs_area:
            lines.append(f"{level.Name}: net area {total:.2f} m2" if not missing else f"{level.Name}: total unavailable")
    lines.insert(0, f"Total Spaces: {len(all_ids)}")
    if missing:
        return _reply(path, None, "IfcSpace inventory and explicit net area quantities", entities,
                      f"incomplete areas: {len(missing)} spaces lack explicit net quantities")
    return _reply(path, "\n".join(lines), "IfcSpace inventory and explicit net area quantities" if needs_area else "IfcSpace inventory", entities,
                  "raw space records may include overlapping/gross-area zones; no usable-area or function inference")


def _fire_rating(f, path, text):
    cls = "IfcDoor" if "door" in text else "IfcWindow" if "window" in text else None
    if cls is None or re.search(r"internal|external|room|floor|level", text):
        return None
    elements = f.by_type(cls)
    known = []
    for e in elements:
        for props in ue.get_psets(e).values():
            value = props.get("FireRating")
            if _present(value, "FireRating"):
                known.append((e, value))
                break
    if not known:
        return _reply(path, None, f"{cls} occurrence/type FireRating properties", elements,
                      "fire rating information is not available in this model")
    lines = [f"{e.Name or e.GlobalId}: {value}" for e, value in known]
    lines.append(f"{len(elements) - len(known)} elements have no recorded FireRating")
    return _reply(path, "\n".join(lines), f"{cls} FireRating properties", [e for e, _ in known])


def _mep(f, path, text):
    elements = f.by_type("IfcDistributionElement")
    systems = f.by_type("IfcSystem")
    by_system = collections.defaultdict(set)
    assigned = set()
    for e in elements:
        for rel in e.HasAssignments:
            if rel.is_a("IfcRelAssignsToGroup") and rel.RelatingGroup.is_a("IfcSystem"):
                by_system[rel.RelatingGroup.id()].add(e.GlobalId)
                assigned.add(e.GlobalId)
    if re.search(r"by system|system type|grouped|distribution|distributed|breakdown|quantitative", text) and len(assigned) != len(elements):
        return _reply(path, None, "IfcDistributionElement / explicit IfcSystem assignments", elements,
                      f"system classification unavailable for {len(elements) - len(assigned)} elements; no system types inferred")
    lines = [f"Total MEP Components: {len(elements)}", f"Explicit IfcSystem records: {len(systems)}"]
    for cls, count in sorted(collections.Counter(e.is_a() for e in elements).items()):
        lines.append(f"{cls}: {count}")
    for system in systems:
        lines.append(f"System {system.Name or system.GlobalId}: {len(by_system[system.id()])} components")
    lines.append("Counts cover this IFC file only; absence is not a claim about the constructed building.")
    return _reply(path, "\n".join(lines), "IfcDistributionElement inventory and explicit system assignments", [*systems, *elements])


def answer(question: str, path: Path) -> Answer | None:
    text = norm(question)
    wording = text
    for label in quoted(text):
        wording = wording.replace(label, " ")
    # Recognize a bounded operation before opening a potentially large IFC.
    if re.search(r"software|ifc.*(?:version|standard)|schema|model[l]?ing standards", wording):
        if re.search(r"carbon|fire|rooms|spaces|footprint|capacity|materials|dimensions|mep", wording):
            return None
        intent = "software"
    elif "fire rating" in wording:
        intent = "fire"
    elif "live load capacity" in wording:
        intent = "load"
    elif "mep" in wording and not re.search(r"serving|level|floor|heating|cooling|terminal", wording):
        intent = "mep"
    elif re.search(r"building(?:'s)? (?:name|type|usage|function|information)|type of building|project information|building details", wording):
        if re.search(r"area|height|volume|footprint|rooms|spaces|levels", wording):
            return None
        intent = "identity"
    elif re.search(r"spaces?|rooms?", wording) and re.search(r"breakdown|distribution|names|list|spaces (?:are )?(?:on|in)|all the spaces", wording):
        if re.search(r"percentage|primary|program|utilization|office|toilet|largest|smallest|height|function", wording):
            return None
        intent = "spaces"
    elif re.search(r"(?:number|names|list|elevation).*?(?:levels|storeys)|how many (?:levels|storeys)", wording):
        if re.search(r"area|footprint|height|volume|program", wording):
            return None
        intent = "levels"
    else:
        return None
    stat = path.stat()
    f = _open(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if intent == "software":
        return _software(f, path)
    if intent == "identity":
        return _identity(f, path, text)
    if intent == "levels":
        return _levels(f, path)
    if intent == "spaces":
        return _spaces(f, path, text)
    if intent == "fire":
        return _fire_rating(f, path, text)
    if intent == "mep":
        return _mep(f, path, text)
    # Placeholders such as LoadCapacity='LoadCapacity' do not establish capacity.
    for e in [*f.by_type("IfcSlab"), *f.by_type("IfcSpace")]:
        for props in ue.get_psets(e).values():
            if any(_present(props.get(k), k) for k in ("LiveLoad", "LiveLoadCapacity", "LoadCapacity")):
                return None  # a nontrivial capacity/scope query remains outside this bounded path
    return _reply(path, None, "explicit live-load property lookup",
                  reason="live load capacity is not available; structural capacity is not inferred")
