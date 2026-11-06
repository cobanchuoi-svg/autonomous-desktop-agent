import pytest

from agent.workflows.registry import WorkflowRegistry
from agent.workflows.router import WorkflowRouter
from agent.workflows.runtime import WorkflowRuntime


@pytest.mark.asyncio
async def test_chat_command_routes_document_to_foreground_workflow():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route(
        r"mở C:\Users\me\scan.pdf lên full screen và để WPS chạy nền"
    )
    assert request.workflow == "OPEN_DOCUMENT_FOREGROUND"
    assert request.parameters["document_path"].endswith("scan.pdf")
    assert request.parameters["wps_title"] == "WPS"


@pytest.mark.asyncio
async def test_chat_command_routes_scan_to_ocr_and_brain():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route(
        r"quét C:\Users\me\scan.pdf và để WPS chạy nền"
    )
    assert request.workflow == "SCAN_DOCUMENT"
    assert request.parameters["document_path"].endswith("scan.pdf")


@pytest.mark.asyncio
async def test_chat_command_routes_image_copy_to_wps():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route(
        r"chép ảnh C:\Users\me\diagram.png vào WPS"
    )
    assert request.workflow == "COPY_IMAGE_TO_WPS"
    assert request.parameters["image_path"].endswith("diagram.png")


@pytest.mark.asyncio
async def test_runtime_reuses_latest_scanned_path_for_short_copy_command():
    class FakeEngine:
        capture = object()
        ocr = object()
        brain_client = object()
        memory = None

    runtime = WorkflowRuntime(object(), FakeEngine(), gemini_enabled=False)
    runtime._last_document_path = r"C:\Users\me\latest.png"

    request = runtime._resolve_last_document_command("chép ảnh đã chọn vào wps doc")

    assert request is not None
    assert request.workflow == "COPY_IMAGE_TO_WPS"
    assert request.parameters["image_path"].endswith("latest.png")


@pytest.mark.asyncio
async def test_runtime_does_not_reuse_path_for_unrelated_command():
    class FakeEngine:
        capture = object()
        ocr = object()
        brain_client = object()
        memory = None

    runtime = WorkflowRuntime(object(), FakeEngine(), gemini_enabled=False)
    runtime._last_document_path = r"C:\Users\me\latest.png"

    assert runtime._resolve_last_document_command("chép vào email") is None


def test_runtime_detects_independent_command():
    assert WorkflowRuntime._looks_like_independent_command("quét ảnh mới")
    assert WorkflowRuntime._looks_like_independent_command("chép ảnh đã chọn vào WPS")
    assert not WorkflowRuntime._looks_like_independent_command("C:\\Users\\me\\scan.png")


def test_runtime_removes_hardcoded_path_example_from_clarification():
    question = (
        'Vui lòng gửi đường dẫn, ví dụ: '
        '"C:/Users/Lenovo/Downloads/5_1.jpg" vào WPS.'
    )
    assert WorkflowRuntime._sanitize_clarification_question(question) == (
        "Vui lòng cung cấp đường dẫn đầy đủ của file cần xử lý."
    )
