from agent.actions.window_layout import DocumentWindowController


def test_window_title_matching_ignores_spacing_and_case():
    assert DocumentWindowController._matches_title("WPS Office - Report", "wpsoffice")
    assert DocumentWindowController._matches_title("scan_001.PDF - Viewer", "scan001")
    assert not DocumentWindowController._matches_title("WPS Office", "Excel")


def test_missing_document_is_rejected_before_window_operations(tmp_path):
    result = DocumentWindowController().prepare_foreground_document(str(tmp_path / "missing.pdf"))
    assert result.success is False
    assert "does not exist" in result.reason


def test_image_document_uses_headless_layout(tmp_path, monkeypatch):
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"not opened by the window shell")
    monkeypatch.setattr("agent.actions.window_layout.os.name", "nt")
    monkeypatch.setattr(
        "agent.actions.window_layout.os.startfile",
        lambda _path: (_ for _ in ()).throw(AssertionError("image must not be opened")),
        raising=False,
    )

    result = DocumentWindowController().prepare_foreground_document(str(image_path))

    assert result.success
    assert result.document_title == image_path.name
