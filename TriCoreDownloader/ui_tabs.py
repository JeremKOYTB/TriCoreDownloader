import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QProgressBar, QFrame, 
                             QRadioButton, QScrollArea, QButtonGroup, 
                             QSizePolicy, QPlainTextEdit, QCheckBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextOption

SCROLLBAR_CSS = """
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #80888888;
    min-height: 30px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #CC888888;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0px;
    background: transparent;
}
"""

class UiTabsMixin:
    def create_wrapped_checkbox(self, chk_obj, text, indent=0):
        chk_obj.setText("")
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        
        lbl.mousePressEvent = lambda e: chk_obj.click()
        
        lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lbl.setMinimumHeight(lbl.fontMetrics().height() * 2)
        
        chk_obj.setText = lbl.setText
        
        cont = QWidget()
        cont.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        
        lay = QHBoxLayout(cont)
        lay.setContentsMargins(indent, 0, 0, 0)
        lay.setSpacing(8)
        
        lay.addWidget(chk_obj, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        
        lay.addStretch(1) 
        
        return cont, lbl

    def create_card(self, title_text):
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        lbl_title = QLabel(title_text)
        lbl_title.setObjectName("CardTitle")
        layout.addWidget(lbl_title)
        
        return card, layout, lbl_title

    def add_grid_row_extended(self, grid, row, label_text, line_edit, browse_func, help_func=None):
        lbl = QLabel(label_text)
        lbl.setMinimumWidth(150)
        
        btn_browse = QPushButton(self.T("btn_browse"))
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(browse_func)
        self.browse_buttons.append(btn_browse)
        
        btns_layout = QHBoxLayout()
        btns_layout.addWidget(btn_browse)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        
        if help_func:
            btn_help = QPushButton("?")
            btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_help.setFixedSize(32, 32)
            btn_help.setStyleSheet("padding: 0px;")
            btn_help.clicked.connect(help_func)
            btns_layout.addWidget(btn_help)
            
        btns_widget = QWidget()
        btns_widget.setLayout(btns_layout)
        
        grid.addWidget(lbl, row, 0)
        grid.addWidget(line_edit, row, 1)
        grid.addWidget(btns_widget, row, 2)
        
        return lbl, btns_widget

    def update_manual_input_context(self):
        mode = getattr(self, 'current_console', 'NX')
        
        if mode == 'NX':
            self.input_manual.setPlaceholderText(self.T("ph_manual_version_nx"))
            self.lbl_datfile_link.setText(self.T("manual_link_nx"))
        elif mode == 'CAFE':
            self.input_manual.setPlaceholderText(self.T("ph_manual_version_cafe"))
            self.lbl_datfile_link.setText(self.T("manual_link_cafe"))
        elif mode == 'CTR':
            self.input_manual.setPlaceholderText(self.T("ph_manual_version_ctr"))
            self.lbl_datfile_link.setText(self.T("manual_link_ctr"))

    def setup_main_tab(self):
        layout = QHBoxLayout(self.tab_main)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(20)
        
        self.grp_target, left_layout, self.lbl_grp_target = self.create_card(self.T("grp_target"))
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(SCROLLBAR_CSS)
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_content.setStyleSheet("background: transparent;")
        
        self.scroll_layout.setContentsMargins(0, 0, 8, 0)
        self.scroll_layout.setSpacing(8)
        
        self.radio_group = QButtonGroup(self)
        self.radio_latest = QRadioButton(self.T("opt_latest"))
        self.radio_latest.setChecked(True)
        self.radio_manual = QRadioButton(self.T("opt_manual"))
        
        self.manual_input_container = QWidget()
        manual_layout = QVBoxLayout(self.manual_input_container)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(4)
        
        self.input_manual = QLineEdit()
        self.input_manual.setMinimumHeight(36)
        
        self.lbl_manual_hint = QLabel(self.T("lbl_manual_hint"))
        self.lbl_manual_hint.setObjectName("HintText")
        self.lbl_manual_hint.setOpenExternalLinks(True)
        self.lbl_manual_hint.setWordWrap(True)
        self.lbl_manual_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.lbl_manual_hint.setStyleSheet("padding-left: 2px; margin-top: 4px; margin-bottom: 2px; line-height: 1.4;")

        self.lbl_datfile_link = QLabel("")
        self.lbl_datfile_link.setObjectName("HintText")
        self.lbl_datfile_link.setOpenExternalLinks(True)
        self.lbl_datfile_link.setWordWrap(True)
        self.lbl_datfile_link.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.lbl_datfile_link.setStyleSheet("padding-left: 2px; margin-bottom: 8px; line-height: 1.4;")
        
        manual_layout.addWidget(self.input_manual)
        manual_layout.addWidget(self.lbl_manual_hint)
        manual_layout.addWidget(self.lbl_datfile_link)
        
        self.manual_input_container.setVisible(False)
        
        def toggle_manual(checked):
            self.manual_input_container.setVisible(checked)
            self.update_manual_input_context()
            
        self.radio_manual.toggled.connect(toggle_manual)
        
        self.radio_group.addButton(self.radio_latest)
        self.radio_group.addButton(self.radio_manual)
        
        self.scroll_layout.addWidget(self.radio_latest)
        self.scroll_layout.addWidget(self.radio_manual)
        self.scroll_layout.addWidget(self.manual_input_container)
        
        self.chk_build_nsp = QCheckBox()
        self.chk_build_nsp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_build_nsp.setVisible(False)
        if hasattr(self, "config"):
            self.chk_build_nsp.setChecked(self.config.get("build_nsp", False))
            
        self.scroll_layout.addWidget(self.chk_build_nsp)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll_area.setWidget(self.scroll_content)
        left_layout.addWidget(self.scroll_area)
        
        self.btn_action = QPushButton(self.T("btn_start"))
        self.btn_action.setObjectName("btnDownload")
        self.btn_action.clicked.connect(self.toggle_download)
        left_layout.addWidget(self.btn_action)
        
        self.grp_live, right_layout, self.lbl_grp_live = self.create_card(self.T("grp_live"))
        right_layout.removeWidget(self.lbl_grp_live)
        
        live_header = QHBoxLayout()
        
        left_container = QWidget()
        left_lay = QHBoxLayout(left_container)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(self.lbl_grp_live)
        left_lay.addStretch(1)
        
        center_container = QWidget()
        center_lay = QHBoxLayout(center_container)
        center_lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_dl_mode = QLabel()
        self.lbl_dl_mode.setObjectName("HintText")
        self.lbl_dl_mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_dl_mode.setStyleSheet("font-weight: 600;")
        center_lay.addWidget(self.lbl_dl_mode)
        
        self.right_container = QWidget()
        self.right_lay = QHBoxLayout(self.right_container)
        self.right_lay.setContentsMargins(0, 0, 0, 0)
        self.right_lay.addStretch(1)
        
        self.btn_clear_console = QPushButton(self.T("btn_clear_console"))
        self.btn_clear_console.setCursor(Qt.CursorShape.PointingHandCursor)
        self.right_lay.addWidget(self.btn_clear_console)
        
        live_header.addWidget(left_container, 1)
        live_header.addWidget(center_container, 1, Qt.AlignmentFlag.AlignCenter)
        live_header.addWidget(self.right_container, 1)
        
        right_layout.insertLayout(0, live_header)
        
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)
        
        self.lbl_progress_pct = QLabel("0%")
        self.lbl_progress_pct.setFixedWidth(38)
        self.lbl_progress_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_progress_pct.setStyleSheet("font-weight: bold;")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        
        progress_layout.addWidget(self.lbl_progress_pct, 0, Qt.AlignmentFlag.AlignVCenter)
        progress_layout.addWidget(self.progress_bar, 1, Qt.AlignmentFlag.AlignVCenter)
        right_layout.addLayout(progress_layout)
        
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth) 
        self.console.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.console.document().setMaximumBlockCount(1000)
        right_layout.addWidget(self.console)
        
        self.btn_clear_console.clicked.connect(self.console.clear)
        
        layout.addWidget(self.grp_target, 1)
        layout.addWidget(self.grp_live, 2)
        
        self.update_dl_mode_label()
        self.update_manual_input_context()

    def setup_credits_tab(self):
        layout = QVBoxLayout(self.tab_credits)
        layout.setContentsMargins(16, 16, 16, 16)
        
        self.grp_credits, credits_layout, self.lbl_credits_title = self.create_card(self.T("credits_header"))
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(SCROLLBAR_CSS)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 8, 0)
        
        self.lbl_credits_text = QLabel(self.T("credits_text"))
        self.lbl_credits_text.setWordWrap(True)
        self.lbl_credits_text.setOpenExternalLinks(True)
        self.lbl_credits_text.setObjectName("DialogText")
        self.lbl_credits_text.setTextFormat(Qt.TextFormat.RichText)
        
        scroll_layout.addWidget(self.lbl_credits_text)
        scroll_layout.addStretch()
        
        scroll.setWidget(scroll_content)
        credits_layout.addWidget(scroll)
        layout.addWidget(self.grp_credits)