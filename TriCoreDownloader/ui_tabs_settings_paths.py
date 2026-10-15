import os
import sys
import platform
import subprocess
import re
from pathlib import Path

import requests
import urllib3
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QDialog, QStyle,
    QFileDialog, QInputDialog, QApplication, QSizePolicy
)
from PyQt6.QtCore import Qt, QUrl, QEventLoop
from PyQt6.QtGui import QDesktopServices, QColor, QPalette

from .custom_widgets import ClickableLineEdit
from .config import save_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _is_dialog_light_mode(main_win) -> bool:
    if main_win and hasattr(main_win, "config"):
        th = str(main_win.config.get("theme", "dark")).lower()
        if th == "light":
            return True
        if th == "auto":
            if hasattr(main_win, "get_effective_is_dark"):
                return not bool(main_win.get_effective_is_dark())
            try:
                import darkdetect
                if darkdetect and not darkdetect.isDark():
                    return True
            except Exception:
                pass
    return False


def _center_dialog_on_window(dlg: QDialog, main_win, use_frame_geo: bool = False):
    if not main_win or not hasattr(main_win, "frameGeometry"):
        return
    win_geo = main_win.frameGeometry()
    size_ref = dlg.frameGeometry() if use_frame_geo else dlg.sizeHint()
    x = win_geo.x() + (win_geo.width() - size_ref.width()) // 2
    y = win_geo.y() + (win_geo.height() - size_ref.height()) // 2
    if sys.platform == "darwin":
        y = max(win_geo.y() + 28, y)
    dlg.move(x, y)


class PathMessageDialog(QDialog):
    def __init__(self, title, text, icon_pixmap=QStyle.StandardPixmap.SP_MessageBoxInformation, parent=None):
        self.main_win = parent.window() if (parent and hasattr(parent, "window") and parent.window()) else parent
        if not self.main_win:
            self.main_win = QApplication.activeWindow()
        super().__init__(self.main_win)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(460)
        self._already_centered = False

        is_light = _is_dialog_light_mode(self.main_win)
        link_color = "#0066CC" if is_light else "#FFFFFF"

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Link, QColor(link_color))
        pal.setColor(QPalette.ColorRole.LinkVisited, QColor(link_color))
        self.setPalette(pal)

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_lbl = QLabel(self)
        pm = self.style().standardIcon(icon_pixmap)
        icon_lbl.setPixmap(pm.pixmap(48, 48))
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        content_layout.addWidget(icon_lbl)

        lbl_msg = QLabel(self)
        lbl_msg.setPalette(pal)
        lbl_msg.setFixedWidth(356)
        lbl_msg.setWordWrap(True)
        lbl_msg.setOpenExternalLinks(True)
        lbl_msg.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        processed_text = text
        if "<a" in processed_text.lower():
            processed_text = re.sub(r'style=(["\'])color:[^"\']*\1', '', processed_text)
            processed_text = re.sub(
                r'<a\s+',
                f'<a style="color: {link_color}; text-decoration: underline;" ',
                processed_text,
                flags=re.IGNORECASE
            )
        elif "http://" in processed_text or "https://" in processed_text:
            processed_text = re.sub(
                r'(https?://[^\s<>"]+)',
                f'<a href="\\1" style="color: {link_color}; text-decoration: underline;">\\1</a>',
                processed_text
            )
        lbl_msg.setText(processed_text)
        lbl_msg.setStyleSheet(f"font-size: 10pt; line-height: 1.35; color: {'#1D1D1F' if is_light else '#E8E8E8'};")
        content_layout.addWidget(lbl_msg)

        layout.addLayout(content_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 4, 0, 0)
        btn_layout.addStretch()

        btn_ok = QPushButton("OK", self)
        btn_ok.setFixedSize(80, 32)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)

        layout.addLayout(btn_layout)
        _center_dialog_on_window(self, self.main_win, use_frame_geo=False)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._already_centered:
            self._already_centered = True
            _center_dialog_on_window(self, self.main_win, use_frame_geo=True)


class HactoolIntroDialog(QDialog):
    def __init__(self, title, html_text, parent=None, open_link_cb=None):
        self.main_win = parent.window() if (parent and hasattr(parent, "window") and parent.window()) else parent
        if not self.main_win:
            self.main_win = QApplication.activeWindow()
        super().__init__(self.main_win)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(640)
        self.choice = "cancel"
        self._already_centered = False

        is_light = _is_dialog_light_mode(self.main_win)
        link_color = "#0066CC" if is_light else "#FFFFFF"

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Link, QColor(link_color))
        pal.setColor(QPalette.ColorRole.LinkVisited, QColor(link_color))
        self.setPalette(pal)

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_lbl = QLabel(self)
        pm = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        icon_lbl.setPixmap(pm.pixmap(48, 48))
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        content_layout.addWidget(icon_lbl)

        lbl = QLabel(self)
        lbl.setPalette(pal)
        lbl.setFixedWidth(536)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        processed_html = html_text
        if "<a" in processed_html.lower():
            processed_html = re.sub(r'style=(["\'])color:[^"\']*\1', '', processed_html)
            processed_html = re.sub(
                r'<a\s+',
                f'<a style="color: {link_color}; text-decoration: underline;" ',
                processed_html,
                flags=re.IGNORECASE
            )
        lbl.setText(processed_html)
        lbl.setStyleSheet(f"font-size: 10pt; line-height: 1.35; color: {'#1D1D1F' if is_light else '#E8E8E8'};")
        if open_link_cb:
            lbl.linkActivated.connect(open_link_cb)
        content_layout.addWidget(lbl)

        layout.addLayout(content_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.setSpacing(8)

        tr_obj = self.main_win if (self.main_win and hasattr(self.main_win, "T")) else self
        btn_dl_txt = tr_obj.T("btn_hactool_auto_dl") if hasattr(tr_obj, "T") else "Télécharger automatiquement"
        btn_br_txt = tr_obj.T("btn_hactool_open_browser") if hasattr(tr_obj, "T") else "Ouvrir dans le navigateur"
        btn_cancel_txt = tr_obj.T("btn_cancel") if hasattr(tr_obj, "T") else "Annuler"

        self.btn_dl = QPushButton(btn_dl_txt, self)
        self.btn_dl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dl.clicked.connect(self._choose_dl)

        self.btn_browser = QPushButton(btn_br_txt, self)
        self.btn_browser.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browser.clicked.connect(self._choose_browser)

        self.btn_cancel = QPushButton(btn_cancel_txt, self)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_dl)
        btn_layout.addWidget(self.btn_browser)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        _center_dialog_on_window(self, self.main_win, use_frame_geo=False)

    def _choose_dl(self):
        self.choice = "download"
        self.accept()

    def _choose_browser(self):
        self.choice = "browser"
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._already_centered:
            self._already_centered = True
            _center_dialog_on_window(self, self.main_win, use_frame_geo=True)


class HactoolExistsDialog(QDialog):
    def __init__(self, title, text, parent=None):
        self.main_win = parent.window() if (parent and hasattr(parent, "window") and parent.window()) else parent
        if not self.main_win:
            self.main_win = QApplication.activeWindow()
        super().__init__(self.main_win)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(480)
        self.choice = "cancel"
        self._already_centered = False

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_lbl = QLabel(self)
        pm = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion)
        icon_lbl.setPixmap(pm.pixmap(48, 48))
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        content_layout.addWidget(icon_lbl)

        lbl = QLabel(text, self)
        lbl.setFixedWidth(376)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet("font-size: 10pt; line-height: 1.35;")
        content_layout.addWidget(lbl)

        layout.addLayout(content_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.setSpacing(8)

        tr_obj = self.main_win if (self.main_win and hasattr(self.main_win, "T")) else self
        btn_use_txt = tr_obj.T("btn_hactool_use_existing") if hasattr(tr_obj, "T") else "Utiliser l'existant"
        btn_rep_txt = tr_obj.T("btn_hactool_replace") if hasattr(tr_obj, "T") else "Remplacer"
        btn_cancel_txt = tr_obj.T("btn_cancel") if hasattr(tr_obj, "T") else "Annuler"

        self.btn_use = QPushButton(btn_use_txt, self)
        self.btn_use.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_use.clicked.connect(self._choose_use)

        self.btn_replace = QPushButton(btn_rep_txt, self)
        self.btn_replace.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_replace.clicked.connect(self._choose_replace)

        self.btn_cancel = QPushButton(btn_cancel_txt, self)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_use)
        btn_layout.addWidget(self.btn_replace)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        _center_dialog_on_window(self, self.main_win, use_frame_geo=False)

    def _choose_use(self):
        self.choice = "use"
        self.accept()

    def _choose_replace(self):
        self.choice = "replace"
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._already_centered:
            self._already_centered = True
            _center_dialog_on_window(self, self.main_win, use_frame_geo=True)


class UiTabsSettingsPathsMixin:
    def setup_paths_section(self, parent_layout):
        self.grp_paths = QFrame()
        self.grp_paths.setObjectName("Card")

        layout_paths = QVBoxLayout(self.grp_paths)
        layout_paths.setContentsMargins(20, 20, 20, 20)
        layout_paths.setSpacing(12)

        self.lbl_grp_paths_title = QLabel(self.T("grp_crypto"))
        self.lbl_grp_paths_title.setObjectName("CardTitle")
        layout_paths.addWidget(self.lbl_grp_paths_title)
        layout_paths.addSpacing(4)

        self.paths_stack = QStackedWidget()
        self.paths_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        LABEL_COL_WIDTH = 170

        self.page_nx = QWidget()
        grid_nx = QGridLayout(self.page_nx)
        grid_nx.setContentsMargins(0, 0, 0, 0)
        grid_nx.setSpacing(12)
        grid_nx.setColumnMinimumWidth(0, LABEL_COL_WIDTH)
        grid_nx.setColumnStretch(0, 0)
        grid_nx.setColumnStretch(1, 1)
        grid_nx.setColumnMinimumWidth(2, 90)
        grid_nx.setColumnStretch(2, 0)
        grid_nx.setColumnMinimumWidth(3, 90)
        grid_nx.setColumnStretch(3, 0)
        grid_nx.setColumnMinimumWidth(4, 36)
        grid_nx.setColumnStretch(4, 0)

        self.lbl_hactool = QLabel(self.T("lbl_hactool"))
        self.input_hactool = ClickableLineEdit()
        self.input_hactool.setMinimumHeight(36)

        self.btn_browse_hactool = QPushButton(self.T("btn_browse"))
        self.btn_browse_hactool.setFixedSize(90, 36)
        self.btn_browse_hactool.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_auto_hactool = QPushButton(self.T("btn_auto"))
        self.btn_auto_hactool.setFixedSize(90, 36)
        self.btn_auto_hactool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auto_hactool.setToolTip(self.T("tooltip_hactool_auto"))

        self.btn_help_hactool = QPushButton("?")
        self.btn_help_hactool.setFixedSize(36, 36)
        self.btn_help_hactool.setStyleSheet("padding: 0px; font-weight: bold; font-size: 11pt;")
        self.btn_help_hactool.setCursor(Qt.CursorShape.PointingHandCursor)

        grid_nx.addWidget(self.lbl_hactool, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        grid_nx.addWidget(self.input_hactool, 0, 1)
        grid_nx.addWidget(self.btn_browse_hactool, 0, 2)
        grid_nx.addWidget(self.btn_auto_hactool, 0, 3)
        grid_nx.addWidget(self.btn_help_hactool, 0, 4)

        self.lbl_keys = QLabel(self.T("lbl_keys"))
        self.input_keys = ClickableLineEdit()
        self.input_keys.setMinimumHeight(36)

        self.btn_browse_keys = QPushButton(self.T("btn_browse"))
        self.btn_browse_keys.setFixedSize(192, 36)
        self.btn_browse_keys.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_help_keys = QPushButton("?")
        self.btn_help_keys.setFixedSize(36, 36)
        self.btn_help_keys.setStyleSheet("padding: 0px; font-weight: bold; font-size: 11pt;")
        self.btn_help_keys.setCursor(Qt.CursorShape.PointingHandCursor)

        grid_nx.addWidget(self.lbl_keys, 1, 0, Qt.AlignmentFlag.AlignVCenter)
        grid_nx.addWidget(self.input_keys, 1, 1)
        grid_nx.addWidget(self.btn_browse_keys, 1, 2, 1, 2)
        grid_nx.addWidget(self.btn_help_keys, 1, 4)

        self.lbl_prodinfo = QLabel(self.T("lbl_prodinfo"))
        self.input_prodinfo = ClickableLineEdit()
        self.input_prodinfo.setMinimumHeight(36)

        self.btn_browse_prodinfo = QPushButton(self.T("btn_browse"))
        self.btn_browse_prodinfo.setFixedSize(192, 36)
        self.btn_browse_prodinfo.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_help_prodinfo = QPushButton("?")
        self.btn_help_prodinfo.setFixedSize(36, 36)
        self.btn_help_prodinfo.setStyleSheet("padding: 0px; font-weight: bold; font-size: 11pt;")
        self.btn_help_prodinfo.setCursor(Qt.CursorShape.PointingHandCursor)

        grid_nx.addWidget(self.lbl_prodinfo, 2, 0, Qt.AlignmentFlag.AlignVCenter)
        grid_nx.addWidget(self.input_prodinfo, 2, 1)
        grid_nx.addWidget(self.btn_browse_prodinfo, 2, 2, 1, 2)
        grid_nx.addWidget(self.btn_help_prodinfo, 2, 4)

        self.paths_stack.addWidget(self.page_nx)

        self.page_ctr = QWidget()
        grid_ctr = QGridLayout(self.page_ctr)
        grid_ctr.setContentsMargins(0, 0, 0, 0)
        grid_ctr.setSpacing(12)
        grid_ctr.setColumnMinimumWidth(0, LABEL_COL_WIDTH)
        grid_ctr.setColumnStretch(0, 0)
        grid_ctr.setColumnStretch(1, 1)
        grid_ctr.setColumnMinimumWidth(2, 90)
        grid_ctr.setColumnStretch(2, 0)
        grid_ctr.setColumnMinimumWidth(3, 90)
        grid_ctr.setColumnStretch(3, 0)
        grid_ctr.setColumnMinimumWidth(4, 36)
        grid_ctr.setColumnStretch(4, 0)

        self.lbl_boot9 = QLabel(self.T("lbl_boot9"))
        self.input_boot9 = ClickableLineEdit()
        self.input_boot9.setMinimumHeight(36)
        self.input_boot9.setPlaceholderText(self.T("ctr_hint_boot9"))

        self.btn_browse_boot9 = QPushButton(self.T("btn_browse"))
        self.btn_browse_boot9.setFixedSize(192, 36)
        self.btn_browse_boot9.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_help_boot9 = QPushButton("?")
        self.btn_help_boot9.setFixedSize(36, 36)
        self.btn_help_boot9.setStyleSheet("padding: 0px; font-weight: bold; font-size: 11pt;")
        self.btn_help_boot9.setCursor(Qt.CursorShape.PointingHandCursor)

        grid_ctr.addWidget(self.lbl_boot9, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        grid_ctr.addWidget(self.input_boot9, 0, 1)
        grid_ctr.addWidget(self.btn_browse_boot9, 0, 2, 1, 2)
        grid_ctr.addWidget(self.btn_help_boot9, 0, 4)

        self.paths_stack.addWidget(self.page_ctr)

        self.page_cafe = QWidget()
        grid_cafe = QGridLayout(self.page_cafe)
        grid_cafe.setContentsMargins(0, 0, 0, 0)
        grid_cafe.setSpacing(12)
        grid_cafe.setColumnMinimumWidth(0, LABEL_COL_WIDTH)
        grid_cafe.setColumnStretch(0, 0)
        grid_cafe.setColumnStretch(1, 1)
        grid_cafe.setColumnMinimumWidth(2, 90)
        grid_cafe.setColumnStretch(2, 0)
        grid_cafe.setColumnMinimumWidth(3, 90)
        grid_cafe.setColumnStretch(3, 0)
        grid_cafe.setColumnMinimumWidth(4, 36)
        grid_cafe.setColumnStretch(4, 0)

        self.lbl_otp = QLabel(self.T("lbl_otp"))
        self.input_otp = ClickableLineEdit()
        self.input_otp.setMinimumHeight(36)

        self.btn_browse_otp = QPushButton(self.T("btn_browse"))
        self.btn_browse_otp.setFixedSize(192, 36)
        self.btn_browse_otp.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_help_otp = QPushButton("?")
        self.btn_help_otp.setFixedSize(36, 36)
        self.btn_help_otp.setStyleSheet("padding: 0px; font-weight: bold; font-size: 11pt;")
        self.btn_help_otp.setCursor(Qt.CursorShape.PointingHandCursor)

        grid_cafe.addWidget(self.lbl_otp, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        grid_cafe.addWidget(self.input_otp, 0, 1)
        grid_cafe.addWidget(self.btn_browse_otp, 0, 2, 1, 2)
        grid_cafe.addWidget(self.btn_help_otp, 0, 4)

        self.paths_stack.addWidget(self.page_cafe)
        layout_paths.addWidget(self.paths_stack)

        grid_out = QGridLayout()
        grid_out.setContentsMargins(0, 0, 0, 0)
        grid_out.setSpacing(12)
        grid_out.setColumnMinimumWidth(0, LABEL_COL_WIDTH)
        grid_out.setColumnStretch(0, 0)
        grid_out.setColumnStretch(1, 1)
        grid_out.setColumnMinimumWidth(2, 114)
        grid_out.setColumnStretch(2, 0)
        grid_out.setColumnMinimumWidth(3, 114)
        grid_out.setColumnStretch(3, 0)

        self.lbl_out = QLabel(self.T("lbl_out"))
        self.input_output = ClickableLineEdit()
        self.input_output.setMinimumHeight(36)

        self.btn_browse_out = QPushButton(self.T("btn_browse"))
        self.btn_browse_out.setFixedSize(114, 36)
        self.btn_browse_out.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_suggest = QPushButton(self.T("btn_suggest"))
        self.btn_suggest.setFixedSize(114, 36)
        self.btn_suggest.setCursor(Qt.CursorShape.PointingHandCursor)

        grid_out.addWidget(self.lbl_out, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        grid_out.addWidget(self.input_output, 0, 1)
        grid_out.addWidget(self.btn_browse_out, 0, 2)
        grid_out.addWidget(self.btn_suggest, 0, 3)

        layout_paths.addLayout(grid_out)
        parent_layout.addWidget(self.grp_paths)

        self.browse_buttons = [
            self.btn_browse_hactool, self.btn_browse_keys, self.btn_browse_prodinfo,
            self.btn_browse_boot9, self.btn_browse_otp, self.btn_browse_out
        ]

        self.labels_config = {
            "hactool": self.lbl_hactool,
            "keys": self.lbl_keys,
            "prodinfo": self.lbl_prodinfo,
            "boot9": self.lbl_boot9,
            "otp": self.lbl_otp,
            "out": self.lbl_out
        }

        hactool_exec = "hactool.exe" if sys.platform == "win32" else "hactool"

        self.input_hactool.clicked.connect(lambda: self.browse_file(self.input_hactool, hactool_exec))
        self.btn_browse_hactool.clicked.connect(lambda: self.browse_file(self.input_hactool, hactool_exec))
        self.btn_auto_hactool.clicked.connect(self.auto_download_hactool)

        self.input_keys.clicked.connect(lambda: self.browse_file(self.input_keys, "prod.keys"))
        self.btn_browse_keys.clicked.connect(lambda: self.browse_file(self.input_keys, "prod.keys"))

        self.input_prodinfo.clicked.connect(lambda: self.browse_file(self.input_prodinfo, "PRODINFO.bin"))
        self.btn_browse_prodinfo.clicked.connect(lambda: self.browse_file(self.input_prodinfo, "PRODINFO.bin"))

        self.input_boot9.clicked.connect(lambda: self.browse_file(self.input_boot9, "boot9.bin"))
        self.btn_browse_boot9.clicked.connect(lambda: self.browse_file(self.input_boot9, "boot9.bin"))

        self.input_otp.clicked.connect(lambda: self.browse_file(self.input_otp, "otp.bin"))
        self.btn_browse_otp.clicked.connect(lambda: self.browse_file(self.input_otp, "otp.bin"))

        self.input_output.clicked.connect(lambda: self.browse_folder(self.input_output))
        self.btn_browse_out.clicked.connect(lambda: self.browse_folder(self.input_output))

        self.btn_suggest.clicked.connect(self.suggest_export_folder)
        self.input_output.textChanged.connect(self.on_output_dir_changed)

        self.input_hactool.textChanged.connect(lambda t: self._on_path_input_changed("hactool", t))
        self.input_keys.textChanged.connect(lambda t: self._on_path_input_changed("prod_keys", t))
        self.input_prodinfo.textChanged.connect(lambda t: self._on_path_input_changed("prodinfo", t))
        self.input_boot9.textChanged.connect(lambda t: self._on_path_input_changed("boot9_path", t))
        self.input_otp.textChanged.connect(lambda t: self._on_path_input_changed("otp_path", t))

        self.btn_help_hactool.clicked.connect(lambda: self.show_path_help("hactool"))
        self.btn_help_keys.clicked.connect(lambda: self.show_path_help("keys"))
        self.btn_help_prodinfo.clicked.connect(lambda: self.show_path_help("prodinfo"))
        self.btn_help_boot9.clicked.connect(lambda: self.show_path_help("boot9"))
        self.btn_help_otp.clicked.connect(lambda: self.show_path_help("otp"))

    def _open_hactool_web_link(self, url=None):
        target_url = url or "https://github.com/JeremKOYTB/TriCoreDownloader/tree/main/hactool"
        opened = False
        try:
            opened = QDesktopServices.openUrl(QUrl(target_url))
        except Exception:
            opened = False

        if not opened:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(target_url)
            win = self.window() if (hasattr(self, "window") and self.window()) else self
            dlg = PathMessageDialog(
                self.T("hactool_browser_err_title"),
                self.T("hactool_browser_err_msg").format(url=target_url),
                QStyle.StandardPixmap.SP_MessageBoxWarning,
                win
            )
            dlg.exec()
        return opened

    def _detect_hactool_target(self):
        system = sys.platform
        machine = platform.machine().lower()

        if system == "win32":
            if "64" in machine or "arm" in machine or platform.architecture()[0] == "64bit":
                return "hactool-Windowsx-64.exe", "hactool.exe"
        elif system == "darwin":
            is_silicon = machine in ("arm64", "aarch64")
            if not is_silicon:
                try:
                    res = subprocess.run(
                        ["sysctl", "-n", "sysctl.proc_translated"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=2
                    )
                    if res.stdout.strip() == "1":
                        is_silicon = True
                except Exception:
                    pass
            if is_silicon:
                return "hactool-macOS-Silicon", "hactool"
            else:
                return "hactool-macOS-intel", "hactool"
        elif system.startswith("linux"):
            if machine in ("x86_64", "amd64"):
                return "hactool-Linux-x64", "hactool"

        return None, None

    def _prepare_and_verify_hactool_binary(self, target_final):
        if sys.platform != "win32":
            try:
                os.chmod(target_final, 0o755)
            except Exception:
                pass
            if sys.platform == "darwin":
                try:
                    subprocess.run(
                        ["xattr", "-d", "com.apple.quarantine", target_final],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass

        flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        subprocess.run(
            [target_final],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=4,
            **flags
        )

    def auto_download_hactool(self):
        hactool_url = "https://github.com/JeremKOYTB/TriCoreDownloader/tree/main/hactool"
        win = self.window() if (hasattr(self, "window") and self.window()) else self

        intro_dlg = HactoolIntroDialog(
            self.T("hactool_v110_title"),
            self.T("hactool_v110_msg").format(url=hactool_url),
            win,
            self._open_hactool_web_link
        )
        intro_dlg.exec()

        if intro_dlg.choice == "browser":
            self._open_hactool_web_link(hactool_url)
            return
        elif intro_dlg.choice != "download":
            return

        remote_binary, local_binary = self._detect_hactool_target()

        if not remote_binary:
            options = [
                "hactool-Windowsx-64.exe (Windows 64-bit)",
                "hactool-macOS-Silicon (macOS Apple Silicon)",
                "hactool-macOS-intel (macOS Intel)",
                "hactool-Linux-x64 (Linux 64-bit)"
            ]
            file_map = {
                options[0]: ("hactool-Windowsx-64.exe", "hactool.exe"),
                options[1]: ("hactool-macOS-Silicon", "hactool"),
                options[2]: ("hactool-macOS-intel", "hactool"),
                options[3]: ("hactool-Linux-x64", "hactool")
            }
            chosen_item, ok = QInputDialog.getItem(
                win,
                self.T("hactool_select_title"),
                self.T("hactool_select_msg"),
                options,
                0,
                False
            )
            if not ok or not chosen_item:
                return
            remote_binary, local_binary = file_map[chosen_item]

        default_dir = os.path.dirname(self.config.get("hactool", "")) or str(Path.home())
        dest_dir = QFileDialog.getExistingDirectory(
            win,
            self.T("hactool_dir_title"),
            default_dir
        )
        if not dest_dir:
            return

        dest_dir = os.path.normpath(dest_dir)
        target_final = os.path.normpath(os.path.join(dest_dir, local_binary))

        if os.path.exists(target_final):
            exists_dlg = HactoolExistsDialog(
                self.T("hactool_exists_title"),
                self.T("hactool_exists_msg").format(path=target_final),
                win
            )
            exists_dlg.exec()
            if exists_dlg.choice == "cancel":
                return
            elif exists_dlg.choice == "use":
                try:
                    self._prepare_and_verify_hactool_binary(target_final)
                except Exception as e:
                    err_dlg = PathMessageDialog(
                        self.T("hactool_err_title"),
                        f"{self.T('hactool_err_exec')}\n({e})",
                        QStyle.StandardPixmap.SP_MessageBoxCritical,
                        win
                    )
                    err_dlg.exec()
                    return

                self.input_hactool.setText(target_final)
                self.config["hactool"] = target_final
                save_config(self.config)
                self._settings_dirty = True
                if hasattr(self, "trigger_auto_save"):
                    self.trigger_auto_save()

                succ_dlg = PathMessageDialog(
                    self.T("hactool_success_title"),
                    self.T("hactool_success_msg").format(path=target_final),
                    QStyle.StandardPixmap.SP_MessageBoxInformation,
                    win
                )
                succ_dlg.exec()
                return

        test_probe = os.path.join(dest_dir, f".perm_check_{os.getpid()}.tmp")
        try:
            with open(test_probe, "wb") as f:
                f.write(b"PERM_OK")
            os.remove(test_probe)
        except Exception:
            err_dlg = PathMessageDialog(
                self.T("hactool_err_title"),
                self.T("hactool_err_write_perm").format(path=dest_dir),
                QStyle.StandardPixmap.SP_MessageBoxCritical,
                win
            )
            err_dlg.exec()
            return

        url = f"https://raw.githubusercontent.com/JeremKOYTB/TriCoreDownloader/main/hactool/{remote_binary}"
        fallback_url = f"https://github.com/JeremKOYTB/TriCoreDownloader/raw/main/hactool/{remote_binary}"
        target_tmp = os.path.join(dest_dir, f".{local_binary}.download.tmp")

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        session = requests.Session()
        try:
            resp = None
            try:
                try:
                    resp = session.get(url, stream=True, timeout=15)
                except requests.exceptions.SSLError:
                    resp = session.get(url, stream=True, timeout=15, verify=False)
                if resp.status_code == 404:
                    resp.close()
                    try:
                        resp = session.get(fallback_url, stream=True, timeout=15)
                    except requests.exceptions.SSLError:
                        resp = session.get(fallback_url, stream=True, timeout=15, verify=False)
                resp.raise_for_status()
            except requests.exceptions.HTTPError:
                status = resp.status_code if resp is not None else 0
                if status == 403:
                    raise RuntimeError(self.T("hactool_err_403"))
                elif status == 404:
                    raise RuntimeError(self.T("hactool_err_404").format(binary=remote_binary))
                else:
                    raise RuntimeError(self.T("hactool_err_http").format(code=status))
            except requests.exceptions.ConnectionError:
                raise RuntimeError(self.T("hactool_err_net"))
            except requests.exceptions.Timeout:
                raise RuntimeError(self.T("hactool_err_timeout"))

            with open(target_tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        f.write(chunk)
                        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

            if os.path.exists(target_final):
                try:
                    os.remove(target_final)
                except Exception:
                    pass
            os.replace(target_tmp, target_final)

            try:
                self._prepare_and_verify_hactool_binary(target_final)
            except Exception as e:
                raise RuntimeError(f"{self.T('hactool_err_exec')}\n({e})")

        except Exception as e:
            if os.path.exists(target_tmp):
                try:
                    os.remove(target_tmp)
                except Exception:
                    pass
            QApplication.restoreOverrideCursor()
            err_dlg = PathMessageDialog(
                self.T("hactool_err_title"),
                str(e),
                QStyle.StandardPixmap.SP_MessageBoxCritical,
                win
            )
            err_dlg.exec()
            return
        finally:
            session.close()
            QApplication.restoreOverrideCursor()

        self.input_hactool.setText(target_final)
        self.config["hactool"] = target_final
        save_config(self.config)
        self._settings_dirty = True
        if hasattr(self, "trigger_auto_save"):
            self.trigger_auto_save()

        succ_dlg = PathMessageDialog(
            self.T("hactool_success_title"),
            self.T("hactool_success_msg").format(path=target_final),
            QStyle.StandardPixmap.SP_MessageBoxInformation,
            win
        )
        succ_dlg.exec()

    def _on_path_input_changed(self, key, value):
        if getattr(self, "_is_loading_ui", False):
            return
        if hasattr(self, "config"):
            self.config[key] = value
            self._settings_dirty = True
            if hasattr(self, "trigger_auto_save"):
                self.trigger_auto_save()

    def show_path_help(self, key):
        win = self.window() if (hasattr(self, "window") and self.window()) else self
        dlg = PathMessageDialog(
            self.T(f"help_{key}_title"),
            self.T(f"help_{key}_msg"),
            QStyle.StandardPixmap.SP_MessageBoxInformation,
            win
        )
        dlg.exec()

    def retranslate_paths_section(self):
        if hasattr(self, "lbl_grp_paths_title"):
            self.lbl_grp_paths_title.setText(self.T("grp_crypto"))
        if hasattr(self, "lbl_hactool"):
            self.lbl_hactool.setText(self.T("lbl_hactool"))
        if hasattr(self, "lbl_keys"):
            self.lbl_keys.setText(self.T("lbl_keys"))
        if hasattr(self, "lbl_prodinfo"):
            self.lbl_prodinfo.setText(self.T("lbl_prodinfo"))
        if hasattr(self, "lbl_boot9"):
            self.lbl_boot9.setText(self.T("lbl_boot9"))
        if hasattr(self, "input_boot9"):
            self.input_boot9.setPlaceholderText(self.T("ctr_hint_boot9"))
        if hasattr(self, "lbl_otp"):
            self.lbl_otp.setText(self.T("lbl_otp"))
        if hasattr(self, "lbl_out"):
            self.lbl_out.setText(self.T("lbl_out"))
        if hasattr(self, "btn_suggest"):
            self.btn_suggest.setText(self.T("btn_suggest"))
        if hasattr(self, "browse_buttons"):
            for btn in self.browse_buttons:
                btn.setText(self.T("btn_browse"))
        if hasattr(self, "btn_auto_hactool"):
            self.btn_auto_hactool.setText(self.T("btn_auto"))
            self.btn_auto_hactool.setToolTip(self.T("tooltip_hactool_auto"))
