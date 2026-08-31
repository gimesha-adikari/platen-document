# Workspace Relocation

This record documents the local repository-organization move for the
standalone `platen-document` SDK. It does not change the extracted document
engine or begin PDFNest consumer migration.

## Locations

- Original extraction location: `/home/gimesha/My_Projects/platen-document`
- Current canonical local location:
  `/home/gimesha/My_Projects/platen/platen-document`
- Existing extraction/parity reports retain the original path because that was
  the path used when those historical runs were performed. The evidence was
  moved with the repository and remains available under
  `output/extraction-parity-01/` at the current location.

## Independent Git baseline

- Repository: independent Git repository at the current SDK location
- Branch: `main`
- Initial baseline commit: `ce442ba71dc9abbb219686a7662fd96812a40d75`
- Commit message: `Initial standalone document SDK extraction`
- The baseline contains the parity-proven source, tests, benchmark harness,
  documentation, project configuration, and `.gitignore`.
- Generated output, `.venv/`, IDE files, bytecode/cache files, and generated
  `*.egg-info` metadata are ignored and were not part of the baseline commit.
  Existing parity output remains on disk and was not deleted.

## Outer Platen workspace

The SDK is physically nested in the Platen workspace for local development,
but it is not part of the outer repository history. The outer repository's
local `.git/info/exclude` contains:

```text
platen-document/
```

No submodule or gitlink was created. The SDK is not currently a published
package, remote repository, deployed service, or PDFNest dependency.

## Editable-install repair

The pre-relocation editable installation in
`pdfnest-worker/.venv` referenced the original path. It was refreshed without
installing unrelated dependencies so it now points to:

```text
/home/gimesha/My_Projects/platen/platen-document
```

The worker environment resolves `platen_document` from the relocated
`src/platen_document/` tree, and no stale reference to the original path
remains in its editable-install metadata.

## Standalone SDK verification

An SDK-owned environment was created at:

```text
/home/gimesha/My_Projects/platen/platen-document/.venv
```

Verified from the relocated project:

- package import: PASS;
- `platen-document doctor`: PASS;
- Python compilation for `src` and `tests`: PASS;
- focused SDK tests: 11 passed;
- lightweight native-PDF extraction smoke: PASS, one successful page and
  valid document validation;
- Tesseract: 5.3.4 at `/usr/bin/tesseract`;
- tessdata: `/usr/share/tesseract-ocr/5/tessdata`;
- installed OCR languages: `eng`, `sin`, `tam`.

The SDK environment resolved the declared dependency ranges independently.
The historical 10-case parity evidence remains authoritative and was not
rerun for this relocation milestone.

## Scope guard

The PDFNest worker still owns and imports its existing
`app/core/ocr_v2/` implementation. No PDFNest product consumer imports
`platen_document`, no OCR algorithm or contract was changed, and no OCR Text
V2 migration was started.
