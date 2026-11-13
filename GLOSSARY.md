# Stoa

Answers quantity-takeoff questions about construction drawings and shows the evidence behind each answer, so a human can verify it.

## Language

**Question**:
A natural-language request about one drawing, such as a count, an area, a length, a volume or free text. Each exists as an English and a native-language pair.
_Avoid_: query, prompt

**Drawing**:
One building plan in any format. Files with the same stem and a different extension are the same drawing.
_Avoid_: document, file (when the content matters)

**Sibling**:
The same drawing in another format, such as the DXF next to a Swiss PDF.
_Avoid_: twin, companion (except for an IFC model, see below)

**Companion model**:
The IFC model a floor-plan PDF or SVG was rendered from.

**Source**:
The dataset folder a drawing comes from, such as `swiss_dwellings` or `cubicasa5k`. It decides the lane.
_Avoid_: dataset (means the whole corpus)

**Lane**:
A path that answers questions for one kind of drawing: ifc, swiss, vision or doc.
_Avoid_: pipeline, handler, route

**Router**:
Picks the lane for a question by source and file format, never by question type.

**Answer**:
A value, its unit, its evidence and the lane that produced it.
_Avoid_: result, response

**Abstain**:
An answer with no value, returned when a lane cannot answer reliably. It is preferred over a guess.
_Avoid_: fail, null answer

**Evidence**:
The part of a drawing that supports an answer: a file, page and box, or an IFC GlobalId. The viewer draws it.
_Avoid_: proof, citation

**Fallback**:
Handing a question to the doc lane when the ifc lane abstains for a reason the LLM can handle.

**Prior**:
The most common answer to a question template across the preview questions, used instead of a model answer.
_Avoid_: default, guess

**Template**:
A recurring question wording, matched across languages, such as "how many bedrooms".

## Evaluation

**Dev split / Test split**:
Drawings divided by a hash of their path, never question by question, so sibling questions cannot leak between them.

**Gate**:
The regression check that fails when lane accuracy drops under a threshold.
