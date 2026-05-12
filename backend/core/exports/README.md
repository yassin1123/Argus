# `core.exports` — system dependencies

WeasyPrint (used by `one_pager.OnePagerPdfExporter` and the legacy
`deliverables/render_pdf.py`) needs three native GTK libraries on
top of the Python package. They are **already installed by
`backend/Dockerfile`** so production / CI containers are ready out
of the box.

The list below is only useful when running tests or smoke directly on
the host machine (rare; we recommend running the smoke inside the
`backend` service via `docker compose run --rm backend python ...`).

## Required runtime libs (already in Dockerfile)

- `libcairo2`
- `libpango-1.0-0`
- `libpangocairo-1.0-0`
- `libgdk-pixbuf-2.0-0`
- `libffi-dev`
- `shared-mime-info`

## Debian / Ubuntu

```bash
sudo apt-get install -y \
  libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
  libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info
```

## macOS

```bash
brew install pango cairo gdk-pixbuf libffi
```

## Windows

Use Docker — the WeasyPrint runtime is not packaged for Windows by
default and the workaround (MSYS2 + GTK runtime) is fragile. On a
Windows dev host the Python package will import but the C-level call
fails with `OSError: cannot load library 'gobject-2.0-0'`. To smoke
the PDF exporter from Windows, run inside the container:

```bash
docker compose run --rm backend python -c \
  "import asyncio; from core.exports import GenerateArtifactRequest, generate_artifact; \
   asyncio.run(generate_artifact(GenerateArtifactRequest(session_id='<uuid>', artifact_type='one_pager', format='pdf')))"
```

## Fonts

The 1-pager PDF uses CSS fonts that fall back to the WeasyPrint
default if not installed system-wide. Branding `font_family` values
are passed through but never failure-loaded — a missing TTF gracefully
degrades to the next entry in the CSS stack (`Inter, system-ui,
sans-serif`). No external CDN fonts are embedded; PDF generation
never makes a network request.
