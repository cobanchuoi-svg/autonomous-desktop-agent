import pytest
from agent.workflows.registry import WorkflowRegistry
from agent.workflows.router import WorkflowRouter
from agent.workflows.runtime import WorkflowRuntime
from agent.workflows.models import WorkflowRequest


class FakeLLM:
    provider_name = "test"
    async def generate(self, *args, **kwargs):
        return '{"status":"NO_MATCH","workflow":"NO_MATCH","confidence":0.1,"parameters":{},"clarification_question":null}'


@pytest.mark.asyncio
async def test_scan_with_parentheses_and_quotes():
    router = WorkflowRouter(FakeLLM(), WorkflowRegistry())
    cmd = 'quét "C:/Users/Lenovo/Downloads/OIP (1).webp" và để WPS chạy nền'
    req = await router.route(cmd)
    assert req.workflow == "SCAN_DOCUMENT"
    assert req.parameters["document_path"] == "C:/Users/Lenovo/Downloads/OIP (1).webp"


@pytest.mark.asyncio
async def test_followup_copy_reuses_last_document_path_for_doc():
    router = WorkflowRouter(FakeLLM(), WorkflowRegistry())
    router.last_document_path = "C:/Users/Lenovo/Downloads/OIP (1).webp"
    
    # User types short follow-up in chat without path
    cmd = "chép ảnh đã chọn vào wps doc"
    req = await router.route(cmd)
    assert req.workflow == "COPY_IMAGE_CONTENT_TO_WPS"
    assert req.parameters["image_path"] == "C:/Users/Lenovo/Downloads/OIP (1).webp"
    assert req.parameters["wps_title"] == "WPS"


@pytest.mark.asyncio
async def test_followup_copy_reuses_last_document_path_for_sheet():
    router = WorkflowRouter(FakeLLM(), WorkflowRegistry())
    router.last_document_path = "C:/Users/Lenovo/Downloads/invoice (final).png"
    
    # User types short follow-up in chat for sheet
    cmd = "chép vào wps sheet"
    req = await router.route(cmd)
    assert req.workflow == "COPY_IMAGE_CONTENT_TO_WPS"
    assert req.parameters["image_path"] == "C:/Users/Lenovo/Downloads/invoice (final).png"
    assert req.parameters["wps_title"] == "WPS Sheet"


@pytest.mark.asyncio
async def test_runtime_clears_pending_clarification_on_new_command():
    runtime = WorkflowRuntime(
        provider=FakeLLM(),
        engine=type("Engine", (), {"capture": None, "ocr": None, "brain_client": None, "memory": None})(),
    )
    # Set pending clarification with an example
    runtime._pending_clarification = ("chép vào wps", "Bạn gửi giúp mình đường dẫn...")
    
    # User issues a fresh scan command with a new file
    req, res = await runtime.handle('quét "C:/Users/Lenovo/Downloads/new_file (1).jpg" và để WPS chạy nền')
    assert runtime._pending_clarification is None
    assert req.workflow == "SCAN_DOCUMENT"
    assert req.parameters["document_path"] == "C:/Users/Lenovo/Downloads/new_file (1).jpg"
