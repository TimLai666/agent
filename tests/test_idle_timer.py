import sys
import time
from PySide6.QtWidgets import QApplication
import main

class DummyRuntime:
    class DummySignal:
        def connect(self, *_):
            pass
    def __init__(self, *_args, **_kwargs):
        self.ready = DummyRuntime.DummySignal()
        self.result_ready = DummyRuntime.DummySignal()
        self.chunk_ready = DummyRuntime.DummySignal()
        self.error_occurred = DummyRuntime.DummySignal()
        self.tool_event = DummyRuntime.DummySignal()
    def start(self):
        return None


def test_typing_resets_idle_timer(monkeypatch):
    # Ensure a QApplication exists for widgets
    QApplication.instance() or QApplication(sys.argv)

    # Monkeypatch AgentRuntime to avoid starting real runtime threads
    monkeypatch.setattr(main, "AgentRuntime", DummyRuntime)

    gui = main.GUIAgentApp()

    try:
        # Ensure idle timer is not active initially
        gui._idle_timer.stop()
        assert not gui._idle_timer.isActive()

        # Simulate typing by emitting the MainWindow typing signal
        gui.main_window.typing.emit()

        # The _reset_idle_timer should start the timer
        assert gui._idle_timer.isActive()
    finally:
        try:
            gui.main_window.close()
        except Exception:
            pass
        # Restore any modified state is handled by monkeypatch fixture
