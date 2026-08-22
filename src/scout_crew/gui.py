#!/usr/bin/env python
"""Scout Desktop GUI — CrewAI controls + integrated local terminal.

All LLM traffic is forced through local Ollama (127.0.0.1:11434).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

# Hard-local OpenAI-compatible routing
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY") or "ollama"
os.environ["OPENAI_API_BASE"] = os.getenv("OPENAI_API_BASE") or "http://127.0.0.1:11434/v1"
os.environ["OPENAI_BASE_URL"] = os.getenv("OPENAI_BASE_URL") or "http://127.0.0.1:11434/v1"
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
os.environ["CREWAI_TRACING_ENABLED"] = os.getenv("CREWAI_TRACING_ENABLED", "true")

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from scout_crew.local_llms import model_roster, status as llm_status
from scout_crew.prompt_syntax import convert_user_prompt, extract_raw_user_query

DEFAULT_SCANNER_TRANSCRIPT = (
    "Unit 23 copy, running radar on I-5 northbound at mile marker 212, "
    "vehicle stop in progress near the Shell station."
)



DARK_QSS = """
QMainWindow, QWidget {
  background-color: #0b1220;
  color: #e2e8f0;
  font-size: 13px;
}
QGroupBox {
  border: 1px solid #1e293b;
  border-radius: 8px;
  margin-top: 12px;
  padding-top: 10px;
  font-weight: 600;
}
QGroupBox::title {
  subcontrol-origin: margin;
  left: 10px;
  padding: 0 4px;
  color: #93c5fd;
}
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox {
  background-color: #020617;
  color: #e2e8f0;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 6px;
  selection-background-color: #1d4ed8;
}
QPushButton {
  background-color: #1d4ed8;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 8px 14px;
  font-weight: 600;
}
QPushButton:hover { background-color: #2563eb; }
QPushButton:disabled { background-color: #334155; color: #94a3b8; }
QPushButton#danger { background-color: #b91c1c; }
QPushButton#danger:hover { background-color: #dc2626; }
QPushButton#secondary { background-color: #334155; }
QPushButton#secondary:hover { background-color: #475569; }
QTabWidget::pane {
  border: 1px solid #1e293b;
  border-radius: 8px;
  top: -1px;
}
QTabBar::tab {
  background: #0f172a;
  color: #94a3b8;
  padding: 8px 14px;
  border-top-left-radius: 6px;
  border-top-right-radius: 6px;
  margin-right: 2px;
}
QTabBar::tab:selected {
  background: #1e293b;
  color: #f8fafc;
}
QStatusBar {
  background: #020617;
  color: #94a3b8;
}
QLabel#badge {
  background: #052e16;
  color: #86efac;
  border: 1px solid #166534;
  border-radius: 999px;
  padding: 4px 10px;
  font-weight: 600;
}
QLabel#badgeWarn {
  background: #450a0a;
  color: #fca5a5;
  border: 1px solid #7f1d1d;
  border-radius: 999px;
  padding: 4px 10px;
  font-weight: 600;
}
"""


def _venv_python() -> str:
    return str(_PROJECT_ROOT / ".venv" / "bin" / "python")


def _local_env() -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    env.insert("OPENAI_API_KEY", "ollama")
    env.insert("OPENAI_API_BASE", "http://127.0.0.1:11434/v1")
    env.insert("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    env.insert("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    env.insert("PYTHONUNBUFFERED", "1")
    # Prefer project venv on PATH for nested tools
    path = env.value("PATH", "")
    vbin = str(_PROJECT_ROOT / ".venv" / "bin")
    local_bin = str(Path.home() / ".local" / "bin")
    env.insert("PATH", f"{vbin}:{local_bin}:{path}")
    return env


class ProcessConsole(QPlainTextEdit):
    """Append-only console bound to a QProcess."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(8000)
        self.setFont(QFont("monospace", 11))
        self._proc: Optional[QProcess] = None

    def attach(self, proc: QProcess) -> None:
        self._proc = proc
        proc.readyReadStandardOutput.connect(self._read_stdout)
        proc.readyReadStandardError.connect(self._read_stderr)

    def _append(self, text: str, color: Optional[str] = None) -> None:
        if not text:
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if color:
            self.setTextColor(QColor(color))  # type: ignore[attr-defined]
        # QPlainTextEdit has no setTextColor; use HTML-ish via appendPlain
        self.appendPlainText(text.rstrip("\n"))
        self.moveCursor(QTextCursor.MoveOperation.End)

    def _read_stdout(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._append(line)

    def _read_stderr(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardError()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._append(f"[err] {line}")


class TerminalPane(QWidget):
    """Interactive local shell pane (bash) with forced local LLM env."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.cwd_label = QLabel(str(_PROJECT_ROOT))
        self.cwd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("secondary")
        btn_clear.clicked.connect(self._clear)
        btn_interrupt = QPushButton("Ctrl+C")
        btn_interrupt.setObjectName("danger")
        btn_interrupt.clicked.connect(self._interrupt)
        btn_restart = QPushButton("Restart shell")
        btn_restart.setObjectName("secondary")
        btn_restart.clicked.connect(self.restart)
        top.addWidget(QLabel("cwd:"))
        top.addWidget(self.cwd_label, 1)
        top.addWidget(btn_clear)
        top.addWidget(btn_interrupt)
        top.addWidget(btn_restart)
        layout.addLayout(top)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(12000)
        self.view.setFont(QFont("monospace", 11))
        layout.addWidget(self.view, 1)

        row = QHBoxLayout()
        self.prompt = QLabel("$")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a shell command and press Enter…")
        self.input.returnPressed.connect(self._run_line)
        btn_run = QPushButton("Run")
        btn_run.clicked.connect(self._run_line)
        row.addWidget(self.prompt)
        row.addWidget(self.input, 1)
        row.addWidget(btn_run)
        layout.addLayout(row)

        self._shell = QProcess(self)
        self._shell.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._shell.setWorkingDirectory(str(_PROJECT_ROOT))
        self._shell.setProcessEnvironment(_local_env())
        self._shell.readyReadStandardOutput.connect(self._on_out)
        self._shell.readyReadStandardError.connect(self._on_out)
        self._shell.started.connect(lambda: self._append("[shell started — local env forced to Ollama]\n"))
        self._shell.finished.connect(self._on_finished)
        self.restart()

    def restart(self) -> None:
        if self._shell.state() != QProcess.ProcessState.NotRunning:
            self._shell.kill()
            self._shell.waitForFinished(1000)
        shell = shutil.which("bash") or "/bin/bash"
        # Interactive-ish: keep bash alive reading commands we write to stdin
        self._shell.setProgram(shell)
        self._shell.setArguments(["--noprofile", "--norc", "-i"])
        self._shell.start()
        # Disable history expansion noise etc.
        if self._shell.waitForStarted(2000):
            self._write("export PS1='scout:\\w$ '\n")
            self._write("export OPENAI_API_KEY=ollama\n")
            self._write("export OPENAI_BASE_URL=http://127.0.0.1:11434/v1\n")
            self._write("export OPENAI_API_BASE=http://127.0.0.1:11434/v1\n")
            self._write("cd %s\n" % _PROJECT_ROOT.as_posix())
            self._write("echo \"Scout terminal ready (local Ollama routing)\"\n")

    def _write(self, data: str) -> None:
        if self._shell.state() == QProcess.ProcessState.Running:
            self._shell.write(data.encode("utf-8"))

    def _append(self, text: str) -> None:
        self.view.moveCursor(QTextCursor.MoveOperation.End)
        self.view.insertPlainText(text)
        self.view.moveCursor(QTextCursor.MoveOperation.End)

    def _on_out(self) -> None:
        data = bytes(self._shell.readAllStandardOutput()).decode("utf-8", errors="replace")
        # strip some interactive junk
        self._append(data)

    def _on_finished(self, code: int, _status) -> None:
        self._append(f"\n[shell exited code={code}]\n")

    def _clear(self) -> None:
        self.view.clear()

    def _interrupt(self) -> None:
        if self._shell.state() == QProcess.ProcessState.Running:
            self._shell.write(b"\x03")

    def _run_line(self) -> None:
        cmd = self.input.text().strip()
        if not cmd:
            return
        self._append(f"\n$ {cmd}\n")
        self.input.clear()
        # Prevent exiting the managed shell accidentally ending GUI session tools
        if cmd in {"exit", "logout"}:
            self._append("[use Restart shell instead of exit]\n")
            return
        self._write(cmd + "\n")



class DevConversationWindow(QDialog):
    """Dedicated window for ongoing conversations with scout-dev (admin)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scout Dev Conversations")
        self.resize(900, 700)
        self.setModal(False)
        self._proc: Optional[QProcess] = None
        self._history: list[dict] = []
        self._stdout: list[str] = []
        self._stderr: list[str] = []

        icon_path = _PROJECT_ROOT / "assets" / "scout.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("scout-dev (admin) conversations")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        self.status = QLabel("idle")
        self.status.setObjectName("badge")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status)
        root.addLayout(header)

        meta = QHBoxLayout()
        meta.addWidget(QLabel("Task mode"))
        self.task_mode = QComboBox()
        self.task_mode.addItems(["DEBUG", "PROCESS", "REVIEW", "IMPLEMENT", "TEST", "DOCS", "REFACTOR"])
        self.task_mode.setCurrentText("DEBUG")
        meta.addWidget(self.task_mode)
        meta.addStretch(1)
        root.addLayout(meta)

        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("monospace", 11))
        self.transcript.setPlaceholderText("Dev conversation history appears here...")
        root.addWidget(self.transcript, 1)

        self.input = QTextEdit()
        self.input.setFixedHeight(110)
        self.input.setPlaceholderText(
            "Message scout-dev (ADMIN-PRIVILEGED). Uses prompt syntax v1 and local Ollama only..."
        )
        root.addWidget(self.input)

        btns = QHBoxLayout()
        self.btn_send = QPushButton("Send to scout-dev")
        self.btn_send.clicked.connect(self.send_message)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_message)
        self.btn_clear = QPushButton("Clear history")
        self.btn_clear.setObjectName("secondary")
        self.btn_clear.clicked.connect(self.clear_history)
        btns.addWidget(self.btn_send)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_clear)
        btns.addStretch(1)
        root.addLayout(btns)

        note = QLabel(
            "Model locked to scout-dev. Main window chat is limited to manager (admin) and core."
        )
        note.setStyleSheet("color: #94a3b8;")
        root.addWidget(note)

    def append_history(self, role: str, content: str) -> None:
        content = (content or "").rstrip()
        self._history.append({"role": role, "content": content})
        block = chr(10) + "## " + role + chr(10) + content + chr(10)
        self.transcript.appendPlainText(block)
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)

    def clear_history(self) -> None:
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Busy", "Stop the current dev reply first.")
            return
        self._history.clear()
        self.transcript.clear()
        self.status.setText("idle")

    def send_message(self) -> None:
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Busy", "Dev is still replying.")
            return
        prompt = self.input.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "Prompt", "Enter a message for scout-dev.")
            return

        self.append_history("you", prompt)
        self.input.clear()
        self.btn_send.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status.setText("scout-dev thinking...")
        self.status.setObjectName("badge")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

        out_dir = _PROJECT_ROOT / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = out_dir / "gui_dev_prompt.txt"

        history_bits = []
        for item in self._history[:-1][-12:]:
            history_bits.append(str(item.get("role", "")).upper() + ": " + str(item.get("content", "")))
        history_ctx = (chr(10) + chr(10)).join(history_bits)

        # Write RAW user text only — CLI cmd_chat/build_chat_messages applies
        # PROMPT SYNTAX v1 once (idempotent). History goes via task-context-file.
        prompt_path.write_text(prompt + chr(10), encoding="utf-8")
        ctx_path = out_dir / "gui_dev_task_context.txt"
        if history_ctx:
            ctx_path.write_text(
                "=== DEV CONVERSATION CONTEXT (retain) ==="
                + chr(10)
                + history_ctx
                + chr(10),
                encoding="utf-8",
            )
        elif ctx_path.exists():
            try:
                ctx_path.unlink()
            except OSError:
                pass

        mode = self.task_mode.currentText().strip() or "DEBUG"
        args = [
            "dev",
            "-f",
            str(prompt_path),
            "--task-mode",
            mode,
            "-v",
            "--max-tokens",
            "2048",
        ]
        if history_ctx:
            args.extend(["--task-context-file", str(ctx_path)])

        proc = QProcess(self)
        proc.setWorkingDirectory(str(_PROJECT_ROOT))
        proc.setProcessEnvironment(_local_env())
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        scout_bin = Path.home() / ".local" / "bin" / "scout"
        if scout_bin.exists():
            prog = str(scout_bin)
            prog_args = args
        else:
            prog = _venv_python()
            prog_args = ["-m", "scout_crew.cli", *args]
        proc.setProgram(prog)
        proc.setArguments(prog_args)
        self._stdout = []
        self._stderr = []
        proc.readyReadStandardOutput.connect(lambda: self._collect(proc, False))
        proc.readyReadStandardError.connect(lambda: self._collect(proc, True))
        proc.finished.connect(self._finished)
        self._proc = proc
        proc.start()
        self.transcript.appendPlainText("[gui-dev] prompt_syntax=v1 model=dev mode=" + mode)

    def _collect(self, proc: QProcess, err: bool) -> None:
        if err:
            data = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace")
            self._stderr.append(data)
            for line in data.splitlines():
                if line.strip():
                    self.transcript.appendPlainText("[meta] " + line)
        else:
            data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._stdout.append(data)

    def stop_message(self) -> None:
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self.transcript.appendPlainText("[dev reply stopped]")

    def _finished(self, code: int, _status) -> None:
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        out = "".join(self._stdout).strip()
        if not out:
            out = "(empty dev response, exit=" + str(code) + ")"
        self.append_history("scout-dev", out)
        self.status.setText("idle (exit=" + str(code) + ")")
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_response_transcript"):
            last_user = ""
            for item in reversed(self._history):
                if item.get("role") == "you":
                    last_user = item.get("content") or ""
                    break
            parent.set_response_transcript(last_user, out, source="dev-window exit=" + str(code))


class ScoutMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scout Crew — Local CrewAI + Terminal")
        self.resize(1280, 840)
        icon_path = _PROJECT_ROOT / "assets" / "scout.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._crew_proc: Optional[QProcess] = None
        self._chat_proc: Optional[QProcess] = None
        self._dev_window = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        # Header
        header = QHBoxLayout()
        title = QLabel("Scout Local Control Plane")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        self.badge = QLabel("checking…")
        self.badge.setObjectName("badge")
        btn_refresh = QPushButton("Refresh status")
        btn_refresh.setObjectName("secondary")
        btn_refresh.clicked.connect(self.refresh_status)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.badge)
        header.addWidget(btn_refresh)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # Left: CrewAI controls
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 8, 0)

        status_box = QGroupBox("Local models / routing")
        sf = QVBoxLayout(status_box)
        self.status_view = QPlainTextEdit()
        self.status_view.setReadOnly(True)
        self.status_view.setFont(QFont("monospace", 10))
        self.status_view.setMaximumHeight(180)
        sf.addWidget(self.status_view)
        left_l.addWidget(status_box)

        crew_box = QGroupBox("CrewAI pipeline")
        cf = QFormLayout(crew_box)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText(
            "Response to the current prompt appears here (read-only)…"
        )
        self.transcript.setFixedHeight(140)
        self.transcript.setText(
            "(no response yet — send a chat or run the crew)"
        )
        self._last_prompt_text = ""
        self.dev_mode = QComboBox()
        self.dev_mode.addItems(["PROCESS", "REVIEW", "DEBUG", "IMPLEMENT", "TEST", "DOCS"])
        self.dev_request = QTextEdit()
        self.dev_request.setFixedHeight(70)
        self.dev_request.setPlainText(
            "Review local Scout crew health and propose a short upkeep checklist "
            "for models, Ollama, and scout crew. Stay offline."
        )
        self.user_prompt = QTextEdit()
        self.user_prompt.setFixedHeight(70)
        self.user_prompt.setPlaceholderText(
            "Operator prompt for the manager (required intent the manager must answer)…"
        )
        self.user_prompt.setPlainText(
            "Alpha development check: confirm phase_class=alpha_development is still held, Arizona jurisdiction is active (AZ_JURISDICTION_ACTIVE), AZ marker filters are set, and scanner/hazard remain essential inside AZ only. Stay in alpha persona unless this prompt explicitly starts the second deployment phase. Then finish the brief."
        )
        cf.addRow("Response (read-only)", self.transcript)
        cf.addRow("Dev mode", self.dev_mode)
        cf.addRow("Dev request", self.dev_request)
        cf.addRow("Manager prompt (admin priority)", self.user_prompt)
        crew_btns = QHBoxLayout()
        self.btn_run_crew = QPushButton("Run full crew")
        self.btn_run_crew.clicked.connect(self.run_crew)
        self.btn_stop_crew = QPushButton("Stop")
        self.btn_stop_crew.setObjectName("danger")
        self.btn_stop_crew.clicked.connect(self.stop_crew)
        self.btn_stop_crew.setEnabled(False)
        self.btn_open_out = QPushButton("Open output folder")
        self.btn_open_out.setObjectName("secondary")
        self.btn_open_out.clicked.connect(self.open_output)
        crew_btns.addWidget(self.btn_run_crew)
        crew_btns.addWidget(self.btn_stop_crew)
        crew_btns.addWidget(self.btn_open_out)
        cf.addRow(crew_btns)
        left_l.addWidget(crew_box)

        chat_box = QGroupBox("Admin / Core chat")
        chf = QFormLayout(chat_box)
        self.chat_model = QComboBox()
        self.chat_model.addItems(["manager", "core"])
        self.chat_model.setToolTip(
            "Main chat is limited to admin (manager) and core. Use Dev Conversations for scout-dev."
        )
        self.chat_prompt = QTextEdit()
        self.chat_prompt.setFixedHeight(70)
        self.chat_prompt.setPlaceholderText("USER QUERY for any model (dev/manager/core/alert/intel/vet/rank/base) — always sent via prompt syntax v1…")
        ch_btns = QHBoxLayout()
        self.btn_chat = QPushButton("Send chat")
        self.btn_chat.clicked.connect(self.run_chat)
        self.btn_stop_chat = QPushButton("Stop chat")
        self.btn_stop_chat.setObjectName("danger")
        self.btn_stop_chat.setEnabled(False)
        self.btn_stop_chat.clicked.connect(self.stop_chat)
        self.btn_to_manager = QPushButton("Use as manager prompt")
        self.btn_to_manager.setObjectName("secondary")
        self.btn_to_manager.clicked.connect(self.copy_chat_to_manager)
        self.btn_open_dev = QPushButton("Dev Conversations")
        self.btn_open_dev.setObjectName("secondary")
        self.btn_open_dev.clicked.connect(self.open_dev_window)
        ch_btns.addWidget(self.btn_chat)
        ch_btns.addWidget(self.btn_stop_chat)
        ch_btns.addWidget(self.btn_open_dev)
        ch_btns.addWidget(self.btn_to_manager)
        chf.addRow("Model / role", self.chat_model)
        chf.addRow("Prompt", self.chat_prompt)
        chf.addRow(ch_btns)
        left_l.addWidget(chat_box)
        left_l.addStretch(1)

        # Right: tabs console + terminal
        right = QTabWidget()
        self.crew_console = ProcessConsole()
        self.chat_console = ProcessConsole()
        self.terminal = TerminalPane()
        right.addTab(self.crew_console, "Crew output")
        right.addTab(self.chat_console, "Chat output")
        right.addTab(self.terminal, "Terminal")

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Project: {_PROJECT_ROOT} · local-only routing")

        # menu
        file_menu = self.menuBar().addMenu("&File")
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)
        tools = self.menuBar().addMenu("&Tools")
        act_status = QAction("Refresh status", self)
        act_status.triggered.connect(self.refresh_status)
        tools.addAction(act_status)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self.refresh_status)
        self._status_timer.start(15000)
        self.refresh_status()

    def refresh_status(self) -> None:
        try:
            st = llm_status()
            roster = model_roster()
            payload = {"status": st, "roster": roster}
            self.status_view.setPlainText(json.dumps(payload, indent=2))
            if st.get("ollama_up") and st.get("external_token_usage") is False:
                self.badge.setText("LOCAL · Ollama up · no cloud tokens")
                self.badge.setObjectName("badge")
            else:
                self.badge.setText("Ollama down or misconfigured")
                self.badge.setObjectName("badgeWarn")
            # re-polish objectName style
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
            self.statusBar().showMessage(
                f"Ollama {st.get('ollama_host')} · base {st.get('openai_compatible_base')}",
                5000,
            )
        except Exception as exc:  # noqa: BLE001
            self.status_view.setPlainText(f"status error: {exc}")
            self.badge.setText("status error")
            self.badge.setObjectName("badgeWarn")
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)

    def _start_proc(self, args: list[str], console: ProcessConsole, kind: str) -> QProcess:
        proc = QProcess(self)
        proc.setWorkingDirectory(str(_PROJECT_ROOT))
        proc.setProcessEnvironment(_local_env())
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        console.clear()
        console.attach(proc)
        console.appendPlainText(f"$ {' '.join(args)}\n")
        scout_bin = Path.home() / ".local" / "bin" / "scout"
        if scout_bin.exists():
            prog = str(scout_bin)
            prog_args = args
        else:
            prog = _venv_python()
            prog_args = ["-m", "scout_crew.cli", *args]
        proc.setProgram(prog)
        proc.setArguments(prog_args)
        if kind == "crew":
            proc.finished.connect(self._crew_finished)
        else:
            proc.finished.connect(self._chat_finished)
        proc.start()
        return proc

    def run_crew(self) -> None:
        if self._crew_proc and self._crew_proc.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Busy", "Crew is already running.")
            return
        # Write a temp inputs file for reproducibility
        out_dir = _PROJECT_ROOT / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_up = (
            self.user_prompt.toPlainText().strip()
            or "Summarize the specialist results for the operator."
        )
        raw_up = extract_raw_user_query(raw_up) or raw_up
        inputs = {
            "transcript": DEFAULT_SCANNER_TRANSCRIPT,
            "dev_mode": self.dev_mode.currentText(),
            "dev_request": self.dev_request.toPlainText().strip(),
            "user_prompt": convert_user_prompt(
                raw_up, role="manager", source="gui-crew"
            ),
            "user_prompt_raw": raw_up,
            "user_prompt_privilege": "admin",
            "prompt_syntax": "v1",
        }
        inputs_path = out_dir / "gui_inputs.json"
        inputs_path.write_text(json.dumps(inputs, indent=2), encoding="utf-8")
        self.btn_run_crew.setEnabled(False)
        self.btn_stop_crew.setEnabled(True)
        self._crew_proc = self._start_proc(
            ["crew", "-v", "--inputs", str(inputs_path)],
            self.crew_console,
            "crew",
        )
        self.statusBar().showMessage("Crew running (local models)…")

    def stop_crew(self) -> None:
        if self._crew_proc and self._crew_proc.state() != QProcess.ProcessState.NotRunning:
            self._crew_proc.kill()
            self.crew_console.appendPlainText("\n[killed]\n")

    def _crew_finished(self, code: int, _status) -> None:
        self.btn_run_crew.setEnabled(True)
        self.btn_stop_crew.setEnabled(False)
        self.crew_console.appendPlainText(f"\n[crew finished exit={code}]\n")
        # Show brief tails if present
        brief_bits = []
        for name in ("local_brief.json", "dev_brief.md"):
            path = _PROJECT_ROOT / "output" / name
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                self.crew_console.appendPlainText(f"\n===== {name} =====\n")
                self.crew_console.appendPlainText(text[:4000])
                brief_bits.append(f"===== {name} =====\n{text[:6000]}")
        # Prefer structured brief as the response panel content
        if brief_bits:
            response = "\n\n".join(brief_bits)
        else:
            response = self._extract_console_response(self.crew_console)
        prompt = ""
        if hasattr(self, "user_prompt"):
            prompt = self.user_prompt.toPlainText().strip()
        if not prompt:
            prompt = getattr(self, "_last_prompt_text", "") or "(crew run)"
        self.set_response_transcript(prompt, response, source=f"crew exit={code}")
        self.statusBar().showMessage(f"Crew finished ({code})", 8000)
        self.refresh_status()

    
    def open_dev_window(self) -> None:
        """Open/focus dedicated scout-dev conversation window."""
        if self._dev_window is None:
            self._dev_window = DevConversationWindow(self)
        self._dev_window.show()
        self._dev_window.raise_()
        self._dev_window.activateWindow()

    def run_chat(self) -> None:
        if self._chat_proc and self._chat_proc.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Busy", "Chat is already running.")
            return
        prompt = self.chat_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "Prompt", "Enter a prompt first.")
            return
        model = (self.chat_model.currentText() or "dev").strip()
        # Persist multi-line USER QUERY so shell/argv never drops prompt syntax.
        out_dir = _PROJECT_ROOT / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = out_dir / "gui_chat_prompt.txt"
        # Always write RAW user text. scout chat applies PROMPT SYNTAX v1 once.
        prompt_path.write_text(prompt + "\n", encoding="utf-8")

        # Optional retained context from crew fields (helps manager/dev mid-task chats).
        ctx_lines = []
        # Response panel is read-only output; do not feed it back as scanner transcript.
        # Prefer last user chat prompt / manager prompt as retained context instead.
        if getattr(self, "_last_prompt_text", ""):
            ctx_lines.append("current_prompt:\n" + self._last_prompt_text)
        dr = self.dev_request.toPlainText().strip()
        if dr:
            ctx_lines.append("dev_request:\n" + dr)
        mp = ""
        if hasattr(self, "user_prompt"):
            mp = self.user_prompt.toPlainText().strip()
            if mp:
                ctx_lines.append("manager_user_prompt:\n" + mp)
        ctx_path = out_dir / "gui_chat_task_context.txt"
        if ctx_lines:
            ctx_path.write_text("\n\n".join(ctx_lines) + "\n", encoding="utf-8")
        else:
            if ctx_path.exists():
                try:
                    ctx_path.unlink()
                except OSError:
                    pass

        args = [
            "chat",
            "-m",
            model,
            "-f",
            str(prompt_path),
            "-v",
            "--max-tokens",
            "2048",
        ]
        # task-mode: for dev use GUI dev_mode; for others leave empty unless dev selected
        if model in {"dev", "scout-dev"} and hasattr(self, "dev_mode"):
            args.extend(["--task-mode", self.dev_mode.currentText().strip() or "PROCESS"])
        if model in {"manager", "admin", "mgr", "dev", "scout-dev"}:
            # Manager chats also carry operator prompt context when present
            args.extend(["--task-mode", "ADMIN_USER_PROMPT"])
        if ctx_lines:
            args.extend(["--task-context-file", str(ctx_path)])

        self.btn_chat.setEnabled(False)
        self.btn_stop_chat.setEnabled(True)
        self.chat_console.appendPlainText(
            f"[gui] prompt_syntax=v1 model={model} user_query_chars={len(prompt)} file={prompt_path}\n"
        )
        self._chat_proc = self._start_proc(args, self.chat_console, "chat")
        self.statusBar().showMessage(
            f"Chat → {model} via prompt syntax v1 (local Ollama)", 5000
        )

    def stop_chat(self) -> None:
        if self._chat_proc and self._chat_proc.state() != QProcess.ProcessState.NotRunning:
            self._chat_proc.kill()
            self.chat_console.appendPlainText("\n[killed]\n")

    def _chat_finished(self, code: int, _status) -> None:
        self.btn_chat.setEnabled(True)
        self.btn_stop_chat.setEnabled(False)
        response = self._extract_console_response(self.chat_console)
        prompt = getattr(self, "_last_prompt_text", "") or self.chat_prompt.toPlainText().strip()
        self.set_response_transcript(prompt, response, source=f"chat exit={code}")
        self.chat_console.appendPlainText(f"\n[chat finished exit={code}]\n")


    def set_response_transcript(self, prompt: str, response: str, *, source: str = "chat") -> None:
        """Show the model/crew response for the current prompt (read-only field)."""
        prompt = (prompt or "").strip()
        response = (response or "").strip()
        self._last_prompt_text = prompt
        header = f"[source: {source}]"
        if prompt:
            # Keep prompt short in the header so the response dominates the box
            preview = prompt if len(prompt) <= 240 else prompt[:240] + "…"
            body = (
                f"{header}\n"
                f"--- current prompt ---\n"
                f"{preview}\n"
                f"--- response ---\n"
                f"{response if response else '(empty response)'}"
            )
        else:
            body = f"{header}\n--- response ---\n{response if response else '(empty response)'}"
        self.transcript.setPlainText(body)
        # Keep cursor at top so user sees the start of the response
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.transcript.setTextCursor(cursor)

    def _extract_console_response(self, console: QPlainTextEdit) -> str:
        """Best-effort: take console text after the launch command line, drop meta/err noise."""
        raw = console.toPlainText()
        lines = raw.splitlines()
        out_lines = []
        started = False
        for line in lines:
            if not started:
                # first non-empty line is usually the echoed $ command or [gui] meta
                if line.startswith("$ ") or line.startswith("[gui]"):
                    started = True
                continue
            if line.startswith("[err]"):
                continue
            if line.startswith("[chat finished") or line.startswith("[crew finished"):
                break
            if line.startswith("{") and '"route"' in line:
                # skip verbose JSON blocks if they leaked to stdout (shouldn't)
                continue
            out_lines.append(line)
        text = "\n".join(out_lines).strip()
        # If filtering was too aggressive, fall back to full console minus first line
        if not text and len(lines) > 1:
            text = "\n".join(lines[1:]).strip()
        return text

    def copy_chat_to_manager(self) -> None:
        text = self.chat_prompt.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Prompt", "Chat prompt is empty.")
            return
        self.user_prompt.setPlainText(text)
        self.statusBar().showMessage(
            "Copied chat prompt into Manager prompt (used on next Run full crew)",
            6000,
        )

    def open_output(self) -> None:
        out = _PROJECT_ROOT / "output"
        out.mkdir(parents=True, exist_ok=True)
        QProcess.startDetached("xdg-open", [str(out)])


def main(argv: Optional[list[str]] = None) -> int:
    # Guard display
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("scout-gui: no DISPLAY/WAYLAND_DISPLAY — cannot start GUI", file=sys.stderr)
        return 2
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Scout Crew")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    win = ScoutMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
