# -*- coding: utf-8 -*-
import os
import sys
import json
import shutil
import threading
import queue
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import cv2
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QMenuBar, QMenu,
    QMessageBox, QFileDialog, QGroupBox, QDialog, QTextEdit, QFrame,
    QComboBox
)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("设置" if parent.language == "zh-CN" else "Settings")
        self.resize(450, 180)
        self.setModal(True)

        layout = QVBoxLayout(self)

        lang_group = QGroupBox("语言" if parent.language == "zh-CN" else "Language")
        lang_layout = QVBoxLayout(lang_group)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("选择语言:" if parent.language == "zh-CN" else "Select Language:"))
        self.lang_combo = QComboBox()
        self.refresh_lang_list()
        self.lang_combo.currentIndexChanged.connect(self.on_lang_changed)
        lang_row.addWidget(self.lang_combo)
        lang_layout.addLayout(lang_row)

        import_btn = QPushButton("导入语言包..." if parent.language == "zh-CN" else "Import Language Pack...")
        import_btn.setFixedWidth(140)
        import_btn.setStyleSheet("padding: 6px 12px; font-size: 11pt;")
        import_btn.clicked.connect(self.import_language)
        lang_layout.addWidget(import_btn, alignment=Qt.AlignCenter)

        layout.addWidget(lang_group)

    def refresh_lang_list(self):
        self.lang_combo.clear()
        lang_dir = "Languages"
        if not os.path.exists(lang_dir):
            os.makedirs(lang_dir)
        files = [f for f in os.listdir(lang_dir) if f.endswith(".json")]
        for f in files:
            self.lang_combo.addItem(f)

        current = ""
        if hasattr(self.parent, 'language_file') and self.parent.language_file:
            current = os.path.basename(self.parent.language_file)

        if current and current in files:
            idx = self.lang_combo.findText(current)
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)
        else:
            if not files:
                self.lang_combo.addItem("中文" if self.parent.language == "zh-CN" else "Built-in Chinese")
                self.lang_combo.setCurrentIndex(0)
            else:
                self.lang_combo.setCurrentIndex(0)

    def on_lang_changed(self, index):
        if index < 0:
            return
        lang_file = self.lang_combo.currentText()
        if lang_file in ("中文", "Built-in Chinese"):
            return
        if lang_file:
            self.parent.load_language_from_file(os.path.join("Languages", lang_file))
            QMessageBox.information(self, "提示" if self.parent.language == "zh-CN" else "Info",
                                    "语言已切换，部分界面可能需要重启程序才能完全更新。" if self.parent.language == "zh-CN" else "Language switched. Some UI may need restart to fully update.")

    def import_language(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择语言包文件" if self.parent.language == "zh-CN" else "Select Language Pack",
            "",
            "JSON文件 (*.json);;所有文件 (*)"
        )
        if not file_path:
            return
        lang_dir = "Languages"
        if not os.path.exists(lang_dir):
            os.makedirs(lang_dir)
        target = os.path.join(lang_dir, os.path.basename(file_path))
        try:
            shutil.copy2(file_path, target)
            QMessageBox.information(self, "成功" if self.parent.language == "zh-CN" else "Success",
                                    f"语言包已导入：{os.path.basename(file_path)}" if self.parent.language == "zh-CN" else f"Language pack imported: {os.path.basename(file_path)}")
            self.refresh_lang_list()
            idx = self.lang_combo.findText(os.path.basename(file_path))
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)
                self.on_lang_changed(idx)
        except Exception as e:
            QMessageBox.critical(self, "错误" if self.parent.language == "zh-CN" else "Error",
                                 f"导入失败：{str(e)}" if self.parent.language == "zh-CN" else f"Import failed: {str(e)}")

    def reject(self):
        super().reject()


class MainWindow(QMainWindow):
    progress_signal = Signal(int, int)
    status_signal = Signal(str)
    finish_signal = Signal(int)
    error_signal = Signal(str)
    corrupt_signal = Signal(int)

    def __init__(self):
        super().__init__()
        self.language = "zh-CN"
        self.lang = {}
        self.load_builtin_language()
        self.language_file = None
        self.load_external_language()

        window_width = 1200 if self.language == "en-US" else 900
        window_height = 600
        self.resize(window_width, window_height)
        self.center_window()

        self.setWindowTitle(self.lang["app_title"])
        self.setMinimumSize(750, 500)

        self.video_path = ""
        self.output_dir = ""
        self.total_frames = 0
        self.processing = False
        self.stop_processing = False
        self.worker_threads = []

        self.setup_ui()
        self.create_menu()

        self.progress_signal.connect(self.update_progress)
        self.status_signal.connect(self.update_status)
        self.finish_signal.connect(self.finish_processing)
        self.error_signal.connect(self.show_error)
        self.corrupt_signal.connect(self.show_corrupt_error)

        self.set_window_icon()
        self.apply_light_style()

    def set_window_icon(self):
        ico_path = os.path.join("ico", "VFE_w.ico")
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

    def center_window(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def apply_light_style(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #F2F4F8;
                color: #1E293B;
                font-family: "Segoe UI", "Helvetica", sans-serif;
                font-size: 11pt;
            }
            QGroupBox {
                background-color: #FFFFFF;
                border: 1px solid #D0D7DE;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
                background-color: #FFFFFF;
            }
            QLineEdit {
                background-color: white;
                border: 1px solid #D0D7DE;
                border-radius: 6px;
                padding: 8px 10px;
                selection-background-color: #5B8DEF;
            }
            QLineEdit:focus {
                border-color: #5B8DEF;
            }
            QPushButton {
                background-color: #5B8DEF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4A7FD9;
            }
            QPushButton:pressed {
                background-color: #3A6BC4;
            }
            QPushButton#secondaryBtn {
                background-color: #E2E8F0;
                color: #1E293B;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #CBD5E1;
            }
            QPushButton#secondaryBtn:pressed {
                background-color: #B0BEC5;
            }
            QPushButton#dangerBtn {
                background-color: #EF4444;
                color: white;
            }
            QPushButton#dangerBtn:hover {
                background-color: #DC2626;
            }
            QPushButton#dangerBtn:pressed {
                background-color: #B91C1C;
            }
            QLabel#warningLabel {
                color: #EF4444;
                font-weight: bold;
            }
            QLabel#totalFrames {
                font-weight: bold;
                color: #0F172A;
            }
            QLabel#statusLabel {
                color: #64748B;
            }
            QLabel#versionLabel {
                color: #94A3B8;
                font-size: 10pt;
            }
            QProgressBar {
                background-color: #E2E8F0;
                border-radius: 10px;
                height: 20px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 10px;
            }
            QMenuBar {
                background-color: #F2F4F8;
                color: #1E293B;
            }
            QMenuBar::item:selected {
                background-color: #E2E8F0;
            }
            QMenu {
                background-color: white;
                border: 1px solid #D0D7DE;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #E2E8F0;
            }
        """)

    def load_builtin_language(self):
        self.lang = {
            "app_title": "视频帧提取工具",
            "menu_help": "帮助",
            "menu_instructions": "使用说明",
            "menu_precautions": "注意事项",
            "menu_about": "关于",
            "menu_settings": "设置",
            "label_video_path": "视频文件路径:",
            "label_output_dir": "输出目录路径:",
            "path_warning": "提示：请避免使用以下非法字符：? * < > | \" 以及空格和控制字符（如换行、制表符等）。",
            "label_total_frames": "总帧数：0",
            "label_start_frame": "起始帧:",
            "label_end_frame": "结束帧:",
            "btn_browse": "浏览...",
            "btn_process": "开始处理",
            "btn_stop": "停止处理",
            "btn_extract_all": "全部提取",
            "btn_close": "关闭",
            "status_ready": "就绪",
            "status_processing": "处理中...",
            "status_stopping": "正在停止...",
            "status_stopped": "处理已停止",
            "status_complete": "处理完成！已保存 {0} 帧",
            "version_info": "版本: v7.5 | ShuoDev",
            "instructions_title": "使用说明",
            "instructions_content": "使用说明：\n\n1. 选择视频文件：支持MP4、AVI、MOV、MKV、FLV、WMV格式\n2. 设置输出目录：建议使用空文件夹存放提取结果\n3. 【路径要求】路径不要包含 ? * < > | \" 等非法字符，也不要包含空格和控制字符（如换行符）。\n4. 设置帧范围：\n   - 起始帧：从0开始的帧序号\n   - 结束帧：不超过视频总帧数-1\n5. 点击\"开始处理\"进行提取\n6. 可随时点击\"停止处理\"中断操作\n\n提取的图片将按以下规则保存：\n- 每5000帧自动创建子目录（Part1、Part2...）\n- 图片命名为frame_0000001.jpg格式\n- 处理日志记录在extraction_log.txt中（按Part汇总）\n\n【大文件处理说明】\n- 当您要提取的帧数（结束帧 - 起始帧 + 1）超过 499,999 帧时，程序将拒绝处理，请缩小提取范围。\n- 若提取帧数在 50,000 ~ 499,999 之间，会提示您检查磁盘剩余空间，您可选择继续或取消。\n- 处理过程中请勿关闭窗口或修改输出目录，以免数据损坏。",
            "precautions_title": "注意事项",
            "precautions_content": "注意事项：\n\n【路径要求】\n1. 路径必须避免使用 ? * < > | \" 以及控制字符（如换行、回车、制表符等）\n2. 建议使用纯英文路径以避免潜在兼容性问题，但并非强制\n\n【文件处理】\n1. 请确保输出目录有足够存储空间（建议至少预留视频文件5倍大小）\n2. 处理过程中不要修改输出目录中的文件\n3. 大文件（提取超过5万帧）处理可能耗时较长，请耐心等待\n4. 提取超过50万帧将被拒绝，以防止系统资源耗尽\n\n【性能相关】\n1. 处理时间取决于视频长度和计算机性能\n\n【其他限制】\n1. 不支持加密/DRM保护的视频\n2. 帧数定位精度取决于视频编码格式\n3. 遇到错误时请检查日志文件（extraction_errors.txt，仅在有错误时生成）\n\n版本信息：v7.5 | ShuoDev",
            "error_title": "错误",
            "confirm_title": "确认",
            "confirm_stop": "确定要停止处理吗？",
            "complete_title": "完成",
            "complete_message": "处理完成！",
            "warning_title": "路径警告",
            "warning_message": "警告：路径中包含非法字符（? * < > | \" 或空格和控制字符），可能导致处理失败！\n\n{0}\n{1}\n\n请修改路径，避免使用这些字符。\n是否继续处理？",
            "invalid_frames": "帧范围无效！请确保起始帧在0-{0}之间，且起始帧不大于结束帧",
            "invalid_numbers": "请输入有效的帧号（整数）",
            "no_output_dir": "请选择输出目录",
            "video_open_error": "无法打开视频文件",
            "frame_read_error": "读取第 {0} 帧失败",
            "frame_save_error": "保存第 {0} 帧失败：{1}",
            "log_write_error": "写入日志失败: {0}",
            "dir_create_error": "无法创建输出目录：{0}",
            "log_create_error": "创建日志文件失败: {0}",
            "video_info_error": "获取视频信息失败: {0}",
            "seek_error": "跳转帧时出错: {0}",
            "process_error": "处理过程中发生错误: {0}",
            "large_file_warning": "您将提取 {0} 帧，预估占用约 {1:.1f} GB（范围 {2} ~ {3} GB），建议确保磁盘至少有 {4} GB 可用空间。\n\n是否继续处理？",
            "huge_file_error": "提取帧数过多（{0} 帧），超过 499,999 帧限制，程序无法处理。\n请缩小提取范围（调整起始帧和结束帧）后重试。",
            "corrupt_video_error": "视频可能已损坏：连续 50 帧读取失败，已停止处理。\n已成功保存 {0} 帧。\n请检查视频文件或尝试其他工具。",
            "about_title": "关于 {app_title}",
            "about_version": "版本 {version}",
            "about_description": "一款开源，为专业工作者打造的视频帧提取工具",
            "about_author": "作者：ShuoDev",
            "about_license": "许可证：MIT License",
            "about_copyright": "版权所有 © 2026 ShuoDev",
            "about_github": "GitHub：https://github.com/ShuoDev/Video-Frame-Extractor"
        }

    def load_external_language(self):
        lang_dir = "Languages"
        if not os.path.exists(lang_dir):
            return
        files = [f for f in os.listdir(lang_dir) if f.endswith(".json")]
        if not files:
            return
        first_file = files[0]
        try:
            with open(os.path.join(lang_dir, first_file), 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                self.lang.update(loaded)
                self.language_file = os.path.join(lang_dir, first_file)
                if "language_code" in loaded:
                    self.language = loaded["language_code"]
                else:
                    name = os.path.splitext(first_file)[0]
                    if "_" in name or "-" in name:
                        self.language = name
        except Exception as e:
            print(f"加载外部语言包失败: {e}，继续使用中文。")

    def load_language_from_file(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                self.lang.update(loaded)
                self.language_file = filepath
                if "language_code" in loaded:
                    self.language = loaded["language_code"]
                else:
                    name = os.path.splitext(os.path.basename(filepath))[0]
                    self.language = name
            self.setWindowTitle(self.lang["app_title"])
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载语言文件失败: {e}")

    def create_menu(self):
        menubar = self.menuBar()

        help_menu = menubar.addMenu(self.lang["menu_help"])
        action_inst = QAction(self.lang["menu_instructions"], self)
        action_inst.triggered.connect(self.show_instructions)
        help_menu.addAction(action_inst)

        action_prec = QAction(self.lang["menu_precautions"], self)
        action_prec.triggered.connect(self.show_precautions)
        help_menu.addAction(action_prec)

        help_menu.addSeparator()
        action_about = QAction(self.lang["menu_about"], self)
        action_about.triggered.connect(self.show_about)
        help_menu.addAction(action_about)

        settings_action = QAction(self.lang["menu_settings"], self)
        settings_action.triggered.connect(self.open_settings)
        menubar.addAction(settings_action)

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 20, 20, 20)

        title_layout = QHBoxLayout()
        title_label = QLabel("🎬  " + self.lang["app_title"])
        title_font = QFont("Segoe UI" if os.name == "nt" else "Helvetica", 30, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        title_layout.addWidget(title_label)
        main_layout.addLayout(title_layout)

        file_group = QGroupBox("📁 " + ("文件与路径设置" if self.language == "zh-CN" else "File & Path Settings"))
        file_group.setObjectName("fileGroup")
        file_layout = QVBoxLayout(file_group)

        video_row = QHBoxLayout()
        video_label = QLabel(self.lang["label_video_path"])
        video_label.setMinimumWidth(100)
        self.video_entry = QLineEdit()
        self.video_entry.textChanged.connect(self.update_path_warning)
        self.video_browse_btn = QPushButton(self.lang["btn_browse"])
        self.video_browse_btn.clicked.connect(self.browse_video)
        video_row.addWidget(video_label)
        video_row.addWidget(self.video_entry)
        video_row.addWidget(self.video_browse_btn)
        file_layout.addLayout(video_row)

        output_row = QHBoxLayout()
        output_label = QLabel(self.lang["label_output_dir"])
        output_label.setMinimumWidth(100)
        self.output_entry = QLineEdit()
        self.output_entry.textChanged.connect(self.update_path_warning)
        self.output_browse_btn = QPushButton(self.lang["btn_browse"])
        self.output_browse_btn.clicked.connect(self.browse_output)
        output_row.addWidget(output_label)
        output_row.addWidget(self.output_entry)
        output_row.addWidget(self.output_browse_btn)
        file_layout.addLayout(output_row)

        fixed_warning = QLabel(self.lang["path_warning"])
        fixed_warning.setObjectName("warningLabel")
        fixed_warning.setWordWrap(True)
        file_layout.addWidget(fixed_warning)

        self.path_warning_label = QLabel("")
        self.path_warning_label.setObjectName("warningLabel")
        self.path_warning_label.setWordWrap(True)
        self.path_warning_label.hide()
        file_layout.addWidget(self.path_warning_label)

        main_layout.addWidget(file_group)

        control_group = QGroupBox("⚙️ " + ("提取控制" if self.language == "zh-CN" else "Extraction Control"))
        control_group.setObjectName("controlGroup")
        control_layout = QVBoxLayout(control_group)

        self.total_frames_label = QLabel(self.lang["label_total_frames"])
        self.total_frames_label.setObjectName("totalFrames")
        control_layout.addWidget(self.total_frames_label)

        range_layout = QHBoxLayout()
        start_label = QLabel(self.lang["label_start_frame"])
        self.start_frame_entry = QLineEdit()
        self.start_frame_entry.setFixedWidth(100)
        end_label = QLabel(self.lang["label_end_frame"])
        self.end_frame_entry = QLineEdit()
        self.end_frame_entry.setFixedWidth(100)
        range_layout.addWidget(start_label)
        range_layout.addWidget(self.start_frame_entry)
        range_layout.addSpacing(20)
        range_layout.addWidget(end_label)
        range_layout.addWidget(self.end_frame_entry)
        range_layout.addStretch()
        control_layout.addLayout(range_layout)

        btn_layout = QHBoxLayout()
        self.process_btn = QPushButton(self.lang["btn_process"])
        self.process_btn.setObjectName("primaryBtn")
        self.process_btn.clicked.connect(self.on_process_clicked)
        self.extract_all_btn = QPushButton(self.lang["btn_extract_all"])
        self.extract_all_btn.setObjectName("secondaryBtn")
        self.extract_all_btn.clicked.connect(self.extract_all_frames)
        self.extract_all_btn.hide()
        btn_layout.addWidget(self.process_btn)
        btn_layout.addWidget(self.extract_all_btn)
        btn_layout.addStretch()
        control_layout.addLayout(btn_layout)

        main_layout.addWidget(control_group)

        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setFixedHeight(24)
        progress_layout.addWidget(self.progress_bar)
        main_layout.addLayout(progress_layout)

        self.status_label = QLabel(self.lang["status_ready"])
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setObjectName("statusLabel")
        main_layout.addWidget(self.status_label)

        version_label = QLabel(self.lang["version_info"])
        version_label.setAlignment(Qt.AlignRight)
        version_label.setObjectName("versionLabel")
        main_layout.addWidget(version_label)

    def contains_invalid_chars(self, path):
        if not path:
            return False
        invalid_chars = set('?*<>|"')
        if any(ord(c) < 32 for c in path):
            return True
        if any(c in invalid_chars for c in path):
            return True
        return False

    def update_path_warning(self):
        video_invalid = self.contains_invalid_chars(self.video_entry.text())
        output_invalid = self.contains_invalid_chars(self.output_entry.text())
        if video_invalid or output_invalid:
            warning_text = "⚠️ " + ("警告：" if self.language == "zh-CN" else "Warning: ")
            if video_invalid:
                warning_text += "视频路径包含非法字符（? * < > | \" 或控制字符）" if self.language == "zh-CN" else "Video path contains invalid characters"
            if output_invalid:
                if video_invalid:
                    warning_text += "，且" if self.language == "zh-CN" else ", and "
                warning_text += "输出路径包含非法字符（? * < > | \" 或控制字符）" if self.language == "zh-CN" else "output path contains invalid characters"
            warning_text += "，可能导致处理失败！" if self.language == "zh-CN" else ", may cause processing to fail!"
            self.path_warning_label.setText(warning_text)
            self.path_warning_label.show()
        else:
            self.path_warning_label.hide()

    def browse_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.flv *.wmv);;所有文件 (*)"
        )
        if file_path:
            self.video_entry.setText(file_path)
            self.video_path = file_path
            self.update_path_warning()
            self.get_video_info()

    def browse_output(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_entry.setText(dir_path)
            self.output_dir = dir_path
            self.update_path_warning()

    def get_video_info(self):
        try:
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                QMessageBox.critical(self, self.lang["error_title"], self.lang["video_open_error"])
                return
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.total_frames = total
            self.total_frames_label.setText(
                f"📊 {'总帧数：' if self.language == 'zh-CN' else 'Total Frames: '}{total}"
            )
            if total >= 50000:
                self.status_label.setText(f"ℹ️ 检测到大文件（{total} 帧），提取时请注意范围")

            if total < 5000:
                self.extract_all_btn.show()
            else:
                self.extract_all_btn.hide()

            cap.release()
        except Exception as e:
            QMessageBox.critical(self, self.lang["error_title"],
                                 self.lang["video_info_error"].format(str(e)))

    def estimate_frame_size(self):
        if hasattr(self, '_cached_frame_size'):
            return self._cached_frame_size

        cap = None
        try:
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                return 100 * 1024

            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total <= 0:
                return 100 * 1024

            num_samples = min(10, total)
            if num_samples == 1:
                positions = [0]
            else:
                step = total // (num_samples - 1)
                positions = [i * step for i in range(num_samples)]
                if positions[-1] >= total:
                    positions[-1] = total - 1

            total_size = 0
            count = 0
            for pos in positions:
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue
                _, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                total_size += len(encoded)
                count += 1

            if count > 0:
                avg = total_size / count
                self._cached_frame_size = avg
                return avg
            else:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if width > 0 and height > 0:
                    estimated = width * height * 0.4
                    self._cached_frame_size = max(estimated, 50 * 1024)
                    return self._cached_frame_size
        except Exception as e:
            print(f"估算帧大小失败: {e}")
        finally:
            if cap is not None:
                cap.release()

        return 100 * 1024

    def validate_inputs(self):
        try:
            start = int(self.start_frame_entry.text())
            end = int(self.end_frame_entry.text())
            if start < 0 or end >= self.total_frames or start > end:
                QMessageBox.critical(self, self.lang["error_title"],
                                     self.lang["invalid_frames"].format(self.total_frames - 1))
                return False
            return True
        except ValueError:
            QMessageBox.critical(self, self.lang["error_title"], self.lang["invalid_numbers"])
            return False

    def check_large_file(self, start, end):
        extract_count = end - start + 1
        if extract_count >= 500000:
            QMessageBox.critical(self, self.lang["error_title"],
                                 self.lang["huge_file_error"].format(extract_count))
            return False
        elif extract_count >= 50000:
            avg_frame_size = self.estimate_frame_size()
            total_bytes = extract_count * avg_frame_size
            estimated_gb = total_bytes / (1024 ** 3)
            min_gb = max(0.1, int(total_bytes * 0.7 / (1024 ** 3)))
            max_gb = int(total_bytes * 1.3 / (1024 ** 3)) + 1
            required_gb = int(estimated_gb) + 2

            reply = QMessageBox.question(
                self, self.lang["warning_title"],
                self.lang["large_file_warning"].format(
                    extract_count, estimated_gb, min_gb, max_gb, required_gb
                ),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return False
        return True

    def on_process_clicked(self):
        if self.processing:
            self.confirm_stop_processing()
        else:
            self.start_processing()

    def start_processing(self):
        if self.processing:
            return

        if not self.validate_inputs():
            return

        start = int(self.start_frame_entry.text())
        end = int(self.end_frame_entry.text())

        if not self.check_large_file(start, end):
            return

        output_dir = self.output_entry.text().strip()
        if not output_dir:
            QMessageBox.critical(self, self.lang["error_title"], self.lang["no_output_dir"])
            return

        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                QMessageBox.critical(self, self.lang["error_title"],
                                     self.lang["dir_create_error"].format(str(e)))
                return

        video_path = self.video_path
        video_invalid = self.contains_invalid_chars(video_path)
        output_invalid = self.contains_invalid_chars(output_dir)
        if video_invalid or output_invalid:
            warning_msg = self.lang["warning_message"].format(
                f"{'视频路径' if self.language == 'zh-CN' else 'Video path'}: {video_path}" if video_invalid else "",
                f"{'输出路径' if self.language == 'zh-CN' else 'Output path'}: {output_dir}" if output_invalid else ""
            )
            reply = QMessageBox.question(
                self, self.lang["warning_title"], warning_msg,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        self.processing = True
        self.stop_processing = False
        self.process_btn.setText("⏹ " + self.lang["btn_stop"])
        self.process_btn.setObjectName("dangerBtn")
        self.status_label.setText(self.lang["status_processing"])
        self.status_signal.emit(self.lang["status_processing"])

        self.worker_threads.clear()

        threading.Thread(
            target=self.process_video,
            args=(video_path, output_dir, start, end),
            daemon=True
        ).start()

    def process_video(self, video_path, output_dir, start, end):
        """
        Multi-threaded processing: main thread reads frames, worker threads encode and write concurrently.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            self.error_signal.emit(self.lang["video_open_error"])
            return

        actual_start = self.seek_to_frame(cap, start)
        if actual_start != start:
            self.error_signal.emit(
                f"{'无法定位到起始帧' if self.language == 'zh-CN' else 'Cannot seek to start frame'} {start}，{'实际定位到' if self.language == 'zh-CN' else 'actual position'} {actual_start}"
            )
            cap.release()
            return

        total_to_save = end - start + 1
        saved_count = 0
        consecutive_failures = 0
        error_occurred = False
        error_occurred_lock = threading.Lock()

        log_path = os.path.join(output_dir, "extraction_log.txt")
        try:
            log_file = open(log_path, 'a', encoding='utf-8-sig', errors='ignore')
        except Exception as e:
            self.error_signal.emit(self.lang["log_create_error"].format(str(e)))
            cap.release()
            return

        log_file.write(
            f"\n\n=== {'新的提取任务' if self.language == 'zh-CN' else 'New Extraction Task'} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log_file.write(f"{'视频文件' if self.language == 'zh-CN' else 'Video File'}: {video_path}\n")
        log_file.flush()

        error_log_path = os.path.join(output_dir, "extraction_errors.txt")
        error_file = None
        error_lock = threading.Lock()

        part_lock = threading.Lock()
        current_part = None
        part_start_frame = None
        part_end_frame = None

        progress_lock = threading.Lock()

        task_queue = queue.Queue(maxsize=200)

        def worker():
            nonlocal saved_count, error_occurred, current_part, part_start_frame, part_end_frame
            while True:
                try:
                    item = task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                if item is None:
                    task_queue.task_done()
                    break
                frame_data, frame_num = item

                try:
                    part_num = (frame_num // 5000) + 1
                    part_folder = os.path.join(output_dir, f"Part{part_num}")
                    os.makedirs(part_folder, exist_ok=True)

                    filename = os.path.join(part_folder, f"frame_{frame_num:07d}.jpg")
                    success, encoded = cv2.imencode('.jpg', frame_data, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    if not success:
                        raise IOError("图像编码失败")
                    with open(filename, 'wb') as f:
                        f.write(encoded.tobytes())

                    with part_lock:
                        if current_part is None:
                            current_part = part_num
                            part_start_frame = frame_num
                            part_end_frame = frame_num
                        elif part_num != current_part:
                            log_file.write(f"保存帧 {part_start_frame}-{part_end_frame} 到 Part{current_part}\n")
                            log_file.flush()
                            current_part = part_num
                            part_start_frame = frame_num
                            part_end_frame = frame_num
                        else:
                            if frame_num > part_end_frame:
                                part_end_frame = frame_num

                    with progress_lock:
                        saved_count += 1
                        cur = saved_count
                    if cur % 10 == 0:
                        self.progress_signal.emit(cur, total_to_save)
                        self.status_signal.emit(
                            f"⏳ {'处理进度：' if self.language == 'zh-CN' else 'Processing: '}{cur}/{total_to_save} {'帧' if self.language == 'zh-CN' else 'frames'} ({cur/total_to_save:.1%})"
                        )

                except Exception as e:
                    with error_lock:
                        if error_file is None:
                            try:
                                error_file = open(error_log_path, 'a', encoding='utf-8-sig', errors='ignore')
                            except:
                                pass
                        if error_file:
                            error_file.write(
                                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 帧 {frame_num} 保存失败: {str(e)}\n")
                            error_file.flush()
                    with error_occurred_lock:
                        error_occurred = True
                finally:
                    task_queue.task_done()

        num_workers = max(1, os.cpu_count() - 1) if os.cpu_count() else 4
        num_workers = min(num_workers, 8)
        threads = []
        for _ in range(num_workers):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)
        self.worker_threads = threads

        try:
            for frame_num in range(actual_start, end + 1):
                if self.stop_processing:
                    break

                ret = False
                frame = None
                for retry in range(3):
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        break
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)

                if not ret or frame is None:
                    with error_lock:
                        if error_file is None:
                            try:
                                error_file = open(error_log_path, 'a', encoding='utf-8-sig', errors='ignore')
                            except:
                                pass
                        if error_file:
                            error_file.write(
                                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 帧 {frame_num} 读取失败（重试3次）\n")
                            error_file.flush()
                    consecutive_failures += 1
                    if consecutive_failures > 50:
                        with error_occurred_lock:
                            error_occurred = True
                        break
                    continue
                consecutive_failures = 0

                task_queue.put((frame, frame_num))

            for _ in range(num_workers):
                task_queue.put(None)

            task_queue.join()

        except Exception as e:
            self.error_signal.emit(self.lang["process_error"].format(str(e)))
        finally:
            for t in threads:
                t.join(timeout=1.0)

            with part_lock:
                if current_part is not None:
                    log_file.write(f"保存帧 {part_start_frame}-{part_end_frame} 到 Part{current_part}\n")
                    log_file.flush()

            log_file.close()
            if error_file:
                error_file.close()
            cap.release()

        with error_occurred_lock:
            if error_occurred:
                self.corrupt_signal.emit(saved_count)
            elif self.stop_processing:
                self.finish_signal.emit(saved_count)
            else:
                self.finish_signal.emit(saved_count)

    def seek_to_frame(self, cap, target_frame):
        """
        Fast seek using grab() to skip decoding.
        """
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            actual = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            while actual < target_frame:
                if not cap.grab():
                    break
                actual += 1
            return actual
        except Exception as e:
            self.error_signal.emit(self.lang["seek_error"].format(str(e)))
            return target_frame

    def confirm_stop_processing(self):
        reply = QMessageBox.question(
            self, self.lang["confirm_title"], self.lang["confirm_stop"],
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.stop_requested = True
            self.stop_processing = True
            self.status_signal.emit(self.lang["status_stopping"])
        else:
            self.stop_requested = False

    def extract_all_frames(self):
        if self.total_frames <= 0:
            QMessageBox.warning(self, self.lang["warning_title"],
                                "请先加载视频文件。" if self.language == "zh-CN" else "Please load a video file first.")
            return
        self.start_frame_entry.setText("0")
        self.end_frame_entry.setText(str(self.total_frames - 1))
        self.start_processing()

    def update_progress(self, current, total):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}%")
        self.status_label.setText(
            f"⏳ {'处理进度：' if self.language == 'zh-CN' else 'Processing: '}{current}/{total} {'帧' if self.language == 'zh-CN' else 'frames'} ({current / total:.1%})"
        )

    def update_status(self, text):
        self.status_label.setText(text)

    def finish_processing(self, saved_count):
        self.processing = False
        self.process_btn.setText(self.lang["btn_process"])
        self.process_btn.setObjectName("primaryBtn")
        self.status_label.setText(self.lang["status_complete"].format(saved_count))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.show_custom_complete_dialog(self.lang["complete_message"])

    def show_custom_complete_dialog(self, message):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.lang["complete_title"])
        dialog.setFixedSize(200, 100)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)

        label = QLabel(message)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 12pt;")
        layout.addWidget(label)

        btn = QPushButton("OK")
        btn.setFixedSize(50, 22)
        btn.setStyleSheet("font-size: 9pt; padding: 2px;")
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn, alignment=Qt.AlignCenter)

        dialog.exec()

    def show_error(self, message):
        self.processing = False
        self.process_btn.setText(self.lang["btn_process"])
        self.process_btn.setObjectName("primaryBtn")
        self.status_label.setText(self.lang["status_ready"])
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        QMessageBox.critical(self, self.lang["error_title"], message)

    def show_corrupt_error(self, saved_count):
        self.processing = False
        self.process_btn.setText(self.lang["btn_process"])
        self.process_btn.setObjectName("primaryBtn")
        self.status_label.setText(self.lang["status_ready"])
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        QMessageBox.critical(self, self.lang["error_title"],
                             self.lang["corrupt_video_error"].format(saved_count))

    def show_help_window(self, title, content):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(700, 500)

        layout = QVBoxLayout(dialog)

        title_label = QLabel(title)
        title_font = QFont("Segoe UI" if os.name == "nt" else "Helvetica", 16, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("background-color: white; border: none;")
        layout.addWidget(text_edit)

        close_btn = QPushButton(self.lang["btn_close"])
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        dialog.exec()

    def show_instructions(self):
        self.show_help_window(self.lang["instructions_title"], self.lang["instructions_content"])

    def show_precautions(self):
        self.show_help_window(self.lang["precautions_title"], self.lang["precautions_content"])

    def show_about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.lang["about_title"].format(app_title=self.lang["app_title"]))
        dialog.resize(550, 290)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(6)

        icon_label = QLabel()
        ico_path = os.path.join("ico", "VFE_b.ico")
        if os.path.exists(ico_path):
            pixmap = QPixmap(ico_path)
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel("🎬 " + self.lang["app_title"])
        title_font = QFont("Segoe UI" if os.name == "nt" else "Helvetica", 20, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        version_label = QLabel(self.lang["about_version"].format(version="7.5"))
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        desc_label = QLabel(self.lang["about_description"])
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc_label)

        author_label = QLabel(self.lang["about_author"])
        author_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(author_label)

        license_label = QLabel(self.lang["about_license"])
        license_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(license_label)

        copyright_label = QLabel(self.lang["about_copyright"])
        copyright_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(copyright_label)

        github_layout = QHBoxLayout()
        github_layout.setAlignment(Qt.AlignCenter)
        github_icon_label = QLabel()
        github_ico_path = os.path.join("ico", "Github.ico")
        if os.path.exists(github_ico_path):
            pixmap = QPixmap(github_ico_path)
            if not pixmap.isNull():
                github_icon_label.setPixmap(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        github_layout.addWidget(github_icon_label)

        github_label = QLabel(self.lang["about_github"])
        github_label.setStyleSheet("color: #5B8DEF;")
        github_layout.addWidget(github_label)
        layout.addLayout(github_layout)

        layout.addStretch()
        dialog.exec()

    def closeEvent(self, event):
        if self.processing:
            reply = QMessageBox.question(
                self, self.lang["confirm_title"],
                self.lang["confirm_stop"],
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.stop_processing = True
                for t in self.worker_threads:
                    t.join(timeout=1.0)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())