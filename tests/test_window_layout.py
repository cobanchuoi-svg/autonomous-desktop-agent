from agent.actions.window_layout import DocumentWindowController


def test_window_title_matching_ignores_spacing_and_case():
    assert DocumentWindowController._matches_title("WPS Office - Report", "wpsoffice")
    assert DocumentWindowController._matches_title("scan_001.PDF - Viewer", "scan001")
    assert not DocumentWindowController._matches_title("WPS Office", "Excel")


def test_missing_document_is_rejected_before_window_operations(tmp_path):
    result = DocumentWindowController().prepare_foreground_document(str(tmp_path / "missing.pdf"))
    assert result.success is False
    assert "does not exist" in result.reason
