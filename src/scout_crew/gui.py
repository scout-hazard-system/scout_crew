#!/usr/bin/env python
# Copyright 2026 Scout Project Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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

try:
    from scout_crew.blackboard.client import BlackboardClient
except Exception:  # pragma: no cover
    BlackboardClient = None  # type: ignore

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
QLabel#badgeHermes {
  background: #1e1b4b;
  color: #c4b5fd;
  border: 1px solid #5b21b6;
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



class HermesConversationPane(QWidget):
    """Integrated Hermes-model chat (classic Hermes desktop can also be launched)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: Optional[QProcess] = None
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._history: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel("Hermes · scout-hermes-hc (Project Director)")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #c4b5fd;")
        self.status = QLabel("idle")
        self.status.setObjectName("badgeHermes")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status)
        root.addLayout(header)

        meta = QHBoxLayout()
        meta.addWidget(QLabel("Model"))
        self.model = QComboBox()
        self.model.addItems([
            "hermes",
            "scout-hermes-hc1.0.0",
            "scout-hermes-hc1.0.0-64k",
            "scout-hermes-hc1.1.0",
            "manager",
            "core",
        ])
        self.model.setCurrentText("hermes")
        meta.addWidget(self.model)
        meta.addWidget(QLabel("Mode"))
        self.mode = QComboBox()
        self.mode.addItems([
            "MANAGER", "DEV", "CORE", "PIPELINE", "ALERT", "CHAT", "NAV", "DEBUG", "PROCESS"
        ])
        self.mode.setCurrentText("MANAGER")
        meta.addWidget(self.mode)
        self.btn_classic = QPushButton("Launch classic Hermes GUI")
        self.btn_classic.setObjectName("secondary")
        self.btn_classic.clicked.connect(self.launch_classic_hermes)
        meta.addWidget(self.btn_classic)
        meta.addStretch(1)
        root.addLayout(meta)

        note = QLabel(
            "Integrated chat uses local Ollama via scout CLI (PROMPT SYNTAX v1). "
            "Classic Hermes opens the Electron desktop app (hermes desktop) with the same model config."
        )
        note.setStyleSheet("color: #94a3b8;")
        note.setWordWrap(True)
        root.addWidget(note)

        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("monospace", 11))
        self.transcript.setPlaceholderText("Hermes conversation history…")
        root.addWidget(self.transcript, 1)

        self.input = QTextEdit()
        self.input.setFixedHeight(110)
        self.input.setPlaceholderText(
            "Message Hermes Project Director (ADMIN-PRIVILEGED). Blackboard is read-only for hermes."
        )
        root.addWidget(self.input)

        btns = QHBoxLayout()
        self.btn_send = QPushButton("Send to Hermes")
        self.btn_send.clicked.connect(self.send_message)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_message)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("secondary")
        self.btn_clear.clicked.connect(self.clear_history)
        self.btn_bb = QPushButton("Snapshot blackboard")
        self.btn_bb.setObjectName("secondary")
        self.btn_bb.clicked.connect(self.snapshot_blackboard)
        btns.addWidget(self.btn_send)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_clear)
        btns.addWidget(self.btn_bb)
        btns.addStretch(1)
        root.addLayout(btns)

    def append_history(self, role: str, content: str) -> None:
        content = (content or "").rstrip()
        self._history.append({"role": role, "content": content})
        self.transcript.appendPlainText("\n## " + role + "\n" + content + "\n")
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)

    def clear_history(self) -> None:
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Busy", "Stop the current Hermes reply first.")
            return
        self._history.clear()
        self.transcript.clear()
        self.status.setText("idle")

    def launch_classic_hermes(self) -> None:
        """Launch classic Hermes Electron desktop (best-effort)."""
        hermes = shutil.which("hermes") or str(Path.home() / ".local/bin/hermes")
        if not Path(hermes).exists():
            QMessageBox.warning(
                self,
                "Hermes",
                "hermes CLI not found. Install Hermes Agent, then retry.",
            )
            return
        env = _local_env()
        # Prefer desktop; fall back to plain hermes TUI in terminal tab note
        ok = QProcess.startDetached(
            hermes,
            ["desktop", "--cwd", str(_PROJECT_ROOT)],
            str(_PROJECT_ROOT),
        )
        if not ok:
            ok = QProcess.startDetached(hermes, [], str(_PROJECT_ROOT))
        if ok:
            self.transcript.appendPlainText(
                "[gui] launched classic Hermes desktop (hermes desktop)\n"
            )
            self.status.setText("classic Hermes launched")
        else:
            QMessageBox.warning(self, "Hermes", "Failed to launch hermes desktop.")

    def snapshot_blackboard(self) -> None:
        if BlackboardClient is None:
            self.transcript.appendPlainText("[blackboard] client unavailable\n")
            return
        try:
            client = BlackboardClient()
            snap = client.snapshot(role="hermes", limit_per_category=12)
            self.transcript.appendPlainText(
                "\n## blackboard snapshot (hermes read-only)\n"
                + json.dumps(snap, indent=2)[:8000]
                + "\n"
            )
        except Exception as exc:  # noqa: BLE001
            self.transcript.appendPlainText(f"[blackboard error] {exc}\n")

    def send_message(self) -> None:
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Busy", "Hermes is still replying.")
            return
        prompt = self.input.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "Prompt", "Enter a message for Hermes.")
            return
        self.append_history("you", prompt)
        self.input.clear()
        self.btn_send.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status.setText("hermes thinking…")

        out_dir = _PROJECT_ROOT / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = out_dir / "gui_hermes_prompt.txt"
        # Include MODE for unified hermes brain
        mode = self.mode.currentText().strip() or "MANAGER"
        body = f"MODE: {mode}\n=== USER QUERY (ADMIN-PRIVILEGED) ===\n{prompt}\n=== END USER QUERY ===\n"
        # retain short history as task context
        history_bits = []
        for item in self._history[:-1][-8:]:
            history_bits.append(
                str(item.get("role", "")).upper() + ": " + str(item.get("content", ""))[:500]
            )
        ctx_path = out_dir / "gui_hermes_task_context.txt"
        if history_bits:
            ctx_path.write_text(
                "=== HERMES CONVERSATION CONTEXT ===\n" + "\n\n".join(history_bits) + "\n",
                encoding="utf-8",
            )
        prompt_path.write_text(body, encoding="utf-8")

        model = (self.model.currentText() or "hermes").strip()
        args = [
            "chat",
            "-m",
            model,
            "-f",
            str(prompt_path),
            "--task-mode",
            mode,
            "-v",
            "--max-tokens",
            "2048",
        ]
        if history_bits:
            args.extend(["--task-context-file", str(ctx_path)])

        proc = QProcess(self)
        proc.setWorkingDirectory(str(_PROJECT_ROOT))
        proc.setProcessEnvironment(_local_env())
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        scout_bin = Path.home() / ".local" / "bin" / "scout"
        if scout_bin.exists():
            prog, prog_args = str(scout_bin), args
        else:
            prog, prog_args = _venv_python(), ["-m", "scout_crew.cli", *args]
        proc.setProgram(prog)
        proc.setArguments(prog_args)
        self._stdout = []
        self._stderr = []
        proc.readyReadStandardOutput.connect(lambda: self._collect(proc, False))
        proc.readyReadStandardError.connect(lambda: self._collect(proc, True))
        proc.finished.connect(self._finished)
        self._proc = proc
        proc.start()
        self.transcript.appendPlainText(
            f"[gui-hermes] model={model} mode={mode} prompt_syntax=v1\n"
        )

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
            self.transcript.appendPlainText("[hermes reply stopped]")

    def _finished(self, code: int, _status) -> None:
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        out = "".join(self._stdout).strip()
        if not out:
            out = f"(empty hermes response, exit={code})"
        self.append_history("hermes", out)
        self.status.setText(f"idle (exit={code})")
        parent = self.parent()
        # walk up to main window
        w = self
        while w is not None and not hasattr(w, "set_response_transcript"):
            w = w.parent() if hasattr(w, "parent") else None
        if w is not None and hasattr(w, "set_response_transcript"):
            last_user = ""
            for item in reversed(self._history):
                if item.get("role") == "you":
                    last_user = item.get("content") or ""
                    break
            w.set_response_transcript(last_user, out, source=f"hermes-tab exit={code}")


class BlackboardMonitorPane(QWidget):
    """Live view of blackboard server + category activity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server_proc: Optional[QProcess] = None
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel("Blackboard processes")
        title.setStyleSheet("font-weight: 700; color: #93c5fd;")
        self.badge = QLabel("local/remote")
        self.badge.setObjectName("badge")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.badge)
        root.addLayout(header)

        controls = QHBoxLayout()
        self.btn_start = QPushButton("Start BB server :8765")
        self.btn_start.clicked.connect(self.start_server)
        self.btn_stop = QPushButton("Stop server")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_server)
        self.btn_refresh = QPushButton("Refresh now")
        self.btn_refresh.setObjectName("secondary")
        self.btn_refresh.clicked.connect(self.refresh)
        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_stop)
        controls.addWidget(self.btn_refresh)
        controls.addStretch(1)
        root.addLayout(controls)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("monospace", 10))
        self.view.setPlaceholderText("Blackboard stats, pipeline + dev_debug snapshots…")
        root.addWidget(self.view, 1)

        self.server_log = ProcessConsole()
        self.server_log.setMaximumHeight(160)
        self.server_log.setPlaceholderText("Blackboard server process log…")
        root.addWidget(QLabel("Server process log"))
        root.addWidget(self.server_log)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(4000)
        self.refresh()

    def start_server(self) -> None:
        if self._server_proc and self._server_proc.state() != QProcess.ProcessState.NotRunning:
            return
        proc = QProcess(self)
        proc.setWorkingDirectory(str(_PROJECT_ROOT))
        proc.setProcessEnvironment(_local_env())
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.server_log.clear()
        self.server_log.attach(proc)
        proc.setProgram(_venv_python())
        proc.setArguments(
            [
                "-m",
                "scout_crew.blackboard.server",
                "--host",
                "0.0.0.0",
                "--port",
                "8765",
            ]
        )
        self._server_proc = proc
        proc.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.badge.setText("server starting…")
        self.server_log.appendPlainText("$ python -m scout_crew.blackboard.server --host 0.0.0.0 --port 8765\n")

    def stop_server(self) -> None:
        if self._server_proc and self._server_proc.state() != QProcess.ProcessState.NotRunning:
            self._server_proc.kill()
            self.server_log.appendPlainText("\n[server killed]\n")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.badge.setText("server stopped")

    def refresh(self) -> None:
        if BlackboardClient is None:
            self.view.setPlainText("blackboard module unavailable")
            return
        try:
            client = BlackboardClient()
            stats = client.stats()
            # hermes-visible snapshot
            try:
                snap = client.snapshot(role="hermes", limit_per_category=8)
            except Exception as exc:  # noqa: BLE001
                snap = {"error": str(exc)}
            mode = client.mode
            running = bool(
                self._server_proc
                and self._server_proc.state() != QProcess.ProcessState.NotRunning
            )
            self.badge.setText(
                f"{mode}" + (" · server up" if running else " · server off")
            )
            self.badge.setObjectName("badge" if mode else "badgeWarn")
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
            payload = {
                "mode": mode,
                "server_process_running": running,
                "stats": stats,
                "snapshot_hermes_readonly": snap,
            }
            self.view.setPlainText(json.dumps(payload, indent=2))
        except Exception as exc:  # noqa: BLE001
            self.view.setPlainText(f"blackboard refresh error: {exc}")
            self.badge.setText("error")
            self.badge.setObjectName("badgeWarn")
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)


class PipelineMonitorPane(QWidget):
    """Per-pipeline process / blackboard pipeline category view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel("Pipeline processes")
        title.setStyleSheet("font-weight: 700; color: #86efac;")
        self.badge = QLabel("pipeline")
        self.badge.setObjectName("badge")
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setObjectName("secondary")
        self.btn_refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.badge)
        header.addWidget(self.btn_refresh)
        root.addLayout(header)

        split = QSplitter(Qt.Orientation.Vertical)

        self.board = QPlainTextEdit()
        self.board.setReadOnly(True)
        self.board.setFont(QFont("monospace", 10))
        self.board.setPlaceholderText("pipeline category entries (specialist writers + manager summaries)…")
        split.addWidget(self.board)

        self.crew_tail = QPlainTextEdit()
        self.crew_tail.setReadOnly(True)
        self.crew_tail.setFont(QFont("monospace", 10))
        self.crew_tail.setPlaceholderText("Recent crew / pipeline file artifacts…")
        split.addWidget(self.crew_tail)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)
        self.refresh()

    def refresh(self) -> None:
        lines = []
        # blackboard pipeline
        if BlackboardClient is not None:
            try:
                client = BlackboardClient()
                entries = client.read(
                    category="pipeline", role="manager", limit=20, active_only=True
                )
                lines.append("=== BLACKBOARD pipeline ===")
                lines.append(client.format_entries(entries))
                self.badge.setText(f"pipeline entries={len(entries)}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"[blackboard] {exc}")
                self.badge.setText("pipeline error")
        else:
            lines.append("[blackboard unavailable]")
        self.board.setPlainText("\n".join(lines))

        # artifact tails
        art = []
        out = _PROJECT_ROOT / "output"
        for name in (
            "local_brief.json",
            "dev_brief.md",
            "az_manager_status.json",
            "gui_inputs.json",
        ):
            p = out / name
            if p.exists():
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    art.append(f"===== {name} =====\n{txt[:2500]}")
                except OSError as exc:
                    art.append(f"===== {name} =====\n(read error: {exc})")
        # role roster
        try:
            art.insert(0, "=== model roster ===\n" + json.dumps(model_roster(), indent=2))
        except Exception as exc:  # noqa: BLE001
            art.insert(0, f"roster error: {exc}")
        self.crew_tail.setPlainText("\n\n".join(art) if art else "(no pipeline artifacts yet)")


class ScoutMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scout Crew — Hermes + CrewAI + Blackboard")
        self.resize(1440, 920)
        icon_path = _PROJECT_ROOT / "assets" / "scout.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._crew_proc: Optional[QProcess] = None
        self._chat_proc: Optional[QProcess] = None
        self._dev_window = None
        self._hermes_classic_launched = False

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
        self.chat_model.addItems(["manager", "core", "hermes", "scout-hermes-hc1.0.0"])
        self.chat_model.setToolTip(
            "Main chat: manager/core/hermes. Dev Conversations = scout-dev. Hermes tab = Project Director + classic GUI."
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

        # Right: tabs — Hermes first (selected at startup)
        right = QTabWidget()
        self.hermes_pane = HermesConversationPane(self)
        self.crew_console = ProcessConsole()
        self.chat_console = ProcessConsole()
        self.blackboard_pane = BlackboardMonitorPane(self)
        self.pipeline_pane = PipelineMonitorPane(self)
        self.terminal = TerminalPane()
        right.addTab(self.hermes_pane, "Hermes")
        right.addTab(self.crew_console, "Crew output")
        right.addTab(self.chat_console, "Chat output")
        right.addTab(self.blackboard_pane, "Blackboard")
        right.addTab(self.pipeline_pane, "Pipeline")
        right.addTab(self.terminal, "Terminal")
        right.setCurrentIndex(0)  # Hermes open at startup

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
        act_hermes = QAction("Launch classic Hermes GUI", self)
        act_hermes.triggered.connect(self.hermes_pane.launch_classic_hermes)
        tools.addAction(act_hermes)
        act_bb = QAction("Start blackboard server", self)
        act_bb.triggered.connect(self.blackboard_pane.start_server)
        tools.addAction(act_bb)
        act_dev = QAction("Open Dev Conversations", self)
        act_dev.triggered.connect(self.open_dev_window)
        tools.addAction(act_dev)

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
            # include hermes model presence
            installed = st.get("installed_models") or []
            has_hermes = any("hermes-hc" in str(x) for x in installed)
            roster_line = roster.get("hermes") or roster.get("manager")
            if has_hermes:
                self.badge.setText(
                    f"LOCAL · Ollama up · hermes={roster_line} · no cloud"
                )
            if hasattr(self, "pipeline_pane"):
                # lightweight; timer also refreshes
                pass
            self.statusBar().showMessage(
                f"Ollama {st.get('ollama_host')} · base {st.get('openai_compatible_base')} · hermes={roster_line}",
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
        if hasattr(self, "pipeline_pane"):
            self.pipeline_pane.refresh()
        if hasattr(self, "blackboard_pane"):
            self.blackboard_pane.refresh()

    
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
    # Optionally auto-launch classic Hermes desktop once
    if os.getenv("SCOUT_GUI_LAUNCH_HERMES_DESKTOP", "").lower() in {"1", "true", "yes"}:
        QTimer.singleShot(800, win.hermes_pane.launch_classic_hermes)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
