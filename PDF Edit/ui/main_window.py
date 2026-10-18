"""Main window: menus, toolbar, search, and wiring between panels."""

import os

import fitz
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog, QDoubleSpinBox, QFileDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QScrollArea, QSplitter, QToolBar, QToolButton, QWidget,
)

from document import MAX_PAGES, PdfDocument, PdfError
from ui.icons import make_icon
from ui.page_view import PageView, Tool
from ui.thumbnail_panel import ThumbnailPanel


class MainWindow(QMainWindow):
    def __init__(self, app_name: str, app_version: str):
        super().__init__()
        self.app_name = app_name
        self.app_version = app_version
        self.pdf = PdfDocument()
        self._search_hits: list[tuple[int, fitz.Rect]] = []
        self._search_idx = -1

        self.setAcceptDrops(True)
        self.resize(1280, 860)

        # --- central layout
        self.thumbs = ThumbnailPanel()
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidgetResizable(False)
        self.view = PageView(self.scroll)
        self.scroll.setWidget(self.view)

        split = QSplitter()
        split.addWidget(self.thumbs)
        split.addWidget(self.scroll)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        # --- status bar
        self.page_label = QLabel("No document")
        self.zoom_label = QLabel("")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.statusBar().addPermanentWidget(self.page_label)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._wire_signals()
        self._update_ui_state()
        self._update_title()

    # ================================================================ actions

    def _build_actions(self):
        def act(text, slot, shortcut=None, checkable=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if checkable:
                a.setCheckable(True)
            a.triggered.connect(slot)
            return a

        self.act_open = act("&Open…", self.open_dialog, "Ctrl+O")
        self.act_insert = act("&Insert PDF…", self.insert_dialog)
        self.act_merge = act("&Merge PDFs…", self.merge_dialog)
        self.act_split = act("Sp&lit Into Pages…", self.split_dialog)
        self.act_save_as = act("Save &As…", self.save_as_dialog, "Ctrl+S")
        self.act_export = act("&Export Flattened…", self.export_dialog)
        self.act_close = act("&Close Document", self.close_document, "Ctrl+W")
        self.act_exit = act("E&xit", self.close, "Alt+F4")

        self.act_undo = act("&Undo", self.do_undo, "Ctrl+Z")
        self.act_redo = act("&Redo", self.do_redo, "Ctrl+Y")
        self.act_apply_redact = act("Apply &Redactions", self.apply_redactions)

        self.act_del_page = act("&Delete Page", lambda: self.page_op("delete"),
                                "Ctrl+Del")
        self.act_rot_l = act("Rotate &Left", lambda: self.page_op("rotate_l"),
                             "Ctrl+L")
        self.act_rot_r = act("Rotate &Right", lambda: self.page_op("rotate_r"),
                             "Ctrl+R")
        self.act_dup_page = act("D&uplicate Page",
                                lambda: self.page_op("duplicate"), "Ctrl+D")

        self.act_zoom_in = act("Zoom &In", self.view.zoom_in, "Ctrl+=")
        self.act_zoom_out = act("Zoom &Out", self.view.zoom_out, "Ctrl+-")
        self.act_fit = act("&Fit Width", self.view.fit_width, "Ctrl+0")
        self.act_fit_page = act("Fit &Page", self.view.fit_page, "Ctrl+9")
        self.act_prev = act("&Previous Page", lambda: self.goto_page(-1, True),
                            "PgUp")
        self.act_next = act("&Next Page", lambda: self.goto_page(1, True),
                            "PgDown")

        self.act_about = act("&About", self.about)

        # toolbar icons for non-tool actions
        for action, icon in [
            (self.act_open, "open"), (self.act_save_as, "save"),
            (self.act_undo, "undo"), (self.act_redo, "redo"),
            (self.act_rot_l, "rotate_l"), (self.act_rot_r, "rotate_r"),
            (self.act_zoom_in, "zoom_in"), (self.act_zoom_out, "zoom_out"),
            (self.act_fit, "fit_width"), (self.act_fit_page, "fit_page"),
        ]:
            action.setIcon(make_icon(icon))

        # tools
        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        tools = [
            (Tool.SELECT, "Select", "S", "select"),
            (Tool.PAN, "Pan", "1", "pan"),
            (Tool.HIGHLIGHT, "Highlight", "2", "highlight"),
            (Tool.UNDERLINE, "Underline", "3", "underline"),
            (Tool.STRIKEOUT, "Strikeout", "4", "strikeout"),
            (Tool.PEN, "Pen", "5", "pen"),
            (Tool.RECT, "Rectangle", "6", "rect"),
            (Tool.ELLIPSE, "Ellipse", "7", "ellipse"),
            (Tool.LINE, "Line", "8", "line"),
            (Tool.ARROW, "Arrow", "9", "arrow"),
            (Tool.TEXTBOX, "Text Box", "T", "textbox"),
            (Tool.NOTE, "Note", "N", "note"),
            (Tool.ERASER, "Eraser", "E", "eraser"),
            (Tool.REDACT, "Redact", "X", "redact"),
            (Tool.CROSSOUT, "Cross Out", "C", "crossout"),
            (Tool.CALLOUT, "Callout", "B", "callout"),
        ]
        for tool, name, key, icon in tools:
            a = QAction(make_icon(icon), name, self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(key))
            a.setToolTip(f"{name} ({key})")
            a.triggered.connect(lambda _, t=tool: self.view.set_tool(t))
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a
        self.tool_actions[Tool.PAN].setChecked(True)

    def _build_menus(self):
        m = self.menuBar()
        f = m.addMenu("&File")
        for a in (self.act_open, self.act_insert, self.act_merge,
                  self.act_split):
            f.addAction(a)
        f.addSeparator()
        f.addActions([self.act_save_as, self.act_export])
        f.addSeparator()
        f.addActions([self.act_close, self.act_exit])

        e = m.addMenu("&Edit")
        e.addActions([self.act_undo, self.act_redo])
        e.addSeparator()
        e.addAction(self.act_apply_redact)

        p = m.addMenu("&Page")
        p.addActions([self.act_del_page, self.act_rot_l, self.act_rot_r,
                      self.act_dup_page])

        t = m.addMenu("&Tools")
        t.addActions(list(self.tool_actions.values()))

        v = m.addMenu("&View")
        v.addActions([self.act_zoom_in, self.act_zoom_out, self.act_fit,
                      self.act_fit_page])
        v.addSeparator()
        v.addActions([self.act_prev, self.act_next])

        h = m.addMenu("&Help")
        h.addAction(self.act_about)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addActions([self.act_open, self.act_save_as])
        tb.addSeparator()
        tb.addActions([self.act_undo, self.act_redo])
        tb.addSeparator()
        # rotate lives left of the tools — frequently used for scans
        tb.addActions([self.act_rot_l, self.act_rot_r])
        tb.addSeparator()
        for a in self.tool_actions.values():
            tb.addAction(a)
        tb.addSeparator()

        # color swatch
        self.color_btn = QToolButton()
        self.color_btn.setText("Color")
        self.color_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.color_btn.setToolTip("Annotation color")
        self.color_btn.clicked.connect(self.pick_color)
        self._set_color_swatch(self.view.color)
        tb.addWidget(self.color_btn)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 20.0)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setValue(self.view.pen_width)
        self.width_spin.setToolTip("Pen / border width")
        self.width_spin.valueChanged.connect(
            lambda v: setattr(self.view, "pen_width", v))
        tb.addWidget(self.width_spin)

        tb.addSeparator()
        tb.addActions([self.act_zoom_out, self.act_zoom_in, self.act_fit,
                       self.act_fit_page])
        tb.addSeparator()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search text…  (Enter = next)")
        self.search_edit.setMaximumWidth(220)
        self.search_edit.returnPressed.connect(self.search_next)
        tb.addWidget(self.search_edit)
        self.act_search_prev = QAction(make_icon("prev"), "Previous match", self)
        self.act_search_prev.setToolTip("Previous match (Shift+F3)")
        self.act_search_prev.setShortcut("Shift+F3")
        self.act_search_prev.triggered.connect(self.search_prev)
        self.act_search_next = QAction(make_icon("next"), "Next match", self)
        self.act_search_next.setToolTip("Next match (F3)")
        self.act_search_next.setShortcut("F3")
        self.act_search_next.triggered.connect(self.search_next)
        tb.addActions([self.act_search_prev, self.act_search_next])

    def _wire_signals(self):
        self.thumbs.currentRowChanged.connect(self._on_thumb_selected)
        self.thumbs.pagesReordered.connect(self._on_reorder)
        self.thumbs.pdfDropped.connect(self._on_pdf_dropped_on_thumbs)
        self.thumbs.pageAction.connect(self._on_page_action)
        self.view.documentChanged.connect(self._on_doc_changed_light)
        self.view.statusMessage.connect(
            lambda s: self.statusBar().showMessage(s, 4000))
        self.view.zoomChanged.connect(
            lambda z: self.zoom_label.setText(f"{z * 100:.0f}%  "))

    # ================================================================ helpers

    def _set_color_swatch(self, color: QColor):
        pm = QPixmap(20, 20)
        pm.fill(color)
        self.color_btn.setIcon(QIcon(pm))

    def pick_color(self):
        c = QColorDialog.getColor(self.view.color, self, "Annotation color")
        if c.isValid():
            self.view.color = c
            self._set_color_swatch(c)

    def _update_title(self):
        name = os.path.basename(self.pdf.path) if self.pdf.is_open else ""
        star = " *" if self.pdf.modified else ""
        doc = f" — {name}{star}" if name else ""
        self.setWindowTitle(f"{self.app_name} v{self.app_version}{doc}")

    def _update_ui_state(self):
        has_doc = self.pdf.is_open
        for a in (self.act_insert, self.act_merge, self.act_split,
                  self.act_save_as, self.act_export, self.act_close,
                  self.act_del_page, self.act_rot_l, self.act_rot_r,
                  self.act_dup_page, self.act_zoom_in, self.act_zoom_out,
                  self.act_fit, self.act_fit_page, self.act_prev, self.act_next,
                  self.act_apply_redact):
            a.setEnabled(has_doc)
        for a in self.tool_actions.values():
            a.setEnabled(has_doc)
        self.act_undo.setEnabled(self.pdf.is_open and self.pdf.can_undo)
        self.act_redo.setEnabled(self.pdf.is_open and self.pdf.can_redo)
        self.act_del_page.setEnabled(has_doc and self.pdf.page_count > 1)
        if has_doc:
            self.page_label.setText(
                f"Page {self.view.pno + 1} / {self.pdf.page_count}  ")
        else:
            self.page_label.setText("No document")
            self.zoom_label.setText("")
        self._update_title()

    def _error(self, e):
        QMessageBox.warning(self, self.app_name, str(e))

    # ================================================================ refresh

    def _refresh_all(self, keep_page: bool = True):
        """Full refresh after structural changes (pages added/removed/etc)."""
        page = self.view.pno if keep_page else 0
        page = max(0, min(page, self.pdf.page_count - 1))
        self.view.pno = page
        self.view.render_page()
        self.thumbs.populate(self.pdf.to_bytes() if self.pdf.is_open else None,
                             self.pdf.page_count, page)
        self._clear_search()
        self._update_ui_state()

    def _on_doc_changed_light(self):
        """Annotation-level change: refresh current thumb only."""
        self.thumbs.refresh_pages(self.pdf.to_bytes(), [self.view.pno])
        self._update_ui_state()

    def _on_thumb_selected(self, row: int):
        if row >= 0 and self.pdf.is_open and row != self.view.pno:
            self.view.set_page(row)
            self._show_search_on_page()
            self._update_ui_state()

    # ================================================================ file ops

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "",
                                              "PDF files (*.pdf)")
        if path:
            self.open_path(path)

    def open_path(self, path: str):
        if not self._confirm_discard():
            return
        try:
            self.pdf.open(path)
        except PdfError as e:
            self._error(e)
            return
        self.view.set_document(self.pdf)
        self._refresh_all(keep_page=False)
        QTimer.singleShot(0, self.view.fit_width)
        self.statusBar().showMessage(
            f"Opened {os.path.basename(path)} ({self.pdf.page_count} pages)",
            4000)

    def insert_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Insert PDF", "",
                                              "PDF files (*.pdf)")
        if path:
            self._insert_paths([path])

    def _insert_paths(self, paths: list[str]):
        try:
            for p in paths:
                self.pdf.insert_pdf(p)
        except PdfError as e:
            self._error(e)
        self._refresh_all()

    def _on_pdf_dropped_on_thumbs(self, paths: list[str]):
        if self.pdf.is_open:
            self._insert_paths(paths)
        else:
            self.open_path(paths[0])
            if len(paths) > 1:
                self._insert_paths(paths[1:])

    def merge_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Merge PDFs", "",
                                                "PDF files (*.pdf)")
        if paths:
            self._insert_paths(paths)

    def split_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Split into folder")
        if not folder:
            return
        try:
            n = self.pdf.split_to_folder(folder)
            self.statusBar().showMessage(f"Wrote {n} single-page PDFs", 5000)
        except Exception as e:
            self._error(e)

    def save_as_dialog(self):
        start = self.pdf.path or ""
        path, _ = QFileDialog.getSaveFileName(self, "Save As", start,
                                              "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.pdf.save_as(path)
            self._update_title()
            self.statusBar().showMessage(f"Saved {os.path.basename(path)}",
                                         4000)
        except Exception as e:
            self._error(e)

    def export_dialog(self):
        base = os.path.splitext(self.pdf.path or "document")[0]
        path, _ = QFileDialog.getSaveFileName(self, "Export flattened PDF",
                                              base + "_flat.pdf",
                                              "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.pdf.export_flattened(path)
            self.statusBar().showMessage(
                f"Exported flattened copy to {os.path.basename(path)}", 5000)
        except Exception as e:
            self._error(e)

    def close_document(self):
        if not self._confirm_discard():
            return
        self.pdf.close()
        self.view.set_document(self.pdf)
        self._refresh_all()

    def _confirm_discard(self) -> bool:
        if not (self.pdf.is_open and self.pdf.modified):
            return True
        r = QMessageBox.question(
            self, self.app_name,
            "The document has unsaved changes. Save first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            self.save_as_dialog()
            return not self.pdf.modified
        return r == QMessageBox.StandardButton.Discard

    def closeEvent(self, ev):
        if self._confirm_discard():
            ev.accept()
        else:
            ev.ignore()

    # ================================================================ edit ops

    def do_undo(self):
        if self.pdf.is_open and self.pdf.undo():
            self._refresh_all()

    def do_redo(self):
        if self.pdf.is_open and self.pdf.redo():
            self._refresh_all()

    def apply_redactions(self):
        if not self.pdf.has_redactions():
            self.statusBar().showMessage("No redaction marks to apply", 4000)
            return
        r = QMessageBox.question(
            self, "Apply Redactions",
            "Permanently remove all content under redaction marks?\n"
            "This strips the underlying text/images (undo is available "
            "until the file is saved).")
        if r == QMessageBox.StandardButton.Yes:
            n = self.pdf.apply_redactions()
            self._refresh_all()
            self.statusBar().showMessage(f"Applied {n} redactions", 5000)

    def page_op(self, op: str):
        self._on_page_action(op, self.view.pno)

    def _on_page_action(self, op: str, pno: int):
        try:
            if op == "delete":
                self.pdf.delete_page(pno)
            elif op == "rotate_l":
                self.pdf.rotate_page(pno, -90)
            elif op == "rotate_r":
                self.pdf.rotate_page(pno, 90)
            elif op == "duplicate":
                self.pdf.duplicate_page(pno)
        except PdfError as e:
            self._error(e)
            return
        self._refresh_all()

    def _on_reorder(self, new_order: list[int]):
        try:
            self.pdf.reorder_pages(new_order)
        except Exception as e:
            self._error(e)
        # follow the page the user was viewing to its new position
        try:
            self.view.pno = new_order.index(self.view.pno)
        except ValueError:
            pass
        self._refresh_all()

    def goto_page(self, delta: int, relative: bool = False):
        target = self.view.pno + delta if relative else delta
        target = max(0, min(target, self.pdf.page_count - 1))
        self.thumbs.setCurrentRow(target)

    # ================================================================ search

    def _clear_search(self):
        self._search_hits = []
        self._search_idx = -1
        self.view.set_search_results([], None)

    def _run_search(self) -> bool:
        text = self.search_edit.text().strip()
        if not text or not self.pdf.is_open:
            self._clear_search()
            return False
        self._search_hits = self.pdf.search(text)
        self._search_idx = -1
        if not self._search_hits:
            self.statusBar().showMessage(f"No matches for “{text}”", 4000)
            self.view.set_search_results([], None)
            return False
        return True

    def search_next(self):
        self._search_step(1)

    def search_prev(self):
        self._search_step(-1)

    def _search_step(self, step: int):
        if not self._search_hits and not self._run_search():
            return
        n = len(self._search_hits)
        if self._search_idx == -1:
            # first jump: nearest hit at/after current page
            self._search_idx = next(
                (i for i, (p, _) in enumerate(self._search_hits)
                 if p >= self.view.pno), 0)
            if step < 0:
                self._search_idx = (self._search_idx - 1) % n
        else:
            self._search_idx = (self._search_idx + step) % n
        pno, _ = self._search_hits[self._search_idx]
        if pno != self.view.pno:
            self.thumbs.setCurrentRow(pno)
        self._show_search_on_page()
        self.statusBar().showMessage(
            f"Match {self._search_idx + 1} of {n}", 3000)

    def _show_search_on_page(self):
        if not self._search_hits:
            return
        page_rects = [r for p, r in self._search_hits if p == self.view.pno]
        active = (self._search_hits[self._search_idx][1]
                  if self._search_idx >= 0
                  and self._search_hits[self._search_idx][0] == self.view.pno
                  else None)
        self.view.set_search_results(page_rects, active)

    # ================================================================ dnd/misc

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() and any(
                u.toLocalFile().lower().endswith(".pdf")
                for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls()
                 if u.toLocalFile().lower().endswith(".pdf")]
        if paths:
            self.open_path(paths[0])
            if len(paths) > 1 and self.pdf.is_open:
                self._insert_paths(paths[1:])

    def about(self):
        QMessageBox.about(
            self, f"About {self.app_name}",
            f"<b>{self.app_name} v{self.app_version}</b><br>"
            f"PDF markup and page management.<br>"
            f"Page limit: {MAX_PAGES} pages per document.<br><br>"
            f"Built with PyQt6 and PyMuPDF.")
