from __future__ import annotations

from collections import deque

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget


class LogPanel(QWidget):
    COLORS = {'INFO': '#9caec8', 'MARKET': '#8aa8d8', 'ORDER': '#fbbf24', 'FILL': '#22d3ee', 'FSM': '#c4b5fd', 'RISK': '#fbbf24', 'ERROR': '#f87171', 'BALANCE': '#93c5fd', 'SUCCESS': '#4ade80', 'WARN': '#fbbf24'}

    def __init__(self, max_lines: int = 500, parent=None) -> None:
        super().__init__(parent)
        self.max_lines = max_lines
        self._lines = deque(maxlen=max_lines)
        self.text = QTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFont(QFont('Consolas', 10))
        self._collapsed = False
        self._compact_mode = True
        self._visible_limit = min(200, max_lines)
        header = QHBoxLayout()
        self.toggle_btn = QPushButton('Hide Logs')
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        self.compact_btn = QPushButton('Compact: ON')
        self.compact_btn.clicked.connect(self.toggle_compact_mode)
        header.addWidget(self.toggle_btn)
        header.addWidget(self.compact_btn)
        header.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.text)

    def append_record(self, rec) -> None:
        scrollbar = self.text.verticalScrollBar()
        auto_scroll = scrollbar.value() >= scrollbar.maximum() - 2
        color = self.COLORS.get(rec.level, '#e5e5e5')
        line = f"<span style='color:{color}'>[{rec.ts}] [{rec.level}] {rec.message}</span>"
        self._lines.append(line)
        if not self._collapsed:
            if self._compact_mode:
                self.text.moveCursor(QTextCursor.End)
                self.text.insertHtml(line + '<br/>')
                if self.text.document().blockCount() > self._visible_limit:
                    self.text.setHtml('<br/>'.join(list(self._lines)[-self._visible_limit:]))
            else:
                self.text.setHtml('<br/>'.join(self._lines))
            if auto_scroll:
                scrollbar.setValue(scrollbar.maximum())

    def clear(self) -> None:
        self._lines.clear()
        self.text.clear()

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.text.setVisible(not self._collapsed)
        self.toggle_btn.setText('Show Logs' if self._collapsed else 'Hide Logs')
        if not self._collapsed:
            self.text.setHtml('<br/>'.join(list(self._lines)[-self._visible_limit:]))

    def toggle_compact_mode(self) -> None:
        self._compact_mode = not self._compact_mode
        self.compact_btn.setText(f"Compact: {'ON' if self._compact_mode else 'OFF'}")
