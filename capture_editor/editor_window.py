import os
import sys
from pathlib import Path

# Ensure project root is in import path.
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QUndoStack,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSlider,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
    QGraphicsTextItem,
)

from capture.region_selector import RegionSelector
from capture.screen_capture import ScreenCaptureService
from capture_editor.canvas.canvas_scene import EditorScene
from capture_editor.canvas.editor_canvas import EditorCanvas
from capture_editor.items.arrow_item import ArrowItem
from capture_editor.items.shape_item import ShapeItem
from capture_editor.items.text_item import TextItem
from capture_editor.tools.arrow_tool import ArrowTool
from capture_editor.tools.shape_tool import ShapeTool
from capture_editor.tools.spotlight_tool import SpotlightTool
from capture_editor.tools.text_tool import TextTool
from capture_editor.utils.export import copy_to_clipboard, export_scene_to_image


class EditorWindow(QMainWindow):
    def __init__(self, image_path: str | None = None, image: QImage | None = None):
        super().__init__()
        self.setWindowTitle("SuperCapture Premium Editor")
        self.resize(1220, 820)

        style_path = Path(__file__).resolve().parent / "styles" / "dark_theme.qss"
        if style_path.exists():
            self.setStyleSheet(style_path.read_text(encoding="utf-8"))

        self.history_stack = QUndoStack(self)
        self.capture_service = ScreenCaptureService()
        self.region_selector: RegionSelector | None = None
        self._fit_pending = False
        self._placed_on_screen = False

        self.arrow_color = QColor("#E94560")
        self.shape_stroke_color = QColor("#0EA5E9")
        self.shape_fill_color = QColor(14, 165, 233, 56)
        self.text_border_color = QColor("#E94560")
        self.text_fill_color = QColor(233, 69, 96, 60)
        self.text_color = QColor("#FFFFFF")
        self.text_stroke_color = QColor("#111827")
        self.text_font_size = 24

        self._init_ui()
        self._init_tools()

        if image is not None and not image.isNull():
            self.load_qimage(image)
        elif image_path:
            self.load_image(image_path)

        self.canvas.imageDropped.connect(self.load_image)
        QTimer.singleShot(0, self._ensure_window_in_screen)

    def _init_ui(self) -> None:
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left tool panel
        self.tool_panel = QWidget()
        self.tool_panel.setObjectName("ToolPanel")
        self.tool_panel.setFixedWidth(90)
        tool_layout = QVBoxLayout(self.tool_panel)
        tool_layout.setContentsMargins(10, 20, 10, 20)
        tool_layout.setSpacing(12)

        self.btn_arrow = QPushButton("Arrow")
        self.btn_shape = QPushButton("Shape")
        self.btn_text = QPushButton("Text")
        self.btn_spotlight = QPushButton("Focus")

        for btn in [self.btn_arrow, self.btn_shape, self.btn_text, self.btn_spotlight]:
            btn.setCheckable(True)
            btn.setProperty("class", "tool-btn")
            tool_layout.addWidget(btn)
            btn.clicked.connect(lambda checked, b=btn: self._on_tool_selected(b))

        tool_layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )
        main_layout.addWidget(self.tool_panel)

        # Center canvas
        self.scene = EditorScene(self)
        self.canvas = EditorCanvas(self.scene, self)
        main_layout.addWidget(self.canvas, stretch=1)

        # Right property panel
        self.property_panel = QWidget()
        self.property_panel.setObjectName("PropertyPanel")
        self.property_panel.setFixedWidth(320)
        prop_layout = QVBoxLayout(self.property_panel)
        prop_layout.setContentsMargins(18, 18, 18, 18)
        prop_layout.setSpacing(10)

        prop_layout.addWidget(QLabel("Thickness"))
        self.slider_width = QSlider(Qt.Orientation.Horizontal)
        self.slider_width.setRange(1, 20)
        self.slider_width.setValue(4)
        self.slider_width.valueChanged.connect(self._on_property_changed)
        prop_layout.addWidget(self.slider_width)

        prop_layout.addWidget(QLabel("Arrow Style"))
        self.combo_arrow = QComboBox()
        self.combo_arrow.addItems(["Straight", "Curved", "Pigtail", "Hand-drawn"])
        self.combo_arrow.currentIndexChanged.connect(self._on_property_changed)
        prop_layout.addWidget(self.combo_arrow)

        self._add_color_row(
            prop_layout,
            "Arrow Color",
            self._line_colors(),
            self._set_arrow_color,
            self.arrow_color,
        )

        prop_layout.addWidget(QLabel("Shape Type"))
        self.combo_shape = QComboBox()
        self.combo_shape.addItems(["Rectangle", "Rounded Rect", "Ellipse", "Diamond", "Line"])
        self.combo_shape.currentIndexChanged.connect(self._on_property_changed)
        prop_layout.addWidget(self.combo_shape)

        self._add_color_row(
            prop_layout,
            "Shape Border",
            self._line_colors(),
            self._set_shape_stroke_color,
            self.shape_stroke_color,
        )
        self._add_color_row(
            prop_layout,
            "Shape Fill",
            self._fill_colors(),
            self._set_shape_fill_color,
            self.shape_fill_color,
        )

        self._add_color_row(
            prop_layout,
            "Box Border",
            self._line_colors(),
            self._set_text_border_color,
            self.text_border_color,
        )
        self._add_color_row(
            prop_layout,
            "Box Color",
            self._fill_colors(),
            self._set_text_fill_color,
            self.text_fill_color,
        )
        self._add_color_row(
            prop_layout,
            "Text Border",
            self._line_colors(),
            self._set_text_stroke_color,
            self.text_stroke_color,
        )
        self._add_color_row(
            prop_layout,
            "Text Color",
            self._text_colors(),
            self._set_text_color,
            self.text_color,
        )

        text_custom_row = QHBoxLayout()
        self.btn_pick_box_border = QPushButton("박스테두리 직접 선택")
        self.btn_pick_box_border.clicked.connect(self._pick_box_border_color)
        text_custom_row.addWidget(self.btn_pick_box_border)

        self.btn_pick_box_fill = QPushButton("박스색 직접 선택")
        self.btn_pick_box_fill.clicked.connect(self._pick_box_fill_color)
        text_custom_row.addWidget(self.btn_pick_box_fill)

        self.btn_pick_text_border = QPushButton("글자테두리 직접 선택")
        self.btn_pick_text_border.clicked.connect(self._pick_text_border_color)
        text_custom_row.addWidget(self.btn_pick_text_border)

        prop_layout.addLayout(text_custom_row)

        text_custom_row_2 = QHBoxLayout()
        self.btn_pick_text_color = QPushButton("텍스트색 직접 선택")
        self.btn_pick_text_color.clicked.connect(self._pick_text_color)
        text_custom_row_2.addWidget(self.btn_pick_text_color)
        prop_layout.addLayout(text_custom_row_2)

        prop_layout.addWidget(QLabel("Text Size"))
        text_size_row = QHBoxLayout()
        self.slider_text_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_text_size.setRange(8, 96)
        self.slider_text_size.setValue(self.text_font_size)
        self.slider_text_size.valueChanged.connect(self._on_text_size_slider_changed)
        text_size_row.addWidget(self.slider_text_size, 1)

        self.spin_text_size = QSpinBox()
        self.spin_text_size.setRange(8, 96)
        self.spin_text_size.setValue(self.text_font_size)
        self.spin_text_size.valueChanged.connect(self._on_text_size_spin_changed)
        text_size_row.addWidget(self.spin_text_size)
        prop_layout.addLayout(text_size_row)

        self.check_text_tail = QCheckBox("Text Tail")
        self.check_text_tail.setChecked(False)
        self.check_text_tail.toggled.connect(self._on_property_changed)
        prop_layout.addWidget(self.check_text_tail)

        prop_layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        self._init_top_toolbar()
        main_layout.addWidget(self.property_panel)

    def _init_top_toolbar(self) -> None:
        toolbar = self.addToolBar("Editor")
        toolbar.setMovable(False)

        action_region_capture = QAction("부분 캡처", self)
        action_region_capture.setShortcut("Ctrl+Shift+C")
        action_region_capture.triggered.connect(self.start_region_capture)
        toolbar.addAction(action_region_capture)

        toolbar.addSeparator()

        action_undo = QAction("실행 취소", self)
        action_undo.setShortcut("Ctrl+Z")
        action_undo.triggered.connect(self.history_stack.undo)
        toolbar.addAction(action_undo)

        action_redo = QAction("다시 실행", self)
        action_redo.setShortcut("Ctrl+Y")
        action_redo.triggered.connect(self.history_stack.redo)
        toolbar.addAction(action_redo)

        toolbar.addSeparator()

        action_copy = QAction("클립보드 복사", self)
        action_copy.setShortcut("Ctrl+Alt+C")
        action_copy.triggered.connect(self.export_clipboard)
        toolbar.addAction(action_copy)

        action_save = QAction("저장", self)
        action_save.setShortcut("Ctrl+S")
        action_save.triggered.connect(self.export_save)
        toolbar.addAction(action_save)

    def _init_tools(self) -> None:
        self.tools = {
            self.btn_arrow: ArrowTool(self.scene, self.history_stack),
            self.btn_shape: ShapeTool(self.scene, self.history_stack),
            self.btn_text: TextTool(self.scene, self.history_stack),
            self.btn_spotlight: SpotlightTool(self.scene, self.history_stack),
        }
        self._on_tool_selected(self.btn_arrow)

    def _line_colors(self) -> list[QColor]:
        return [
            QColor("#E94560"),
            QColor("#0EA5E9"),
            QColor("#22C55E"),
            QColor("#F59E0B"),
            QColor("#A855F7"),
            QColor("#FFFFFF"),
            QColor("#111827"),
        ]

    def _fill_colors(self) -> list[QColor]:
        return [
            QColor(0, 0, 0, 0),
            QColor(233, 69, 96, 60),
            QColor(14, 165, 233, 56),
            QColor(34, 197, 94, 56),
            QColor(245, 158, 11, 70),
            QColor(168, 85, 247, 58),
            QColor(255, 255, 255, 80),
            QColor(17, 24, 39, 115),
        ]

    def _text_colors(self) -> list[QColor]:
        return [
            QColor("#FFFFFF"),
            QColor("#111827"),
            QColor("#F8FAFC"),
            QColor("#FDE68A"),
            QColor("#BFDBFE"),
            QColor("#86EFAC"),
        ]

    def _add_color_row(
        self,
        parent_layout: QVBoxLayout,
        title: str,
        colors: list[QColor],
        on_select,
        initial: QColor,
    ) -> None:
        parent_layout.addWidget(QLabel(title))
        row = QHBoxLayout()
        row.setSpacing(6)

        group = QButtonGroup(self)
        group.setExclusive(True)

        for color in colors:
            btn = QPushButton()
            btn.setProperty("class", "color-swatch")
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            self._style_color_button(btn, color)
            group.addButton(btn)
            row.addWidget(btn)
            btn.clicked.connect(lambda checked=False, c=QColor(color): on_select(c))

            if self._same_color(color, initial):
                btn.setChecked(True)

        parent_layout.addLayout(row)

    def _style_color_button(self, button: QPushButton, color: QColor) -> None:
        if color.alpha() == 0:
            button.setText("X")
            button.setStyleSheet(
                "QPushButton {"
                "background-color: transparent;"
                "border: 2px dashed rgba(255,255,255,0.5);"
                "border-radius: 14px;"
                "font-size: 10px;"
                "font-weight: 700;"
                "color: #e5e7eb;"
                "}"
                "QPushButton:checked { border: 2px solid #ffffff; }"
            )
            return

        button.setText("")
        button.setStyleSheet(
            "QPushButton {"
            f"background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()});"
            "border: 2px solid rgba(255,255,255,0.2);"
            "border-radius: 14px;"
            "}"
            "QPushButton:checked { border: 2px solid #ffffff; }"
        )

    @staticmethod
    def _same_color(a: QColor, b: QColor) -> bool:
        return (
            a.red() == b.red()
            and a.green() == b.green()
            and a.blue() == b.blue()
            and a.alpha() == b.alpha()
        )

    def _set_arrow_color(self, color: QColor) -> None:
        self.arrow_color = QColor(color)
        self._on_property_changed()

    def _set_shape_stroke_color(self, color: QColor) -> None:
        self.shape_stroke_color = QColor(color)
        self._on_property_changed()

    def _set_shape_fill_color(self, color: QColor) -> None:
        self.shape_fill_color = QColor(color)
        self._on_property_changed()

    def _set_text_border_color(self, color: QColor) -> None:
        self.text_border_color = QColor(color)
        self._on_property_changed()

    def _set_text_fill_color(self, color: QColor) -> None:
        self.text_fill_color = QColor(color)
        self._on_property_changed()

    def _set_text_stroke_color(self, color: QColor) -> None:
        self.text_stroke_color = QColor(color)
        self._on_property_changed()

    def _set_text_color(self, color: QColor) -> None:
        self.text_color = QColor(color)
        self._on_property_changed()

    def _pick_text_color(self) -> None:
        color = QColorDialog.getColor(self.text_color, self, "텍스트 색상 선택")
        if color.isValid():
            self._set_text_color(color)

    def _pick_box_border_color(self) -> None:
        color = QColorDialog.getColor(self.text_border_color, self, "박스 테두리색 선택")
        if color.isValid():
            self._set_text_border_color(color)

    def _pick_box_fill_color(self) -> None:
        dialog = QColorDialog(self.text_fill_color, self)
        dialog.setWindowTitle("박스 색상 선택")
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
        if dialog.exec():
            color = dialog.selectedColor()
            if color.isValid():
                self._set_text_fill_color(color)

    def _pick_text_border_color(self) -> None:
        color = QColorDialog.getColor(self.text_stroke_color, self, "글자 테두리색 선택")
        if color.isValid():
            self._set_text_stroke_color(color)

    def _on_text_size_slider_changed(self, value: int) -> None:
        if self.spin_text_size.value() != value:
            self.spin_text_size.blockSignals(True)
            self.spin_text_size.setValue(value)
            self.spin_text_size.blockSignals(False)
        self.text_font_size = value
        self._on_property_changed()

    def _on_text_size_spin_changed(self, value: int) -> None:
        if self.slider_text_size.value() != value:
            self.slider_text_size.blockSignals(True)
            self.slider_text_size.setValue(value)
            self.slider_text_size.blockSignals(False)
        self.text_font_size = value
        self._on_property_changed()

    def _on_tool_selected(self, active_btn: QPushButton) -> None:
        for btn, tool in self.tools.items():
            if btn == active_btn:
                btn.setChecked(True)
                tool.activate()
                self.scene.set_active_tool(tool)
            else:
                btn.setChecked(False)
                tool.deactivate()

        self._on_property_changed()

    def _on_property_changed(self) -> None:
        width = float(self.slider_width.value())

        arrow_style_map = {0: "straight", 1: "straight", 2: "pigtail", 3: "handdrawn"}
        shape_type_map = {0: "rect", 1: "round_rect", 2: "ellipse", 3: "diamond", 4: "line"}

        arrow_tool = self.tools.get(self.btn_arrow)
        if isinstance(arrow_tool, ArrowTool):
            arrow_tool.current_width = width
            arrow_tool.current_style = arrow_style_map.get(self.combo_arrow.currentIndex(), "straight")
            arrow_tool.current_color = QColor(self.arrow_color)

        shape_tool = self.tools.get(self.btn_shape)
        if isinstance(shape_tool, ShapeTool):
            shape_tool.current_width = width
            shape_tool.current_type = shape_type_map.get(self.combo_shape.currentIndex(), "rect")
            shape_tool.current_stroke_color = QColor(self.shape_stroke_color)
            shape_tool.current_fill_color = QColor(self.shape_fill_color)

        text_tool = self.tools.get(self.btn_text)
        if isinstance(text_tool, TextTool):
            text_tool.current_size = int(self.text_font_size)
            text_tool.current_border_color = QColor(self.text_border_color)
            text_tool.current_fill_color = QColor(self.text_fill_color)
            text_tool.current_text_color = QColor(self.text_color)
            text_tool.current_text_stroke_color = QColor(self.text_stroke_color)
            text_tool.current_has_tail = bool(self.check_text_tail.isChecked())

        self._apply_style_to_selected_items(width)

    def _apply_style_to_selected_items(self, width: float) -> None:
        shape_type_map = {0: "rect", 1: "round_rect", 2: "ellipse", 3: "diamond", 4: "line"}
        selected = list(self.scene.selectedItems())

        for raw_item in selected:
            item = raw_item
            if isinstance(item, QGraphicsTextItem) and isinstance(item.parentItem(), TextItem):
                item = item.parentItem()

            if isinstance(item, ArrowItem):
                item.set_color(self.arrow_color)
                item.set_pen_width(width)

            elif isinstance(item, ShapeItem):
                item.set_color(self.shape_stroke_color)
                item.set_fill_color(self.shape_fill_color)
                item.set_pen_width(width)
                item.set_shape_type(shape_type_map.get(self.combo_shape.currentIndex(), "rect"))

            elif isinstance(item, TextItem):
                item.set_style(
                    self.text_border_color,
                    self.text_fill_color,
                    self.text_color,
                    self.text_stroke_color,
                )
                item.set_tail_enabled(self.check_text_tail.isChecked())
                item.set_font_size(int(self.text_font_size))

    def load_image(self, file_path: str) -> None:
        image = QImage(file_path)
        if image.isNull():
            return
        self.load_qimage(image)

    def load_qimage(self, image: QImage) -> None:
        if image.isNull():
            return

        self.scene.set_base_image(image)
        self._fit_pending = True
        QTimer.singleShot(0, self._fit_scene_to_image)

    def _fit_scene_to_image(self) -> None:
        if self.scene.base_image_item is None:
            return

        self.canvas.resetTransform()
        self.canvas.zoom_factor = 1.0
        self.canvas.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

        current_scale = self.canvas.transform().m11()
        min_initial_scale = 0.35
        if current_scale > 0 and current_scale < min_initial_scale:
            up = min_initial_scale / current_scale
            self.canvas.scale(up, up)
            self.canvas.zoom_factor = min_initial_scale
        else:
            self.canvas.zoom_factor = current_scale

        self.canvas.centerOn(self.scene.base_image_item)
        self._fit_pending = False

    def export_clipboard(self) -> None:
        bg_rect = self.scene.base_image_item.boundingRect() if self.scene.base_image_item else None
        img = export_scene_to_image(self.scene, bg_rect)
        copy_to_clipboard(img)
        QMessageBox.information(self, "복사 완료", "이미지가 클립보드에 복사되었습니다.")

    def export_save(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "이미지 저장",
            "",
            "PNG Images (*.png);;JPEG Images (*.jpg)",
        )
        if not file_path:
            return

        bg_rect = self.scene.base_image_item.boundingRect() if self.scene.base_image_item else None
        img = export_scene_to_image(self.scene, bg_rect)
        img.save(file_path, quality=100)
        QMessageBox.information(self, "저장 완료", f"{file_path}\n저장되었습니다.")

    def start_region_capture(self) -> None:
        if self.region_selector is not None:
            return

        self.hide()
        QApplication.processEvents()

        self.region_selector = RegionSelector(border_color="#00AAFF")
        self.region_selector.region_selected.connect(self._on_region_selected)
        self.region_selector.cancelled.connect(self._on_region_cancelled)
        QTimer.singleShot(120, self.region_selector.start)

    def _on_region_selected(self, rect: QRect) -> None:
        self.region_selector = None

        try:
            image = self.capture_service.capture_region(rect)
            self.load_qimage(image)
        except Exception as exc:
            QMessageBox.warning(self, "캡처 실패", f"선택 영역 캡처에 실패했습니다.\n{exc}")
        finally:
            self._restore_from_capture()

    def _on_region_cancelled(self) -> None:
        self.region_selector = None
        self._restore_from_capture()

    def _restore_from_capture(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_window_in_screen()
        if self._fit_pending:
            QTimer.singleShot(0, self._fit_scene_to_image)

    def _ensure_window_in_screen(self) -> None:
        if self._placed_on_screen:
            frame = self.frameGeometry()
            for s in QGuiApplication.screens():
                if frame.intersects(s.availableGeometry()):
                    return

        screen = (
            QGuiApplication.screenAt(QCursor.pos())
            or self.screen()
            or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return

        available = screen.availableGeometry()
        target_w = min(max(640, self.width()), max(640, int(available.width() * 0.95)))
        target_h = min(max(480, self.height()), max(480, int(available.height() * 0.95)))
        target_w = min(target_w, available.width())
        target_h = min(target_h, available.height())

        x = available.x() + (available.width() - target_w) // 2
        y = available.y() + (available.height() - target_h) // 2

        self.setGeometry(x, y, target_w, target_h)
        self._placed_on_screen = True
