from PySide6.QtCore import QRect, QSize

from internal.services.circle_ui import _compute_todo_window_position


def test_compute_todo_window_position_anchors_to_todo_button():
    frame = QRect(100, 100, 300, 800)
    button = QRect(84, 700, 54, 22)
    panel_size = QSize(300, 420)
    screen = QRect(0, 0, 1600, 1200)

    x, y = _compute_todo_window_position(frame, button, panel_size, screen)

    expected_y = frame.top() + button.center().y() - (panel_size.height() // 2)
    assert x == frame.right() + 12
    assert y == expected_y
    assert y > frame.top() + 20


def test_compute_todo_window_position_clamps_to_screen_bounds():
    frame = QRect(220, 40, 300, 800)
    button = QRect(84, 4, 54, 22)
    panel_size = QSize(300, 500)
    screen = QRect(0, 0, 620, 360)

    x, y = _compute_todo_window_position(frame, button, panel_size, screen)

    assert x <= screen.right() - panel_size.width() - 8
    assert y == screen.top() + 8
