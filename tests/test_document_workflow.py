import pytest

from agent.workflows.registry import WorkflowRegistry
from agent.workflows.router import WorkflowRouter


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
