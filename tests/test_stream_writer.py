import pytest
from unittest.mock import MagicMock, patch

from agent.actions.image_clipboard import (
    copy_image_content_to_wps,
    format_text_as_tsv,
    stream_write_text_to_window,
)


class FakeWindowController:
    def __init__(self, can_activate: bool = True):
        self.can_activate = can_activate
        self.activated_titles = []

    def activate_window(self, title: str) -> bool:
        if self.can_activate:
            self.activated_titles.append(title)
            return True
        return False


def test_format_text_as_tsv_converts_spaces():
    raw = "Tên    Số tiền    Ghi chú\nAlice    1000    Đã thanh toán"
    tsv = format_text_as_tsv(raw)
    assert "Tên\tSố tiền\tGhi chú" in tsv
    assert "Alice\t1000\tĐã thanh toán" in tsv


def test_stream_write_fails_on_empty_text():
    controller = FakeWindowController()
    result = stream_write_text_to_window("   ", wps_title="Word", window_controller=controller)
    assert not result.success
    assert "OCR produced no text" in result.message


def test_stream_write_fails_when_window_cannot_be_focused():
    controller = FakeWindowController(can_activate=False)
    result = stream_write_text_to_window("Hello World", wps_title="Word", window_controller=controller)
    assert not result.success
    assert "Could not focus Word" in result.message


def test_copy_image_content_routes_to_stream_for_word():
    controller = FakeWindowController()
    with patch("agent.actions.image_clipboard.stream_write_text_to_window") as mock_stream:
        mock_stream.return_value = MagicMock(success=True, message="Streamed ok")
        result = copy_image_content_to_wps("Cộng hòa Xã hội", wps_title="Microsoft Word", window_controller=controller)
        assert result.success
        assert mock_stream.called


def test_copy_image_content_routes_to_paste_for_excel():
    controller = FakeWindowController()
    with patch("agent.actions.image_clipboard._paste_text") as mock_paste:
        mock_paste.return_value = MagicMock(success=True, message="Pasted TSV ok")
        result = copy_image_content_to_wps("Cột 1   Cột 2", wps_title="WPS Sheet", window_controller=controller)
        assert result.success
        assert mock_paste.called
