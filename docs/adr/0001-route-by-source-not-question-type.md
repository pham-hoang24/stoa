# Route by source and format, not by question type

The router picks a lane from the drawing's source and file format. A count question on an IFC model and one on a Swiss PDF need different tools, while two different question types on the same drawing share one. Routing by question type would split each drawing's logic across lanes, so each lane owns every question type for its own drawings.
