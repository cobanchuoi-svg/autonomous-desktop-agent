from agent.actions.window_layout import DocumentWindowController


class FakeWindow:
    def __init__(self, title):
        self.title = title


def test_window_title_matching_ignores_spacing_and_case():
    assert DocumentWindowController._matches_title("WPS Office - Report", "wpsoffice")
    assert DocumentWindowController._matches_title("scan_001.PDF - Viewer", "scan001")
    assert not DocumentWindowController._matches_title("WPS Office", "Excel")


def test_wps_office_is_ranked_above_wps_photo_viewer():
    assert DocumentWindowController._wps_window_score("Workbook1 - WPS Office") > 0
    assert DocumentWindowController._wps_window_score("5_1.jpg WPS Photos") < 0


def test_escaped_underscore_matches_document_window_title():
    assert DocumentWindowController._matches_title("5_1.jpg WPS Photos", r"5\_1")


def test_same_title_duplicates_are_safe_to_select(monkeypatch):
    import pygetwindow

    monkeypatch.setattr(
        pygetwindow,
        "getAllWindows",
        lambda: [FakeWindow("5_1.jpg  WPS Photos"), FakeWindow("5_1.jpg  WPS Photos")],
    )
    window = DocumentWindowController._find_window("5_1")
    assert window is not None
    assert window.title == "5_1.jpg  WPS Photos"


def test_missing_document_is_rejected_before_window_operations(tmp_path):
    result = DocumentWindowController().prepare_foreground_document(str(tmp_path / "missing.pdf"))
    assert result.success is False
    assert "does not exist" in result.reason
