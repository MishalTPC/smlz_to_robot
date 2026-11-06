"""The Project Company SMLX -> Autodesk Robot desktop application.

Author: Mishal Mohanlal | Version: 0.1.0
Run from the project root with: python launch_gui.py
The branded logo is shared with the existing TPC licensing application.
"""
from __future__ import annotations

import base64
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from gui_workflow import (
    APP_NAME, AUTHOR, VERSION, ConversionRequest, ConversionResult,
    run_conversion, suggested_files, validate_request,
)

STYLE = """
QWidget { background: #11161d; color: #f8fafc;
          font-family: 'Segoe UI'; font-size: 12px; }
QFrame#Panel { background: #1b232e; border: 1px solid #334155;
               border-radius: 12px; }
QLabel#Heading { font-size: 22px; font-weight: bold; color: #fff; }
QLabel#Subheading { color: #afbdcb; font-size: 12px; }
QLabel#SectionHeading { color: #e4bd4d; font-weight: bold; }
QLabel#Warning { color: #f0d798; }
QLineEdit, QDoubleSpinBox, QTextEdit { background: #0b1220;
    color: #f8fafc; border: 1px solid #475569; border-radius: 6px;
    padding: 7px 9px; }
QLineEdit:focus, QDoubleSpinBox:focus { border: 1px solid #d1ac40; }
QTextEdit { font-family: 'Consolas'; font-size: 11px; }
QCheckBox { spacing: 9px; }
QPushButton { background: #bd9c3b; color: #111827; font-weight: bold;
              padding: 10px 16px; border-radius: 7px; }
QPushButton:hover { background: #e0bd56; }
QPushButton#Secondary { background: #334155; color: #ffffff; }
QPushButton#Secondary:hover { background: #475569; }
QPushButton:disabled { background: #475569; color: #94a3b8; }
QProgressBar { background: #0b1220; border: 1px solid #475569;
               border-radius: 5px; min-height: 9px; }
QProgressBar::chunk { background: #bd9c3b; border-radius: 4px; }
"""


def logo_path() -> Path:
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return bundle / "assets" / "logo.b64"


def logo_widget() -> QWidget:
    container = QWidget()
    column = QVBoxLayout(container)
    column.setContentsMargins(0, 0, 0, 0)
    column.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    src = logo_path()
    if src.is_file():
        picture = QPixmap()
        try:
            loaded = picture.loadFromData(base64.b64decode(src.read_text(encoding="ascii")))
        except (OSError, ValueError):
            loaded = False
        if loaded and not picture.isNull():
            display = QLabel()
            display.setAlignment(Qt.AlignmentFlag.AlignCenter)
            display.setPixmap(picture.scaled(
                370, 125, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            column.addWidget(display)
            return container
    label = QLabel("THE PROJECT COMPANY")
    label.setObjectName("Heading")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    column.addWidget(label)
    return container


def make_panel() -> tuple[QFrame, QVBoxLayout]:
    box = QFrame()
    box.setObjectName("Panel")
    body = QVBoxLayout(box)
    body.setContentsMargins(19, 15, 19, 15)
    body.setSpacing(10)
    return box, body


class ConversionWorker(QThread):
    """Read/export/build off the GUI thread; retain Robot's COM reference.

    COM is initialised and released in the SAME thread. Upon successful Robot
    creation, the worker holds the connection until the GUI is closed. That
    mirrors the original run_robot.py's inspection pause without freezing Qt.
    """
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, request: ConversionRequest, parent: QWidget | None = None):
        super().__init__(parent)
        self.request = request
        self._release = threading.Event()
        self._robot = None

    def release_robot(self) -> None:
        self._release.set()

    def run(self) -> None:
        pythoncom = None
        com_started = False
        try:
            if not self.request.excel_only:
                import pythoncom as pythoncom_module
                pythoncom = pythoncom_module
                pythoncom.CoInitialize()
                com_started = True
            result, self._robot = run_conversion(
                self.request, progress=self.progress.emit,
            )
            self.completed.emit(result)
            if self._robot is not None:
                # Keep the last Python COM reference alive while the GUI is
                # open, and service queued COM messages on this STA thread.
                while not self._release.wait(0.12):
                    pythoncom.PumpWaitingMessages()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._robot = None
            if com_started and pythoncom is not None:
                pythoncom.CoUninitialize()


class MainWindow(QMainWindow):
    """Simple one-screen workflow for SMLX input and Robot/Excel outputs."""

    def __init__(self) -> None:
        super().__init__()
        self.worker: ConversionWorker | None = None
        self._busy = False
        self._success = False
        self._excel_custom = False
        self._setting_default = False
        self._result: ConversionResult | None = None
        self.setWindowTitle(f"The Project Company | {APP_NAME} v{VERSION}")
        self.setMinimumSize(730, 730)
        self.resize(840, 790)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        column = QVBoxLayout(central)
        column.setContentsMargins(26, 12, 26, 18)
        column.setSpacing(11)
        column.addWidget(logo_widget())

        heading = QLabel("SMLX to Autodesk Robot")
        heading.setObjectName("Heading")
        column.addWidget(heading)
        subtitle = QLabel("Select an SMLX source, choose an output Robot model, and retain a full Excel workbook.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("Subheading")
        column.addWidget(subtitle)

        panel, body = make_panel()
        title = QLabel("INPUT AND OUTPUT FILES")
        title.setObjectName("SectionHeading")
        body.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(15)
        form.setVerticalSpacing(11)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select an .smlx, .smlz, .zip, .xml file or an extracted folder")
        self.robot_edit = QLineEdit()
        self.robot_edit.setPlaceholderText("Path for the Autodesk Robot .rtd model")
        self.excel_edit = QLineEdit()
        self.excel_edit.setPlaceholderText("Path for the complete .xlsx export")
        input_browse = QPushButton("Browse file")
        input_browse.setObjectName("Secondary")
        input_browse.clicked.connect(self.browse_source)
        folder_browse = QPushButton("Folder")
        folder_browse.setObjectName("Secondary")
        folder_browse.clicked.connect(self.browse_source_folder)
        group = QHBoxLayout()
        group.setSpacing(6)
        group.addWidget(self.input_edit, 1)
        group.addWidget(input_browse)
        group.addWidget(folder_browse)
        form.addRow("SMLX input", group)
        robot_browse = QPushButton("Browse...")
        robot_browse.setObjectName("Secondary")
        robot_browse.clicked.connect(self.browse_robot_file)
        robot_row = QHBoxLayout()
        robot_row.setSpacing(6)
        robot_row.addWidget(self.robot_edit, 1)
        robot_row.addWidget(robot_browse)
        form.addRow("Robot model (.rtd)", robot_row)
        excel_browse = QPushButton("Browse...")
        excel_browse.setObjectName("Secondary")
        excel_browse.clicked.connect(self.browse_excel_file)
        excel_row = QHBoxLayout()
        excel_row.setSpacing(6)
        excel_row.addWidget(self.excel_edit, 1)
        excel_row.addWidget(excel_browse)
        form.addRow("Excel export (.xlsx)", excel_row)
        body.addLayout(form)
        hint = QLabel("Excel is always exported first. The source section properties and SMLX metadata are preserved for later tools such as OpenSees.")
        hint.setObjectName("Subheading")
        hint.setWordWrap(True)
        body.addWidget(hint)
        column.addWidget(panel)

        options, optbody = make_panel()
        opt_title = QLabel("ROBOT IMPORT SETTINGS")
        opt_title.setObjectName("SectionHeading")
        optbody.addWidget(opt_title)
        self.excel_only_check = QCheckBox("Export Excel only (do not launch Robot)")
        self.sa_catalogue_check = QCheckBox("Use South African steel section catalogues (ZA / SADEF)")
        self.sa_catalogue_check.setChecked(True)
        self.review_check = QCheckBox("Allow review-only modelling approximations")
        self.review_check.setChecked(True)
        optbody.addWidget(self.excel_only_check)
        optbody.addWidget(self.sa_catalogue_check)
        optbody.addWidget(self.review_check)
        poisson = QHBoxLayout()
        label = QLabel("Robot Poisson ratio (approved override)")
        self.poisson_spin = QDoubleSpinBox()
        self.poisson_spin.setRange(0.01, 0.49)
        self.poisson_spin.setDecimals(2)
        self.poisson_spin.setSingleStep(0.01)
        self.poisson_spin.setValue(0.30)
        poisson.addWidget(label)
        poisson.addWidget(self.poisson_spin)
        poisson.addStretch(1)
        optbody.addLayout(poisson)
        disclaimer = QLabel("Review-only: section orientations, eccentricities, global supports and analytical connectivity require engineering verification. Angle and CHS bending releases remain enabled; torsion stays connected.")
        disclaimer.setObjectName("Warning")
        disclaimer.setWordWrap(True)
        optbody.addWidget(disclaimer)
        self.excel_only_check.toggled.connect(self._on_excel_only)
        column.addWidget(options)

        row = QHBoxLayout()
        self.run_button = QPushButton("Generate Robot model + Excel")
        self.run_button.clicked.connect(self.start_conversion)
        self.folder_button = QPushButton("Open output folder")
        self.folder_button.setObjectName("Secondary")
        self.folder_button.clicked.connect(self.open_output_folder)
        row.addWidget(self.run_button, 1)
        row.addWidget(self.folder_button)
        column.addLayout(row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        column.addWidget(self.progress_bar)
        self.status = QLabel("Ready. Choose your SMLX input file.")
        self.status.setObjectName("Subheading")
        column.addWidget(self.status)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Conversion log will appear here...")
        self.log.setMinimumHeight(95)
        column.addWidget(self.log, 1)
        footer = QLabel(f"Author: {AUTHOR}    |    Version {VERSION}    |    The Project Company")
        footer.setObjectName("Subheading")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(footer)

        self.input_edit.editingFinished.connect(self._fill_if_empty)
        self.robot_edit.editingFinished.connect(self._update_excel_auto)
        self.excel_edit.textEdited.connect(self._mark_excel_custom)

    def _mark_excel_custom(self, _value: str) -> None:
        if not self._setting_default:
            self._excel_custom = True

    def _set_paths_from_source(self, text: str) -> None:
        self.input_edit.setText(text)
        robot, excel = suggested_files(Path(text))
        self._setting_default = True
        self.robot_edit.setText(str(robot))
        if not self._excel_custom:
            self.excel_edit.setText(str(excel))
        self._setting_default = False

    def _fill_if_empty(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        robot, excel = suggested_files(Path(text))
        self._setting_default = True
        if not self.robot_edit.text().strip():
            self.robot_edit.setText(str(robot))
        if not self.excel_edit.text().strip() and not self._excel_custom:
            self.excel_edit.setText(str(excel))
        self._setting_default = False

    def _update_excel_auto(self) -> None:
        if self._excel_custom:
            return
        robot = self.robot_edit.text().strip()
        if robot:
            path = Path(robot)
            self._setting_default = True
            self.excel_edit.setText(str(path.with_name(f"{path.stem}_model.xlsx")))
            self._setting_default = False

    def browse_source(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Select SMLX model", "",
            "SMLX / archive / XML (*.smlx *.smlz *.zip *.xml);;All files (*)",
        )
        if name:
            self._set_paths_from_source(name)

    def browse_source_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "Select extracted SMLX folder")
        if name:
            self._set_paths_from_source(name)

    def browse_robot_file(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Save Robot model", self.robot_edit.text(),
            "Autodesk Robot (*.rtd)",
        )
        if name:
            path = Path(name)
            if not path.suffix:
                path = path.with_suffix(".rtd")
            self.robot_edit.setText(str(path))
            self._update_excel_auto()

    def browse_excel_file(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Save Excel structural workbook", self.excel_edit.text(),
            "Excel Workbook (*.xlsx)",
        )
        if name:
            path = Path(name)
            if not path.suffix:
                path = path.with_suffix(".xlsx")
            self._excel_custom = True
            self.excel_edit.setText(str(path))

    def _on_excel_only(self, checked: bool) -> None:
        self.robot_edit.setEnabled(not checked)
        self.sa_catalogue_check.setEnabled(not checked)
        self.review_check.setEnabled(not checked)
        self.poisson_spin.setEnabled(not checked)
        self.run_button.setText("Export Excel workbook" if checked else "Generate Robot model + Excel")

    def _request(self) -> ConversionRequest:
        self._fill_if_empty()
        source = self.input_edit.text().strip()
        if not source:
            raise ValueError("Select an SMLX file or extracted SMLX folder")
        excel = self.excel_edit.text().strip()
        if not excel:
            raise ValueError("Choose an Excel output .xlsx file")
        robot = self.robot_edit.text().strip()
        if not self.excel_only_check.isChecked() and not robot:
            raise ValueError("Choose a Robot output .rtd file")
        return validate_request(ConversionRequest(
            source=Path(source),
            robot_file=Path(robot) if robot else None,
            excel_file=Path(excel),
            excel_only=self.excel_only_check.isChecked(),
            poisson_for_robot=self.poisson_spin.value(),
            use_sa_catalogue=self.sa_catalogue_check.isChecked(),
            allow_review_approximations=self.review_check.isChecked(),
        ))

    def start_conversion(self) -> None:
        if self._busy or self.worker is not None:
            QMessageBox.information(
                self, "Robot session in use",
                "The existing Robot session is still held by this window. "
                "Save and close this window before starting another import.",
            )
            return
        try:
            request = self._request()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Check file selections", str(exc))
            return
        if not request.excel_only:
            confirm = QMessageBox.question(
                self, "Create a new Robot project",
                "A new Robot project will replace any currently open project. "
                "Save your work in Robot first. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        self._busy = True
        self.run_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.log.clear()
        self._write_log(f"Input: {request.source}")
        self.worker = ConversionWorker(request, self)
        self.worker.progress.connect(self._write_log)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_thread_finished)
        self.worker.start()

    def _write_log(self, message: str) -> None:
        self.log.append(message)
        self.status.setText(message)

    def _on_completed(self, result: ConversionResult) -> None:
        self._busy = False
        self._success = True
        self._result = result
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self._write_log(
            f"SUCCESS: {result.bars} members, {result.nodes} nodes. "
            f"Excel: {result.excel_file}"
        )
        if result.robot_file is not None:
            self._write_log(f"Robot model: {result.robot_file}")
            self._write_log(
                "Keep this GUI open while reviewing Robot; closing it may "
                "release the last COM connection and close Robot."
            )
        else:
            self._write_log("Excel export complete (Robot was not launched).")
        QMessageBox.information(
            self, "Conversion complete",
            "Excel workbook exported successfully.\n"
            + (f"Robot model saved to:\n{result.robot_file}"
               if result.robot_file else "Excel-only export complete."),
        )

    def _on_failed(self, message: str) -> None:
        self._busy = False
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._write_log(f"ERROR: {message}")
        QMessageBox.critical(self, "Conversion failed", message)

    def _on_thread_finished(self) -> None:
        # Excel-only conversions end immediately, as do failed conversions.
        if self.worker is not None and not self._success:
            self.worker.deleteLater()
            self.worker = None
            self.run_button.setEnabled(True)
        elif self.worker is not None and self.worker.request.excel_only:
            self.worker.deleteLater()
            self.worker = None
            self.run_button.setEnabled(True)

    def open_output_folder(self) -> None:
        try:
            output = (self._result.excel_file.parent if self._result
                      else Path(self.excel_edit.text()).expanduser().parent)
            if not output.is_dir():
                raise ValueError(f"Folder does not exist: {output}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.resolve())))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Output folder", str(exc))

    def closeEvent(self, event) -> None:
        worker = self.worker
        if worker is not None and worker.isRunning():
            if self._busy:
                QMessageBox.warning(
                    self, "Import in progress",
                    "The import is currently running. Close the window after it finishes.",
                )
                event.ignore()
                return
            worker.release_robot()
            if not worker.wait(5000):
                QMessageBox.warning(
                    self, "Robot connection",
                    "Robot has not released the connection yet. Please try closing again.",
                )
                event.ignore()
                return
        event.accept()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
