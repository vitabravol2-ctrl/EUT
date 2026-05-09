from __future__ import annotations

from collections import deque

from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class LogPanel(QWidget):
    COLORS = {
        'INFO': '#8ab4f8',
        'MARKET': '#6ee7b7',
        'ORDER': '#fbbf24',
        'FILL': '#22d3ee',
        'FSM': '#c4b5fd',
        'RISK': '#fb7185',
        'ERROR': '#f87171',
        'BALANCE': '#93c5fd',
    }

    def __init__(self, max_lines: int = 500, parent=None) -> None:
        super().__init__(parent)
        self.max_lines = max_lines
        self._lines = deque(maxlen=max_lines)
        self.text = QTextEdit(self)
        self.text.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)

    def append_record(self, rec) -> None:
        scrollbar = self.text.verticalScrollBar()
        auto_scroll = scrollbar.value() >= scrollbar.maximum() - 2
        color = self.COLORS.get(rec.level, '#e5e5e5')
        line = f"<span style='color:{color}'>[{rec.ts}] [{rec.level}] {rec.message}</span>"
        self._lines.append(line)
        self.text.setHtml('<br/>'.join(self._lines))
        if auto_scroll:
            scrollbar.setValue(scrollbar.maximum())
