#!/usr/bin/env python3
"""
AOSP Payload Dumper GUI
Modern UI for extracting Android OTA payloads.
v2.0.0
"""

import sys
import os
import json
import threading
import time
import subprocess
import platform
from pathlib import Path
from typing import Optional, Dict, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar, 
    QFileDialog, QMessageBox, QCheckBox, QListWidget, QTabWidget,
    QGroupBox, QSplitter, QStatusBar, QMenuBar, QDialog, QDialogButtonBox,
    QListWidgetItem, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QSize, QPoint
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPalette, QColor, QAction

try:
    import payload_core
except ImportError as e:
    print(f"Error: Cannot import payload_core module: {e}")
    sys.exit(1)

VERSION = "2.0.0"
APP_NAME = "AOSP Payload Dumper"


class ExtractionWorker(QThread):
    """Worker thread - runs extraction in background so UI doesn't freeze"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    partition_signal = pyqtSignal(str, int, int)  # name, current, total
    completed_signal = pyqtSignal(list)  # extracted files
    error_signal = pyqtSignal(str)
    
    def __init__(self, payload_path: str, output_dir: str, images: Optional[List[str]] = None, 
                 diff_mode: bool = False, old_dir: str = "old"):
        super().__init__()
        self.payload_path = payload_path
        self.output_dir = output_dir
        self.images = images
        self.diff_mode = diff_mode
        self.old_dir = old_dir
        self.is_cancelled = False
        self.extracted_files = []
        self.current_partition = ""
        self.total_partitions = 0
        self.current_partition_idx = 0
    
    def cancel(self):
        """Stop extraction gracefully"""
        self.is_cancelled = True
    
    def run(self):
        """Main extraction logic - runs in separate thread"""
        try:
            self.log_signal.emit("🚀 Starting payload extraction...")
            
            # Validate inputs
            if not os.path.exists(self.payload_path):
                raise FileNotFoundError(f"Payload file not found: {self.payload_path}")
            
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir, exist_ok=True)
            
            # Quick test: can we actually write to the output directory?
            test_file = os.path.join(self.output_dir, ".write_test")
            try:
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
            except Exception:
                raise PermissionError(f"Cannot write to output directory: {self.output_dir}")
            
            # Run the actual extraction
            start_time = time.time()
            payload_core.run_payload_dumper(
                payload_path=self.payload_path,
                out_dir=self.output_dir,
                diff=self.diff_mode,
                old_dir=self.old_dir,
                images=self.images,
                log_callback=self._log_callback,
                progress_callback=self._progress_callback,
                cancel_flag=lambda: self.is_cancelled
            )
            
            if not self.is_cancelled:
                elapsed = time.time() - start_time
                self._scan_extracted_files()
                self.log_signal.emit(f"✅ Extraction completed in {elapsed:.1f} seconds!")
                self.completed_signal.emit(self.extracted_files)
            
        except Exception as e:
            self.error_signal.emit(f"❌ Extraction failed: {str(e)}")
    
    def _log_callback(self, message: str):
        """Parse log messages and extract partition info"""
        if "Processing" in message and "partition" in message:
            # Try to grab partition name for progress tracking
            try:
                partition_name = message.split("Processing ")[1].split(" partition")[0]
                self.current_partition = partition_name
                self.current_partition_idx += 1
                self.partition_signal.emit(partition_name, self.current_partition_idx, self.total_partitions)
            except:
                # If parsing fails, just move on
                pass
        self.log_signal.emit(message)
    
    def _progress_callback(self, percentage: int):
        """Forward progress updates to main thread"""
        self.progress_signal.emit(percentage)
    
    def _scan_extracted_files(self):
        """Look at output directory and catalog all the .img files"""
        try:
            for file_path in Path(self.output_dir).glob("*.img"):
                size = file_path.stat().st_size
                self.extracted_files.append({
                    'name': file_path.name,
                    'path': str(file_path),
                    'size': size,
                    'size_mb': size / (1024 * 1024)
                })
        except Exception as e:
            self.log_signal.emit(f"Warning: Could not scan extracted files: {e}")


class AboutDialog(QDialog):
    """About dialog - shows app info"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setFixedSize(400, 300)
        
        layout = QVBoxLayout()
        
        # Title
        title = QLabel(f"{APP_NAME}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Version
        version = QLabel(f"Version {VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        
        # Description
        desc = QLabel(
            "A modern tool for extracting Android OTA payload.bin files.\n\n"
            "Features:\n"
            "• Support for all Android OTA formats\n"
            "• Cross-platform (Windows, Linux)\n"
            "• Real-time progress tracking\n"
            "• Detailed logging and error handling\n"
            "• Differential OTA support"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        
        self.setLayout(layout)


class PayloadDumperGUI(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, "Settings")
        self.worker = None
        self.extraction_start_time = None
        
        # Set up the UI
        self.init_ui()
        self.restore_settings()
        self.setup_timer()
        
        # Dark mode if user had it enabled before
        if self.settings.value("dark_mode", False, type=bool):
            self.apply_dark_theme()
    
    def init_ui(self):
        """Build the user interface"""
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setMinimumSize(900, 600)
        
        # Menu bar
        self.create_menu_bar()
        
        # Main content
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # Two tabs: extraction and results
        tab_widget = QTabWidget()
        tab_widget.addTab(self.create_extraction_tab(), "📂 Extraction")
        tab_widget.addTab(self.create_results_tab(), "📋 Results")
        main_layout.addWidget(tab_widget)
        
        # Status bar at bottom
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def create_menu_bar(self):
        """Create the menu bar with File, View, Help"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        open_action = QAction("Open Payload...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.browse_payload)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        dark_mode_action = QAction("Dark Mode", self)
        dark_mode_action.setCheckable(True)
        dark_mode_action.setChecked(self.settings.value("dark_mode", False, type=bool))
        dark_mode_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(dark_mode_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_extraction_tab(self) -> QWidget:
        """Build the main extraction tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Input section
        input_group = QGroupBox("📁 Input Files")
        input_layout = QVBoxLayout(input_group)
        
        # Payload file
        payload_layout = QHBoxLayout()
        payload_layout.addWidget(QLabel("Payload/OTA File:"))
        self.payload_entry = QLineEdit()
        self.payload_entry.setPlaceholderText("Select payload.bin or OTA zip file...")
        payload_layout.addWidget(self.payload_entry)
        
        self.browse_payload_btn = QPushButton("📁 Browse")
        self.browse_payload_btn.clicked.connect(self.browse_payload)
        payload_layout.addWidget(self.browse_payload_btn)
        input_layout.addLayout(payload_layout)
        
        # Output directory
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Directory:"))
        self.output_entry = QLineEdit()
        self.output_entry.setPlaceholderText("Select output directory...")
        output_layout.addWidget(self.output_entry)
        
        self.browse_output_btn = QPushButton("📁 Browse")
        self.browse_output_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.browse_output_btn)
        input_layout.addLayout(output_layout)
        
        # Partition filter (optional)
        partition_layout = QHBoxLayout()
        partition_layout.addWidget(QLabel("Partitions (optional):"))
        self.images_entry = QLineEdit()
        self.images_entry.setPlaceholderText("e.g., system,boot,vendor (leave empty for all)")
        partition_layout.addWidget(self.images_entry)
        input_layout.addLayout(partition_layout)
        
        # Differential OTA checkbox
        self.diff_checkbox = QCheckBox("🔄 Differential OTA (requires original images)")
        input_layout.addWidget(self.diff_checkbox)
        
        layout.addWidget(input_group)
        
        # Progress section
        progress_group = QGroupBox("📊 Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        self.current_partition_label = QLabel("Ready to start...")
        progress_layout.addWidget(self.current_partition_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        
        # Control buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("🚀 Start Extraction")
        self.start_btn.clicked.connect(self.start_extraction)
        self.start_btn.setMinimumHeight(40)
        button_layout.addWidget(self.start_btn)
        
        self.cancel_btn = QPushButton("⏹ Cancel")
        self.cancel_btn.clicked.connect(self.cancel_extraction)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(40)
        button_layout.addWidget(self.cancel_btn)
        
        progress_layout.addLayout(button_layout)
        layout.addWidget(progress_group)
        
        # Log area
        log_group = QGroupBox("📝 Extraction Log")
        log_layout = QVBoxLayout(log_group)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setMaximumHeight(200)
        log_layout.addWidget(self.log_area)
        
        layout.addWidget(log_group)
        
        return widget
    
    def create_results_tab(self) -> QWidget:
        """Build the results tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Header with results info
        header_layout = QHBoxLayout()
        self.results_label = QLabel("📋 Extracted Files")
        self.results_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        header_layout.addWidget(self.results_label)
        
        header_layout.addStretch()
        
        self.open_folder_btn = QPushButton("📂 Open Output Folder")
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        self.open_folder_btn.setEnabled(False)
        header_layout.addWidget(self.open_folder_btn)
        
        layout.addLayout(header_layout)
        
        # List of extracted files
        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        layout.addWidget(self.results_list)
        
        return widget
    
    def setup_timer(self):
        """Initialize timer for elapsed time updates"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_elapsed_time)
    
    def restore_settings(self):
        """Load saved settings from last run"""
        # Window position/size
        if self.settings.contains("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        
        # Paths and checkboxes
        self.payload_entry.setText(self.settings.value("last_payload_path", ""))
        self.output_entry.setText(self.settings.value("last_output_path", ""))
        self.images_entry.setText(self.settings.value("last_images", ""))
        self.diff_checkbox.setChecked(self.settings.value("diff_mode", False, type=bool))
    
    def save_settings(self):
        """Save current settings for next time"""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("last_payload_path", self.payload_entry.text())
        self.settings.setValue("last_output_path", self.output_entry.text())
        self.settings.setValue("last_images", self.images_entry.text())
        self.settings.setValue("diff_mode", self.diff_checkbox.isChecked())
    
    def toggle_dark_mode(self, checked: bool):
        """Switch between dark and light themes"""
        self.settings.setValue("dark_mode", checked)
        if checked:
            self.apply_dark_theme()
        else:
            self.apply_light_theme()
    
    def apply_dark_theme(self):
        """Apply dark color scheme"""
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(0, 0, 0))
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        self.setPalette(dark_palette)
    
    def apply_light_theme(self):
        """Go back to default light theme"""
        self.setPalette(QApplication.style().standardPalette())
    
    def browse_payload(self):
        """Open file dialog to pick a payload.bin or OTA zip"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Payload File", 
            self.payload_entry.text() or os.path.expanduser("~"),
            "All Supported Files (*.bin *.zip);;Payload Files (*.bin);;ZIP Files (*.zip);;All Files (*.*)"
        )
        if file_path:
            self.payload_entry.setText(file_path)
            self.validate_inputs()
    
    def browse_output(self):
        """Open directory dialog to pick output folder"""
        dir_path = QFileDialog.getExistingDirectory(
            self, 
            "Select Output Directory", 
            self.output_entry.text() or os.path.expanduser("~")
        )
        if dir_path:
            self.output_entry.setText(dir_path)
            self.validate_inputs()
    
    def validate_inputs(self) -> bool:
        """Check if inputs are valid and enable/disable buttons"""
        payload_path = self.payload_entry.text().strip()
        output_path = self.output_entry.text().strip()
        
        # Check payload file exists
        if not payload_path or not os.path.exists(payload_path):
            self.status_bar.showMessage("❌ Please select a valid payload file")
            self.start_btn.setEnabled(False)
            return False
        
        # Check output directory
        if not output_path:
            self.status_bar.showMessage("❌ Please select an output directory")
            self.start_btn.setEnabled(False)
            return False
        
        # Quick validation of file format
        try:
            if payload_path.endswith('.zip'):
                # Check if zip has payload.bin
                import zipfile
                with zipfile.ZipFile(payload_path, 'r') as zf:
                    if "payload.bin" not in zf.namelist():
                        raise ValueError("ZIP file does not contain payload.bin")
            else:
                # Check magic header
                with open(payload_path, 'rb') as f:
                    magic = f.read(4)
                    if magic != b'CrAU':
                        raise ValueError("Invalid payload file format")
        except Exception as e:
            self.status_bar.showMessage(f"❌ Invalid file format: {str(e)}")
            self.start_btn.setEnabled(False)
            return False
        
        self.status_bar.showMessage("✅ Ready to extract")
        self.start_btn.setEnabled(True)
        return True
    
    def start_extraction(self):
        """Kick off the extraction process"""
        if not self.validate_inputs():
            return
        
        payload_path = self.payload_entry.text().strip()
        output_dir = self.output_entry.text().strip()
        images_text = self.images_entry.text().strip()
        # Parse comma-separated partition names
        images = [img.strip() for img in images_text.split(",")] if images_text else None
        
        # Make sure output directory exists
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot create output directory:\n{str(e)}")
            return
        
        # Clear old stuff
        self.log_area.clear()
        self.results_list.clear()
        self.progress_bar.setValue(0)
        self.current_partition_label.setText("Preparing...")
        
        # Save user's settings
        self.save_settings()
        
        # Create and configure worker thread
        self.worker = ExtractionWorker(
            payload_path=payload_path,
            output_dir=output_dir,
            images=images,
            diff_mode=self.diff_checkbox.isChecked()
        )
        
        # Connect all the signals
        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.partition_signal.connect(self.update_partition_progress)
        self.worker.completed_signal.connect(self.extraction_completed)
        self.worker.error_signal.connect(self.extraction_error)
        
        # Update UI - disable stuff while running
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.browse_payload_btn.setEnabled(False)
        self.browse_output_btn.setEnabled(False)
        
        # Start the timer and worker
        self.extraction_start_time = time.time()
        self.timer.start(1000)  # Update every second
        self.worker.start()
    
    def cancel_extraction(self):
        """Stop the extraction process"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.append_log("🛑 Cancellation requested...")
            self.status_bar.showMessage("Cancelling extraction...")
    
    def append_log(self, message: str):
        """Add a line to the log area"""
        self.log_area.append(message)
        self.log_area.ensureCursorVisible()
    
    def update_progress(self, percentage: int):
        """Update the progress bar"""
        self.progress_bar.setValue(percentage)
    
    def update_partition_progress(self, partition_name: str, current: int, total: int):
        """Update the partition progress label"""
        self.current_partition_label.setText(f"📂 Processing: {partition_name} ({current}/{total})")
    
    def update_elapsed_time(self):
        """Update elapsed time display"""
        if self.extraction_start_time:
            elapsed = int(time.time() - self.extraction_start_time)
            mins, secs = divmod(elapsed, 60)
            self.status_bar.showMessage(f"⏱ Elapsed time: {mins:02d}:{secs:02d}")
    
    def extraction_completed(self, extracted_files: List[Dict]):
        """Handle successful extraction - show results"""
        self.timer.stop()
        
        # Re-enable UI buttons
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.browse_payload_btn.setEnabled(True)
        self.browse_output_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(True)
        
        # Show what got extracted
        self.update_results_list(extracted_files)
        self.current_partition_label.setText("✅ Extraction completed!")
        self.progress_bar.setValue(100)
        
        # Summary message
        total_size_mb = sum(f['size_mb'] for f in extracted_files)
        QMessageBox.information(
            self, 
            "Extraction Complete", 
            f"Successfully extracted {len(extracted_files)} partition(s)\n"
            f"Total size: {total_size_mb:.1f} MB"
        )
    
    def extraction_error(self, error_message: str):
        """Handle extraction failure"""
        self.timer.stop()
        
        # Re-enable buttons so user can try again
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.browse_payload_btn.setEnabled(True)
        self.browse_output_btn.setEnabled(True)
        
        self.current_partition_label.setText("❌ Extraction failed")
        self.status_bar.showMessage("❌ Extraction failed")
        
        # Show error details
        QMessageBox.critical(self, "Extraction Failed", error_message)
    
    def update_results_list(self, extracted_files: List[Dict]):
        """Populate the results list widget with extracted files"""
        self.results_list.clear()
        
        for file_info in extracted_files:
            item_text = f"📱 {file_info['name']} ({file_info['size_mb']:.1f} MB)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, file_info['path'])
            self.results_list.addItem(item)
        
        # Update header with count and total size
        total_size_mb = sum(f['size_mb'] for f in extracted_files)
        self.results_label.setText(f"📋 Extracted Files ({len(extracted_files)} files, {total_size_mb:.1f} MB)")
    
    def open_output_folder(self):
        """Open the output folder in file manager"""
        output_path = self.output_entry.text().strip()
        if not output_path or not os.path.exists(output_path):
            QMessageBox.warning(self, "Warning", "Output directory not found")
            return
        
        try:
            # Different commands for different OSes
            if platform.system() == "Windows":
                os.startfile(output_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", output_path])
            else:  # Linux and others
                subprocess.run(["xdg-open", output_path])
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Cannot open folder:\n{str(e)}")
    
    def show_about(self):
        """Show the about dialog"""
        dialog = AboutDialog(self)
        dialog.exec()
    
    def closeEvent(self, event):
        """Handle window close - save settings and stop extraction"""
        # Save everything
        self.save_settings()
        
        # Kill extraction if it's running
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, 
                "Confirm Exit", 
                "Extraction is in progress. Are you sure you want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.worker.wait(5000)  # Wait up to 5 seconds for it to finish
            else:
                event.ignore()
                return
        
        event.accept()


def main():
    """Entry point - create and run the app"""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("AOSP Tools")
    
    # Set app icon if we have one
    # app.setWindowIcon(QIcon("icon.png"))
    
    window = PayloadDumperGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()