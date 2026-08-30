---
name: document-inspection
description: Inspect PDF layout, page order, text extraction, figures, or OCR evidence when the rendered document matters; do not use when source text alone answers the request.
---

# Inspect a rendered document

Use the installed `document-inspect` command to produce page images, a contact
sheet, layout-preserving extracted text, PDF metadata, hashes, and an inspection
manifest in the task's scratch directory:

```console
document-inspect FILE.pdf --output INSPECTION_DIR --json
document-inspect FILE.pdf --output INSPECTION_DIR --pages 4-9 --ocr --json
```

Use OCR only for scanned or image-only pages. Treat OCR as an aid, not exact
text: verify names, numbers, equations, citations, and ambiguous characters
against the page image.

Inspect the contact sheet for page order, density, breaks, clipping, blank
pages, and inconsistent layout. Open individual page images at full detail for
small text, figures, tables, footnotes, and visual defects. Compare extracted
text with the rendered pages when missing glyphs or reading order could matter.

Keep private documents and generated inspection artifacts out of repositories
unless they are intentional project inputs. Report the selected pages, concrete
findings, extraction or OCR limitations, and the retained manifest path.
