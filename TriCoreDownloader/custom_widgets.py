import os
import sys
import shutil
import time
import subprocess
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QMenu, QMessageBox, QWidget,
    QGraphicsOpacityEffect, QApplication, QTextEdit,
    QScrollArea, QFrame, QWidgetAction, QSizePolicy
)
from PyQt6.QtCore import (
    QTimer, pyqtSignal, Qt, QPoint, QSize, QPropertyAnimation,
    QEasingCurve, QParallelAnimationGroup, QObject
)
from PyQt6.QtGui import QIcon, QAction, QFont, QTextCursor
from .config import APPDATA_DIR, EULA_FILE, save_config

if sys.platform == "darwin":
    CW_INFO_FONT_SIZE = "13pt"
    CW_MONO_FONT_NAME = "Menlo"
    CW_MONO_FONT_SIZE = 11
    CW_TRANS_FONT_SIZE = "13pt"
    CW_TRANS_WEIGHT = "600"
elif sys.platform == "win32":
    CW_INFO_FONT_SIZE = "11pt"
    CW_MONO_FONT_NAME = "Consolas"
    CW_MONO_FONT_SIZE = 9
    CW_TRANS_FONT_SIZE = "11pt"
    CW_TRANS_WEIGHT = "600"
else:
    CW_INFO_FONT_SIZE = "10pt"
    CW_MONO_FONT_NAME = "Monospace"
    CW_MONO_FONT_SIZE = 9
    CW_TRANS_FONT_SIZE = "10pt"
    CW_TRANS_WEIGHT = "500"


def is_running_in_terminal():
    return sys.stdout is not None and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _get_mac_app_bundle_path(path):
    abs_path = os.path.abspath(path)
    parts = abs_path.split(os.sep)
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return os.sep.join(parts[:i + 1])
    return abs_path


def _animate_dialog_open(dialog):
    if sys.platform.startswith("linux"):
        return
    try:
        dialog.setWindowOpacity(0.0)
        anim = QPropertyAnimation(dialog, b"windowOpacity", dialog)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        dialog._open_anim = anim
        anim.start()
    except Exception:
        dialog.setWindowOpacity(1.0)


class LogStream(QObject):
    text_written = pyqtSignal(str)

    def __init__(self, original_stream=None):
        super().__init__()
        self.original_stream = original_stream

    def write(self, text):
        if self.original_stream and hasattr(self.original_stream, "write"):
            try:
                self.original_stream.write(text)
            except Exception:
                pass
        if text:
            self.text_written.emit(str(text))

    def flush(self):
        if self.original_stream and hasattr(self.original_stream, "flush"):
            try:
                self.original_stream.flush()
            except Exception:
                pass


class LogConsoleWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TriCoreDownloader - Log Console")
        self.resize(750, 450)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.lbl_info = QLabel("Live Log Console (Advanced Mode)")
        self.lbl_info.setStyleSheet(f"font-weight: bold; font-size: {CW_INFO_FONT_SIZE};")
        layout.addWidget(self.lbl_info)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.document().setMaximumBlockCount(2500)
        self.text_edit.setFont(QFont(CW_MONO_FONT_NAME, CW_MONO_FONT_SIZE))
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self.text_edit.clear)

        self.btn_close = QPushButton("Hide")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

    def append_log(self, text):
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.text_edit.insertPlainText(text)
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def showEvent(self, event):
        super().showEvent(event)
        _animate_dialog_open(self)
        QTimer.singleShot(50, self._force_foreground)

    def _force_foreground(self):
        self.raise_()
        self.activateWindow()


class CustomConsoleSelector(QPushButton):
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConsoleSelector")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(24, 24))

        self.menu = QMenu(self)
        self.menu.setObjectName("ConsoleCustomMenu")

        self.items = []
        self._current_index = 0
        self._signals_blocked = False
        self._active_anim_group = None
        self._menu_open_anim = None
        self._centered = False

        self.clicked.connect(self._show_menu)

    def setCentered(self, centered: bool):
        self._centered = bool(centered)
        if self._centered:
            self.setStyleSheet("QPushButton#ConsoleSelector { text-align: center; padding-left: 12px; padding-right: 12px; }")
        else:
            self.setStyleSheet("")
        if 0 <= self._current_index < len(self.items):
            item = self.items[self._current_index]
            prefix = "" if (self._centered and (not item['icon'] or item['icon'].isNull())) else " "
            self.setText(prefix + item['text'])

    def isCentered(self) -> bool:
        return self._centered

    def blockSignals(self, b):
        self._signals_blocked = b
        return super().blockSignals(b)

    def setSizeAdjustPolicy(self, *args, **kwargs):
        pass

    def _update_minimum_width(self):
        if not self.items:
            return

        font_metrics = self.fontMetrics()
        max_w = max(
            (font_metrics.horizontalAdvance(" " + str(item['text'])) +
             (28 if (item['icon'] and not item['icon'].isNull()) else 0) + 56)
            for item in self.items
        )
        if max_w > 0:
            max_allowed = self.maximumWidth()
            if 0 < max_allowed < 16777215:
                self.setMinimumWidth(min(max_w, max_allowed))
            else:
                self.setMinimumWidth(min(max_w, 260))

    def addItem(self, icon_or_text, text_or_data=None, user_data=None, userData=None):
        if userData is not None and user_data is None:
            user_data = userData

        if isinstance(icon_or_text, QIcon):
            icon = icon_or_text
            text = str(text_or_data or "")
            data = user_data
        else:
            icon = QIcon()
            text = str(icon_or_text or "")
            data = text_or_data if text_or_data is not None else user_data

        idx = len(self.items)
        action = QAction(text, self.menu)
        action.setData(idx)
        action.setIconVisibleInMenu(True)

        if not icon.isNull():
            action.setIcon(icon)

        self.menu.addAction(action)
        self.items.append({'text': text, 'icon': icon, 'action': action, 'data': data})
        self._update_minimum_width()

        if len(self.items) == 1:
            self.setCurrentIndex(0)

    def insertItem(self, index, icon_or_text, text_or_data=None, user_data=None, userData=None):
        if userData is not None and user_data is None:
            user_data = userData

        if isinstance(icon_or_text, QIcon):
            icon = icon_or_text
            text = str(text_or_data or "")
            data = user_data
        else:
            icon = QIcon()
            text = str(icon_or_text or "")
            data = text_or_data if text_or_data is not None else user_data

        action = QAction(text, self.menu)
        action.setData(index)
        action.setIconVisibleInMenu(True)
        if not icon.isNull():
            action.setIcon(icon)

        if index >= len(self.items):
            self.menu.addAction(action)
            self.items.append({'text': text, 'icon': icon, 'action': action, 'data': data})
        else:
            before_action = self.items[index]['action']
            self.menu.insertAction(before_action, action)
            self.items.insert(index, {'text': text, 'icon': icon, 'action': action, 'data': data})

        for i, itm in enumerate(self.items):
            itm['action'].setData(i)

        self._update_minimum_width()

    def currentData(self, role=None):
        return self.itemData(self._current_index)

    def currentText(self):
        return self.itemText(self._current_index)

    def itemData(self, index, role=None):
        if 0 <= index < len(self.items):
            return self.items[index].get('data')
        return None

    def setItemData(self, index, data, role=None):
        if role is not None and role != Qt.ItemDataRole.UserRole:
            return
        if 0 <= index < len(self.items):
            self.items[index]['data'] = data

    def itemText(self, index):
        if 0 <= index < len(self.items):
            return self.items[index].get('text', "")
        return ""

    def findData(self, data):
        for idx, item in enumerate(self.items):
            if item.get('data') == data:
                return idx
        return -1

    def findText(self, text):
        for idx, item in enumerate(self.items):
            if item.get('text') == text:
                return idx
        return -1

    def clear(self):
        self.menu.clear()
        self.items = []
        self._current_index = 0
        self.setText("")
        self.setIcon(QIcon())

    def setCurrentIndex(self, index):
        if 0 <= index < len(self.items):
            old_idx = self._current_index
            self._current_index = index
            item = self.items[index]
            prefix = "" if (self._centered and (not item['icon'] or item['icon'].isNull())) else " "
            self.setText(prefix + item['text'])
            if item['icon'] and not item['icon'].isNull():
                self.setIcon(item['icon'])
            else:
                self.setIcon(QIcon())

            self._update_minimum_width()

            if not self._signals_blocked and old_idx != index:
                self.currentIndexChanged.emit(index)

    def currentIndex(self):
        return self._current_index

    def count(self):
        return len(self.items)

    def setItemIcon(self, index, icon):
        if 0 <= index < len(self.items):
            self.items[index]['icon'] = icon
            self.items[index]['action'].setIcon(icon)
            self.items[index]['action'].setIconVisibleInMenu(True)
            if self._current_index == index:
                self.setIcon(icon)
            self._update_minimum_width()

    def setItemText(self, index, text):
        if 0 <= index < len(self.items):
            self.items[index]['text'] = text
            self.items[index]['action'].setText(text)
            if self._current_index == index:
                item = self.items[index]
                prefix = "" if (self._centered and (not item['icon'] or item['icon'].isNull())) else " "
                self.setText(prefix + text)
            self._update_minimum_width()

    def _animate_menu_popup(self, menu_widget, target_pos):
        try:
            if self._menu_open_anim:
                self._menu_open_anim.stop()
                self._menu_open_anim = None

            start_pos = QPoint(target_pos.x(), target_pos.y() - 8)
            menu_widget.move(start_pos)

            group = QParallelAnimationGroup(self)

            anim_pos = QPropertyAnimation(menu_widget, b"pos", group)
            anim_pos.setDuration(120)
            anim_pos.setStartValue(start_pos)
            anim_pos.setEndValue(target_pos)
            anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(anim_pos)

            if not sys.platform.startswith("linux"):
                menu_widget.setWindowOpacity(0.0)
                anim_op = QPropertyAnimation(menu_widget, b"windowOpacity", group)
                anim_op.setDuration(120)
                anim_op.setStartValue(0.0)
                anim_op.setEndValue(1.0)
                anim_op.setEasingCurve(QEasingCurve.Type.OutCubic)
                group.addAnimation(anim_op)

            self._menu_open_anim = group
            group.start()
        except Exception:
            try:
                menu_widget.move(target_pos)
                menu_widget.setWindowOpacity(1.0)
            except Exception:
                pass

    def _play_transition_animation(self, new_index, action=None, on_finished=None, global_start=None):
        try:
            top_win = self.window()
            if not top_win or not self.isVisible():
                if on_finished:
                    on_finished()
                return

            if hasattr(self, "_active_anim_group") and self._active_anim_group:
                self._active_anim_group.stop()
                self._active_anim_group = None

            if global_start is None and action is not None:
                action_rect = self.menu.actionGeometry(action)
                global_start = self.menu.mapToGlobal(action_rect.topLeft())

            if global_start is None:
                if on_finished:
                    on_finished()
                return

            start_pt = top_win.mapFromGlobal(global_start)
            end_pt = top_win.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))

            new_item = self.items[new_index]

            anim_card = QWidget(top_win)
            anim_card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            anim_card.setObjectName("ConsoleSelector")
            anim_card.setStyleSheet(self.styleSheet())

            lay = QHBoxLayout(anim_card)
            lay.setContentsMargins(16, 0, 16, 0)
            lay.setSpacing(8)

            if self._centered:
                lay.addStretch()

            if new_item['icon'] and not new_item['icon'].isNull():
                lbl_icon = QLabel()
                lbl_icon.setPixmap(new_item['icon'].pixmap(QSize(24, 24)))
                lay.addWidget(lbl_icon)

            lbl_text = QLabel(new_item['text'])
            lbl_text.setStyleSheet(f"font-size: {CW_TRANS_FONT_SIZE}; font-weight: {CW_TRANS_WEIGHT};")
            if self._centered:
                lbl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lbl_text)
            lay.addStretch()

            anim_card.setGeometry(start_pt.x(), start_pt.y(), self.width(), self.height())
            anim_card.show()

            opacity = QGraphicsOpacityEffect(anim_card)
            anim_card.setGraphicsEffect(opacity)

            anim_pos = QPropertyAnimation(anim_card, b"pos", self)
            anim_pos.setDuration(155)
            anim_pos.setStartValue(start_pt)
            anim_pos.setEndValue(end_pt)
            anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)

            anim_fade = QPropertyAnimation(opacity, b"opacity", self)
            anim_fade.setDuration(155)
            anim_fade.setStartValue(0.25)
            anim_fade.setEndValue(1.0)
            anim_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

            anim_group = QParallelAnimationGroup(self)
            anim_group.addAnimation(anim_pos)
            anim_group.addAnimation(anim_fade)
            self._active_anim_group = anim_group

            def cleanup():
                self._active_anim_group = None
                anim_card.deleteLater()
                if on_finished:
                    on_finished()

            anim_group.finished.connect(cleanup)
            anim_group.start()
        except Exception:
            if on_finished:
                on_finished()

    def _resolve_menu_theme_colors(self):
        top_win = self.window()
        theme_pref = "dark"
        accent = "#C4A1FF"
        if top_win and hasattr(top_win, "config"):
            theme_pref = str(top_win.config.get("theme", "auto")).lower()
            if theme_pref == "auto":
                if hasattr(top_win, "get_effective_is_dark"):
                    theme_pref = "dark" if top_win.get_effective_is_dark() else "light"
                else:
                    theme_pref = "dark"
            if hasattr(top_win, "get_current_accent_color"):
                accent = top_win.get_current_accent_color()

        if theme_pref == "light":
            return {
                "bg": "#FFFFFF",
                "border": "#CED4DA",
                "text": "#212529",
                "hover_bg": "#E9ECEF",
                "hover_text": "#212529",
                "active_border": accent,
                "sb_handle": "#CED4DA",
                "sb_hover": "#ADB5BD",
            }
        elif theme_pref == "oled":
            return {
                "bg": "#000000",
                "border": "#333333",
                "text": "#E0E0E0",
                "hover_bg": "#151518",
                "hover_text": "#FFFFFF",
                "active_border": accent,
                "sb_handle": "#333333",
                "sb_hover": "#424242",
            }
        return {
            "bg": "#32323A",
            "border": "#555560",
            "text": "#E8E8E8",
            "hover_bg": "#4A4A54",
            "hover_text": "#FFFFFF",
            "active_border": accent,
            "sb_handle": "#5A5A66",
            "sb_hover": "#70707D",
        }

    def _show_scrollable_menu(self):
        colors = self._resolve_menu_theme_colors()
        popup_menu = QMenu(self)
        popup_menu.setObjectName("ConsoleCustomMenu")
        popup_menu.setWindowFlags(
            popup_menu.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        popup_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        menu_width = max(self.width(), 200)
        popup_menu.setStyleSheet(f"""
            QMenu#ConsoleCustomMenu {{
                background-color: {colors['bg']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                padding: 4px;
            }}
        """)

        scroll_area = QScrollArea(popup_menu)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setFixedWidth(menu_width - 10)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 6px;
                margin: 2px 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {colors['sb_handle']};
                min-height: 28px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {colors['sb_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                height: 0px;
                background: transparent;
            }}
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(2, 2, 4 if len(self.items) > 7 else 2, 2)
        vbox.setSpacing(2)

        align_css = "center" if self._centered else "left"
        item_css = f"""
            QPushButton {{
                background-color: transparent;
                color: {colors['text']};
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 8px 14px;
                text-align: {align_css};
                font-size: {CW_TRANS_FONT_SIZE};
                font-weight: 500;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background-color: {colors['hover_bg']};
                color: {colors['hover_text']};
                border: 1px solid {colors['border']};
            }}
        """
        active_item_css = f"""
            QPushButton {{
                background-color: {colors['hover_bg']};
                color: {colors['hover_text']};
                border: 1px solid {colors['active_border']};
                border-radius: 6px;
                padding: 8px 14px;
                text-align: {align_css};
                font-size: {CW_TRANS_FONT_SIZE};
                font-weight: {CW_TRANS_WEIGHT};
                min-height: 24px;
            }}
            QPushButton:hover {{
                background-color: {colors['hover_bg']};
                color: {colors['hover_text']};
                border: 1px solid {colors['active_border']};
            }}
        """

        chosen = {"idx": None, "global_pt": None}
        active_btn = None

        for i, item in enumerate(self.items):
            has_icon = bool(item['icon'] and not item['icon'].isNull())
            btn_label = (" " + item['text']) if (has_icon and not self._centered) else item['text']
            btn = QPushButton(btn_label, container)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if has_icon:
                btn.setIcon(item['icon'])
                btn.setIconSize(QSize(24, 24))
            btn.setStyleSheet(active_item_css if i == self._current_index else item_css)

            def on_item_clicked(checked=False, idx=i, b=btn):
                chosen["idx"] = idx
                chosen["global_pt"] = b.mapToGlobal(QPoint(0, 0))
                popup_menu.close()

            btn.clicked.connect(on_item_clicked)
            vbox.addWidget(btn)
            if i == self._current_index:
                active_btn = btn

        scroll_area.setWidget(container)
        container.adjustSize()

        total_content_h = container.sizeHint().height() + 4
        visible_h = min(300, max(44, total_content_h))
        scroll_area.setFixedHeight(visible_h)

        widget_action = QWidgetAction(popup_menu)
        widget_action.setDefaultWidget(scroll_area)
        popup_menu.addAction(widget_action)

        pos = self.mapToGlobal(QPoint(0, self.height() + 4))

        def on_popup_shown():
            self._animate_menu_popup(popup_menu, pos)
            vbar = scroll_area.verticalScrollBar()
            if active_btn is not None and vbar and vbar.maximum() > 0:
                viewport_h = scroll_area.viewport().height()
                target_val = active_btn.y() - (viewport_h // 2) + (active_btn.height() // 2)
                target_val = max(0, min(vbar.maximum(), target_val))
                start_val = max(0, target_val - 40) if target_val > 0 else 0
                vbar.setValue(start_val)
                if start_val != target_val:
                    scroll_anim = QPropertyAnimation(vbar, b"value", popup_menu)
                    scroll_anim.setDuration(150)
                    scroll_anim.setStartValue(start_val)
                    scroll_anim.setEndValue(target_val)
                    scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                    popup_menu._scroll_anim = scroll_anim
                    scroll_anim.start()

        QTimer.singleShot(0, on_popup_shown)
        popup_menu.exec(pos)

        sel_idx = chosen["idx"]
        if sel_idx is not None and 0 <= sel_idx < len(self.items):
            if self._current_index != sel_idx:
                self._play_transition_animation(
                    sel_idx,
                    action=None,
                    on_finished=lambda: self.setCurrentIndex(sel_idx),
                    global_start=chosen["global_pt"],
                )

    def _show_menu(self):
        if not self.isEnabled() or not self.items:
            return
        self._show_scrollable_menu()


def launch_updater(parent_window=None, tr_func=None):
    if tr_func is None and parent_window is not None and hasattr(parent_window, "T"):
        tr_func = parent_window.T

    if parent_window:
        if getattr(parent_window, "worker", None) is not None and parent_window.worker.isRunning():
            block_box = QMessageBox(parent_window)
            if hasattr(parent_window, "get_app_icon"):
                block_box.setWindowIcon(parent_window.get_app_icon())
            block_box.setIcon(QMessageBox.Icon.Information)
            block_title = tr_func("close_blocked_title") if callable(tr_func) else "Closing Blocked"
            block_msg = tr_func("close_blocked_msg") if callable(tr_func) else "An operation is currently running."
            block_box.setWindowTitle(block_title)
            block_box.setText(block_msg)
            block_box.exec()
            return False

        confirm_box = QMessageBox(parent_window)
        if hasattr(parent_window, "get_app_icon"):
            confirm_box.setWindowIcon(parent_window.get_app_icon())
        confirm_box.setIcon(QMessageBox.Icon.Question)
        conf_title = tr_func("title_confirm") if callable(tr_func) else "Confirm Action"
        conf_msg = tr_func("upd_msg_handoff_warn") if callable(tr_func) else (
            "Warning:\nThis action will completely close TriCoreDownloader to initialize the independent updater module.\n\nDo you want to continue?"
        )
        yes_label = tr_func("btn_yes") if callable(tr_func) else "Yes"
        no_label = tr_func("btn_no") if callable(tr_func) else "No"

        confirm_box.setWindowTitle(conf_title)
        confirm_box.setText(conf_msg)
        btn_yes = confirm_box.addButton(yes_label, QMessageBox.ButtonRole.YesRole)
        btn_no = confirm_box.addButton(no_label, QMessageBox.ButtonRole.NoRole)
        confirm_box.setDefaultButton(btn_yes)
        confirm_box.exec()

        if confirm_box.clickedButton() != btn_yes:
            return False

        if hasattr(parent_window, "config"):
            try:
                save_config(parent_window.config)
            except Exception:
                pass
        parent_window._is_restarting = True

    is_frozen = getattr(sys, "frozen", False)

    clean_env = os.environ.copy()
    clean_env.pop("_MEIPASS2", None)
    clean_env.pop("_MEIPASS", None)
    clean_env.pop("APPDIR", None)

    if parent_window and hasattr(parent_window, "app_lock") and parent_window.app_lock.isLocked():
        try:
            parent_window.app_lock.unlock()
        except Exception:
            pass

    if is_frozen:
        appimage_env = os.environ.get("ORIGINAL_APPIMAGE") or os.environ.get("APPIMAGE")
        if appimage_env and os.path.exists(appimage_env):
            current_exe = os.path.abspath(appimage_env)
            base_dir = os.path.dirname(current_exe)
            orig_target = current_exe
            clean_env["ORIGINAL_APPIMAGE"] = current_exe
        elif sys.platform == "darwin" and ".app" in os.path.abspath(sys.executable):
            current_exe = os.path.abspath(sys.executable)
            mac_bundle = _get_mac_app_bundle_path(current_exe)
            base_dir = mac_bundle
            orig_target = mac_bundle
        else:
            current_exe = os.path.abspath(sys.executable)
            base_dir = os.path.dirname(current_exe)
            orig_target = current_exe

        args = [current_exe, "--updater", "--install-dir", base_dir, "--original-target", orig_target]
        kwargs = {
            "cwd": os.path.expanduser("~"),
            "env": clean_env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(args, **kwargs)

        if parent_window:
            parent_window.close()
        if QApplication.instance():
            QApplication.instance().quit()

        return True

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    updater_path = os.path.join(base_dir, "Updater.py")

    if not os.path.exists(updater_path):
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        updater_path = os.path.join(base_dir, "Updater.py")

    if not os.path.exists(updater_path):
        if parent_window:
            parent_window._is_restarting = False
            err_title = tr_func("msg_error_title") if callable(tr_func) else "Error"
            err_msg = tr_func("upd_err_missing_script") if callable(tr_func) else f"Updater.py script not found at:\n{updater_path}"
            QMessageBox.critical(parent_window, err_title, err_msg)
        return False

    main_script = os.path.join(base_dir, "run_TriCoreDownloader.py")
    orig_target = main_script if os.path.exists(main_script) else os.path.abspath(sys.argv[0])

    target_script = updater_path
    try:
        appdata_dir = str(APPDATA_DIR)
        os.makedirs(appdata_dir, exist_ok=True)
        temp_updater = os.path.join(appdata_dir, "TempUpdater.py")
        shutil.copy2(updater_path, temp_updater)
        for _ in range(10):
            if os.path.exists(temp_updater) and os.path.getsize(temp_updater) > 0:
                target_script = temp_updater
                break
            time.sleep(0.05)
    except Exception:
        target_script = updater_path

    kwargs = {
        "cwd": base_dir,
        "env": clean_env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        [sys.executable, target_script, "--install-dir", base_dir, "--original-target", orig_target],
        **kwargs
    )
    time.sleep(0.25)
    if proc.poll() is not None and target_script != updater_path:
        subprocess.Popen(
            [sys.executable, updater_path, "--install-dir", base_dir, "--original-target", orig_target],
            **kwargs
        )

    if parent_window:
        parent_window.close()
    if QApplication.instance():
        QApplication.instance().quit()

    return True


class AutoCloseDialog(QDialog):
    def __init__(self, title, message, timeout_sec, btn_template_text, parent=None):
        super().__init__(parent)
        self.timeout = timeout_sec
        self.btn_template = btn_template_text

        self.setWindowTitle(title)
        self.setMinimumSize(400, 200)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        lbl = QLabel(message)
        lbl.setObjectName("DialogText")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        layout.addStretch()

        self.btn = QPushButton(self.btn_template.format(self.timeout))
        self.btn.setObjectName("btnActionDialog")
        self.btn.clicked.connect(self.accept)
        self.btn.setMinimumWidth(120)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def showEvent(self, event):
        super().showEvent(event)
        _animate_dialog_open(self)
        QTimer.singleShot(50, self._force_foreground)

    def _force_foreground(self):
        self.raise_()
        self.activateWindow()

    def tick(self):
        self.timeout -= 1
        self.btn.setText(self.btn_template.format(self.timeout))
        if self.timeout <= 0:
            self.timer.stop()
            self.accept()

    def closeEvent(self, event):
        if hasattr(self, "timer") and self.timer.isActive():
            self.timer.stop()
        super().closeEvent(event)


class EulaDialog(QDialog):
    def __init__(self, parent, is_first_time, translation_func):
        super().__init__(parent)
        self.parent_app = parent
        self.T = translation_func
        self.is_first_time = is_first_time
        self.dont_show_again = False

        self.setWindowTitle(self.T("eula_title"))
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(600)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        lang_layout = QHBoxLayout()
        lang_layout.addStretch()
        self.combo_lang = QComboBox()
        self.combo_lang.addItems([self.T("lang_en"), self.T("lang_fr")])

        current_lang = str(self.parent_app.config.get("lang") or "en").lower()
        self.combo_lang.setCurrentIndex(1 if current_lang == "fr" else 0)
        self.combo_lang.currentIndexChanged.connect(self.change_language)

        lang_layout.addWidget(self.combo_lang)
        layout.addLayout(lang_layout)

        msg = self.T("eula_first") if is_first_time else self.T("eula_return")

        self.lbl_msg = QLabel(msg)
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setObjectName("DialogText")
        layout.addWidget(self.lbl_msg)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        if is_first_time:
            self.btn_ok = QPushButton(self.T("btn_ok_cont"))
            self.btn_ok.setObjectName("btnEulaOk")
            self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_ok.clicked.connect(self.accept)

            self.btn_no = QPushButton(self.T("btn_no_quit"))
            self.btn_no.setObjectName("btnEulaCancel")
            self.btn_no.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_no.clicked.connect(self.reject)

            btn_layout.addWidget(self.btn_ok)
            btn_layout.addWidget(self.btn_no)
        else:
            self.btn_ok = QPushButton(self.T("btn_ok_only"))
            self.btn_ok.setObjectName("btnEulaOk")
            self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_ok.clicked.connect(self.accept)

            self.btn_never = QPushButton(self.T("btn_never_again"))
            self.btn_never.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_never.clicked.connect(self.accept_never_again)

            btn_layout.addWidget(self.btn_ok)
            btn_layout.addWidget(self.btn_never)

        layout.addLayout(btn_layout)

    def showEvent(self, event):
        super().showEvent(event)
        _animate_dialog_open(self)
        QTimer.singleShot(50, self._force_foreground)

    def _force_foreground(self):
        self.raise_()
        self.activateWindow()

    def accept_never_again(self):
        self.dont_show_again = True
        self.accept()

    def change_language(self, index):
        new_lang = "FR" if index == 1 else "EN"
        self.parent_app.config["lang"] = new_lang
        save_config(self.parent_app.config)

        if hasattr(self.parent_app, "reload_locales"):
            self.parent_app.reload_locales()

        self.setWindowTitle(self.T("eula_title"))
        msg = self.T("eula_first") if self.is_first_time else self.T("eula_return")
        self.lbl_msg.setText(msg)

        if self.is_first_time:
            self.btn_ok.setText(self.T("btn_ok_cont"))
            self.btn_no.setText(self.T("btn_no_quit"))
        else:
            self.btn_ok.setText(self.T("btn_ok_only"))
            self.btn_never.setText(self.T("btn_never_again"))

        if hasattr(self.parent_app, "retranslate_ui"):
            self.parent_app.retranslate_ui()

        if hasattr(self.parent_app, "combo_lang"):
            self.parent_app.combo_lang.blockSignals(True)
            target_idx = self.parent_app.combo_lang.findData(new_lang)
            if target_idx >= 0:
                self.parent_app.combo_lang.setCurrentIndex(target_idx)
            else:
                self.parent_app.combo_lang.setCurrentIndex(index)
            self.parent_app.combo_lang.blockSignals(False)


class ClickableLineEdit(QLineEdit):
    clicked = pyqtSignal()

    def __init__(self, text=""):
        super().__init__(text)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                local_path = urls[0].toLocalFile()
                if local_path:
                    norm_path = os.path.normpath(local_path)
                    self.setText(norm_path)
                    event.acceptProposedAction()
                    return
        event.ignore()
