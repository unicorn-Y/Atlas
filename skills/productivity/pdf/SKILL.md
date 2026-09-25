---
name: pdf
description: "PDF files: create, read, merge, fill, OCR, edit text."
version: 1.0.0
category: productivity
triggers:
  - pattern: "pdf|PDF"
  - pattern: "合并.*pdf|pdf.*合并|拆分.*pdf|pdf.*拆分"
  - pattern: "填.*表单|form.*fill|水印|watermark"
  - command: "/pdf"
dependencies:
  mcp_servers:
    - filesystem
  python_packages:
    - pypdf
    - reportlab
    - pdfplumber
author: Atlas
tags: [pdf, documents, forms, ocr, text-extraction, merge, split]
related_skills: [docx, xlsx]
---

# PDF Skill

Create PDFs from structured specs, build and fill AcroForm forms, extract text/tables/metadata, merge/split/rotate/watermark, encrypt/decrypt — using pypdf, reportlab, and pdfplumber.

## When to Use

- Generate reports, invoices, multi-page documents as PDF
- Build fillable AcroForms from JSON spec
- Extract text, tables, metadata, form values from PDF
- Merge, split, rotate, extract pages, watermark, stamp, bookmark
- Fill or flatten AcroForm forms; encrypt/decrypt
- NOT for: scanned/image-only PDFs (use OCR); pixel-perfect HTML→PDF (use headless browser)

## Prerequisites

```bash
pip install pypdf reportlab pdfplumber
# Optional for page rasterization:
pip install pypdfium2
```

## Instructions

### Quick Reference

| Task | Script |
|------|--------|
| Create PDF | `python scripts/pdf_create.py spec.json -o out.pdf` |
| Build form | `python scripts/pdf_make_form.py formspec.json -o form.pdf` |
| Lint form layout | `python scripts/pdf_form_layout.py formspec.json` |
| Extract text | `python scripts/pdf_read.py doc.pdf --text` |
| Extract tables | `python scripts/pdf_read.py doc.pdf --tables --csv-dir t/` |
| Metadata | `python scripts/pdf_read.py doc.pdf --meta` |
| Form fields | `python scripts/pdf_read.py form.pdf --fields` |
| Merge | `python scripts/pdf_merge.py a.pdf b.pdf -o merged.pdf` |
| Split/Rotate | `python scripts/pdf_split.py doc.pdf --pages 1-3,7 -o part.pdf` |
| Fill form | `python scripts/pdf_fill_form.py form.pdf --fields-json vals.json -o filled.pdf` |
| Encrypt | `python scripts/pdf_secure.py doc.pdf --encrypt -o enc.pdf --user-password pw` |
| Decrypt | `python scripts/pdf_secure.py enc.pdf --decrypt -o dec.pdf --password pw` |
| Watermark | `python scripts/pdf_watermark.py doc.pdf --stamp mark.pdf -o stamped.pdf` |
| Stamp text/image | `python scripts/pdf_stamp.py doc.pdf -o out.pdf --text "DRAFT" --x 150 --y 400` |
| Pages → PNG | `python scripts/pdf_page_image.py doc.pdf --pages 1-3 --out-dir imgs/` |

### Procedure

1. **Inspect first:** `pdf_read.py file.pdf --meta`. Check `encrypted` and `likely_scanned_pages`.
2. **Create:** Write JSON spec, run `pdf_create.py`.
3. **Extract:** `--text` gives per-page strings; `--tables` gives row arrays + CSV.
4. **Manipulate:** merge, split, rotate, watermark, stamp.
5. **Forms:** lint → build → fill → verify with `--fields`.
6. **Secure:** encrypt (AES-256) or decrypt.
7. **Verify** before reporting success.

### Pitfalls

- **Scanned PDFs**: empty `extract_text()` = no text layer. Route to OCR.
- **Flattening limits**: reliable for text/checkboxes; exotic widgets may need Ghostscript fallback.
- **Non-Latin form values**: stored correctly (UTF-16) but may not render if font lacks glyphs.
- **Compression**: `--compress` only deflates content streams (0-20% savings).
- **Permission flags don't enforce**: owner-password bits are polite requests, not security.
- **Page indexing**: CLI takes 1-based pages; pypdf APIs are 0-based.
