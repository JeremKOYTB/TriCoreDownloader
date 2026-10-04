import os
import sys
import subprocess
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QLineEdit, QMenu, QMessageBox, QWidget, QGraphicsOpacityEffect, QApplication
)
from PyQt6.QtCore import QTimer, pyqtSignal, Qt, QPoint, QSize, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PyQt6.QtGui import QIcon, QAction
from .config import APPDATA_DIR, EULA_FILE, save_config

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
        
        self.clicked.connect(self._show_menu)

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
            self.setMinimumWidth(max_w)

    def addItem(self, icon_or_text, text_or_data=None, user_data=None):
        if isinstance(icon_or_text, QIcon):
            icon = icon_or_text
            text = str(text_or_data or "")
            data = user_data
        else:
            icon = QIcon()
            text = str(icon_or_text or "")
            data = text_or_data

        idx = len(self.items)
        action = QAction(text, self.menu)
        action.setData(idx)
        
        if not icon.isNull():
            action.setIcon(icon)

        self.menu.addAction(action)
        self.items.append({'text': text, 'icon': icon, 'action': action, 'data': data})
        self._update_minimum_width()

        if len(self.items) == 1:
            self.setCurrentIndex(0)

    def insertItem(self, index, icon_or_text, text_or_data=None, user_data=None):
        if isinstance(icon_or_text, QIcon):
            icon = icon_or_text
            text = str(text_or_data or "")
            data = user_data
        else:
            icon = QIcon()
            text = str(icon_or_text or "")
            data = text_or_data

        action = QAction(text, self.menu)
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

    def itemData(self, index):
        if 0 <= index < len(self.items):
            return self.items[index].get('data')
        return None

    def setItemData(self, index, data):
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
            self.setText(" " + item['text'])
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
            if self._current_index == index:
                self.setIcon(icon)
            self._update_minimum_width()

    def setItemText(self, index, text):
        if 0 <= index < len(self.items):
            self.items[index]['text'] = text
            self.items[index]['action'].setText(text)
            if self._current_index == index:
                self.setText(" " + text)
            self._update_minimum_width()

    def _play_transition_animation(self, new_index, action, on_finished=None):
        try:
            top_win = self.window()
            if not top_win or not self.isVisible():
                if on_finished:
                    on_finished()
                return

            if hasattr(self, "_active_anim_group") and self._active_anim_group:
                self._active_anim_group.stop()
                self._active_anim_group = None

            action_rect = self.menu.actionGeometry(action)
            global_start = self.menu.mapToGlobal(action_rect.topLeft())
            start_pt = top_win.mapFromGlobal(global_start)
            end_pt = top_win.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))

            new_item = self.items[new_index]

            anim_card = QWidget(top_win)
            anim_card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            anim_card.setObjectName("ConsoleSelector")
            anim_card.setStyleSheet(self.styleSheet())

            lay = QHBoxLayout(anim_card)
            lay.setContentsMargins(12, 0, 12, 0)
            lay.setSpacing(8)

            if new_item['icon'] and not new_item['icon'].isNull():
                lbl_icon = QLabel()
                lbl_icon.setPixmap(new_item['icon'].pixmap(QSize(20, 20)))
                lay.addWidget(lbl_icon)

            lbl_text = QLabel(new_item['text'])
            lbl_text.setStyleSheet("font-size: 10pt; font-weight: 600;")
            lay.addWidget(lbl_text)
            lay.addStretch()

            anim_card.setGeometry(start_pt.x(), start_pt.y(), self.width(), self.height())
            anim_card.show()

            opacity = QGraphicsOpacityEffect(anim_card)
            anim_card.setGraphicsEffect(opacity)

            anim_pos = QPropertyAnimation(anim_card, b"pos", self)
            anim_pos.setDuration(150)
            anim_pos.setStartValue(start_pt)
            anim_pos.setEndValue(end_pt)
            anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)

            anim_fade = QPropertyAnimation(opacity, b"opacity", self)
            anim_fade.setDuration(150)
            anim_fade.setStartValue(0.3)
            anim_fade.setEndValue(1.0)

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

    def _show_menu(self):
        if not self.isEnabled() or not self.menu or self.menu.isEmpty():
            return
        
        self.menu.setMinimumWidth(max(self.width(), self.menu.sizeHint().width()))
        pos = self.mapToGlobal(QPoint(0, self.height() + 4))
        
        selected_action = self.menu.exec(pos)
        if selected_action is not None:
            idx = selected_action.data()
            if idx is not None and 0 <= idx < len(self.items):
                if self._current_index != idx:
                    self._play_transition_animation(idx, selected_action, on_finished=lambda: self.setCurrentIndex(idx))

def launch_updater(parent_window=None):
    if hasattr(sys, '_MEIPASS'):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

    updater_path = os.path.join(base_dir, "Updater.py")

    if not os.path.exists(updater_path):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        updater_path = os.path.join(base_dir, "Updater.py")

    if not os.path.exists(updater_path):
        if parent_window:
            QMessageBox.critical(
                parent_window,
                "Erreur",
                f"Le script Updater.py est introuvable à la racine :\n{updater_path}"
            )
        return False

    kwargs = {'cwd': base_dir}
    if sys.platform == 'win32':
        kwargs['creationflags'] = 0x00000008 | 0x00000200
    else:
        kwargs['start_new_session'] = True

    subprocess.Popen([sys.executable, updater_path, "--install-dir", base_dir], **kwargs)

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
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

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
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

        lang_layout = QHBoxLayout()
        lang_layout.addStretch()
        self.combo_lang = QComboBox()
        self.combo_lang.addItems([self.T("lang_en"), self.T("lang_fr")])
        
        current_lang = str(self.parent_app.config.get("lang", "en")).lower()
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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)