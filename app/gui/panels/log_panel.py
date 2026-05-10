from __future__ import annotations

from collections import deque
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class LogPanel(QWidget):
    COLORS = {'INFO': '#9caec8', 'MARKET': '#8aa8d8', 'ORDER': '#fbbf24', 'FILL': '#22d3ee', 'FSM': '#c4b5fd', 'RISK': '#fbbf24', 'ERROR': '#f87171', 'BALANCE': '#93c5fd', 'SUCCESS': '#4ade80', 'WARN': '#fbbf24'}

    def __init__(self, max_lines: int = 500, parent=None) -> None:
        super().__init__(parent)
        self.max_lines = max_lines
        self._lines = deque(maxlen=max_lines)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFont(QFont('Consolas', 10))
        self.text.setMaximumBlockCount(max(1000, max_lines))
        self._collapsed = False
        self._compact_mode = True
        self._visible_limit = min(1000, max_lines)
        self._compact_tags = ('[BUY]', '[SELL]', '[TRADE]', '[PNL]', '[RISK]', '[ERROR]', '[DATA]', '[BOOT]')
        self._compact_excluded_fragments = (
            '[live] tick before',
            '[live] tick after',
        )
        self._queue = deque()
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(350)
        self._flush_timer.timeout.connect(self._flush_queue)
        self._flush_timer.start()
        header = QHBoxLayout()
        self.toggle_btn = QPushButton('Hide Logs')
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        self.compact_btn = QPushButton('Compact: ON')
        self.compact_btn.clicked.connect(self.toggle_compact_mode)
        self.clear_btn = QPushButton('Clear Logs')
        self.clear_btn.clicked.connect(self.clear)
        self.open_folder_btn = QPushButton('Open Log Folder')
        self.open_folder_btn.clicked.connect(self.open_log_folder)
        header.addWidget(self.toggle_btn)
        header.addWidget(self.compact_btn)
        header.addWidget(self.clear_btn)
        header.addWidget(self.open_folder_btn)
        header.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.text)

    def append_record(self, rec) -> None:
        line = f"[{rec.ts}] [{rec.level}] {rec.message}"
        self._lines.append(line)
        self._queue.append(line)

    def _flush_queue(self) -> None:
        if self._collapsed or not self._queue:
            return
        scrollbar = self.text.verticalScrollBar()
        auto_scroll = scrollbar.value() >= scrollbar.maximum() - 2
        flushed = 0
        while self._queue and flushed < 100:
            line = self._queue.popleft()
            if self._compact_mode:
                lower = line.lower()
                if not any(tag in line for tag in self._compact_tags):
                    continue
                if any(fragment in lower for fragment in self._compact_excluded_fragments):
                    continue
            self.text.appendPlainText(line)
            flushed += 1
        if auto_scroll:
            scrollbar.setValue(scrollbar.maximum())

    def clear(self) -> None:
        self._lines.clear()
        self._queue.clear()
        self.text.clear()

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.text.setVisible(not self._collapsed)
        self.toggle_btn.setText('Show Logs' if self._collapsed else 'Hide Logs')
        if not self._collapsed:
            self.text.clear()
            for line in list(self._lines)[-self._visible_limit:]:
                if self._compact_mode:
                    lower = line.lower()
                    if not any(tag in line for tag in self._compact_tags):
                        continue
                    if any(fragment in lower for fragment in self._compact_excluded_fragments):
                        continue
                self.text.appendPlainText(line)

    def toggle_compact_mode(self) -> None:
        self._compact_mode = not self._compact_mode
        self.compact_btn.setText(f"Compact: {'ON' if self._compact_mode else 'OFF'}")
        self.toggle_collapsed()
        self.toggle_collapsed()

    def open_log_folder(self) -> None:
        path = Path('logs').resolve()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
