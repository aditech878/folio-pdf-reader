# Folio PDF Reader

Folio is a focused desktop PDF reader with continuous pages, fast search,
thumbnails, document outlines, tabs, zoom, rotation, night colors, and printing.
PDFs are opened locally; the app does not upload documents.

Folio is released under the GNU AGPL version 3 or later. The full license is
in `LICENSE`. If you enjoy the app, you can [support its development](https://buymeacoffee.com/aadityabanwari).
The source is available at https://github.com/aditech878/folio-pdf-reader.

## Run

To try Folio from a checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/folio-pdf-reader /path/to/file.pdf
```

Drag PDFs into the window to open more tabs. Drag over text to copy it. The
reader remembers recently opened file paths in its local user settings.

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Open PDF |
| Ctrl+F | Focus search |
| F3 / Shift+F3 | Next / previous match |
| Ctrl+mouse wheel | Zoom |
| Alt+Left / Alt+Right | Previous / next page |
| Ctrl+B | Toggle sidebar |
| Ctrl+R | Rotate clockwise |
| Ctrl+D | Toggle night colors |
| Ctrl+P | Print |
| Ctrl+W | Close tab |
| F11 | Full screen |

## Project and Snap Store package

The Python package source is in `folio_reader/`. The theme is
`folio_reader/style.qss`, the icon is `assets/folio.svg`, and sample-only
screenshots are in `assets/store/`. `snap/snapcraft.yaml` and `snap/gui/`
contain a strict-confinement Snap package. Its grade is `devel` until the snap
has been built and tested inside confinement.

To build a Python wheel:

```bash
python3 -m pip wheel --no-deps -w dist .
```

The Snap package still needs a successful confined build and store review.
