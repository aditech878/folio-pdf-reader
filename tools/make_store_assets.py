#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create public demo screenshots without exposing a personal document."""

import os
import sys
import tempfile
from pathlib import Path

import pymupdf
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from folio_reader.app import MainWindow  # noqa: E402


def demo_pdf(path):
    doc = pymupdf.open()
    ink = (0.09, 0.19, 0.31)
    muted = (0.28, 0.36, 0.46)
    orange = (0.91, 0.33, 0.12)
    for index in range(4):
        page = doc.new_page(width=595, height=842)
        page.draw_rect(pymupdf.Rect(0, 0, 595, 10), color=orange, fill=orange)
        page.insert_text((48, 66), 'FIELD NOTES  /  FOLIO', fontsize=10, color=orange)
        title = ['A quieter way to read', 'Stay close to the details',
                 'Find what matters', 'Keep the whole story'][index]
        page.insert_text((48, 122), title, fontsize=29, fontname='hebo', color=ink)
        page.draw_line((48, 144), (547, 144), color=(0.79, 0.83, 0.87), width=1)
        lead = [
            'Good reading starts with less noise. Folio gives every page the room it deserves.',
            'Move through a document naturally, with a page rail and a clear reading surface.',
            'Search across pages and follow the highlighted result back to its context.',
            'Return to recent files, rotate when needed, and print without leaving the app.',
        ][index]
        page.insert_textbox(pymupdf.Rect(48, 171, 547, 235), lead, fontsize=13,
                            lineheight=1.35, color=muted)
        page.draw_rect(pymupdf.Rect(48, 262, 547, 493), color=(0.86, 0.89, 0.92),
                       fill=(0.96, 0.97, 0.98), radius=0.03)
        page.insert_text((72, 304), 'READ WITH FOCUS', fontsize=12, fontname='hebo', color=orange)
        items = ['Continuous pages with sharp rendering', 'Fast search through the whole document',
                 'Thumbnails and contents at a glance', 'Comfortable reading colors and zoom']
        for row, item in enumerate(items):
            y = 344 + row * 40
            page.draw_circle((80, y - 5), 7, color=orange, fill=orange)
            page.insert_text((103, y), item, fontsize=12, color=ink)
        page.insert_textbox(pymupdf.Rect(48, 535, 547, 638),
            'Folio keeps the interface out of your way while giving you the useful tools close at hand. '
            'This is a sample document created only for the store screenshots.',
            fontsize=12, lineheight=1.55, color=muted)
        page.draw_line((48, 790), (547, 790), color=(0.79, 0.83, 0.87), width=1)
        page.insert_text((48, 811), 'FOLIO PDF READER', fontsize=8, color=muted)
        page.insert_text((510, 811), f'{index + 1} / 4', fontsize=8, color=muted)
    doc.save(str(path))
    doc.close()


def main():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    out = ROOT / 'assets' / 'store'
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont('Ubuntu', 10))
    app.setStyleSheet((ROOT / 'folio_reader' / 'style.qss').read_text())
    with tempfile.TemporaryDirectory() as temp:
        os.environ['XDG_CONFIG_HOME'] = temp
        window = MainWindow([])
        window.resize(1440, 900)
        window.show()
        for _ in range(8):
            app.processEvents()
        window.grab().save(str(out / 'welcome.png'))
        pdf = Path(temp) / 'Folio_Field_Notes.pdf'
        demo_pdf(pdf)
        window.open_pdf(pdf)
        for _ in range(12):
            app.processEvents()
        window.current()._render_visible()
        app.processEvents()
        window.grab().save(str(out / 'reading.png'))
        window.close()
    print(out)


if __name__ == '__main__':
    main()
