from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, on_save, on_test_connection, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setModal(False)
        self._on_save = on_save
        self._on_test_connection = on_test_connection

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.api_key = QLineEdit(cfg.get('api_key', ''))
        self.api_secret = QLineEdit(cfg.get('api_secret', ''))
        self.api_secret.setEchoMode(QLineEdit.Password)
        self.testnet = QCheckBox()
        self.testnet.setChecked(bool(cfg.get('testnet', False)))
        self.read_only = QCheckBox()
        self.read_only.setChecked(bool(cfg.get('read_only', True)))
        self.trading_enabled = QCheckBox()
        self.trading_enabled.setChecked(bool(cfg.get('trading_enabled', False)))

        form.addRow('API Key', self.api_key)
        form.addRow('API Secret', self.api_secret)
        form.addRow('Testnet', self.testnet)
        form.addRow('Read Only', self.read_only)
        form.addRow('Trading Enabled', self.trading_enabled)
        root.addLayout(form)

        self.status = QLabel('')
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        save_btn = QPushButton('Save')
        test_btn = QPushButton('Test Connection')
        close_btn = QPushButton('Close')
        save_btn.clicked.connect(self._save)
        test_btn.clicked.connect(self._test_connection)
        close_btn.clicked.connect(self.close)
        buttons.addWidget(save_btn)
        buttons.addWidget(test_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def values(self) -> dict:
        return {
            'api_key': self.api_key.text().strip(),
            'api_secret': self.api_secret.text().strip(),
            'testnet': self.testnet.isChecked(),
            'read_only': self.read_only.isChecked(),
            'trading_enabled': self.trading_enabled.isChecked(),
        }

    def _save(self) -> None:
        self._on_save(self.values())
        self.status.setText('Saved')

    def _test_connection(self) -> None:
        ok, message = self._on_test_connection(self.values())
        self.status.setText(message)
        if ok:
            self._on_save(self.values())
