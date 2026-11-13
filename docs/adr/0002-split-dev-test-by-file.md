# Split dev and test by drawing, not by question

Questions come in bilingual pairs and many share one drawing, so a per-question split leaks answers between dev and test. The split hashes the file path, which keeps every question about a drawing on the same side. The cost is uneven split sizes.
