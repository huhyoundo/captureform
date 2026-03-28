import sys
import os
from pathlib import Path

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
    
from PyQt6.QtWidgets import QApplication
from capture_editor.editor_window import EditorWindow

def main():
    app = QApplication(sys.argv)
    
    # 테마 적용
    qss_path = Path(os.path.dirname(__file__)) / "styles" / "dark_theme.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
        
    # 샘플 이미지 경로 (인자가 없으면 None)
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    
    window = EditorWindow(image_path)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
