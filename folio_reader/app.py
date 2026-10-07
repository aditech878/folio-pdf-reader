#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Folio: a small, local PDF reader for this desktop."""

import os
import sys
from pathlib import Path

import pymupdf as fitz
from PyQt5.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QSettings, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
from PyQt5.QtWidgets import (
    QAction, QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QInputDialog,
    QPushButton, QScrollArea, QSplitter, QStackedWidget, QTabBar, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


MARGIN = 14
PAGE_GAP = 24
MAX_RENDER_PIXELS = 20_000_000
SUPPORT_URL = 'https://buymeacoffee.com/aadityabanwari'


class PageWidget(QWidget):
    def __init__(self, reader, number):
        super().__init__()
        self.reader = reader
        self.number = number
        self.image = None
        self.selection = None
        self.drag_start = None
        self.setMouseTracking(True)
        self.setCursor(Qt.IBeamCursor)
        self.resize_for_zoom()

    def geometry_for_page(self):
        rect = self.reader.doc.load_page(self.number).rect
        if self.reader.rotation % 180:
            width, height = rect.height, rect.width
        else:
            width, height = rect.width, rect.height
        return width, height

    def resize_for_zoom(self):
        width, height = self.geometry_for_page()
        scale = self.reader.scale
        self.setFixedSize(round(width * scale) + 2 * MARGIN,
                          round(height * scale) + 2 * MARGIN)
        self.image = None
        self.update()

    def render(self):
        if self.image is not None:
            return
        page = self.reader.doc.load_page(self.number)
        ratio = self.devicePixelRatioF()
        scale = self.reader.scale * ratio
        width, height = self.geometry_for_page()
        pixels = width * height * scale * scale
        if pixels > MAX_RENDER_PIXELS:
            scale *= (MAX_RENDER_PIXELS / pixels) ** 0.5
            ratio = scale / self.reader.scale
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale).prerotate(self.reader.rotation),
                              alpha=False)
        # Keep the Python buffer alive until QImage has made an owned copy.
        samples = pix.samples
        image = QImage(samples, pix.width, pix.height, pix.stride,
                       QImage.Format_RGB888).copy()
        if self.reader.night:
            image.invertPixels()
        self.image = image
        self.update()

    def pdf_to_widget(self, rect):
        page = self.reader.doc.load_page(self.number)
        matrix = fitz.Matrix(self.reader.scale, self.reader.scale).prerotate(self.reader.rotation)
        bounds = page.rect * matrix
        transformed = rect * matrix
        return QRectF(transformed.x0 - bounds.x0 + MARGIN,
                      transformed.y0 - bounds.y0 + MARGIN,
                      transformed.width, transformed.height)

    def widget_to_pdf(self, pos):
        page = self.reader.doc.load_page(self.number)
        matrix = fitz.Matrix(self.reader.scale, self.reader.scale).prerotate(self.reader.rotation)
        bounds = page.rect * matrix
        point = fitz.Point(pos.x() - MARGIN + bounds.x0,
                           pos.y() - MARGIN + bounds.y0) * ~matrix
        return fitz.Point(max(0, min(page.rect.width, point.x)),
                          max(0, min(page.rect.height, point.y)))

    def paintEvent(self, event):
        # A visible page must render even if the scroll timer has not fired yet.
        if self.image is None:
            self.render()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#1d222b'))
        width, height = self.geometry_for_page()
        paper = QRectF(MARGIN, MARGIN, width * self.reader.scale,
                       height * self.reader.scale)
        painter.fillRect(paper, QColor('#141922' if self.reader.night else 'white'))
        if self.image is not None:
            painter.drawImage(paper, self.image)
        painter.setPen(QPen(QColor('#acb2bb'), 1))
        painter.drawRect(paper)
        for rect in self.reader.results.get(self.number, []):
            painter.fillRect(self.pdf_to_widget(rect), QColor(250, 198, 58, 105))
        if self.selection:
            painter.fillRect(self.pdf_to_widget(self.selection), QColor(65, 143, 244, 95))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start = self.widget_to_pdf(event.pos())
            self.selection = None
            self.update()

    def mouseMoveEvent(self, event):
        if self.drag_start and event.buttons() & Qt.LeftButton:
            end = self.widget_to_pdf(event.pos())
            self.selection = fitz.Rect(self.drag_start, end).normalize()
            self.reader.selected_page = self.number
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.selection and self.selection.width > 3 and self.selection.height > 3:
            text = self.reader.doc.load_page(self.number).get_textbox(self.selection)
            QApplication.clipboard().setText(text)
            self.reader.status.emit('Selected text copied to clipboard')
        elif self.drag_start:
            point = self.widget_to_pdf(event.pos())
            for link in self.reader.doc.load_page(self.number).get_links():
                if point in fitz.Rect(link['from']):
                    if link.get('kind') == fitz.LINK_GOTO and link.get('page', -1) >= 0:
                        self.reader.goto_page(link['page'])
                    elif link.get('uri'):
                        from PyQt5.QtCore import QUrl
                        from PyQt5.QtGui import QDesktopServices
                        QDesktopServices.openUrl(QUrl(link['uri']))
                    break
        self.drag_start = None


class DocumentView(QWidget):
    status = pyqtSignal(str)
    position_changed = pyqtSignal(int, int, float)

    def __init__(self, path):
        super().__init__()
        self.path = str(Path(path).resolve())
        self.doc = fitz.open(self.path)
        if self.doc.needs_pass:
            password, ok = QInputDialog.getText(self, 'Encrypted PDF',
                                                'Enter PDF password:', QLineEdit.Password)
            if not ok or not self.doc.authenticate(password):
                self.doc.close()
                raise ValueError('PDF password was not accepted')
        if not self.doc.is_pdf:
            self.doc.close()
            raise ValueError('This file is not a PDF')
        self.scale = 1.0
        self.fit = 'width'
        self.rotation = 0
        self.night = False
        self.results = {}
        self.matches = []
        self.match_index = -1
        self.search_page = 0
        self.query = ''
        self.selected_page = None
        self.page_widgets = []

        self.outline = QTreeWidget()
        self.outline.setHeaderHidden(True)
        self.outline.itemClicked.connect(lambda item, _: self.goto_page(item.data(0, Qt.UserRole)))
        self._make_outline()
        self.thumbs = QListWidget()
        self.thumbs.setIconSize(QSize(64, 84))
        for index in range(len(self.doc)):
            item = QListWidgetItem(f'Page {index + 1}')
            item.setData(Qt.UserRole, index)
            self.thumbs.addItem(item)
        self.thumbs.itemClicked.connect(lambda item: self.goto_page(item.data(Qt.UserRole)))
        self.thumbs.verticalScrollBar().valueChanged.connect(self._render_thumbnails)
        self.sidebar = QTabWidget()
        self.sidebar.addTab(self.thumbs, 'Pages')
        self.sidebar.addTab(self.outline, 'Contents')
        self.sidebar.setMinimumWidth(220)
        self.sidebar.tabBar().setUsesScrollButtons(False)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QScrollArea.NoFrame)
        self.area.viewport().installEventFilter(self)
        self.container = QWidget()
        self.pages_layout = QVBoxLayout(self.container)
        self.pages_layout.setContentsMargins(22, 20, 22, 20)
        self.pages_layout.setSpacing(PAGE_GAP)
        self.pages_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        for index in range(len(self.doc)):
            page = PageWidget(self, index)
            self.page_widgets.append(page)
            self.pages_layout.addWidget(page, 0, Qt.AlignHCenter)
        self.area.setWidget(self.container)
        self.area.verticalScrollBar().valueChanged.connect(self._schedule_visible)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.area)
        self.splitter.setSizes([250, 1000])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self.visible_timer = QTimer(self)
        self.visible_timer.setSingleShot(True)
        self.visible_timer.timeout.connect(self._render_visible)
        self.search_timer = QTimer(self)
        self.search_timer.timeout.connect(self._search_batch)
        QTimer.singleShot(0, self.fit_width)
        QTimer.singleShot(0, self._render_thumbnails)

    def _make_outline(self):
        parents = {}
        for level, title, page, *_ in self.doc.get_toc():
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, max(0, page - 1))
            if level > 1 and (level - 1) in parents:
                parents[level - 1].addChild(item)
            else:
                self.outline.addTopLevelItem(item)
            parents[level] = item
        self.outline.expandToDepth(0)

    def eventFilter(self, source, event):
        if source is self.area.viewport():
            if event.type() == event.Resize:
                if self.fit == 'width':
                    QTimer.singleShot(0, self.fit_width)
                elif self.fit == 'page':
                    QTimer.singleShot(0, self.fit_page)
                self._schedule_visible()
            elif event.type() == event.Wheel and event.modifiers() & Qt.ControlModifier:
                self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
                return True
        return super().eventFilter(source, event)

    def _schedule_visible(self):
        self.visible_timer.start(35)

    def _render_visible(self):
        viewport = self.area.viewport()
        top = -250
        bottom = viewport.height() + 250
        current = 0
        best_overlap = -1
        for page in self.page_widgets:
            y = page.mapTo(viewport, QPoint(0, 0)).y()
            overlap = max(0, min(y + page.height(), viewport.height()) - max(y, 0))
            if overlap > best_overlap:
                current = page.number
                best_overlap = overlap
            if y + page.height() >= top and y <= bottom:
                page.render()
            elif page.image is not None:
                page.image = None
                page.update()
        self.position_changed.emit(current + 1, len(self.doc), self.scale)
        if self.thumbs.currentRow() != current:
            self.thumbs.setCurrentRow(current)
        self._render_thumbnails()

    def _render_thumbnails(self):
        if not self.thumbs.isVisible():
            return
        first = max(0, self.thumbs.indexAt(QPoint(5, 0)).row())
        last = min(len(self.doc), first + max(8, self.thumbs.viewport().height() // 80 + 3))
        for index in range(first, last):
            item = self.thumbs.item(index)
            if item.icon().isNull():
                page = self.doc.load_page(index)
                factor = min(64 / page.rect.width, 84 / page.rect.height)
                pix = page.get_pixmap(matrix=fitz.Matrix(factor, factor), alpha=False)
                samples = pix.samples
                image = QImage(samples, pix.width, pix.height, pix.stride,
                               QImage.Format_RGB888).copy()
                item.setIcon(QIcon(QPixmap.fromImage(image)))

    def _resize_pages(self):
        current = self.current_page()
        for page in self.page_widgets:
            page.resize_for_zoom()
        QTimer.singleShot(0, lambda: self.goto_page(current, smooth=False))

    def current_page(self):
        viewport = self.area.viewport()
        current = 0
        best_overlap = -1
        for page in self.page_widgets:
            y = page.mapTo(viewport, QPoint(0, 0)).y()
            overlap = max(0, min(y + page.height(), viewport.height()) - max(y, 0))
            if overlap > best_overlap:
                current = page.number
                best_overlap = overlap
        return current

    def goto_page(self, number, smooth=True):
        if number is None or not 0 <= number < len(self.doc):
            return
        self.area.verticalScrollBar().setValue(self.page_widgets[number].y() - 16)
        self.thumbs.setCurrentRow(number)
        self._schedule_visible()

    def set_scale(self, scale, fit=None):
        scale = max(0.25, min(4.0, scale))
        if abs(scale - self.scale) < 0.002:
            return
        self.scale = scale
        if fit is not None:
            self.fit = fit
        self._resize_pages()

    def zoom_by(self, factor):
        self.fit = 'custom'
        self.set_scale(self.scale * factor)

    def fit_width(self):
        if not self.page_widgets or self.area.viewport().width() < 100:
            return
        width, _ = self.page_widgets[self.current_page()].geometry_for_page()
        self.fit = 'width'
        self.set_scale((self.area.viewport().width() - 92) / width)
        self._schedule_visible()

    def fit_page(self):
        if not self.page_widgets or self.area.viewport().height() < 100:
            return
        width, height = self.page_widgets[self.current_page()].geometry_for_page()
        self.fit = 'page'
        self.set_scale(min((self.area.viewport().width() - 92) / width,
                           (self.area.viewport().height() - 48) / height))
        self._schedule_visible()

    def rotate(self):
        self.rotation = (self.rotation + 90) % 360
        if self.fit == 'page':
            self.fit_page()
        elif self.fit == 'width':
            self.fit_width()
        else:
            self._resize_pages()

    def toggle_night(self):
        self.night = not self.night
        for page in self.page_widgets:
            page.image = None
        self._schedule_visible()

    def find(self, query):
        self.search_timer.stop()
        self.query = query.strip()
        self.results.clear()
        self.matches.clear()
        self.match_index = -1
        self.search_page = 0
        for page in self.page_widgets:
            page.update()
        if self.query:
            self.search_timer.start(0)
        else:
            self.status.emit('Search cleared')

    def _search_batch(self):
        stop = min(len(self.doc), self.search_page + 8)
        for index in range(self.search_page, stop):
            rects = self.doc.load_page(index).search_for(self.query)
            if rects:
                self.results[index] = rects
                self.matches.extend((index, rect) for rect in rects)
                self.page_widgets[index].update()
        self.search_page = stop
        if stop >= len(self.doc):
            self.search_timer.stop()
            self.status.emit(f'{len(self.matches)} matches for “{self.query}”')
            if self.matches:
                self.find_next()

    def find_next(self, reverse=False):
        if not self.matches:
            return
        self.match_index = (self.match_index + (-1 if reverse else 1)) % len(self.matches)
        index, rect = self.matches[self.match_index]
        self.goto_page(index)
        page_widget = self.page_widgets[index]
        target = page_widget.y() + int(page_widget.pdf_to_widget(rect).top()) - 90
        self.area.verticalScrollBar().setValue(target)
        self.status.emit(f'Match {self.match_index + 1} of {len(self.matches)}')

    def print_document(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(Path(self.path).name)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QPrintDialog.Accepted:
            return
        painter = QPainter(printer)
        first = max(1, printer.fromPage()) if printer.fromPage() else 1
        last = min(len(self.doc), printer.toPage()) if printer.toPage() else len(self.doc)
        for index in range(first - 1, last):
            if index > first - 1:
                printer.newPage()
            page = self.doc.load_page(index)
            factor = min(2.0, 2500 / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(factor, factor), alpha=False)
            samples = pix.samples
            image = QImage(samples, pix.width, pix.height, pix.stride,
                           QImage.Format_RGB888).copy()
            bounds = printer.pageRect()
            fitted = image.size().scaled(bounds.size(), Qt.KeepAspectRatio)
            x = bounds.x() + (bounds.width() - fitted.width()) // 2
            y = bounds.y() + (bounds.height() - fitted.height()) // 2
            painter.drawImage(QRectF(x, y, fitted.width(), fitted.height()), image)
        painter.end()

    def close_document(self):
        self.search_timer.stop()
        for page in self.page_widgets:
            page.image = None
        self.doc.close()


class MainWindow(QMainWindow):
    def __init__(self, paths):
        super().__init__()
        self.setWindowTitle('Folio PDF Reader')
        self.resize(1320, 880)
        self.settings = QSettings('Local', 'FolioPDFReader')
        self.tabs = QTabWidget()
        self.tabs.setObjectName('documentTabs')
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setElideMode(Qt.ElideMiddle)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._sync)
        self.stage = QStackedWidget()
        self.welcome = self._build_welcome()
        self.stage.addWidget(self.welcome)
        self.stage.addWidget(self.tabs)
        root = QWidget()
        root.setObjectName('root')
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self.stage, 1)
        self.setCentralWidget(root)
        self.setAcceptDrops(True)
        self.statusBar().showMessage('Open a PDF to begin')
        for path in paths:
            self.open_pdf(path)
        self._sync()

    def _action(self, text, shortcut, slot, tip=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        action.setToolTip(tip or text)
        self.addAction(action)
        return action

    def _button(self, label, slot, variant='quiet', tip=None):
        button = QPushButton(label)
        button.setProperty('variant', variant)
        button.setCursor(Qt.PointingHandCursor)
        if tip:
            button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def _build_header(self):
        header = QWidget()
        header.setObjectName('header')
        vertical = QVBoxLayout(header)
        vertical.setContentsMargins(22, 13, 22, 12)
        vertical.setSpacing(13)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        mark = QLabel('F')
        mark.setObjectName('brandMark')
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(39, 39)
        brand_row.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel('Folio')
        title.setObjectName('brandTitle')
        eyebrow = QLabel('A BETTER PLACE TO READ')
        eyebrow.setObjectName('brandEyebrow')
        titles.addWidget(title)
        titles.addWidget(eyebrow)
        brand_row.addLayout(titles)
        brand_row.addSpacing(18)
        self.doc_label = QLabel('YOUR LOCAL LIBRARY')
        self.doc_label.setObjectName('documentBadge')
        brand_row.addWidget(self.doc_label)
        brand_row.addStretch(1)
        brand_row.addWidget(self._button('♥  Support Folio', self._open_support, 'support'))
        self.recent_button = self._button('Recent  ▾', self._recent_menu)
        brand_row.addWidget(self.recent_button)
        brand_row.addWidget(self._button('Print', lambda: self._with_doc('print_document')))
        brand_row.addWidget(self._button('Open PDF', self.choose_file, 'accent'))
        vertical.addLayout(brand_row)

        controls = QHBoxLayout()
        controls.setSpacing(7)
        controls.addWidget(self._button('☰', self._toggle_sidebar, 'square', 'Toggle sidebar (Ctrl+B)'))
        controls.addSpacing(8)
        controls.addWidget(self._button('‹', lambda: self._move_page(-1), 'square', 'Previous page (Alt+Left)'))
        self.page_entry = QLineEdit()
        self.page_entry.setObjectName('pageEntry')
        self.page_entry.setFixedWidth(48)
        self.page_entry.setAlignment(Qt.AlignCenter)
        self.page_entry.returnPressed.connect(self._entered_page)
        controls.addWidget(self.page_entry)
        self.page_total = QLabel('of 0')
        self.page_total.setObjectName('mutedLabel')
        controls.addWidget(self.page_total)
        controls.addWidget(self._button('›', lambda: self._move_page(1), 'square', 'Next page (Alt+Right)'))
        controls.addSpacing(15)
        controls.addWidget(self._button('−', lambda: self._zoom(1 / 1.2), 'square', 'Zoom out (Ctrl+−)'))
        self.zoom_label = QLabel('100%')
        self.zoom_label.setObjectName('zoomLabel')
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setFixedWidth(52)
        controls.addWidget(self.zoom_label)
        controls.addWidget(self._button('+', lambda: self._zoom(1.2), 'square', 'Zoom in (Ctrl++)'))
        controls.addSpacing(8)
        controls.addWidget(self._button('Fit width', lambda: self._with_doc('fit_width')))
        controls.addWidget(self._button('Fit page', lambda: self._with_doc('fit_page')))
        controls.addWidget(self._button('↻', lambda: self._with_doc('rotate'), 'square', 'Rotate (Ctrl+R)'))
        self.night_button = self._button('◐', self._toggle_night, 'square', 'Night colors (Ctrl+D)')
        controls.addWidget(self.night_button)
        controls.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName('searchEntry')
        self.search.setPlaceholderText('⌕  Find in document')
        self.search.setMinimumWidth(140)
        self.search.setMaximumWidth(250)
        self.search.textChanged.connect(self._search_changed)
        controls.addWidget(self.search, 1)
        controls.addWidget(self._button('↑', lambda: self._find(True), 'square', 'Previous match (Shift+F3)'))
        controls.addWidget(self._button('↓', lambda: self._find(False), 'square', 'Next match (F3)'))
        vertical.addLayout(controls)

        self._action('Open', 'Ctrl+O', self.choose_file)
        self._action('Print', 'Ctrl+P', lambda: self._with_doc('print_document'))
        self._action('Previous page', 'Alt+Left', lambda: self._move_page(-1))
        self._action('Next page', 'Alt+Right', lambda: self._move_page(1))
        self._action('Zoom out', 'Ctrl+-', lambda: self._zoom(1 / 1.2))
        self._action('Zoom in', 'Ctrl++', lambda: self._zoom(1.2))
        self._action('Rotate', 'Ctrl+R', lambda: self._with_doc('rotate'))
        self._action('Night', 'Ctrl+D', self._toggle_night)
        self._action('Find', 'Ctrl+F', self.search.setFocus)
        self._action('Next match', 'F3', lambda: self._find(False))
        self._action('Previous match', 'Shift+F3', lambda: self._find(True))
        self._action('Toggle sidebar', 'Ctrl+B', self._toggle_sidebar)
        self._action('Full screen', 'F11', self._toggle_fullscreen)
        self._action('Close tab', 'Ctrl+W', lambda: self.close_tab(self.tabs.currentIndex()))
        return header

    def _build_welcome(self):
        welcome = QWidget()
        welcome.setObjectName('welcome')
        outer = QVBoxLayout(welcome)
        outer.setContentsMargins(30, 20, 30, 20)
        outer.addStretch(1)
        card = QWidget()
        card.setObjectName('welcomeCard')
        card.setFixedWidth(660)
        box = QVBoxLayout(card)
        box.setContentsMargins(42, 38, 42, 38)
        box.setSpacing(13)
        monogram = QLabel('F')
        monogram.setObjectName('welcomeMark')
        monogram.setAlignment(Qt.AlignCenter)
        monogram.setFixedSize(54, 54)
        box.addWidget(monogram, 0, Qt.AlignLeft)
        heading = QLabel('Make room for the good stuff.')
        heading.setObjectName('welcomeTitle')
        box.addWidget(heading)
        description = QLabel('Open a PDF and settle in. Search every page, keep your place, and read without distractions.')
        description.setObjectName('welcomeDescription')
        description.setWordWrap(True)
        box.addWidget(description)
        box.addSpacing(5)
        open_button = self._button('Open a PDF  →', self.choose_file, 'accent')
        box.addWidget(open_button, 0, Qt.AlignLeft)
        box.addSpacing(19)
        divider = QWidget()
        divider.setObjectName('welcomeDivider')
        divider.setFixedHeight(1)
        box.addWidget(divider)
        recent_title = QLabel('RECENT DOCUMENTS')
        recent_title.setObjectName('recentTitle')
        box.addWidget(recent_title)
        self.recent_list = QVBoxLayout()
        self.recent_list.setSpacing(5)
        box.addLayout(self.recent_list)
        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(2)
        return welcome

    def _refresh_recent(self):
        while self.recent_list.count():
            child = self.recent_list.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        recent = [p for p in self.settings.value('recent', [], type=list) if os.path.isfile(p)]
        if not recent:
            label = QLabel('Your recently opened PDFs will appear here.')
            label.setObjectName('recentEmpty')
            self.recent_list.addWidget(label)
        for path in recent[:4]:
            button = self._button('▤   ' + Path(path).name, lambda checked=False, p=path: self.open_pdf(p), 'recent', path)
            self.recent_list.addWidget(button)

    def current(self):
        return self.tabs.currentWidget()

    def _with_doc(self, name):
        if self.current():
            getattr(self.current(), name)()

    def _move_page(self, delta):
        if self.current():
            doc = self.current()
            doc.goto_page(doc.current_page() + delta)

    def _entered_page(self):
        if self.current():
            try:
                self.current().goto_page(int(self.page_entry.text()) - 1)
            except ValueError:
                pass

    def _zoom(self, factor):
        if self.current():
            self.current().zoom_by(factor)

    def _find(self, reverse):
        if self.current():
            self.current().find_next(reverse)

    def _search_changed(self, text):
        if self.current():
            self.current().find(text)

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _open_support(self):
        QDesktopServices.openUrl(QUrl(SUPPORT_URL))

    def _toggle_night(self):
        if self.current():
            self.current().toggle_night()
            self._style_night_button()

    def _style_night_button(self):
        active = bool(self.current() and self.current().night)
        self.night_button.setProperty('active', 'true' if active else 'false')
        self.night_button.style().unpolish(self.night_button)
        self.night_button.style().polish(self.night_button)

    def _toggle_sidebar(self):
        if self.current():
            sidebar = self.current().sidebar
            sidebar.setVisible(not sidebar.isVisible())

    def _sync(self, *args):
        doc = self.current()
        if doc:
            self.stage.setCurrentWidget(self.tabs)
            self.setWindowTitle(f'{Path(doc.path).name} — Folio PDF Reader')
            self.doc_label.setText(Path(doc.path).name)
            self.doc_label.setToolTip(doc.path)
            self.search.blockSignals(True)
            self.search.setText(doc.query)
            self.search.blockSignals(False)
            self._position(doc.current_page() + 1, len(doc.doc), doc.scale)
        else:
            self.stage.setCurrentWidget(self.welcome)
            self._refresh_recent()
            self.setWindowTitle('Folio PDF Reader')
            self.doc_label.setText('YOUR LOCAL LIBRARY')
            self._position(0, 0, 1)
        self._style_night_button()

    def _position(self, current, total, scale):
        self.page_entry.setText(str(current) if current else '')
        self.page_total.setText(f'of {total}')
        self.zoom_label.setText(f'{scale * 100:.0f}%')

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open PDF', str(Path.home()), 'PDF files (*.pdf);;All files (*)')
        if path:
            self.open_pdf(path)

    def open_pdf(self, path):
        path = str(Path(path).expanduser().resolve())
        for index in range(self.tabs.count()):
            if self.tabs.widget(index).path == path:
                self.tabs.setCurrentIndex(index)
                return
        try:
            doc = DocumentView(path)
        except Exception as exc:
            QMessageBox.warning(self, 'Could not open PDF', f'{path}\n\n{exc}')
            return
        doc.status.connect(self.statusBar().showMessage)
        doc.position_changed.connect(lambda page, count, scale, d=doc:
                                     self._position(page, count, scale) if self.current() is d else None)
        tab_index = self.tabs.addTab(doc, Path(path).name)
        close_button = QPushButton('×')
        close_button.setObjectName('tabCloseButton')
        close_button.setFixedSize(20, 20)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(lambda checked=False, d=doc:
                                     self.close_tab(self.tabs.indexOf(d)))
        self.tabs.tabBar().setTabButton(tab_index, QTabBar.RightSide, close_button)
        self.tabs.setCurrentWidget(doc)
        recent = [path] + [p for p in self.settings.value('recent', [], type=list) if p != path]
        self.settings.setValue('recent', recent[:12])
        self.statusBar().showMessage(f'Opened {Path(path).name}')

    def _recent_menu(self):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        for path in self.settings.value('recent', [], type=list):
            if os.path.isfile(path):
                menu.addAction(Path(path).name, lambda checked=False, p=path: self.open_pdf(p)).setToolTip(path)
        if menu.isEmpty():
            menu.addAction('No recent files').setEnabled(False)
        menu.exec_(self.recent_button.mapToGlobal(QPoint(0, self.recent_button.height())))

    def close_tab(self, index):
        if index < 0:
            return
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        widget.close_document()
        widget.deleteLater()
        self._sync()

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() and url.toLocalFile().lower().endswith('.pdf')
               for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith('.pdf'):
                self.open_pdf(url.toLocalFile())

    def closeEvent(self, event):
        while self.tabs.count():
            self.close_tab(0)
        super().closeEvent(event)


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName('Folio PDF Reader')
    app.setOrganizationName('Local')
    app.setWindowIcon(QIcon(str(Path(__file__).with_name('icon.png'))))
    app.setFont(QFont('Ubuntu', 10))
    app.setStyleSheet(Path(__file__).with_name('style.qss').read_text())
    window = MainWindow(sys.argv[1:])
    window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
