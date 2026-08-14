import sys
import os
import json
import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from PyQt5.QtCore import (
    Qt, QTimer, QThreadPool, QRunnable, QObject, pyqtSignal, QSize,
    QModelIndex, QAbstractListModel, QVariant, QDateTime
)
from PyQt5.QtGui import (
    QPixmap, QIcon, QColor, QFont, QStandardItemModel, QStandardItem,
    QImageReader, QImage, QPainter
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QPushButton, QLabel,
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QFileDialog,
    QMessageBox, QProgressDialog, QCheckBox, QSlider, QGroupBox,
    QFormLayout, QGridLayout, QScrollArea, QToolButton, QMenu,
    QAction, QToolBar, QStatusBar, QAbstractItemView, QListView,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QDateTimeEdit, QRadioButton, QButtonGroup, QDialog, QDialogButtonBox,
    QDateEdit
)
from PIL import Image

# 禁用DecompressionBomb检查，避免大图警告
Image.MAX_IMAGE_PIXELS = None

# 常量
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
THUMBNAIL_SIZE = 160
DEBOUNCE_MS = 200


# ========== 数据结构 ==========
class ImageInfo:
    """图片元数据"""
    def __init__(self, path: str, width: int = 0, height: int = 0,
                 file_size: int = 0, modified: float = 0.0,
                 orientation: str = 'unknown', aspect_ratio: float = 0.0):
        self.path = path
        self.width = width
        self.height = height
        self.file_size = file_size
        self.modified = modified
        self.orientation = orientation
        self.aspect_ratio = aspect_ratio

    def compute_derived(self):
        if self.width > 0 and self.height > 0:
            if abs(self.width - self.height) < 10:
                self.orientation = 'square'
            elif self.width > self.height:
                self.orientation = 'landscape'
            else:
                self.orientation = 'portrait'
            self.aspect_ratio = self.width / self.height
        else:
            self.orientation = 'unknown'
            self.aspect_ratio = 0.0


# ========== 缩略图异步加载 ==========
class ThumbnailLoaderSignals(QObject):
    thumbnail_ready = pyqtSignal(str, QPixmap)
    error = pyqtSignal(str, str)


class ThumbnailLoaderTask(QRunnable):
    def __init__(self, path: str, size: int = THUMBNAIL_SIZE):
        super().__init__()
        self.path = path
        self.size = size
        self.signals = ThumbnailLoaderSignals()

    def run(self):
        try:
            with Image.open(self.path) as img:
                img.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
                img = img.convert('RGBA')
                data = img.tobytes('raw', 'RGBA')
                qimage = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
                pixmap = QPixmap.fromImage(qimage)
                self.signals.thumbnail_ready.emit(self.path, pixmap)
        except Exception as e:
            self.signals.error.emit(self.path, str(e))


# ========== 数据模型 ==========
class ImageListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._images: List[ImageInfo] = []
        self._filtered: List[ImageInfo] = []
        self._thumbnails: Dict[str, QPixmap] = {}
        self._thumbnail_pool = QThreadPool.globalInstance()
        self._loading_paths = set()

    def rowCount(self, parent=QModelIndex()):
        return len(self._filtered)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._filtered)):
            return QVariant()
        img = self._filtered[index.row()]
        if role == Qt.DisplayRole:
            return os.path.basename(img.path)
        elif role == Qt.DecorationRole:
            thumb = self._thumbnails.get(img.path)
            if thumb is None:
                self._request_thumbnail(img.path)
                return self._placeholder_icon()
            return thumb
        elif role == Qt.UserRole:
            return img.path
        elif role == Qt.ToolTipRole:
            return f"{img.width}x{img.height} | {img.file_size/1024:.1f} KB | {img.orientation}"
        return QVariant()

    def _placeholder_icon(self):
        pixmap = QPixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        pixmap.fill(QColor(200, 200, 200))
        return QIcon(pixmap)

    def _request_thumbnail(self, path: str):
        if path in self._loading_paths:
            return
        self._loading_paths.add(path)
        task = ThumbnailLoaderTask(path, THUMBNAIL_SIZE)
        task.signals.thumbnail_ready.connect(self._on_thumbnail_ready)
        task.signals.error.connect(self._on_thumbnail_error)
        self._thumbnail_pool.start(task)

    def _on_thumbnail_ready(self, path: str, pixmap: QPixmap):
        self._thumbnails[path] = pixmap
        self._loading_paths.discard(path)
        for i, img in enumerate(self._filtered):
            if img.path == path:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])
                break

    def _on_thumbnail_error(self, path: str, error: str):
        self._loading_paths.discard(path)

    def set_images(self, images: List[ImageInfo]):
        self.beginResetModel()
        self._images = images
        self._filtered = images.copy()
        self._thumbnails.clear()
        self._loading_paths.clear()
        self.endResetModel()

    def set_filtered(self, filtered: List[ImageInfo]):
        self.beginResetModel()
        self._filtered = filtered
        self.endResetModel()

    def get_image_at(self, index: int) -> Optional[ImageInfo]:
        if 0 <= index < len(self._filtered):
            return self._filtered[index]
        return None

    def clear_thumbnails(self):
        self._thumbnails.clear()
        self._loading_paths.clear()


# ========== 规则引擎 ==========
class Rule:
    FIELD_DEFS = {
        'orientation': {
            'label': '横竖屏',
            'operators': ['is', 'is not'],
            'values': ['landscape', 'portrait', 'square'],
            'default_value': 'landscape',
        },
        'width': {
            'label': '宽度 (px)',
            'operators': ['>=', '<=', 'between'],
            'default_value': 1920,
            'second_value': 3840,
        },
        'height': {
            'label': '高度 (px)',
            'operators': ['>=', '<=', 'between'],
            'default_value': 1080,
            'second_value': 2160,
        },
        'megapixels': {
            'label': '总像素 (MP)',
            'operators': ['>=', '<=', 'between'],
            'default_value': 5,
            'second_value': 20,
        },
        'aspect_ratio': {
            'label': '长宽比',
            'operators': ['equals', 'approx'],
            'default_value': 16/9,
            'second_value': 0.05,
        },
        'file_size': {
            'label': '文件大小',
            'operators': ['>=', '<=', 'between'],
            'default_value': 1.0,
            'second_value': 10.0,
            'unit': 'MB',
        },
        'extension': {
            'label': '扩展名',
            'operators': ['in', 'not in'],
            'default_value': '.jpg,.png',
        },
        'filename': {
            'label': '文件名',
            'operators': ['contains', 'regex'],
            'default_value': '',
        },
        'date_modified': {
            'label': '修改日期',
            'operators': ['after', 'before', 'range'],
            'default_value': None,
        },
    }

    def __init__(self, field: str, operator: str, value: Any, second_value: Any = None):
        self.field = field
        self.operator = operator
        self.value = value
        self.second_value = second_value
        self.enabled = True

    def matches(self, img: ImageInfo) -> bool:
        if not self.enabled:
            return True
        val = self.value
        if self.field == 'orientation':
            if self.operator == 'is':
                return img.orientation == val
            elif self.operator == 'is not':
                return img.orientation != val
        elif self.field == 'width':
            if self.operator == '>=':
                return img.width >= val
            elif self.operator == '<=':
                return img.width <= val
            elif self.operator == 'between':
                return val <= img.width <= self.second_value
        elif self.field == 'height':
            if self.operator == '>=':
                return img.height >= val
            elif self.operator == '<=':
                return img.height <= val
            elif self.operator == 'between':
                return val <= img.height <= self.second_value
        elif self.field == 'megapixels':
            mp = (img.width * img.height) / 1_000_000
            if self.operator == '>=':
                return mp >= val
            elif self.operator == '<=':
                return mp <= val
            elif self.operator == 'between':
                return val <= mp <= self.second_value
        elif self.field == 'aspect_ratio':
            if self.operator == 'equals':
                return abs(img.aspect_ratio - val) < 0.01
            elif self.operator == 'approx':
                tolerance = self.second_value if self.second_value is not None else 0.05
                return abs(img.aspect_ratio - val) <= tolerance
        elif self.field == 'file_size':
            size_mb = img.file_size / (1024 * 1024)
            if self.operator == '>=':
                return size_mb >= val
            elif self.operator == '<=':
                return size_mb <= val
            elif self.operator == 'between':
                return val <= size_mb <= self.second_value
        elif self.field == 'extension':
            ext = os.path.splitext(img.path)[1].lower()
            if self.operator == 'in':
                return ext in [e.strip().lower() for e in val.split(',')]
            elif self.operator == 'not in':
                return ext not in [e.strip().lower() for e in val.split(',')]
        elif self.field == 'filename':
            name = os.path.basename(img.path)
            if self.operator == 'contains':
                return val.lower() in name.lower()
            elif self.operator == 'regex':
                try:
                    return re.search(val, name, re.IGNORECASE) is not None
                except re.error:
                    return False
        elif self.field == 'date_modified':
            mod = datetime.fromtimestamp(img.modified)
            if self.operator == 'after':
                return mod > val
            elif self.operator == 'before':
                return mod < val
            elif self.operator == 'range':
                return self.second_value and val <= mod <= self.second_value
        return False

    def to_dict(self):
        return {
            'field': self.field,
            'operator': self.operator,
            'value': self.value,
            'second_value': self.second_value,
            'enabled': self.enabled,
        }

    @staticmethod
    def from_dict(data: dict):
        return Rule(
            field=data['field'],
            operator=data['operator'],
            value=data['value'],
            second_value=data.get('second_value'),
        )


class RuleEngine:
    def __init__(self):
        self.rules: List[Rule] = []
        self.logic = 'AND'

    def add_rule(self, rule: Rule):
        self.rules.append(rule)

    def remove_rule(self, index: int):
        if 0 <= index < len(self.rules):
            del self.rules[index]

    def clear_rules(self):
        self.rules.clear()

    def set_logic(self, logic: str):
        self.logic = logic

    def apply(self, images: List[ImageInfo]) -> List[ImageInfo]:
        if not self.rules:
            return images.copy()
        if self.logic == 'AND':
            return [img for img in images if all(rule.matches(img) for rule in self.rules)]
        else:
            return [img for img in images if any(rule.matches(img) for rule in self.rules)]


# ========== 文件夹扫描器 ==========
class FolderScannerSignals(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)


class FolderScanner(QRunnable):
    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path
        self.signals = FolderScannerSignals()

    def run(self):
        try:
            files = []
            for root, dirs, filenames in os.walk(self.folder_path):
                for fname in filenames:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in IMAGE_EXTENSIONS:
                        files.append(os.path.join(root, fname))
            total = len(files)
            images = []
            for i, path in enumerate(files):
                self.signals.progress.emit(i + 1, total)
                try:
                    stat = os.stat(path)
                    file_size = stat.st_size
                    modified = stat.st_mtime
                    width, height = 0, 0
                    try:
                        with Image.open(path) as img:
                            width, height = img.size
                    except Exception:
                        pass
                    img_info = ImageInfo(
                        path=path,
                        width=width,
                        height=height,
                        file_size=file_size,
                        modified=modified,
                    )
                    img_info.compute_derived()
                    images.append(img_info)
                except Exception:
                    continue
            self.signals.finished.emit(images)
        except Exception as e:
            self.signals.error.emit(str(e))


# ========== 规则编辑控件 ==========
class RuleWidget(QWidget):
    remove_requested = pyqtSignal(object)
    changed = pyqtSignal()

    def __init__(self, rule: Rule, parent=None):
        super().__init__(parent)
        self.rule = rule
        self.init_ui()
        self.update_ui_from_rule()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 2, 4, 2)

        self.remove_btn = QToolButton()
        self.remove_btn.setText('✕')
        self.remove_btn.clicked.connect(self._on_remove)
        layout.addWidget(self.remove_btn)

        self.field_combo = QComboBox()
        for field_key, field_def in Rule.FIELD_DEFS.items():
            self.field_combo.addItem(field_def['label'], field_key)
        self.field_combo.currentIndexChanged.connect(self._on_field_changed)
        layout.addWidget(self.field_combo)

        self.op_combo = QComboBox()
        layout.addWidget(self.op_combo)

        self.value_container = QWidget()
        self.value_layout = QHBoxLayout()
        self.value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_container.setLayout(self.value_layout)
        layout.addWidget(self.value_container, 1)

        self.setLayout(layout)

        # 初始化操作符和值控件，确保 value_widget 存在
        self._update_operators()
        self._update_value_widgets()

        # 连接操作符变化信号
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)

    def _on_remove(self):
        self.remove_requested.emit(self)

    def _on_field_changed(self):
        self._update_operators()
        self._update_value_widgets()
        self.changed.emit()

    def _on_op_changed(self):
        self._update_value_widgets()
        self.changed.emit()

    def _update_operators(self):
        field_key = self.field_combo.currentData()
        field_def = Rule.FIELD_DEFS[field_key]
        self.op_combo.clear()
        for op in field_def['operators']:
            self.op_combo.addItem(op, op)

    def _update_value_widgets(self):
        # 清空值区域
        while self.value_layout.count():
            item = self.value_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        field_key = self.field_combo.currentData()
        field_def = Rule.FIELD_DEFS[field_key]

        if field_key == 'orientation':
            combo = QComboBox()
            for val in field_def['values']:
                combo.addItem(val, val)
            self.value_layout.addWidget(combo)
            self.value_widget = combo
            self.second_value_widget = None
        elif field_key in ('width', 'height', 'megapixels'):
            if self.op_combo.currentText() == 'between':
                spin1 = QSpinBox()
                spin1.setRange(0, 100000)
                spin1.setSuffix(' px' if field_key in ('width', 'height') else ' MP')
                spin2 = QSpinBox()
                spin2.setRange(0, 100000)
                spin2.setSuffix(' px' if field_key in ('width', 'height') else ' MP')
                self.value_layout.addWidget(spin1)
                self.value_layout.addWidget(QLabel('~'))
                self.value_layout.addWidget(spin2)
                self.value_widget = spin1
                self.second_value_widget = spin2
            else:
                spin = QSpinBox()
                spin.setRange(0, 100000)
                spin.setSuffix(' px' if field_key in ('width', 'height') else ' MP')
                self.value_layout.addWidget(spin)
                self.value_widget = spin
                self.second_value_widget = None
        elif field_key == 'aspect_ratio':
            combo = QComboBox()
            ratios = {
                '16:9': 16/9,
                '4:3': 4/3,
                '1:1': 1.0,
                '3:2': 3/2,
                '21:9': 21/9,
            }
            for label, ratio in ratios.items():
                combo.addItem(label, ratio)
            self.value_layout.addWidget(combo)
            self.value_widget = combo
            if self.op_combo.currentText() == 'approx':
                slider = QSlider(Qt.Horizontal)
                slider.setRange(0, 30)
                slider.setValue(5)
                slider.setTickInterval(5)
                self.value_layout.addWidget(slider)
                self.second_value_widget = slider
            else:
                self.second_value_widget = None
        elif field_key == 'file_size':
            if self.op_combo.currentText() == 'between':
                spin1 = QDoubleSpinBox()
                spin1.setRange(0, 100000)
                spin1.setSuffix(' MB')
                spin2 = QDoubleSpinBox()
                spin2.setRange(0, 100000)
                spin2.setSuffix(' MB')
                self.value_layout.addWidget(spin1)
                self.value_layout.addWidget(QLabel('~'))
                self.value_layout.addWidget(spin2)
                self.value_widget = spin1
                self.second_value_widget = spin2
            else:
                spin = QDoubleSpinBox()
                spin.setRange(0, 100000)
                spin.setSuffix(' MB')
                self.value_layout.addWidget(spin)
                self.value_widget = spin
                self.second_value_widget = None
        elif field_key == 'extension':
            edit = QLineEdit()
            edit.setPlaceholderText('.jpg, .png')
            self.value_layout.addWidget(edit)
            self.value_widget = edit
            self.second_value_widget = None
        elif field_key == 'filename':
            edit = QLineEdit()
            edit.setPlaceholderText('关键词或正则')
            self.value_layout.addWidget(edit)
            self.value_widget = edit
            self.second_value_widget = None
        elif field_key == 'date_modified':
            if self.op_combo.currentText() == 'range':
                date1 = QDateTimeEdit(QDateTime.currentDateTime())
                date1.setCalendarPopup(True)
                date2 = QDateTimeEdit(QDateTime.currentDateTime())
                date2.setCalendarPopup(True)
                self.value_layout.addWidget(date1)
                self.value_layout.addWidget(QLabel('~'))
                self.value_layout.addWidget(date2)
                self.value_widget = date1
                self.second_value_widget = date2
            else:
                date_edit = QDateTimeEdit(QDateTime.currentDateTime())
                date_edit.setCalendarPopup(True)
                self.value_layout.addWidget(date_edit)
                self.value_widget = date_edit
                self.second_value_widget = None

        # 连接值控件的信号
        if hasattr(self, 'value_widget') and self.value_widget is not None:
            if isinstance(self.value_widget, QComboBox):
                self.value_widget.currentIndexChanged.connect(self.changed.emit)
            elif isinstance(self.value_widget, QSpinBox):
                self.value_widget.valueChanged.connect(self.changed.emit)
            elif isinstance(self.value_widget, QDoubleSpinBox):
                self.value_widget.valueChanged.connect(self.changed.emit)
            elif isinstance(self.value_widget, QLineEdit):
                self.value_widget.textChanged.connect(self.changed.emit)
            elif isinstance(self.value_widget, QDateTimeEdit):
                self.value_widget.dateTimeChanged.connect(self.changed.emit)
            elif isinstance(self.value_widget, QSlider):
                self.value_widget.valueChanged.connect(self.changed.emit)
        if hasattr(self, 'second_value_widget') and self.second_value_widget is not None:
            if isinstance(self.second_value_widget, QSpinBox):
                self.second_value_widget.valueChanged.connect(self.changed.emit)
            elif isinstance(self.second_value_widget, QDoubleSpinBox):
                self.second_value_widget.valueChanged.connect(self.changed.emit)
            elif isinstance(self.second_value_widget, QDateTimeEdit):
                self.second_value_widget.dateTimeChanged.connect(self.changed.emit)
            elif isinstance(self.second_value_widget, QSlider):
                self.second_value_widget.valueChanged.connect(self.changed.emit)

    def update_ui_from_rule(self):
        idx = self.field_combo.findData(self.rule.field)
        if idx >= 0:
            self.field_combo.setCurrentIndex(idx)  # 可能不触发信号
        self._update_operators()
        op_idx = self.op_combo.findData(self.rule.operator)
        if op_idx >= 0:
            self.op_combo.setCurrentIndex(op_idx)  # 触发 _on_op_changed，更新值控件
        # 设置值
        if hasattr(self, 'value_widget') and self.value_widget is not None:
            if isinstance(self.value_widget, QComboBox):
                v_idx = self.value_widget.findData(self.rule.value)
                if v_idx >= 0:
                    self.value_widget.setCurrentIndex(v_idx)
            elif isinstance(self.value_widget, (QSpinBox, QDoubleSpinBox)):
                self.value_widget.setValue(self.rule.value)
            elif isinstance(self.value_widget, QLineEdit):
                self.value_widget.setText(str(self.rule.value))
            elif isinstance(self.value_widget, QDateTimeEdit):
                if isinstance(self.rule.value, datetime):
                    self.value_widget.setDateTime(self.rule.value)
        if hasattr(self, 'second_value_widget') and self.second_value_widget is not None:
            if isinstance(self.second_value_widget, (QSpinBox, QDoubleSpinBox)):
                self.second_value_widget.setValue(self.rule.second_value or 0)
            elif isinstance(self.second_value_widget, QDateTimeEdit):
                if isinstance(self.rule.second_value, datetime):
                    self.second_value_widget.setDateTime(self.rule.second_value)
            elif isinstance(self.second_value_widget, QSlider):
                tolerance = self.rule.second_value if self.rule.second_value else 0.05
                self.second_value_widget.setValue(int(tolerance * 100))

    def collect_rule(self) -> Rule:
        field = self.field_combo.currentData()
        operator = self.op_combo.currentText()
        value = None
        second_value = None

        if field == 'orientation':
            value = self.value_widget.currentData()
        elif field in ('width', 'height', 'megapixels'):
            value = self.value_widget.value()
            if self.second_value_widget:
                second_value = self.second_value_widget.value()
        elif field == 'aspect_ratio':
            value = self.value_widget.currentData()
            if self.second_value_widget:
                second_value = self.second_value_widget.value() / 100.0
        elif field == 'file_size':
            value = self.value_widget.value()
            if self.second_value_widget:
                second_value = self.second_value_widget.value()
        elif field == 'extension':
            value = self.value_widget.text()
        elif field == 'filename':
            value = self.value_widget.text()
        elif field == 'date_modified':
            value = self.value_widget.dateTime().toPyDateTime()
            if self.second_value_widget:
                second_value = self.second_value_widget.dateTime().toPyDateTime()

        return Rule(field=field, operator=operator, value=value, second_value=second_value)


# ========== 主窗口 ==========
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Lens Pro - 图片筛选工具')
        self.resize(1400, 900)

        self.all_images: List[ImageInfo] = []
        self.folder_list: List[str] = []
        self.rules_engine = RuleEngine()
        self.model = ImageListModel()
        self.current_filtered: List[ImageInfo] = []

        self.scan_pool = QThreadPool.globalInstance()

        # 防抖定时器
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.apply_filters)

        self.init_ui()
        self.statusBar().showMessage('就绪')

    def init_ui(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('文件')
        add_folder_action = QAction('添加文件夹', self)
        add_folder_action.triggered.connect(self.add_folders)
        file_menu.addAction(add_folder_action)
        file_menu.addSeparator()
        exit_action = QAction('退出', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menubar.addMenu('视图')
        refresh_action = QAction('刷新索引', self)
        refresh_action.triggered.connect(self.refresh_all)
        view_menu.addAction(refresh_action)

        toolbar = QToolBar()
        self.addToolBar(toolbar)
        toolbar.addAction(add_folder_action)
        toolbar.addAction(refresh_action)

        central_splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(central_splitter)

        # 左面板
        self.folder_panel = QWidget()
        folder_layout = QVBoxLayout(self.folder_panel)
        folder_layout.setContentsMargins(5, 5, 5, 5)

        folder_header = QHBoxLayout()
        folder_label = QLabel('文件夹')
        folder_label.setFont(QFont('Arial', 10, QFont.Bold))
        folder_header.addWidget(folder_label)
        folder_header.addStretch()
        add_btn = QPushButton('+ 添加')
        add_btn.clicked.connect(self.add_folders)
        folder_header.addWidget(add_btn)
        folder_layout.addLayout(folder_header)

        self.folder_list_widget = QListWidget()
        self.folder_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list_widget.customContextMenuRequested.connect(self.show_folder_context_menu)
        folder_layout.addWidget(self.folder_list_widget)

        refresh_btn = QPushButton('🔄 刷新选中索引')
        refresh_btn.clicked.connect(self.refresh_selected_folder)
        folder_layout.addWidget(refresh_btn)

        # 右面板
        self.rules_panel = QWidget()
        rules_layout = QVBoxLayout(self.rules_panel)
        rules_layout.setContentsMargins(5, 5, 5, 5)

        rules_header = QLabel('筛选规则')
        rules_header.setFont(QFont('Arial', 10, QFont.Bold))
        rules_layout.addWidget(rules_header)

        logic_group = QGroupBox('逻辑关系')
        logic_layout = QHBoxLayout()
        self.and_radio = QRadioButton('AND (且)')
        self.or_radio = QRadioButton('OR (或)')
        self.and_radio.setChecked(True)
        self.and_radio.toggled.connect(self.on_logic_changed)
        logic_layout.addWidget(self.and_radio)
        logic_layout.addWidget(self.or_radio)
        logic_group.setLayout(logic_layout)
        rules_layout.addWidget(logic_group)

        self.rules_scroll = QScrollArea()
        self.rules_scroll.setWidgetResizable(True)
        self.rules_container = QWidget()
        self.rules_layout = QVBoxLayout(self.rules_container)
        self.rules_layout.setAlignment(Qt.AlignTop)
        self.rules_scroll.setWidget(self.rules_container)
        rules_layout.addWidget(self.rules_scroll, 1)

        btn_layout = QHBoxLayout()
        add_rule_btn = QPushButton('➕ 添加规则')
        # 使用 lambda 避免传递布尔参数
        add_rule_btn.clicked.connect(lambda: self.add_rule_widget())
        clear_rules_btn = QPushButton('🗑️ 清空规则')
        clear_rules_btn.clicked.connect(self.clear_rules)
        btn_layout.addWidget(add_rule_btn)
        btn_layout.addWidget(clear_rules_btn)
        rules_layout.addLayout(btn_layout)

        self.hit_label = QLabel('命中: 0 张')
        self.hit_label.setFont(QFont('Arial', 10, QFont.Bold))
        rules_layout.addWidget(self.hit_label)

        # 中部视图
        self.image_view = QListView()
        self.image_view.setModel(self.model)
        self.image_view.setViewMode(QListView.IconMode)
        self.image_view.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.image_view.setResizeMode(QListView.Adjust)
        self.image_view.setUniformItemSizes(True)
        self.image_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.image_view.setWordWrap(True)
        self.image_view.doubleClicked.connect(self.open_image)

        central_splitter.addWidget(self.folder_panel)
        central_splitter.addWidget(self.image_view)
        central_splitter.addWidget(self.rules_panel)
        central_splitter.setStretchFactor(0, 1)
        central_splitter.setStretchFactor(1, 4)
        central_splitter.setStretchFactor(2, 2)

        # 底部状态栏
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(5, 2, 5, 2)

        self.total_label = QLabel('总计: 0 张')
        status_layout.addWidget(self.total_label)

        status_layout.addStretch()

        export_label = QLabel('导出到:')
        status_layout.addWidget(export_label)
        self.export_path_edit = QLineEdit()
        self.export_path_edit.setPlaceholderText('选择目标文件夹...')
        self.export_path_edit.setFixedWidth(300)
        status_layout.addWidget(self.export_path_edit)
        browse_btn = QPushButton('浏览...')
        browse_btn.clicked.connect(self.browse_export_folder)
        status_layout.addWidget(browse_btn)

        self.export_btn = QPushButton('🚀 导出')
        self.export_btn.clicked.connect(self.export_images)
        status_layout.addWidget(self.export_btn)

        self.statusBar().addPermanentWidget(status_widget, 1)

        # 初始规则
        self.add_default_rule()

    # ---------- 文件夹管理 ----------
    def add_folders(self):
        dirs = QFileDialog.getExistingDirectory(
            self, '选择文件夹', '', QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if not dirs:
            return
        if dirs not in self.folder_list:
            self.folder_list.append(dirs)
            item = QListWidgetItem(dirs)
            self.folder_list_widget.addItem(item)
            self.scan_folder(dirs)

    def scan_folder(self, folder: str):
        scanner = FolderScanner(folder)
        scanner.signals.progress.connect(self.on_scan_progress)
        scanner.signals.finished.connect(self.on_scan_finished)
        scanner.signals.error.connect(self.on_scan_error)
        self.scan_pool.start(scanner)

    def on_scan_progress(self, current, total):
        self.statusBar().showMessage(f'扫描中... {current}/{total}')

    def on_scan_finished(self, images: List[ImageInfo]):
        existing_paths = {img.path for img in self.all_images}
        new_images = [img for img in images if img.path not in existing_paths]
        self.all_images.extend(new_images)
        self.total_label.setText(f'总计: {len(self.all_images)} 张')
        self.statusBar().showMessage(f'扫描完成，新增 {len(new_images)} 张')
        self.model.set_images(self.all_images)
        self.apply_filters()

    def on_scan_error(self, error: str):
        QMessageBox.warning(self, '扫描错误', error)

    def refresh_all(self):
        self.all_images.clear()
        self.model.set_images([])
        self.total_label.setText('总计: 0 张')
        for folder in self.folder_list:
            self.scan_folder(folder)

    def refresh_selected_folder(self):
        selected_items = self.folder_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, '提示', '请先选择一个文件夹')
            return
        folder = selected_items[0].text()
        self.all_images = [img for img in self.all_images if not img.path.startswith(folder)]
        self.model.set_images(self.all_images)
        self.total_label.setText(f'总计: {len(self.all_images)} 张')
        self.scan_folder(folder)

    def show_folder_context_menu(self, pos):
        menu = QMenu()
        remove_action = menu.addAction('移除文件夹')
        remove_action.triggered.connect(self.remove_selected_folder)
        menu.exec_(self.folder_list_widget.mapToGlobal(pos))

    def remove_selected_folder(self):
        selected_items = self.folder_list_widget.selectedItems()
        if not selected_items:
            return
        folder = selected_items[0].text()
        self.all_images = [img for img in self.all_images if not img.path.startswith(folder)]
        self.folder_list.remove(folder)
        self.folder_list_widget.takeItem(self.folder_list_widget.row(selected_items[0]))
        self.model.set_images(self.all_images)
        self.total_label.setText(f'总计: {len(self.all_images)} 张')
        self.apply_filters()

    # ---------- 规则管理 ----------
    def add_default_rule(self):
        rule = Rule(field='orientation', operator='is', value='landscape')
        self.add_rule_widget(rule)

    def add_rule_widget(self, rule: Optional[Rule] = None):
        # 兼容按钮点击可能传入的 bool 参数
        if rule is None or isinstance(rule, bool):
            rule = Rule(field='width', operator='>=', value=1920)
        widget = RuleWidget(rule)
        widget.remove_requested.connect(self.remove_rule_widget)
        widget.changed.connect(self.schedule_filter)
        self.rules_layout.addWidget(widget)
        self.rules_engine.add_rule(rule)
        self.schedule_filter()

    def remove_rule_widget(self, widget: RuleWidget):
        idx = self.rules_layout.indexOf(widget)
        if idx >= 0:
            self.rules_layout.removeWidget(widget)
            widget.deleteLater()
            self.rules_engine.remove_rule(idx)
        self.schedule_filter()

    def clear_rules(self):
        while self.rules_layout.count():
            item = self.rules_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.rules_engine.clear_rules()
        self.schedule_filter()

    def on_logic_changed(self):
        if self.and_radio.isChecked():
            self.rules_engine.set_logic('AND')
        else:
            self.rules_engine.set_logic('OR')
        self.schedule_filter()

    def schedule_filter(self):
        self.debounce_timer.start(DEBOUNCE_MS)

    def apply_filters(self):
        self.rules_engine.rules.clear()
        for i in range(self.rules_layout.count()):
            widget = self.rules_layout.itemAt(i).widget()
            if isinstance(widget, RuleWidget):
                rule = widget.collect_rule()
                self.rules_engine.add_rule(rule)

        filtered = self.rules_engine.apply(self.all_images)
        self.current_filtered = filtered
        self.model.set_filtered(filtered)
        self.hit_label.setText(f'命中: {len(filtered)} 张')

    # ---------- 缩略图视图 ----------
    def open_image(self, index):
        img = self.model.get_image_at(index.row())
        if img:
            os.startfile(img.path)

    # ---------- 导出功能 ----------
    def browse_export_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择导出文件夹')
        if folder:
            self.export_path_edit.setText(folder)

    def export_images(self):
        if not self.current_filtered:
            QMessageBox.information(self, '提示', '没有可导出的图片')
            return
        export_folder = self.export_path_edit.text().strip()
        if not export_folder:
            QMessageBox.warning(self, '提示', '请先选择导出文件夹')
            return
        if not os.path.isdir(export_folder):
            QMessageBox.warning(self, '提示', '导出文件夹不存在')
            return

        dialog = ExportDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return
        flatten = dialog.flatten_radio.isChecked()
        copy_mode = dialog.copy_radio.isChecked()  # 是否复制（否则移动）
        self.export_worker(export_folder, self.current_filtered, flatten, copy_mode)

    def export_worker(self, dest_folder: str, images: List[ImageInfo], flatten: bool, copy_mode: bool):
        progress = QProgressDialog('导出中...', '取消', 0, len(images), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        count = 0
        errors = []
        for i, img in enumerate(images):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            source = img.path
            if flatten:
                dest = os.path.join(dest_folder, os.path.basename(source))
            else:
                rel_path = source.replace(':', '').lstrip('\\/')
                dest = os.path.join(dest_folder, rel_path)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                if os.path.exists(dest):
                    base, ext = os.path.splitext(dest)
                    counter = 1
                    while os.path.exists(f"{base}_{counter}{ext}"):
                        counter += 1
                    dest = f"{base}_{counter}{ext}"
                if copy_mode:
                    shutil.copy2(source, dest)
                else:
                    shutil.move(source, dest)
                count += 1
            except Exception as e:
                errors.append(f"{source}: {str(e)}")
            progress.setValue(i + 1)
        progress.close()
        msg = f'导出完成，成功 {count} 张'
        if errors:
            msg += f'\n失败 {len(errors)} 张:\n' + '\n'.join(errors[:10])
        QMessageBox.information(self, '导出结果', msg)


class ExportDialog(QDialog):
    """导出选项对话框，包含复制/移动和目录结构选项"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('导出选项')
        layout = QVBoxLayout(self)

        # 目录结构
        self.flatten_radio = QRadioButton('平铺导出（所有文件放到目标根目录）')
        self.preserve_radio = QRadioButton('保留目录结构（重建子文件夹）')
        self.flatten_radio.setChecked(True)

        layout.addWidget(QLabel('目录结构:'))
        layout.addWidget(self.flatten_radio)
        layout.addWidget(self.preserve_radio)

        # 操作方式
        layout.addSpacing(10)
        self.copy_radio = QRadioButton('复制到文件夹（保留原文件）')
        self.move_radio = QRadioButton('移动到文件夹（删除原文件）')
        self.copy_radio.setChecked(True)

        layout.addWidget(QLabel('操作方式:'))
        layout.addWidget(self.copy_radio)
        layout.addWidget(self.move_radio)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()