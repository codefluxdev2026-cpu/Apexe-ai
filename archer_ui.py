"""
archer_ui.py — the "Archer AI" look for MARK LV.

Pure PyQt6 widgets, everything painted with QPainter (no image assets).
ui.py wires these into MainWindow; none of the backend knows about this file.

    THEME            accent colour shared by every widget (cycle / set_hex)
    RootWidget       window background + 1px accent border
    TitleBar         frameless title bar (drag, min / max / close, theme button)
    TaskPanel        tasks + notes, saved to config/archer_tasks.json
    SatelliteMap     2D / 3D world stream card
    NodeGraph        Memory / Soul / Skills / Settings lines into the core
    OrbCanvas        particle-sphere core (same API as the old HudCanvas)
    OrbCard          card around the orb: status, TERMINATE, mic
    AgentTown        pixel-art office with four wandering agents + Visual Hub
    ChatPanel        CHATS / LOGS tabs, bubbles, rounded input, bottom pills
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QRadialGradient, QTransform,
)
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizeGrip, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)


# ════════════════════════════════════════════════════════════════════════════
#  Theme + small helpers
# ════════════════════════════════════════════════════════════════════════════
THEME_COLORS = {
    "cyan":   "#19d3ff",
    "orange": "#ff6a1a",
    "purple": "#a24dff",
    "red":    "#ff2a55",
}
_DIM   = "#7b8a96"
_TEXT  = "#e8eef2"


class _Theme(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.name = "cyan"
        self.hex = THEME_COLORS["cyan"]
        self._path: Path | None = None

    def color(self, alpha: int = 255) -> QColor:
        c = QColor(self.hex)
        c.setAlpha(alpha)
        return c

    def attach(self, path: Path) -> None:
        """Remember where to persist, and load the saved choice."""
        self._path = Path(path)
        try:
            d = json.loads(self._path.read_text(encoding="utf-8"))
            if d.get("name") in THEME_COLORS:
                self.name, self.hex = d["name"], THEME_COLORS[d["name"]]
            elif QColor(d.get("hex", "")).isValid():
                self.name, self.hex = "custom", d["hex"]
        except Exception:
            pass

    def _save(self) -> None:
        if self._path:
            try:
                self._path.write_text(
                    json.dumps({"name": self.name, "hex": self.hex}), encoding="utf-8")
            except Exception:
                pass

    def set_name(self, name: str) -> None:
        if name in THEME_COLORS:
            self.name, self.hex = name, THEME_COLORS[name]
            self._save()
            self.changed.emit()

    def set_hex(self, hx: str) -> None:
        if hx and QColor(hx).isValid():
            self.name, self.hex = "custom", QColor(hx).name()
            self._save()
            self.changed.emit()

    def cycle(self, *_):
        names = list(THEME_COLORS)
        i = (names.index(self.name) + 1) % len(names) if self.name in names else 0
        self.set_name(names[i])


THEME = _Theme()


def qc(hx: str, a: int = 255) -> QColor:
    c = QColor(hx)
    c.setAlpha(a)
    return c


def _font(families, size: float, bold: bool = False, spacing: float = 0) -> QFont:
    f = QFont()
    f.setFamilies(families)
    f.setPointSizeF(size)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def mono(size: float = 8, bold: bool = False, spacing: float = 0) -> QFont:
    return _font(["Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"], size, bold, spacing)


def sans(size: float = 10, bold: bool = False) -> QFont:
    return _font(["Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans"], size, bold)


def label(text: str = "", font: QFont | None = None, css: str = "") -> QLabel:
    l = QLabel(text)
    if font:
        l.setFont(font)
    l.setStyleSheet(f"background: transparent; {css}")
    return l


SCROLL_QSS = """
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.18); border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


# ════════════════════════════════════════════════════════════════════════════
#  Base widgets
# ════════════════════════════════════════════════════════════════════════════
class Card(QFrame):
    """Rounded dark panel with a thin accent border."""

    def __init__(self, parent=None, radius: int = 22):
        super().__init__(parent)
        self._r = radius
        THEME.changed.connect(self.update)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(10, 19, 26))
        g.setColorAt(1, QColor(6, 11, 16))
        p.setBrush(g)
        p.setPen(QPen(THEME.color(75), 1))
        p.drawRoundedRect(r, self._r, self._r)


class Pill(QPushButton):
    """The one button style: accent / danger / ghost, optionally round."""

    def __init__(self, text: str = "", kind: str = "accent", size: float = 8,
                 checkable: bool = False, round_: bool = False, parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self._round = round_
        self._hover = False
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(mono(size, True))
        self.setFlat(True)
        THEME.changed.connect(self.update)

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ghost_off = self.kind == "ghost" and not self.isChecked()
        if self.kind == "danger":
            c = QColor("#ff3355")
        elif ghost_off:
            c = QColor(150, 163, 173)
        else:
            c = THEME.color()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2 if self._round else min(15.0, r.height() / 2)
        fill = QColor(c)
        if ghost_off:
            fill = QColor(255, 255, 255)
            fill.setAlpha(18 if self._hover else 0)
            border = QColor(255, 255, 255, 40)
        else:
            fill.setAlpha(60 if self._hover else 34)
            border = QColor(c)
            border.setAlpha(130)
        p.setBrush(fill)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(r, rad, rad)
        p.setPen(c if self.isEnabled() else QColor(90, 100, 108))
        p.setFont(self.font())
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())


class RootWidget(QWidget):
    """Window background and the thin accent frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("archerRoot")
        THEME.changed.connect(self.update)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#03060a"))
        p.setPen(QPen(THEME.color(120), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))


def make_grip(parent: QWidget) -> QSizeGrip:
    g = QSizeGrip(parent)
    g.setFixedSize(16, 16)
    return g


# ════════════════════════════════════════════════════════════════════════════
#  Title bar
# ════════════════════════════════════════════════════════════════════════════
class _Logo(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(20, 20)
        THEME.changed.connect(self.update)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(THEME.color(), 1.4))
        p.setBrush(THEME.color(40))
        p.drawRoundedRect(QRectF(2, 2, 16, 16), 5, 5)
        path = QPainterPath()
        path.moveTo(6, 14)
        path.lineTo(10, 5)
        path.lineTo(14, 14)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.drawLine(QPointF(7.5, 11.5), QPointF(12.5, 11.5))


class _WinBtn(QPushButton):
    def __init__(self, glyph: str, danger: bool = False):
        super().__init__(glyph)
        self._danger = danger
        self._hover = False
        self.setFixedSize(46, 32)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(sans(10))

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if self._hover:
            p.fillRect(self.rect(), QColor(255, 51, 85, 200) if self._danger
                       else QColor(255, 255, 255, 25))
        p.setPen(QColor("#e8eef2") if self._hover else QColor(170, 182, 190))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class TitleBar(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(_Logo())
        self.title = label(text, sans(9), f"color: {_TEXT};")
        lay.addWidget(self.title)
        lay.addStretch(1)
        self.extra = QHBoxLayout()          # ui.py drops ⚙ / 🎛 here
        self.extra.setSpacing(6)
        lay.addLayout(self.extra)
        self.theme_btn = Pill("◐", "accent", 11)
        self.theme_btn.setFixedSize(30, 28)
        self.theme_btn.setToolTip("Change colour theme")
        lay.addWidget(self.theme_btn)
        lay.addSpacing(70)
        for glyph, fn, danger in (("—", self._min, False), ("☐", self._max, False),
                                  ("✕", self._close, True)):
            b = _WinBtn(glyph, danger)
            b.clicked.connect(fn)
            lay.addWidget(b)

    def _min(self):
        self.window().showMinimized()

    def _max(self):
        w = self.window()
        w.showNormal() if w.isMaximized() else w.showMaximized()

    def _close(self):
        self.window().close()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self.window().windowHandle()
            if h:
                h.startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self._max()


# ════════════════════════════════════════════════════════════════════════════
#  Tasks / notes
# ════════════════════════════════════════════════════════════════════════════
PRIO_COL = {"LOW": "#4ade80", "MEDIUM": "#fbbf24", "HIGH": "#ff4d6d"}


class _Check(QWidget):
    toggled = pyqtSignal()

    def __init__(self, checked: bool = False):
        super().__init__()
        self.checked = checked
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, _):
        self.checked = not self.checked
        self.update()
        self.toggled.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1.5, 1.5, 15, 15)
        if self.checked:
            p.setBrush(THEME.color(220))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(r)
            p.setPen(QPen(QColor("#03060a"), 1.8))
            p.drawPolyline(QPolygonF([QPointF(5, 9.5), QPointF(8, 12.5), QPointF(13, 6)]))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(150, 163, 173, 150), 1.3))
            p.drawEllipse(r)


class TaskItem(QFrame):
    toggled = pyqtSignal(str)
    removed = pyqtSignal(str)

    def __init__(self, task: dict):
        super().__init__()
        self._t = task
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(10)
        chk = _Check(task["done"])
        chk.toggled.connect(lambda: self.toggled.emit(task["id"]))
        lay.addWidget(chk, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        done = task["done"]
        txt = label(task["text"], sans(9),
                    f"color: {'#6b7782' if done else _TEXT};"
                    f"{'text-decoration: line-through;' if done else ''}")
        txt.setWordWrap(True)
        col.addWidget(txt)
        pc = PRIO_COL.get(task["prio"], "#fbbf24")
        meta = label("", mono(6.5), "")
        meta.setTextFormat(Qt.TextFormat.RichText)
        meta.setText(
            f'<span style="color:{pc}">⚠ {task["prio"]}</span>'
            f'<span style="color:{_DIM}"> &nbsp;·&nbsp; ⌂ {task["cat"]}'
            f' &nbsp;·&nbsp; ◷ {task["time"]}</span>')
        col.addWidget(meta)
        lay.addLayout(col, 1)
        x = Pill("✕", "ghost", 7)
        x.setFixedSize(20, 20)
        x.clicked.connect(lambda: self.removed.emit(task["id"]))
        lay.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        c = QColor(PRIO_COL.get(self._t["prio"], "#fbbf24"))
        c.setAlpha(45 if self._t["done"] else 120)
        p.setBrush(QColor(255, 255, 255, 8))
        p.setPen(QPen(c, 1))
        p.drawRoundedRect(r, 12, 12)


class _FieldRow(QWidget):
    """Rounded field that holds an input plus its inline buttons."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(42)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(12, 4, 6, 4)
        self.lay.setSpacing(6)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(255, 255, 255, 12))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawRoundedRect(r, 14, 14)


class TaskPanel(Card):
    PRIOS = ["LOW", "MEDIUM", "HIGH"]
    CATS = ["WORK", "PERSONAL"]

    def __init__(self, store: Path, parent=None):
        super().__init__(parent, 22)
        self._store = Path(store)
        self._tasks: list[dict] = []
        self._notes = ""
        self._flt, self._cat = "ALL", "ALL"
        self._prio, self._newcat = "MEDIUM", "WORK"
        self._load()

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 10)
        v.setSpacing(10)

        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.b_tasks = Pill("☑  TASKS", "accent", 9, True)
        self.b_notes = Pill("▤  NOTES", "ghost", 9, True)
        self.b_tasks.setChecked(True)
        for b in (self.b_tasks, self.b_notes):
            b.setFixedHeight(34)
            tabs.addWidget(b)
        self.b_tasks.clicked.connect(lambda: self._tab(0))
        self.b_notes.clicked.connect(lambda: self._tab(1))
        v.addLayout(tabs)

        self.pages = QStackedWidget()
        v.addWidget(self.pages, 1)

        # ── page 0: tasks ────────────────────────────────────────────────
        p0 = QWidget()
        l0 = QVBoxLayout(p0)
        l0.setContentsMargins(0, 0, 0, 0)
        l0.setSpacing(8)
        prow = QHBoxLayout()
        self.lbl_prog = label("◉  PROGRESS STATUS", mono(7, True, 1), f"color: {_DIM};")
        self.lbl_pct = label("0/0 (0%)", mono(8, True), "")
        prow.addWidget(self.lbl_prog)
        prow.addStretch(1)
        prow.addWidget(self.lbl_pct)
        l0.addLayout(prow)

        self._fb: dict[str, Pill] = {}
        frow = QHBoxLayout()
        frow.setSpacing(4)
        for n in ("ALL", "PENDING", "COMPLETED", "HIGH"):
            b = Pill(n, "ghost", 7, True)
            b.setFixedHeight(26)
            b.clicked.connect(lambda _=False, n=n: self._set_filter(n))
            self._fb[n] = b
            frow.addWidget(b)
        self._fb["ALL"].setChecked(True)
        l0.addLayout(frow)

        self._cb: dict[str, Pill] = {}
        crow = QHBoxLayout()
        crow.setSpacing(4)
        for n in ("ALL", "WORK", "PERSONAL"):
            b = Pill(n, "ghost", 6.5, True)
            b.setFixedHeight(22)
            b.clicked.connect(lambda _=False, n=n: self._set_cat(n))
            self._cb[n] = b
            crow.addWidget(b)
        crow.addStretch(1)
        self._cb["ALL"].setChecked(True)
        l0.addLayout(crow)

        field = _FieldRow()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Add new objective...")
        self.edit.setFont(sans(9))
        self.edit.setStyleSheet(
            f"background: transparent; border: none; color: {_TEXT};")
        self.edit.returnPressed.connect(self._add)
        self.b_prio = Pill("• MEDIUM", "ghost", 6.5)
        self.b_prio.setFixedHeight(22)
        self.b_prio.clicked.connect(self._cycle_prio)
        self.b_ncat = Pill("WORK", "ghost", 6.5)
        self.b_ncat.setFixedHeight(22)
        self.b_ncat.clicked.connect(self._cycle_cat)
        self.b_add = Pill("+", "accent", 12, round_=True)
        self.b_add.setFixedSize(28, 28)
        self.b_add.clicked.connect(self._add)
        field.lay.addWidget(self.edit, 1)
        field.lay.addWidget(self.b_prio)
        field.lay.addWidget(self.b_ncat)
        field.lay.addWidget(self.b_add)
        l0.addWidget(field)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(SCROLL_QSS)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.lay = QVBoxLayout(holder)
        self.lay.setContentsMargins(0, 0, 4, 0)
        self.lay.setSpacing(8)
        self.scroll.setWidget(holder)
        l0.addWidget(self.scroll, 1)
        self.pages.addWidget(p0)

        # ── page 1: notes ────────────────────────────────────────────────
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Quick notes…")
        self.notes.setFont(sans(9))
        self.notes.setPlainText(self._notes)
        self.notes.setStyleSheet(
            f"QTextEdit {{ background: rgba(255,255,255,0.05); color: {_TEXT};"
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 8px; }")
        self.notes.textChanged.connect(self._notes_changed)
        self.pages.addWidget(self.notes)

        THEME.changed.connect(self._restyle)
        self._restyle()
        self._render()

    # ── persistence ─────────────────────────────────────────────────────
    def _load(self):
        try:
            d = json.loads(self._store.read_text(encoding="utf-8"))
            self._tasks = list(d.get("tasks", []))
            self._notes = str(d.get("notes", ""))
        except Exception:
            pass

    def _save(self):
        try:
            self._store.write_text(
                json.dumps({"tasks": self._tasks, "notes": self._notes}, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    def _notes_changed(self):
        self._notes = self.notes.toPlainText()
        self._save()

    # ── behaviour ───────────────────────────────────────────────────────
    def _restyle(self):
        self.lbl_pct.setStyleSheet(f"color: {THEME.hex}; background: transparent;")

    def _tab(self, i: int):
        self.pages.setCurrentIndex(i)
        self.b_tasks.setChecked(i == 0)
        self.b_notes.setChecked(i == 1)
        self.b_tasks.set_kind("accent" if i == 0 else "ghost")
        self.b_notes.set_kind("accent" if i == 1 else "ghost")

    def _set_filter(self, n: str):
        self._flt = n
        for k, b in self._fb.items():
            b.setChecked(k == n)
        self._render()

    def _set_cat(self, n: str):
        self._cat = n
        for k, b in self._cb.items():
            b.setChecked(k == n)
        self._render()

    def _cycle_prio(self):
        self._prio = self.PRIOS[(self.PRIOS.index(self._prio) + 1) % 3]
        self.b_prio.setText(f"• {self._prio}")

    def _cycle_cat(self):
        self._newcat = self.CATS[(self.CATS.index(self._newcat) + 1) % 2]
        self.b_ncat.setText(self._newcat)

    def _add(self):
        text = self.edit.text().strip()
        if not text:
            return
        self.edit.clear()
        self._tasks.insert(0, {
            "id": f"{time.time():.6f}", "text": text, "done": False,
            "prio": self._prio, "cat": self._newcat,
            "time": time.strftime("%I:%M %p"),
        })
        self._save()
        self._render()

    def _toggle(self, tid: str):
        for t in self._tasks:
            if t["id"] == tid:
                t["done"] = not t["done"]
        self._save()
        self._render()

    def _remove(self, tid: str):
        self._tasks = [t for t in self._tasks if t["id"] != tid]
        self._save()
        self._render()

    def _match(self, t: dict) -> bool:
        if self._cat != "ALL" and t["cat"] != self._cat:
            return False
        if self._flt == "PENDING":
            return not t["done"]
        if self._flt == "COMPLETED":
            return t["done"]
        if self._flt == "HIGH":
            return t["prio"] == "HIGH"
        return True

    def _render(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        shown = [t for t in self._tasks if self._match(t)]
        for t in shown:
            item = TaskItem(t)
            item.toggled.connect(self._toggle)
            item.removed.connect(self._remove)
            self.lay.addWidget(item)
        if not shown:
            self.lay.addWidget(label("No objectives here yet.", sans(9), f"color: {_DIM};"))
        self.lay.addStretch(1)
        done = sum(1 for t in self._tasks if t["done"])
        total = len(self._tasks)
        pct = int(100 * done / total) if total else 0
        self.lbl_pct.setText(f"{done}/{total} ({pct}%)")


# ════════════════════════════════════════════════════════════════════════════
#  Satellite stream (world map)
# ════════════════════════════════════════════════════════════════════════════
_CONTINENTS = [
    [(-168, 66), (-140, 70), (-95, 72), (-80, 68), (-62, 60), (-55, 50), (-66, 44), (-76, 35),
     (-81, 25), (-97, 26), (-97, 18), (-88, 16), (-83, 9), (-78, 8), (-86, 14), (-105, 20),
     (-117, 32), (-124, 40), (-125, 49), (-135, 58), (-150, 60), (-165, 60)],
    [(-78, 8), (-62, 10), (-50, 0), (-35, -6), (-40, -22), (-58, -38), (-65, -55), (-72, -50),
     (-72, -30), (-80, -5)],
    [(-10, 36), (-9, 43), (0, 50), (8, 55), (20, 60), (30, 70), (45, 68), (40, 50), (30, 45),
     (25, 36), (10, 38)],
    [(-17, 21), (-10, 35), (10, 37), (32, 31), (43, 12), (51, 12), (40, -5), (40, -15), (33, -27),
     (20, -35), (12, -18), (9, 0), (-8, 4), (-17, 14)],
    [(45, 68), (70, 73), (110, 77), (140, 72), (170, 68), (150, 50), (142, 45), (122, 30),
     (122, 22), (108, 10), (100, 2), (95, 16), (80, 8), (72, 20), (58, 24), (50, 30), (36, 36),
     (40, 50)],
    [(114, -22), (130, -12), (142, -11), (153, -27), (146, -39), (135, -35), (115, -34)],
    [(-55, 60), (-45, 60), (-20, 70), (-30, 82), (-60, 80)],
]
_ZONES = [
    [(22, 22), (37, 22), (37, 10), (24, 9)],
    [(44, 39), (61, 36), (61, 26), (50, 26), (44, 33)],
]
_SPOTS = [(30, 50), (28, 44), (36, 34), (44, 33), (52, 34), (3, 50), (-3, 40), (12, 42), (20, 45),
          (-75, 40), (-95, 38), (-118, 34), (-47, -15), (-58, -34), (31, 30), (38, 9), (30, -1),
          (18, -33), (77, 28), (105, 35), (121, 31), (139, 36), (100, 14), (-5, 6), (15, 5),
          (24, 59), (10, 60), (135, -25), (150, -33), (-99, 19)]
_SPOT_COL = ["#ffb020", "#ffd21e", "#ff4d3a"]


class SatelliteMap(Card):
    NAV = [("●", "Today"), ("◉", "Map"), ("⌕", "Search"), ("△", "Alerts"), ("⋯", "More")]

    def __init__(self, parent=None):
        super().__init__(parent, 20)
        self._t = 0.0
        self._mode = "2D"
        self._nav = 0
        self.b2 = Pill("2D", "accent", 7, True)
        self.b3 = Pill("3D", "ghost", 7, True)
        self.b2.setChecked(True)
        for b in (self.b2, self.b3):
            b.setParent(self)
            b.setFixedSize(30, 20)
        self.b2.clicked.connect(lambda: self._set_mode("2D"))
        self.b3.clicked.connect(lambda: self._set_mode("3D"))
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(66)

    def _set_mode(self, m: str):
        self._mode = m
        self.b2.setChecked(m == "2D")
        self.b3.setChecked(m == "3D")
        self.b2.set_kind("accent" if m == "2D" else "ghost")
        self.b3.set_kind("accent" if m == "3D" else "ghost")

    def _step(self):
        self._t += 0.066
        if self.isVisible():
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.b2.move(self.width() - 76, 62)
        self.b3.move(self.width() - 42, 62)

    def mousePressEvent(self, e):
        if e.position().y() > self.height() - 44:
            self._nav = max(0, min(4, int(e.position().x() / (self.width() / 5))))
            self.update()

    def _pt(self, lon: float, lat: float, r: QRectF):
        return QPointF(r.left() + (lon + 180) / 360 * r.width(),
                       r.top() + (82 - lat) / 140 * r.height())

    def _globe(self, lon: float, lat: float, c: QPointF, R: float):
        lam = math.radians(lon - self._t * 8)
        phi = math.radians(lat)
        z = math.cos(phi) * math.cos(lam)
        return QPointF(c.x() + R * math.cos(phi) * math.sin(lam),
                       c.y() - R * math.sin(phi)), z > 0

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # header
        p.setBrush(THEME.color())
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(18, 22), 3, 3)
        p.setFont(mono(7, True, 1))
        p.setPen(THEME.color())
        p.drawText(QPointF(28, 25), "SATELLITE STREAM")
        p.setPen(QColor(120, 135, 145))
        p.setFont(sans(8))
        p.drawText(QRectF(w - 90, 12, 78, 20), Qt.AlignmentFlag.AlignRight, "⟳   ▲   ⤢")

        mr = QRectF(10, 40, w - 20, h - 40 - 46)
        clip = QPainterPath()
        clip.addRoundedRect(mr, 10, 10)
        p.save()
        p.setClipPath(clip)
        p.fillRect(mr, QColor(5, 20, 14))
        pulse = 0.5 + 0.5 * math.sin(self._t * 3)

        if self._mode == "2D":
            p.setPen(QPen(QColor(0, 170, 90, 38), 1))
            for lon in range(-180, 181, 30):
                a, b = self._pt(lon, 82, mr), self._pt(lon, -58, mr)
                p.drawLine(a, b)
            for lat in range(-40, 81, 20):
                p.drawLine(self._pt(-180, lat, mr), self._pt(180, lat, mr))
            for poly in _CONTINENTS:
                pg = QPolygonF([self._pt(x, y, mr) for x, y in poly])
                p.setBrush(QColor(18, 66, 42, 190))
                p.setPen(QPen(QColor(60, 190, 110, 170), 1))
                p.drawPolygon(pg)
            for z in _ZONES:
                pg = QPolygonF([self._pt(x, y, mr) for x, y in z])
                p.setBrush(QColor(255, 50, 50, 70))
                p.setPen(QPen(QColor(255, 70, 70, 220), 1, Qt.PenStyle.DashLine))
                p.drawPolygon(pg)
            for i, (lo, la) in enumerate(_SPOTS):
                pt = self._pt(lo, la, mr)
                col = QColor(_SPOT_COL[i % 3])
                if i % 7 == 0:
                    ring = QColor(col)
                    ring.setAlpha(int(200 * (1 - pulse)))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(ring, 1.2))
                    p.drawEllipse(pt, 3 + 7 * pulse, 3 + 7 * pulse)
                p.setBrush(col)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pt, 2.6, 2.6)
        else:
            c = mr.center()
            R = min(mr.width(), mr.height()) / 2 - 6
            g = QRadialGradient(c, R * 1.15)
            g.setColorAt(0.85, QColor(0, 120, 80, 60))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(g)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(c, R * 1.15, R * 1.15)
            p.setBrush(QColor(4, 24, 18))
            p.setPen(QPen(QColor(60, 190, 110, 150), 1))
            p.drawEllipse(c, R, R)
            for poly in _CONTINENTS:
                vis = [pt for pt, ok in (self._globe(x, y, c, R) for x, y in poly) if ok]
                if len(vis) >= 3:
                    p.setBrush(QColor(18, 66, 42, 200))
                    p.setPen(QPen(QColor(60, 190, 110, 170), 1))
                    p.drawPolygon(QPolygonF(vis))
            for i, (lo, la) in enumerate(_SPOTS):
                pt, ok = self._globe(lo, la, c, R)
                if ok:
                    p.setBrush(QColor(_SPOT_COL[i % 3]))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(pt, 2.4, 2.4)
        p.restore()

        # bottom navigation
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.drawLine(QPointF(10, h - 46), QPointF(w - 10, h - 46))
        cw = w / 5
        for i, (ic, name) in enumerate(self.NAV):
            on = i == self._nav
            p.setPen(THEME.color() if on else QColor(140, 153, 163))
            p.setFont(sans(10))
            p.drawText(QRectF(i * cw, h - 44, cw, 20), Qt.AlignmentFlag.AlignCenter, ic)
            p.setFont(mono(6.5, on))
            p.drawText(QRectF(i * cw, h - 25, cw, 16), Qt.AlignmentFlag.AlignCenter, name)


# ════════════════════════════════════════════════════════════════════════════
#  Node graph: Memory / Soul / Skills / Settings → core
# ════════════════════════════════════════════════════════════════════════════
def _paint_icon(p: QPainter, kind: str, r: QRectF, col: QColor) -> None:
    p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    c = r.center()
    if kind == "memory":
        p.drawEllipse(r.adjusted(6, 6, -6, -6))
        p.drawLine(QPointF(c.x(), r.top() + 6), QPointF(c.x(), r.bottom() - 6))
        p.drawArc(QRectF(r.left() + 4, r.top() + 9, 8, 7), 90 * 16, 180 * 16)
        p.drawArc(QRectF(c.x(), r.top() + 9, 8, 7), -90 * 16, 180 * 16)
    elif kind == "soul":
        l, rt, t, b = r.left() + 7, r.right() - 7, r.top() + 5, r.bottom() - 5
        w = rt - l
        path = QPainterPath()
        path.moveTo(l, b)
        path.lineTo(l, t + w / 2)
        path.arcTo(QRectF(l, t, w, w), 180, -180)
        path.lineTo(rt, b)
        path.lineTo(rt - w / 4, b - 3)
        path.lineTo(c.x(), b)
        path.lineTo(l + w / 4, b - 3)
        path.closeSubpath()
        p.drawPath(path)
        p.drawPoint(QPointF(c.x() - 2.5, c.y() - 1))
        p.drawPoint(QPointF(c.x() + 2.5, c.y() - 1))
    elif kind == "skills":
        a, b = r.left() + 6, r.right() - 6
        t, bt = r.top() + 8, r.bottom() - 7
        p.drawPolyline(QPolygonF([QPointF(c.x(), t + 1), QPointF(a, t), QPointF(a, bt - 1),
                                  QPointF(c.x(), bt)]))
        p.drawPolyline(QPolygonF([QPointF(c.x(), t + 1), QPointF(b, t), QPointF(b, bt - 1),
                                  QPointF(c.x(), bt)]))
        p.drawLine(QPointF(c.x(), t + 1), QPointF(c.x(), bt))
    else:  # settings gear
        p.drawEllipse(c, 3.2, 3.2)
        p.drawEllipse(c, 6.2, 6.2)
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(c.x() + 6.2 * math.cos(a), c.y() + 6.2 * math.sin(a)),
                       QPointF(c.x() + 8.4 * math.cos(a), c.y() + 8.4 * math.sin(a)))


class NodeGraph(QWidget):
    node_clicked = pyqtSignal(str)
    NODES = [("Memory", "#22c55e", "memory"), ("Soul", "#9aa4ad", "soul"),
             ("Skills", "#19b3d6", "skills"), ("Settings", "#ef4444", "settings")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self._t = 0.0
        self._hover = -1
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(33)

    def _step(self):
        self._t += 0.033
        if self.isVisible():
            self.update()

    def _rects(self) -> list[QRectF]:
        w, h = self.width(), self.height()
        nw, nh = min(150.0, w * 0.38), 46.0
        gap = (h - 4 * nh) / 5
        return [QRectF(2, gap + i * (nh + gap), nw, nh) for i in range(4)]

    def mouseMoveEvent(self, e):
        idx = next((i for i, r in enumerate(self._rects()) if r.contains(e.position())), -1)
        if idx != self._hover:
            self._hover = idx
            self.setCursor(Qt.CursorShape.PointingHandCursor if idx >= 0
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        for i, r in enumerate(self._rects()):
            if r.contains(e.position()):
                self.node_clicked.emit(self.NODES[i][2])
                return

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rects = self._rects()
        hub = QPointF(w * 0.62, h / 2)
        accent = QColor("#4f8dff")

        for i, (name, hx, kind) in enumerate(self.NODES):
            col = QColor(hx)
            s = QPointF(rects[i].right(), rects[i].center().y())
            path = QPainterPath(s)
            dx = hub.x() - s.x()
            path.cubicTo(QPointF(s.x() + dx * 0.55, s.y()), QPointF(hub.x() - dx * 0.45, hub.y()), hub)
            glow = QColor(col)
            glow.setAlpha(45)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow, 7))
            p.drawPath(path)
            p.setPen(QPen(col, 2))
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            for k in range(2):
                t = (self._t * 0.22 + i * 0.23 + k * 0.5) % 1
                p.setBrush(QColor(255, 255, 255, 230))
                p.drawEllipse(path.pointAtPercent(t), 2.4, 2.4)

        # core line to the orb
        glow = QColor(accent)
        glow.setAlpha(60)
        p.setPen(QPen(glow, 7))
        p.drawLine(hub, QPointF(w, hub.y()))
        p.setPen(QPen(accent, 2))
        p.drawLine(hub, QPointF(w, hub.y()))
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(3):
            t = (self._t * 0.3 + k / 3) % 1
            x = hub.x() + (w - hub.x()) * t
            p.setBrush(QColor(255, 255, 255, 235) if k % 2 == 0 else accent.lighter(130))
            p.drawEllipse(QPointF(x, hub.y()), 3.2 if k == 1 else 2.2, 3.2 if k == 1 else 2.2)
        p.setBrush(accent)
        p.drawEllipse(QPointF(w - 5, hub.y()), 3, 3)
        p.setBrush(QColor(3, 6, 10))
        p.setPen(QPen(accent, 2))
        p.drawEllipse(hub, 6, 6)

        # nodes
        for i, (name, hx, kind) in enumerate(self.NODES):
            r = rects[i]
            col = QColor(hx)
            hov = i == self._hover
            p.setBrush(QColor(11, 19, 26))
            edge = QColor(col)
            edge.setAlpha(140 if hov else 26)
            p.setPen(QPen(edge if hov else QColor(255, 255, 255, 26), 1))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
            ib = QRectF(r.left() + 8, r.center().y() - 16, 32, 32)
            tint = QColor(col)
            tint.setAlpha(34)
            border = QColor(col)
            border.setAlpha(120)
            p.setBrush(tint)
            p.setPen(QPen(border, 1))
            p.drawRoundedRect(ib, 9, 9)
            _paint_icon(p, kind, ib, col)
            p.setPen(QColor("#d3dbe1") if hov else QColor("#a9b4bd"))
            p.setFont(sans(10, True))
            p.drawText(QRectF(ib.right() + 10, r.top(), r.width() - 70, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            p.setBrush(col)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(r.right() - 10, r.center().y()), 1.8, 1.8)


# ════════════════════════════════════════════════════════════════════════════
#  Orb (particle sphere) + its card
# ════════════════════════════════════════════════════════════════════════════
class OrbCanvas(QWidget):
    """Drop-in for the old HudCanvas: same attributes and audio hooks."""

    def __init__(self, face_path: str = "", assistant_name: str = "", parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.muted = False
        self.speaking = False
        self.state = "INITIALISING"
        self.hud_style = "orb"
        self._assistant_name = assistant_name
        self._live = 0.0
        self._amp = 0.0
        self._t = 0.0
        rnd = random.Random(3)
        n = 440
        self._pts = []
        for i in range(n):
            y = 1 - 2 * (i + 0.5) / n
            r = math.sqrt(1 - y * y)
            th = i * 2.399963
            self._pts.append((math.cos(th) * r, y, math.sin(th) * r,
                              rnd.random() < 0.18, rnd.choice((1, 1, 2))))
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(33)

    # ---- API used by MainWindow / JarvisUI ---------------------------------
    def set_audio_level(self, level: float) -> None:
        try:
            lv = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            return
        if lv > self._live:
            self._live = lv

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        pass

    def push_visemes(self, frames, hop: float, at: float) -> None:
        pass

    # ---- animation ------------------------------------------------------
    def _step(self):
        busy = self.state in ("THINKING", "PROCESSING")
        self._t += 0.033 * (2.4 if busy else 1.0)
        self._live *= 0.86
        self._amp += (self._live - self._amp) * 0.3
        if self.isVisible():
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        R = min(w, h) * 0.40 * (1 + 0.12 * self._amp)
        dim = 0.35 if self.muted else 1.0
        acc = THEME.color()
        amber = QColor("#ffc400")

        g = QRadialGradient(QPointF(cx, cy), R * 1.1)
        g.setColorAt(0, QColor(acc.red(), acc.green(), acc.blue(), int(55 * dim)))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), R * 1.1, R * 1.1)

        ay, ax = self._t * 0.35, 0.38
        cay, say, cax, sax = math.cos(ay), math.sin(ay), math.cos(ax), math.sin(ax)
        for x, y, z, warm, sz in self._pts:
            x1 = x * cay + z * say
            z1 = -x * say + z * cay
            y2 = y * cax - z1 * sax
            z2 = y * sax + z1 * cax
            depth = (z2 + 1) / 2
            col = amber if warm else acc
            col.setAlpha(int((50 + 200 * depth) * dim))
            s = (1.0 + 0.8 * sz) * (0.6 + depth)
            p.fillRect(QRectF(cx + x1 * R - s / 2, cy - y2 * R - s / 2, s, s), col)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for ang, rx, ry, c in ((-32 + self._t * 6, 1.02, 0.36, QColor(255, 196, 0, int(70 * dim))),
                               (38 - self._t * 4, 1.0, 0.30, QColor(acc.red(), acc.green(), acc.blue(), int(60 * dim)))):
            p.save()
            p.translate(cx, cy)
            p.rotate(ang)
            p.setPen(QPen(c, 1))
            p.drawEllipse(QPointF(0, 0), R * rx, R * ry)
            p.restore()


class OrbCard(Card):
    terminate = pyqtSignal()
    mic = pyqtSignal()
    camera = pyqtSignal()
    screen = pyqtSignal()

    def __init__(self, stack: QWidget, parent=None):
        super().__init__(parent, 28)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 16)
        v.setSpacing(8)
        v.addWidget(stack, 1)
        self.status = label("●  SYSTEM ACTIVE  ●", mono(7.5, True, 2), "")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.b_term = Pill("TERMINATE", "danger", 9)
        self.b_term.setFixedSize(150, 38)
        self.b_term.setToolTip("Stop the current response")
        self.b_term.clicked.connect(self.terminate.emit)
        self.b_mic = Pill("🎙", "accent", 11, round_=True)
        self.b_mic.setFixedSize(38, 38)
        self.b_mic.setToolTip("Mute / unmute microphone")
        self.b_mic.clicked.connect(self.mic.emit)
        row.addWidget(self.b_term)
        row.addWidget(self.b_mic)
        row.addStretch(1)
        v.addLayout(row)
        self.b_cam = Pill("📷", "ghost", 10, round_=True, parent=self)
        self.b_scr = Pill("🖥", "ghost", 10, round_=True, parent=self)
        for b in (self.b_cam, self.b_scr):
            b.setFixedSize(34, 34)
        self.b_cam.setToolTip("Camera")
        self.b_scr.setToolTip("Fullscreen")
        self.b_cam.clicked.connect(self.camera.emit)
        self.b_scr.clicked.connect(self.screen.emit)
        THEME.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self):
        self.status.setStyleSheet(f"color: {THEME.hex}; background: transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.b_cam.move(self.width() - 50, 14)
        self.b_scr.move(self.width() - 50, 56)
        self.b_cam.raise_()
        self.b_scr.raise_()

    def set_state(self, state: str, muted: bool) -> None:
        txt = {"MUTED": "MIC MUTED", "LISTENING": "LISTENING", "SPEAKING": "SPEAKING",
               "THINKING": "THINKING", "SLEEPING": "SLEEPING"}.get(state, "SYSTEM ACTIVE")
        self.status.setText(f"●  {txt}  ●")

    def set_muted(self, muted: bool) -> None:
        self.b_mic.set_kind("danger" if muted else "accent")
        self.b_mic.setText("🔇" if muted else "🎙")


# ════════════════════════════════════════════════════════════════════════════
#  Agent Town + Visual Hub
# ════════════════════════════════════════════════════════════════════════════
LW, LH = 256, 128           # logical pixel-art canvas

_AGENTS = [
    # name,   hair,      skin,      shirt,     seat
    ("Alice", "#6b4a3a", "#e0a98a", "#d94f6a", (74, 119)),
    ("Bob",   "#4a3626", "#d9a07c", "#4a7fd9", (36, 57)),
    ("Carol", "#7a2e2a", "#e6b394", "#3fae6a", (100, 57)),
    ("Dave",  "#2a3550", "#d3a17f", "#d9a43f", (68, 57)),
]
_SPOTS_TOWN = [(220, 72), (178, 32), (140, 44), (144, 122), (182, 120), (46, 114),
               (122, 54), (198, 70), (110, 116)]


class MindMap(QWidget):
    """The Visual Hub: a radial map built from whatever the assistant displays."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._center = ""
        self._items: list[str] = []
        self._z = 1.0
        self._pan = QPointF(0, 0)
        self._drag: QPointF | None = None
        self.bi = Pill("+", "ghost", 10, round_=True, parent=self)
        self.bo = Pill("−", "ghost", 10, round_=True, parent=self)
        self.br = Pill("↺", "ghost", 10, round_=True, parent=self)
        for b in (self.bi, self.bo, self.br):
            b.setFixedSize(30, 30)
        self.bi.clicked.connect(lambda: self._zoom(1.15))
        self.bo.clicked.connect(lambda: self._zoom(1 / 1.15))
        self.br.clicked.connect(self._reset)

    def _zoom(self, f: float):
        self._z = max(0.3, min(2.5, self._z * f))
        self.update()

    def _reset(self):
        self._z, self._pan = 1.0, QPointF(0, 0)
        self.update()

    def set_map(self, center: str, items: list[str]) -> None:
        self._center, self._items = center, items
        self.update()

    def set_from_text(self, title: str, text: str) -> None:
        lines = [re.sub(r"^[#*\-•\d.)\s]+", "", ln).strip(" *_`") for ln in str(text).splitlines()]
        items = [ln[:30] for ln in lines if len(ln) > 2][:10]
        self.set_map(str(title)[:30] or "Content", items)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        y = self.height() - 40
        self.bo.move(10, y)
        self.bi.move(80, y)
        self.br.move(116, y)

    def wheelEvent(self, e):
        self._zoom(1.1 if e.angleDelta().y() > 0 else 1 / 1.1)

    def mousePressEvent(self, e):
        self._drag = e.position()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self._pan += e.position() - self._drag
            self._drag = e.position()
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(6, 12, 18))
        p.setPen(QPen(THEME.color(60), 1))
        p.drawRoundedRect(r, 16, 16)
        acc = THEME.color()
        p.setFont(mono(7, True, 1))
        p.setPen(acc)
        p.drawText(QPointF(16, 24), "VISUAL HUB")
        p.setFont(mono(8, True))
        p.setPen(QColor(150, 163, 173))
        p.drawText(QRectF(0, self.height() - 40, self.width(), 30),
                   Qt.AlignmentFlag.AlignCenter, f"{int(self._z * 100)}%")
        p.drawText(QRectF(self.width() - 130, self.height() - 38, 118, 24),
                   Qt.AlignmentFlag.AlignRight, "DRAG TO PAN")
        if not self._items:
            p.setFont(sans(9))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       "Nothing to map yet.\nContent the assistant shows appears here.")
            return
        c = QPointF(self.width() / 2, self.height() / 2) + self._pan
        n = len(self._items)
        rad = 150 * self._z * (1 if n <= 6 else 1.25)
        fm_font = sans(max(6.0, 8.5 * self._z), True)
        p.setFont(fm_font)
        fm = QFontMetrics(fm_font)
        for i, it in enumerate(self._items):
            a = -math.pi / 2 + 2 * math.pi * i / n
            pos = QPointF(c.x() + math.cos(a) * rad * 1.35, c.y() + math.sin(a) * rad)
            p.setPen(QPen(THEME.color(120), 2))
            p.drawLine(c, pos)
            tw = fm.horizontalAdvance(it) + 22
            nr = QRectF(pos.x() - tw / 2, pos.y() - 14 * self._z, tw, 28 * self._z)
            p.setBrush(QColor(8, 26, 34))
            p.setPen(QPen(THEME.color(140), 1))
            p.drawRoundedRect(nr, 8, 8)
            p.setPen(QColor(_TEXT))
            p.drawText(nr, Qt.AlignmentFlag.AlignCenter, it)
        cr = 48 * self._z
        p.setBrush(QColor(8, 24, 31))
        p.setPen(QPen(acc, 1.5))
        p.drawEllipse(c, cr, cr)
        p.setPen(QColor(_TEXT))
        p.drawText(QRectF(c.x() - cr + 6, c.y() - cr + 6, 2 * cr - 12, 2 * cr - 12),
                   int(Qt.AlignmentFlag.AlignCenter.value) | int(Qt.TextFlag.TextWordWrap.value), self._center)


class AgentTown(Card):
    chat_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, 26)
        self.setMouseTracking(True)
        self._bg: QPixmap | None = None
        self._t = 0.0
        self._thinking = False
        self._speaking = False
        self._sel = 0
        self._hub_on = False
        self._ag = []
        for name, hair, skin, shirt, seat in _AGENTS:
            self._ag.append({"name": name, "hair": hair, "skin": skin, "shirt": shirt,
                             "seat": seat, "x": float(seat[0]), "y": float(seat[1]),
                             "tx": float(seat[0]), "ty": float(seat[1]),
                             "state": "seat", "wait": 0.0, "walk": 0.0})
        self.hub = MindMap(self)
        self.hub.hide()

        self.b_town = Pill("AGENT TOWN", "accent", 8, True)
        self.b_hub = Pill("VISUAL HUB", "ghost", 8, True)
        self.b_town.setChecked(True)
        for b in (self.b_town, self.b_hub):
            b.setParent(self)
            b.setFixedSize(104, 28)
        self.b_town.clicked.connect(lambda: self.show_hub(False))
        self.b_hub.clicked.connect(lambda: self.show_hub(True))

        self.tools = []
        for glyph, tip, fn in (("⎇", "Send everyone for a walk", self._scatter),
                               ("☰", "Open Visual Hub", lambda: self.show_hub(True)),
                               ("♟", "Everyone back to their desks", self._home),
                               ("⤢", "Fullscreen", self._fullscreen)):
            b = Pill(glyph, "ghost", 9, round_=True, parent=self)
            b.setFixedSize(28, 28)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            self.tools.append(b)
        self.b_chat = Pill("✉   CHAT", "accent", 10, parent=self)
        self.b_chat.setFixedSize(112, 42)
        self.b_chat.clicked.connect(self.chat_clicked.emit)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)
        self._tmr.start(50)

    # ---- public ---------------------------------------------------------
    def set_activity(self, state: str) -> None:
        self._thinking = state in ("THINKING", "PROCESSING")
        self._speaking = state == "SPEAKING"

    def show_hub(self, on: bool) -> None:
        self._hub_on = on
        self.hub.setVisible(on)
        self.b_town.setChecked(not on)
        self.b_hub.setChecked(on)
        self.b_town.set_kind("ghost" if on else "accent")
        self.b_hub.set_kind("accent" if on else "ghost")
        self.hub.raise_()
        for b in (self.b_town, self.b_hub, *self.tools, self.b_chat):
            b.raise_()

    # ---- behaviour ------------------------------------------------------
    def _fullscreen(self):
        w = self.window()
        w.showNormal() if w.isFullScreen() else w.showFullScreen()

    def _go(self, a: dict, tx: float, ty: float, dest: str):
        a["tx"], a["ty"], a["dest"], a["state"] = float(tx), float(ty), dest, "walk"

    def _scatter(self):
        for a in self._ag:
            sx, sy = random.choice(_SPOTS_TOWN)
            self._go(a, sx, sy, "visit")

    def _home(self):
        for a in self._ag:
            self._go(a, a["seat"][0], a["seat"][1], "seat")

    def _tick(self):
        dt = 0.05
        self._t += dt
        for a in self._ag:
            st = a["state"]
            if st == "walk":
                dx, dy = a["tx"] - a["x"], a["ty"] - a["y"]
                d = math.hypot(dx, dy)
                if d < 1.0:
                    a["state"] = "seat" if a.get("dest") == "seat" else "stay"
                    a["wait"] = random.uniform(3, 7)
                else:
                    step = min(18 * dt, d)
                    a["x"] += dx / d * step
                    a["y"] += dy / d * step
                    a["walk"] += dt * 8
            elif st == "stay":
                a["wait"] -= dt
                if a["wait"] <= 0:
                    self._go(a, a["seat"][0], a["seat"][1], "seat")
            elif st == "seat" and not self._thinking and random.random() < 0.003:
                sx, sy = random.choice(_SPOTS_TOWN)
                self._go(a, sx, sy, "visit")
        if self.isVisible() and not self._hub_on:
            self.update()

    # ---- layout ---------------------------------------------------------
    def _canvas(self) -> QRectF:
        return QRectF(10, 46, self.width() - 20, self.height() - 56)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        self.b_hub.move(w - 14 - 104, 10)
        self.b_town.move(w - 14 - 104 * 2 - 6, 10)
        for i, b in enumerate(self.tools):
            b.move(w - 22 - 28 * (4 - i) - 4 * (3 - i) - 4, 54)
        self.b_chat.move(w - 126, h - 56)
        self.hub.setGeometry(10, 46, w - 20, h - 56)

    def mousePressEvent(self, e):
        x, y = e.position().x(), e.position().y()
        for i in range(len(self._ag)):
            if QRectF(18 + i * 92, 52, 86, 30).contains(x, y):
                self._sel = i
                self.update()

    # ---- artwork --------------------------------------------------------
    def _build_bg(self) -> QPixmap:
        pm = QPixmap(LW, LH)
        pm.fill(QColor("#0a0f16"))
        p = QPainter(pm)

        def R(x, y, w, h, c):
            p.fillRect(QRect(int(x), int(y), int(w), int(h)), QColor(c))

        def tiles(x, y, w, h, a, b):
            R(x, y, w, h, a)
            for ty in range(y, y + h, 8):
                for tx in range(x, x + w, 8):
                    if ((tx // 8) + (ty // 8)) % 2:
                        R(tx, ty, 8, 8, b)

        def plant(x, y):
            R(x + 1, y + 6, 4, 3, "#8a5a3a")
            R(x, y + 1, 6, 6, "#2f7d3a")
            R(x + 1, y - 1, 4, 3, "#3c9a49")

        def desk(x, y):
            R(x, y, 28, 12, "#c9a26b")
            R(x, y, 28, 2, "#a98250")
            R(x + 9, y - 6, 10, 7, "#1d2733")
            R(x + 10, y - 5, 8, 5, "#58b0e6")
            R(x + 10, y + 14, 9, 8, "#2b2f36")

        # office + library
        R(8, 6, 144, 12, "#cfd5da")
        R(8, 16, 144, 2, "#8d949a")
        tiles(8, 18, 144, 60, "#aab0b6", "#a2a8ae")
        R(156, 6, 92, 12, "#d6d0c4")
        R(156, 16, 92, 2, "#8d8579")
        tiles(156, 18, 92, 60, "#9ea5ad", "#97a0a8")
        R(152, 6, 4, 72, "#eef1f3")
        R(8, 78, 240, 4, "#eef1f3")
        R(60, 78, 14, 4, "#a0643a")
        R(164, 78, 14, 4, "#a0643a")
        # whiteboards, desks, printer
        R(20, 8, 24, 10, "#f2f5f7")
        R(22, 10, 20, 6, "#7fb4de")
        R(60, 8, 26, 10, "#f2f5f7")
        R(63, 11, 7, 3, "#d95b5b")
        R(72, 11, 10, 3, "#6ca87a")
        for x in (22, 54, 86):
            desk(x, 36)
        R(118, 38, 12, 8, "#e6e9ec")
        R(120, 36, 8, 3, "#cfd3d7")
        plant(10, 62)
        plant(142, 64)
        # library
        R(160, 8, 34, 16, "#7a5230")
        cols = ["#d9534f", "#4a90d9", "#e8c24a", "#5cb85c"]
        for i in range(10):
            R(162 + i * 3, 10 + (i % 2) * 7, 2, 5, cols[i % 4])
        R(200, 8, 20, 16, "#2c3a33")
        R(224, 8, 20, 16, "#7a5230")
        for i in range(7):
            R(226 + i * 3, 10 + (i % 2) * 7, 2, 5, cols[(i + 1) % 4])
        R(163, 30, 6, 6, "#3f78b8")
        R(206, 38, 30, 28, "#4c6f3a")
        R(208, 40, 26, 24, "#6b9150")
        R(182, 62, 16, 10, "#c9a26b")
        R(178, 64, 4, 6, "#d1a35a")
        R(198, 64, 4, 6, "#d1a35a")
        plant(238, 62)
        # lounge
        R(28, 82, 92, 8, "#6e5a49")
        for x in range(28, 120, 6):
            R(x, 82, 1, 8, "#52443a")
        R(28, 86, 92, 1, "#52443a")
        tiles(28, 90, 92, 34, "#8c9298", "#858b91")
        R(36, 94, 22, 10, "#3a3f47")
        R(36, 92, 22, 3, "#4a505a")
        desk(60, 100)
        plant(32, 112)
        plant(108, 112)
        # lab
        R(124, 82, 92, 8, "#6e5a49")
        for x in range(124, 216, 6):
            R(x, 82, 1, 8, "#52443a")
        R(124, 86, 92, 1, "#52443a")
        tiles(124, 90, 92, 34, "#8c9298", "#858b91")
        R(130, 106, 28, 12, "#c7ccd1")
        R(132, 108, 24, 8, "#9fb3c4")
        R(130, 92, 30, 6, "#aeb4b9")
        R(165, 100, 16, 14, "#5d6a76")
        R(167, 102, 12, 6, "#8fd4ff")
        R(186, 102, 18, 4, "#7ddc3a")
        R(188, 104, 14, 10, "#222a22")
        R(190, 98, 3, 3, "#a5f060")
        R(176, 92, 6, 6, "#ffd24a")
        # side walls
        for x in (24, 120, 216):
            R(x, 82, 4, 42, "#eef1f3")
        R(24, 124, 196, 3, "#eef1f3")
        p.end()
        return pm

    def _draw_agent(self, p: QPainter, a: dict, ox: float, oy: float, s: float):
        walking = a["state"] == "walk"
        bob = (1 if int(a["walk"]) % 2 else 0) if walking else 0
        x, y = a["x"], a["y"] - bob * 0.8
        p.save()
        p.translate(ox, oy)
        p.scale(s, s)
        p.setPen(Qt.PenStyle.NoPen)

        def R(rx, ry, w, h, c):
            p.fillRect(QRectF(x + rx, y + ry, w, h), QColor(c))

        R(-3, -2, 6, 2, QColor(0, 0, 0, 60).name(QColor.NameFormat.HexArgb))
        R(-2.5, -3, 2, 3, "#2a2d36")
        R(0.5, -3, 2, 3, "#2a2d36")
        R(-3, -8, 6, 5, a["shirt"])
        R(-2.5, -12, 5, 4, a["skin"])
        R(-3, -13, 6, 2.5, a["hair"])
        p.restore()
        sx, sy = ox + x * s, oy + (y - 14) * s
        p.setFont(mono(6.5, True))
        p.setPen(QColor(0, 0, 0, 160))
        p.drawText(QRectF(sx - 30 + 1, sy - 11 + 1, 60, 12), Qt.AlignmentFlag.AlignCenter, a["name"])
        p.setPen(QColor("#e8eef2"))
        p.drawText(QRectF(sx - 30, sy - 11, 60, 12), Qt.AlignmentFlag.AlignCenter, a["name"])
        if self._thinking or (self._speaking and a["name"] == "Alice"):
            bub = QRectF(sx + 4, sy - 28, 16, 14)
            p.setBrush(QColor(255, 255, 255, 235))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bub, 5, 5)
            p.setPen(QColor("#1d2733"))
            p.setFont(sans(8, True))
            p.drawText(bub, Qt.AlignmentFlag.AlignCenter, "?" if self._thinking else "…")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setBrush(THEME.color())
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(22, 24), 3.5, 3.5)
        p.setPen(THEME.color())
        p.setFont(mono(8, True, 2))
        p.drawText(QPointF(34, 28), "AGENT TOWN")
        if self._hub_on:
            return
        if self._bg is None:
            self._bg = self._build_bg()
        cv = self._canvas()
        s = min(cv.width() / LW, cv.height() / LH)
        ox = cv.left() + (cv.width() - LW * s) / 2
        oy = cv.top() + (cv.height() - LH * s) / 2
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawPixmap(QRect(int(ox), int(oy), int(LW * s), int(LH * s)), self._bg)
        p.fillRect(QRectF(ox, oy, LW * s, LH * s), QColor(12, 22, 52, 70))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for a in sorted(self._ag, key=lambda q: q["y"]):
            self._draw_agent(p, a, ox, oy, s)

        # agent chips
        for i, a in enumerate(self._ag):
            r = QRectF(18 + i * 92, 52, 86, 30)
            p.setBrush(QColor(8, 14, 20, 225))
            p.setPen(QPen(QColor("#d9a43f") if i == self._sel else QColor(255, 255, 255, 30), 1.2))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(a["skin"]))
            p.drawRoundedRect(QRectF(r.left() + 5, r.top() + 5, 20, 20), 5, 5)
            p.setBrush(QColor(a["hair"]))
            p.drawRoundedRect(QRectF(r.left() + 5, r.top() + 5, 20, 9), 4, 4)
            p.setPen(QColor("#dfe6eb"))
            p.setFont(mono(7.5, True))
            p.drawText(QRectF(r.left() + 29, r.top(), 40, r.height()),
                       Qt.AlignmentFlag.AlignVCenter, a["name"])
            dot = {"seat": "#2ee66b", "walk": "#ffd21e", "stay": "#ffd21e"}.get(a["state"], "#2ee66b")
            p.setBrush(QColor(dot))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(r.right() - 9, r.center().y()), 4, 4)

        # status chips
        seated = sum(1 for a in self._ag if a["state"] == "seat")
        busy = len(self._ag) if self._thinking else 0
        x = 18
        for txt, dot in (("Online", "#2ee66b"), (f"{seated}/7 seat", None),
                         (f"{busy}/{len(self._ag)} busy", None)):
            p.setFont(mono(7, True))
            tw = QFontMetrics(p.font()).horizontalAdvance(txt) + (34 if dot else 22)
            r = QRectF(x, h - 42, tw, 26)
            p.setBrush(QColor(8, 14, 20, 225))
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.drawRoundedRect(r, 13, 13)
            if dot:
                p.setBrush(QColor(dot))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(r.left() + 13, r.center().y()), 4, 4)
            p.setPen(QColor("#b9c4cc"))
            p.drawText(r.adjusted(24 if dot else 0, 0, 0, 0),
                       Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if dot
                                                        else Qt.AlignmentFlag.AlignHCenter), txt)
            x += tw + 6


# ════════════════════════════════════════════════════════════════════════════
#  Chat panel
# ════════════════════════════════════════════════════════════════════════════
class _TabText(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(mono(7.5, True, 1.5))
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 14, 24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(QColor("#e8eef2") if self.isChecked() else QColor(110, 124, 134))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class _InputEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Type to Assistant…")
        self.setFont(sans(10))
        self.setFixedHeight(46)
        self.setTextMargins(6, 0, 44, 0)
        self.send = Pill("↑", "ghost", 11, round_=True, parent=self)
        self.send.setFixedSize(32, 32)
        THEME.changed.connect(self._style)
        self._style()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.send.move(self.width() - 40, (self.height() - 32) // 2)

    def _style(self):
        self.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,0.07); color: #e8eef2;"
            " border: 1px solid rgba(255,255,255,0.07); border-radius: 23px; padding: 0 14px; }"
            f"QLineEdit:focus {{ border: 1px solid {THEME.hex}; }}")


class _Bubble(QLabel):
    def __init__(self, text: str, user: bool):
        super().__init__(text)
        self.setWordWrap(True)
        self.setFont(sans(10))
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setMaximumWidth(300)
        bg = "rgba(255,255,255,0.10)" if user else "rgba(255,255,255,0.05)"
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: #e8eef2; border: 1px solid rgba(255,255,255,0.07);"
            " border-radius: 16px; padding: 12px 14px; }")


class ChatPanel(Card):
    def __init__(self, parent=None):
        super().__init__(parent, 24)
        self.name = "Assistant"
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(2)
        self.t_chat = _TabText("CHATS")
        self.t_log = _TabText("LOGS")
        self.t_chat.setChecked(True)
        self.t_chat.clicked.connect(lambda: self._tab(0))
        self.t_log.clicked.connect(lambda: self._tab(1))
        sep = label("|", mono(8), "color: rgba(255,255,255,0.18);")
        head.addWidget(self.t_chat)
        head.addWidget(sep)
        head.addWidget(self.t_log)
        head.addStretch(1)
        self.b_new = Pill("+", "ghost", 11)
        self.b_hist = Pill("↺", "ghost", 10)
        for b, tip in ((self.b_new, "Clear conversation"), (self.b_hist, "Show activity log")):
            b.setFixedSize(26, 26)
            b.setToolTip(tip)
            head.addWidget(b)
        self.b_new.clicked.connect(self.clear)
        self.b_hist.clicked.connect(lambda: self._tab(1))
        v.addLayout(head)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(SCROLL_QSS)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.cl = QVBoxLayout(holder)
        self.cl.setContentsMargins(0, 0, 4, 0)
        self.cl.setSpacing(14)
        self.cl.addStretch(1)
        self.scroll.setWidget(holder)
        self.stack.addWidget(self.scroll)

        self.log_holder = QWidget()
        self.log_lay = QVBoxLayout(self.log_holder)
        self.log_lay.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.log_holder)

        self.file_hint = label("No file attached", mono(6.5), f"color: {_DIM};")
        self.file_hint.setWordWrap(True)
        v.addWidget(self.file_hint)

        self.input = _InputEdit()
        self.send_btn = self.input.send
        v.addWidget(self.input)

        pills = QHBoxLayout()
        pills.setSpacing(8)
        self.voice_btn = Pill("🎙  VOICE ASSISTANT", "accent", 7.5)
        self.voice_btn.setFixedHeight(30)
        self.upload_btn = Pill("⇪  UPLOAD FILE", "ghost", 7.5)
        self.upload_btn.setFixedHeight(30)
        pills.addWidget(self.voice_btn)
        pills.addWidget(self.upload_btn)
        pills.addStretch(1)
        self.status = label("● Starting", mono(6.5), "")
        pills.addWidget(self.status)
        v.addLayout(pills)

        THEME.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self):
        self.status.setStyleSheet(f"color: {THEME.hex}; background: transparent;")

    def set_log_widget(self, w: QWidget) -> None:
        self.log_lay.addWidget(w)

    def _tab(self, i: int):
        self.stack.setCurrentIndex(i)
        self.t_chat.setChecked(i == 0)
        self.t_log.setChecked(i == 1)

    def set_status(self, state: str) -> None:
        self.status.setText(f"● {state.title()}")

    def clear(self):
        while self.cl.count() > 1:
            it = self.cl.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._tab(0)

    def add(self, role: str, text: str) -> None:
        user = role == "user"
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(5)
        who = label("YOU  ●" if user else f"●  {self.name.upper()}", mono(6.5, True, 1.5),
                    f"color: {_DIM};")
        who.setAlignment(Qt.AlignmentFlag.AlignRight if user else Qt.AlignmentFlag.AlignLeft)
        col.addWidget(who)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        b = _Bubble(text, user)
        if user:
            row.addStretch(1)
            row.addWidget(b)
        else:
            row.addWidget(b)
            row.addStretch(1)
        col.addLayout(row)
        self.cl.insertWidget(self.cl.count() - 1, box)
        QTimer.singleShot(40, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def ingest(self, text: str) -> None:
        """Turn a log line into a chat bubble. SYS / ERR lines stay in LOGS."""
        t = str(text).strip()
        if not t or t.startswith(("SYS:", "ERR:")):
            return
        m = re.match(r"^\[Web\]:\s*(.*)$", t, re.S)
        if m:
            self.add("user", m.group(1))
            return
        m = re.match(r"^([^:\n]{1,32}):\s+(.*)$", t, re.S)
        if not m:
            return
        who, body = m.groups()
        if who.strip().lower() == "you":
            self.add("user", body)
        else:
            self.name = who.strip()
            self.add("ai", body)
