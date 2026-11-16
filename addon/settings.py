"""Settings dialog for Card Timer & Deck Label, opened from the Tools menu, the
add-on's Config button, or the deck label's right-click menu. It edits the
same keys as config.json; keys it doesn't know about are kept as they are."""

from __future__ import annotations

import html
import math
from typing import Any, Callable

from aqt.qt import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColor,
    QColorDialog,
    QCursor,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QIcon,
    QLabel,
    QMessageBox,
    QPainter,
    QPen,
    QPixmap,
    QPoint,
    QPushButton,
    QScrollArea,
    QSize,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    Qt,
    QTimer,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

# Your pace in a deck comes from this many of its most recent answers, and
# needs at least this many; with fewer, the deck uses the target time setting.
PACE_RECENT_ANSWERS = 1000
PACE_MIN_ANSWERS = 20

# (deck name, its preset's Auto Advance seconds or None, its pace target or
# None with too few answers, how many answers the pace is based on)
DeckRow = tuple[str, "float | None", "float | None", int]

_POSITIONS = [
    ("Top right", "top-right"),
    ("Top left", "top-left"),
    ("Top center", "top-center"),
]
# when the counter and the last time show
_SIDES = [
    ("Always", "always"),
    ("On the answer side", "answer"),
    ("Never", "never"),
]
# when the deck label shows
_DECK_MODES = [
    ("When studying a parent deck", "parent"),
    ("Always", "always"),
    ("Never", "never"),
]
# where the deck label goes
_DECK_POSITIONS = [
    ("Opposite the counter", "auto"),
    ("Top left", "top-left"),
    ("Top center", "top-center"),
    ("Top right", "top-right"),
    ("Bottom left", "bottom-left"),
    ("Bottom center", "bottom-center"),
    ("Bottom right", "bottom-right"),
]
# what the deck label shows on a side: nothing, or this much of the deck's name
_DECK_SHOWS = [
    ("Nothing", "nothing"),
    ("Just the deck", "deck"),
    ("The deck and its parent", "parent"),
    ("The deck and two parents", "two_parents"),
    ("The full path", "full"),
]

# What a setting's name shows when hovered.
_HELP = {
    "target": "The time bar fills up over this time, and the counter turns red"
    ' when you reach it. While Auto Advance is running, the deck\'s "Seconds'
    ' to show question for" is used instead.',
    "amber": "The counter and the bar turn amber once this much of the target"
    " time has passed, as a warning before red.",
    "pace": "Each deck gets its own target time, worked out from your last"
    f" {PACE_RECENT_ANSWERS:,} answers there. Until a deck has"
    f" {PACE_MIN_ANSWERS} answers, it uses the target time above.",
    "percentile": "Lower is stricter: at 50%, the counter turns red once you're"
    " slower than half of your recent answers.",
    "targets_by_deck": "Also shows your pace in each deck, even while pace is"
    " off.",
    "counter": "The seconds counter. \"On the answer side\" hides it while"
    " you're recalling, then shows your time once you reveal the answer.",
    "position": "Where the counter sits on the card. The time bar always runs"
    " along the top.",
    "size": "How big the counter's digits are.",
    "hide_builtin": "Anki has its own small timer at the bottom right of the"
    " review screen. Hiding it means you don't see two timers.",
    "normal": "The counter and the bar's color until they turn amber.",
    "near": "Their color from the amber point until the target time.",
    "over": "Their color once the target time has passed, or the deck's"
    " Maximum answer seconds is reached.",
    "last_time": "How long the card took the last time you got it right,"
    " shown under the counter and as a tick on the time bar. Click it to open"
    " Card Info.",
    "bar": "It fills up toward the target time and changes color with the"
    " counter.",
    "count_down": "Shows the seconds left instead of the seconds taken. Past"
    " the target time it shows +1s, +2s and so on.",
    "pause_editing": "Anki normally keeps counting while you edit a card"
    " mid-review, and records that time as part of your answer. With this on,"
    " the clock stops until you're back on the review screen, both on screen"
    " and in what Anki records.",
    "show_deck": "Shows which deck the card is from. \"When studying a parent"
    " deck\" shows it on cards from a subdeck of the deck you're studying."
    " Cards in a filtered deck show their home deck.",
    "deck_position": "\"Opposite the counter\" is the other top corner, or top"
    " left when the counter is centered. At the bottom, the label stays in view"
    " as you scroll a long card.",
    "deck_question": "What the label shows while you're answering. For"
    " Languages › Japanese › Verbs, \"The deck and its parent\" shows"
    " Japanese › Verbs. \"Nothing\" keeps a deck's name from giving the"
    " answer away.",
    "deck_answer": "What the label shows once the answer is revealed.",
    "color_changes": "Off, the counter and the bar keep the normal color the"
    " whole time.",
    "deck_colors": "The color comes from the deck's name, so it stays the same"
    " until you rename the deck.",
    "keep_space": "Where one side shows the label and the other shows"
    " nothing, the label's space stays empty on that side, so the card doesn't"
    " move when you reveal the answer. Turn this off to let the card use the"
    " space.",
    "deck_rules": "Choose what the label shows on each side for particular"
    " decks and their subdecks. You can also right-click the label while"
    " reviewing.",
}


def _dim_color(widget: QWidget) -> str:
    """Text color for a grayed-out row: halfway to the window's background.
    Worked out here because the app's theme decides how (and whether)
    disabled text grays, and its palette grays are too dark on dark themes."""
    text, back = widget.palette().windowText().color(), widget.palette().window().color()
    return QColor(
        (text.red() + back.red()) // 2,
        (text.green() + back.green()) // 2,
        (text.blue() + back.blue()) // 2,
    ).name()


def _underline(widget: QWidget, left: int, right: int, center_y: int) -> None:
    """A fine dotted line just under a line of text centered on center_y."""
    metrics = widget.fontMetrics()
    y = min(center_y + metrics.height() // 2 + 1, widget.height() - 1)
    color = widget.palette().windowText().color()
    color.setAlpha(150)
    pen = QPen(color, 1)
    pen.setDashPattern([1, 2])
    painter = QPainter(widget)
    painter.setPen(pen)
    painter.drawLine(left, y, right, y)
    painter.end()


class _HelpLabel(QLabel):
    """A setting's name that explains itself, as in Anki's deck options: over
    it the cursor becomes a "?" and the words get a dotted underline. The
    explanation is its tooltip, which also shows at once on a click."""

    def __init__(self, text: str, explanation: str) -> None:
        super().__init__(text)
        # rich text, so Qt wraps long tooltips instead of one wide line
        self._tip = f"<p>{html.escape(explanation)}</p>"
        self._hovered = False
        self.setToolTip(self._tip)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._hovered:
            # under the words, not under a trailing colon
            words = self.text().rstrip(":")
            width = self.fontMetrics().horizontalAdvance(words)
            _underline(self, 0, width, self.rect().center().y())

    def mousePressEvent(self, event) -> None:
        QToolTip.showText(QCursor.pos(), self.toolTip(), self)


class _HelpCheck(QCheckBox):
    """A checkbox whose text explains itself the same way: over the words,
    a "?" cursor and a dotted underline, with the explanation as the tooltip.
    It stays an ordinary checkbox, so the theme draws and spaces it."""

    def __init__(self) -> None:
        super().__init__()
        self._over_words = False
        self.setMouseTracking(True)

    def explain(self, text: str, explanation: str) -> None:
        self.setText(text)
        self.setToolTip(f"<p>{html.escape(explanation)}</p>")

    def _words(self):
        """Where the theme puts the text, no wider than the text itself."""
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxContents, option, self
        )
        rect.setWidth(min(rect.width(), self.fontMetrics().horizontalAdvance(self.text())))
        return rect

    def _set_over(self, over: bool) -> None:
        if over == self._over_words:
            return
        self._over_words = over
        if over:
            self.setCursor(Qt.CursorShape.WhatsThisCursor)
        else:
            self.unsetCursor()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._set_over(self.isEnabled() and self._words().contains(event.pos()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_over(False)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._over_words:
            words = self._words()
            _underline(self, words.left(), words.right(), words.center().y())


class _ColorButton(QPushButton):
    """A button showing a color, which opens a color picker. Keeps the
    original CSS string until a new color is picked. An ordinary button with
    the color as its icon, so the theme draws it and lines it up with the
    other fields."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self.color = ""
        self.setIconSize(QSize(34, 14))
        self.clicked.connect(self._pick)

    def set_color(self, color: str) -> None:
        self.color = color
        self.setToolTip(color)
        # grayed out (while color changes are off) the color still shows,
        # faded toward the window's background
        shown, back = QColor(color), self.palette().window().color()
        faded = QColor(
            (shown.red() + back.red()) // 2,
            (shown.green() + back.green()) // 2,
            (shown.blue() + back.blue()) // 2,
        )
        icon = QIcon()
        for mode, fill in ((QIcon.Mode.Normal, shown), (QIcon.Mode.Disabled, faded)):
            pixmap = QPixmap(self.iconSize())
            pixmap.fill(fill)
            icon.addPixmap(pixmap, mode)
        self.setIcon(icon)

    def _pick(self) -> None:
        picked = QColorDialog.getColor(QColor(self.color), self, self._title)
        if picked.isValid():
            self.set_color(picked.name())


class _SortItem(QTableWidgetItem):
    """A cell that sorts by a key instead of its text, so "9.2s" comes before
    "18.9s"."""

    def __init__(self, text: str, key: Any) -> None:
        super().__init__(text)
        self.key = key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        return self.key < other.key


class _TargetTable(QDialog):
    """Each deck's target under the given settings, and where it comes from."""

    def __init__(
        self, parent: QWidget, rows: list[DeckRow], settings: dict[str, Any]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Target time by deck")
        self.setMinimumSize(760, 420)
        percentile = settings["pace_percentile"]
        intro = QLabel(
            "Based on the settings you've chosen, even if not saved yet.\n\n"
            f"Your pace: you were faster than this on {percentile}% of your"
            " recent answers in the deck. It counts only the deck's own cards,"
            f" not its subdecks', and needs {PACE_MIN_ANSWERS} answers.\n\n"
            'Auto Advance: the deck\'s "Seconds to show question for", which'
            " becomes the target time while Auto Advance is running."
        )
        intro.setWordWrap(True)

        self.table = QTableWidget(len(rows), 6)
        self.table.setHorizontalHeaderLabels(
            ["Deck", "Target time", "From", "Your pace", "Answers", "Auto Advance"]
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for i, (name, auto, pace, answers) in enumerate(rows):
            # the review screen's order, outside Auto Advance
            if settings["pace_target"] and pace:
                target, source = pace, "Your pace"
            else:
                target, source = float(settings["target_seconds"]), "Your setting"
            cells = [
                # shown as the rules window and the label show it; sorted by
                # the real name, so subdecks follow their parent
                (name.replace("::", " › "), name.lower(), None),
                (format_secs(target), target, right),
                (source, source, None),
                (format_secs(pace) if pace else "too few", pace or math.inf, right),
                (f"{answers:,}", answers, right),
                (format_secs(auto) if auto else "—", auto or math.inf, right),
            ]
            for column, (text, key, align) in enumerate(cells):
                item = _SortItem(text, key)
                if align:
                    item.setTextAlignment(align)
                if column == 0:
                    # in case a long name is cut short; escaped, as Qt reads
                    # a tooltip that looks like HTML as HTML
                    item.setToolTip(f"<span>{html.escape(text)}</span>")
                self.table.setItem(i, column, item)
        # enabled after filling, or rows would reorder while being added
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        if rows:
            layout.addWidget(self.table)
        else:
            layout.addWidget(QLabel("No decks yet."))
        layout.addWidget(buttons)


class _DeckRules(QDialog):
    """Edits `rules` in place: deck id as text -> a rule with an entry for
    each side ("question", "answer") it changes. An entry is "this" (just
    that deck's own name), "nothing", or "usual" (what the settings say,
    whatever a parent deck's rule says). Rules for decks not listed here,
    such as another profile's, are left alone. (Every profile's Default deck
    has the same id, so a rule on it is shared.)"""

    _SIDES = ("question", "answer")
    _VALUES = ("this", "nothing", "usual")

    def __init__(
        self,
        parent: QWidget,
        decks: list[tuple[str, str]],
        rules: dict[str, dict[str, str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Per-deck rules")
        self.setMinimumSize(760, 380)
        self._rules = rules
        self._paths = dict(decks)
        self._ids = {name: deck_id for deck_id, name in decks}
        self._names = {deck_id: name.replace("::", " › ") for deck_id, name in decks}
        intro = QLabel(
            "What the deck label shows for a deck and everything under it, new"
            " subdecks included. A subdeck with a rule of its own for a side"
            " follows that one instead. A deck's own name isn't shown while"
            " you're studying that deck, as it would only repeat what you picked."
        )
        intro.setWordWrap(True)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Deck", "Question side", "Answer side", ""]
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        # type to search, for collections with many decks
        self.picker = QComboBox()
        self.picker.setEditable(True)
        self.picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for deck_id, name in sorted(self._names.items(), key=lambda d: d[1].lower()):
            self.picker.addItem(name, deck_id)
        self.picker.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.picker.completer().setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.picker.setCurrentIndex(-1)
        self.picker.lineEdit().setPlaceholderText("Type or choose a deck…")
        add = QPushButton("Add rule")
        add.clicked.connect(self._add)
        add.setAutoDefault(False)
        self.picker.lineEdit().returnPressed.connect(self._add)
        adding = QHBoxLayout()
        adding.addWidget(self.picker, 1)
        adding.addWidget(add)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        # no default button: Enter in the picker adds the rule and nothing else
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        close.setAutoDefault(False)
        close.setDefault(False)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.table)
        layout.addLayout(adding)
        layout.addWidget(buttons)
        self._fill()

    def _parent_with_rule(self, deck_id: str, side: str) -> str | None:
        """The name of the closest parent deck whose rule for this side the
        deck would follow, or None when it would follow the settings."""
        parts = self._paths[deck_id].split("::")
        for depth in range(len(parts) - 1, 0, -1):
            rule = self._rules.get(self._ids.get("::".join(parts[:depth])))
            value = rule.get(side) if isinstance(rule, dict) else None
            if value in self._VALUES:
                return None if value == "usual" else parts[depth - 1]
        return None

    def _side_combo(self, deck_id: str, side: str) -> QComboBox:
        rule = self._rules[deck_id]
        own = _short(self._paths[deck_id].split("::")[-1])
        parent = self._parent_with_rule(deck_id, side)
        if parent:
            # no rule of its own means following the parent's; "usual" says
            # to follow the settings anyway
            items = [
                (f'Same as "{_short(parent)}"', None),
                ("Same as other decks", "usual"),
            ]
        else:
            # a "usual" left from when a parent had a rule comes to the same
            # thing, and shows as this entry
            items = [("Same as other decks", None)]
        items += [(f'Just "{own}"', "this"), ("Nothing", "nothing")]
        combo = _combo(items)
        _select(combo, rule.get(side))
        combo.currentIndexChanged.connect(
            lambda _, c=combo: self._set(deck_id, side, c.currentData())
        )
        return combo

    def _set(self, deck_id: str, side: str, value: str | None) -> None:
        if value:
            self._rules[deck_id][side] = value
        else:
            self._rules[deck_id].pop(side, None)
        # the choices for decks under this one depend on it; redrawn once
        # this choice's own signal has finished
        QTimer.singleShot(0, self._fill)

    def _fill(self) -> None:
        shown = sorted(
            (name, deck_id)
            for deck_id, name in self._names.items()
            if isinstance(self._rules.get(deck_id), dict)
        )
        self.table.setRowCount(len(shown))
        for row, (name, deck_id) in enumerate(shown):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            for column, side in enumerate(self._SIDES, start=1):
                self.table.setCellWidget(row, column, self._side_combo(deck_id, side))
            remove = QPushButton("Remove")
            remove.setAutoDefault(False)
            remove.clicked.connect(lambda _=False, d=deck_id: self._remove(d))
            self.table.setCellWidget(row, 3, remove)

    def _add(self) -> None:
        """Adds a rule for the deck typed or chosen: its name in any case, or
        part of it when only one deck matches."""
        text = self.picker.currentText().strip()
        index = self.picker.findText(text, Qt.MatchFlag.MatchFixedString)
        if index < 0 and text:
            matches = [
                i
                for i in range(self.picker.count())
                if text.lower() in self.picker.itemText(i).lower()
            ]
            if len(matches) == 1:
                index = matches[0]
        if index < 0:
            QToolTip.showText(
                self.picker.mapToGlobal(QPoint(0, self.picker.height())),
                "Choose a deck from the list.",
                self.picker,
            )
            return
        # the usual reason for a rule: the deck's subdecks give the answer away
        deck_id = self.picker.itemData(index)
        if not isinstance(self._rules.get(deck_id), dict):
            self._rules[deck_id] = {"question": "this"}
        self.picker.setCurrentIndex(-1)
        self._fill()

    def _remove(self, deck_id: str) -> None:
        self._rules.pop(deck_id, None)
        self._fill()


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        config: dict[str, Any],
        defaults: dict[str, Any],
        deck_targets: Callable[[int], list[DeckRow]],
        deck_list: Callable[[], list[tuple[str, str]]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Card Timer & Deck Label")
        self.setMinimumWidth(440)
        self._config = dict(config)
        self._defaults = defaults
        self._deck_targets = deck_targets
        self._deck_list = deck_list
        self._deck_rules: dict[str, dict[str, str]] = {}

        # target time
        self.target_seconds = _spin(1, 3600, " s")
        self.amber = _spin(10, 100, "%")
        self.pace = _HelpCheck()
        self.percentile = _spin(50, 99, "%")

        target = QFormLayout()
        target.addRow(_name("Target time:", _HELP["target"]), _row(self.target_seconds))
        target.addRow(
            _check(self.pace, "Use my pace in each deck instead", _HELP["pace"])
        )
        percentile_row = _row(self.percentile, suffix="of my recent answers")
        target.addRow(
            _name("Red when slower than:", _HELP["percentile"]), percentile_row
        )
        # only pace uses it
        self._pace_row = (target, percentile_row)
        self.pace.toggled.connect(self._pace_enabled)
        show_targets = QPushButton("Show each deck's target time…")
        show_targets.clicked.connect(self._show_target_table)
        target.addRow(_row(show_targets, tip=_HELP["targets_by_deck"]))

        # display
        self.show_counter = _combo(_SIDES)
        self.counter_position = _combo(_POSITIONS)
        self.font_size = _spin(12, 120, " px")
        self.last_time = _combo(_SIDES)
        self.bar = _HelpCheck()
        self.count_down = _HelpCheck()
        self.hide_builtin = _HelpCheck()

        display = QFormLayout()
        display.addRow(
            _name("Show counter:", _HELP["counter"]), _row(self.show_counter)
        )
        display.addRow(
            _name("Counter position:", _HELP["position"]),
            _row(self.counter_position),
        )
        display.addRow(_name("Counter size:", _HELP["size"]), _row(self.font_size))
        display.addRow(
            _name("Show last answer time:", _HELP["last_time"]), _row(self.last_time)
        )
        display.addRow(
            _check(self.bar, "Show a time bar along the top", _HELP["bar"])
        )
        count_down_row = _check(
            self.count_down, "Count down to the target time", _HELP["count_down"]
        )
        display.addRow(count_down_row)
        display.addRow(
            _check(
                self.hide_builtin,
                "Hide Anki's own timer in the bottom bar",
                _HELP["hide_builtin"],
            )
        )
        # counting down only changes the counter
        self._count_down_row = (display, count_down_row)
        self.show_counter.currentIndexChanged.connect(self._count_down_enabled)

        # colors
        self.color_normal = _ColorButton("Normal color")
        self.color_amber = _ColorButton("Near the target time")
        self.color_over = _ColorButton("Past the target time")
        self.color_changes = _HelpCheck()
        colors = QFormLayout()
        colors.addRow(
            _check(
                self.color_changes,
                "Change color near the target time",
                _HELP["color_changes"],
            )
        )
        amber_row = _row(self.amber, suffix="of the target time")
        colors.addRow(_name("Turn amber at:", _HELP["amber"]), amber_row)
        colors.addRow(_name("Normal:", _HELP["normal"]), _row(self.color_normal))
        near_row, past_row = _row(self.color_amber), _row(self.color_over)
        colors.addRow(_name("Near the target time:", _HELP["near"]), near_row)
        colors.addRow(_name("Past the target time:", _HELP["over"]), past_row)
        # the rows that do nothing while the color stays the same
        self._color_rows = [(colors, amber_row), (colors, near_row), (colors, past_row)]
        self.color_changes.toggled.connect(self._colors_enabled)

        # deck label
        self.show_deck = _combo(_DECK_MODES)
        self.deck_position = _combo(_DECK_POSITIONS)
        self.deck_question = _combo(_DECK_SHOWS)
        self.deck_answer = _combo(_DECK_SHOWS)
        self.deck_colors = _HelpCheck()
        self.keep_space = _HelpCheck()
        self.deck_rules_button = QPushButton()
        self.deck_rules_button.clicked.connect(self._show_deck_rules)
        self.show_deck.currentIndexChanged.connect(self._deck_enabled)
        deck = QFormLayout()
        deck.addRow(
            _name("Show deck label:", _HELP["show_deck"]), _row(self.show_deck)
        )
        # the rows that only matter while the label shows
        self._deck_rows = (deck, [
            (
                _name("Label position:", _HELP["deck_position"]),
                _row(self.deck_position),
            ),
            (
                _name("On the question side:", _HELP["deck_question"]),
                _row(self.deck_question),
            ),
            (
                _name("On the answer side:", _HELP["deck_answer"]),
                _row(self.deck_answer),
            ),
            (
                None,
                _check(
                    self.deck_colors,
                    "Give each deck its own color",
                    _HELP["deck_colors"],
                ),
            ),
            (
                None,
                _check(
                    self.keep_space,
                    "Keep the label's space when one side hides it",
                    _HELP["keep_space"],
                ),
            ),
            (None, _row(self.deck_rules_button, tip=_HELP["deck_rules"])),
        ])
        for name, row in self._deck_rows[1]:
            if name:
                deck.addRow(name, row)
            else:
                deck.addRow(row)

        # answer time
        self.pause_editing = _HelpCheck()
        answer_time = QFormLayout()
        answer_time.addRow(
            _check(
                self.pause_editing,
                "Pause the clock while I'm editing the card",
                _HELP["pause_editing"],
            )
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        # Cancel says what it does, so it doesn't ask first
        buttons.rejected.connect(self._discard)
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.setToolTip("Resets everything here except your per-deck rules.")
        # the rules are a list the user built, not a setting to reset
        restore.clicked.connect(lambda: self._load(
            {**self._config, **self._defaults, "deck_rules": self._deck_rules}))

        content = QWidget()
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(6)
        sections.addWidget(_group("Target time", target))
        sections.addWidget(_group("Display", display))
        sections.addWidget(_group("Colors", colors))
        sections.addWidget(_group("Deck label", deck))
        sections.addWidget(_group("Answer time", answer_time))
        sections.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

        # one width for the number boxes and one for the dropdowns, so the
        # fields and the text after them line up
        spins = (self.target_seconds, self.amber, self.percentile, self.font_size)
        combos = (
            self.show_counter, self.counter_position, self.last_time,
            self.show_deck, self.deck_position, self.deck_question, self.deck_answer,
        )
        for group in (spins, combos):
            width = max(widget.sizeHint().width() for widget in group)
            for widget in group:
                widget.setFixedWidth(width)
        # and one height for every row with a field, whatever kind it is
        fields = spins + combos + (self.color_normal, self.color_amber, self.color_over)
        height = max(widget.sizeHint().height() for widget in fields)
        for widget in fields:
            widget.parentWidget().setMinimumHeight(height)

        # line the fields up across sections
        labels = [
            item.widget()
            for form in (target, display, deck, colors)
            for row in range(form.rowCount())
            if (item := form.itemAt(row, QFormLayout.ItemRole.LabelRole))
        ]
        width = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setMinimumWidth(width)

        self._load(self._config)
        # as the window reads them back, so only a real change counts as one
        self._opened_with = self.config()
        self._scroll, self._buttons = scroll, buttons
        self._sized = False

    def reject(self) -> None:
        """Closing the window or pressing Esc, with changes not yet saved, asks
        what to do with them."""
        if self.config() == self._opened_with:
            self._discard()
            return
        buttons = QMessageBox.StandardButton
        ask = QMessageBox(self)
        ask.setWindowTitle(self.windowTitle())
        ask.setIcon(QMessageBox.Icon.Question)
        ask.setText("Save your changes?")
        ask.setStandardButtons(buttons.Save | buttons.Discard | buttons.Cancel)
        # not "Cancel": on the window itself that button discards the changes
        ask.button(buttons.Cancel).setText("Keep Editing")
        ask.setDefaultButton(buttons.Save)
        ask.setEscapeButton(buttons.Cancel)
        answer = ask.exec()
        ask.deleteLater()
        if answer == buttons.Save:
            self.accept()
        elif answer == buttons.Discard:
            self._discard()

    def _discard(self) -> None:
        super().reject()

    def showEvent(self, event) -> None:
        """As tall as it needs, up to what the screen has room for; beyond that
        the sections scroll, with the buttons still in view. Measured here, as
        rows report their full width only once shown; the window isn't on
        screen yet, so nothing visibly jumps."""
        super().showEvent(event)
        if self._sized:
            return
        self._sized = True
        layout, content = self.layout(), self._scroll.widget()
        width = content.sizeHint().width()
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        self._scroll.setMinimumWidth(width + bar)
        wanted = content.heightForWidth(width)
        if wanted < 0:
            wanted = content.sizeHint().height()
        margins = layout.contentsMargins()
        wanted += self._buttons.sizeHint().height() + layout.spacing()
        wanted += margins.top() + margins.bottom()
        screen = self.screen().availableGeometry()
        height = min(wanted, screen.height() - 60)  # 60 for the title bar
        self.resize(width + bar + margins.left() + margins.right(), height)
        # it was placed before its size was known, so keep it on screen
        bottom_y = screen.bottom() - height - 40
        self.move(self.x(), max(screen.top(), min(self.y(), bottom_y)))

    # Rows that only matter while another setting is on. Grayed out, each
    # says which setting that is.
    def _pace_enabled(self) -> None:
        _enable_row(
            *self._pace_row,
            self.pace.isChecked(),
            'Off while "Use my pace in each deck instead" is unchecked.',
        )

    def _count_down_enabled(self) -> None:
        on = self.show_counter.currentData() != "never"
        _enable_row(
            *self._count_down_row, on, 'Off while "Show counter" is set to Never.'
        )

    def _colors_enabled(self) -> None:
        on = self.color_changes.isChecked()
        for form, row in self._color_rows:
            _enable_row(
                form,
                row,
                on,
                'Off while "Change color near the target time" is unchecked.',
            )

    def _deck_enabled(self) -> None:
        on = self.show_deck.currentData() != "never"
        form, rows = self._deck_rows
        for _, row in rows:
            _enable_row(form, row, on, 'Off while "Show deck label" is set to Never.')

    def _name_rules_button(self) -> None:
        # rules for decks in this profile; another profile's stay out of sight
        count = sum(bool(self._deck_rules.get(d)) for d, _ in self._deck_list())
        self.deck_rules_button.setText(
            f"Per-deck rules ({count})…" if count else "Per-deck rules…"
        )

    def _show_deck_rules(self) -> None:
        dialog = _DeckRules(self, self._deck_list(), self._deck_rules)
        dialog.exec()
        dialog.deleteLater()
        self._name_rules_button()

    def _show_target_table(self) -> None:
        # uses the settings currently in the dialog, saved or not
        settings = self.config()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = self._deck_targets(settings["pace_percentile"])
        finally:
            QApplication.restoreOverrideCursor()
        dialog = _TargetTable(self, rows, settings)
        dialog.exec()
        dialog.deleteLater()

    def _load(self, c: dict[str, Any]) -> None:
        self.target_seconds.setValue(round(float(c["target_seconds"])))
        self.amber.setValue(round(float(c["amber_fraction"]) * 100))
        self.pace.setChecked(bool(c["pace_target"]))
        self.percentile.setValue(int(c["pace_percentile"]))
        self._pace_enabled()
        _select(self.show_counter, c["show_counter"])
        self._count_down_enabled()
        _select(self.counter_position, c["counter_position"])
        self.font_size.setValue(int(c["font_size_px"]))
        _select(self.last_time, c["show_last_time"])
        self.bar.setChecked(bool(c["show_progress_bar"]))
        self.count_down.setChecked(bool(c["count_down"]))
        self.hide_builtin.setChecked(bool(c["hide_builtin_timer"]))
        self.pause_editing.setChecked(bool(c["pause_while_editing"]))
        _select(self.show_deck, c["show_deck"])
        _select(self.deck_position, c["deck_position"])
        _select(self.deck_question, c["deck_question_shows"])
        _select(self.deck_answer, c["deck_answer_shows"])
        self.deck_colors.setChecked(bool(c["deck_colors"]))
        self.keep_space.setChecked(bool(c["deck_keep_space"]))
        # copied, so Cancel leaves the saved rules as they were
        self._deck_rules = {
            d: dict(r) for d, r in c["deck_rules"].items() if isinstance(r, dict)
        }
        self._name_rules_button()
        self._deck_enabled()
        self.color_changes.setChecked(bool(c["color_changes"]))
        self._colors_enabled()
        self.color_normal.set_color(c["color_normal"])
        self.color_amber.set_color(c["color_amber"])
        self.color_over.set_color(c["color_over"])

    def config(self) -> dict[str, Any]:
        return {
            **self._config,
            "target_seconds": self.target_seconds.value(),
            "amber_fraction": self.amber.value() / 100,
            "pace_target": self.pace.isChecked(),
            "pace_percentile": self.percentile.value(),
            "show_counter": self.show_counter.currentData(),
            "counter_position": self.counter_position.currentData(),
            "font_size_px": self.font_size.value(),
            "show_last_time": self.last_time.currentData(),
            "show_progress_bar": self.bar.isChecked(),
            "count_down": self.count_down.isChecked(),
            "hide_builtin_timer": self.hide_builtin.isChecked(),
            "pause_while_editing": self.pause_editing.isChecked(),
            "show_deck": self.show_deck.currentData(),
            "deck_position": self.deck_position.currentData(),
            "deck_question_shows": self.deck_question.currentData(),
            "deck_answer_shows": self.deck_answer.currentData(),
            "deck_colors": self.deck_colors.isChecked(),
            "deck_keep_space": self.keep_space.isChecked(),
            # a rule left with nothing in it is no rule
            "deck_rules": {d: dict(r) for d, r in self._deck_rules.items() if r},
            "color_changes": self.color_changes.isChecked(),
            "color_normal": self.color_normal.color,
            "color_amber": self.color_amber.color,
            "color_over": self.color_over.color,
        }


def format_secs(seconds: float) -> str:
    """18.86 -> "18.9s", 15.0 -> "15s"."""
    return f"{seconds:.1f}".rstrip("0").rstrip(".") + "s"


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _spin(low: int, high: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setSuffix(suffix)
    return spin


def _combo(items: list[tuple[str, Any]]) -> QComboBox:
    combo = QComboBox()
    for label, value in items:
        combo.addItem(label, value)
    return combo


def _select(combo: QComboBox, value: Any) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(max(index, 0))


def _row(widget: QWidget, suffix: str = "", tip: str = "") -> QWidget:
    """The field and any trailing text, kept to the left. `tip` is for a
    button, which shows its explanation as an ordinary tooltip."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)
    if suffix:
        layout.addWidget(QLabel(suffix))
    if tip:
        widget.setToolTip(f"<p>{html.escape(tip)}</p>")
    layout.addStretch()
    return row


def _name(text: str, explanation: str) -> QWidget:
    """A row's name for the left column, which explains itself on hover."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    box.help_label = _HelpLabel(text, explanation)
    layout.addWidget(box.help_label)
    layout.addStretch()
    return box


def _check(box: _HelpCheck, text: str, explanation: str) -> QWidget:
    """A row for a checkbox whose text explains itself on hover."""
    box.explain(text, explanation)
    return _row(box)


def _enable_row(form: QFormLayout, row: QWidget, on: bool, why_off: str = "") -> None:
    """Grays out a row, its name included. Text is dimmed by color, so it
    looks the same in every theme and a name can still explain itself. While
    it's off, its explanation ends with why_off."""
    widgets = [form.labelForField(row)]
    widgets += [row.layout().itemAt(i).widget() for i in range(row.layout().count())]
    for widget in widgets:
        if widget is None:
            continue
        widget = getattr(widget, "help_label", widget)
        if widget.toolTip():
            # the explanation as written, kept so the reason can come and go
            if not hasattr(widget, "base_tip"):
                widget.base_tip = widget.toolTip()
            reason = f"<p><i>{html.escape(why_off)}</i></p>" if why_off and not on else ""
            widget.setToolTip(widget.base_tip + reason)
        if isinstance(widget, QLabel):
            # by a property of this label alone: a plain "color:" would also
            # gray the label's tooltip, which takes its style from the label
            widget.setProperty("ptDim", not on)
            widget.setStyleSheet(
                f'QLabel[ptDim="true"] {{ color: {_dim_color(widget)}; }}'
            )
        else:
            widget.setEnabled(on)


def _group(title: str, form: QFormLayout) -> QGroupBox:
    # left-aligned, rather than the centered macOS default
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    # the same compact spacing on every platform and theme
    form.setVerticalSpacing(4)
    box = QGroupBox(title)
    # wrapped text sits outside the form: QFormLayout under-sizes wrapped labels
    layout = QVBoxLayout(box)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(6)
    layout.addLayout(form)
    return box
