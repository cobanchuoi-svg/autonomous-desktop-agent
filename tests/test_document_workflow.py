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


@pytest.mark.asyncio
async def test_chat_command_routes_quoted_escaped_image_scan():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route(
        r'quét "C:/Users/Lenovo/Downloads/5\_1.jpg" và để WPS chạy nền'
    )
    assert request.workflow == "SCAN_DOCUMENT"
    assert request.parameters["document_path"].endswith("5_1.jpg")


@pytest.mark.asyncio
async def test_chat_command_routes_image_copy_to_wps():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route(
        r"chép ảnh C:\Users\me\diagram.png vào WPS"
    )
    assert request.workflow == "COPY_IMAGE_TO_WPS"
    assert request.parameters["image_path"].endswith("diagram.png")


@pytest.mark.asyncio
async def test_chat_command_routes_image_content_to_wps_sheet():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route(
        r'chép nội dung anhr "C:\Users\me\diagram.png" vào WPS sheet'
    )
    assert request.workflow == "COPY_IMAGE_CONTENT_TO_WPS"
    assert request.parameters["image_path"].endswith("diagram.png")


@pytest.mark.asyncio
async def test_image_copy_without_path_asks_for_path():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route("chép nội dung anhr vào wps sheet đc k")
    assert request.status == "CLARIFY"
    assert "đường dẫn" in (request.clarification_question or "")


@pytest.mark.asyncio
async def test_copy_text_from_image_routes_to_ocr_content_workflow():
    router = WorkflowRouter(object(), WorkflowRegistry())
    request = await router.route(
        r'chép chữ từ ảnh "C:\Users\me\diagram.png" vào WPS Sheet'
    )
    assert request.workflow == "COPY_IMAGE_CONTENT_TO_WPS"
    assert request.parameters["image_path"].endswith("diagram.png")


class AliasProvider:
    provider_name = "test-llm"

    async def generate(self, *args, **kwargs):
        return '{"status":"NO_MATCH","workflow":"NO_MATCH","confidence":0.1,"parameters":{},"clarification_question":null}'


@pytest.mark.asyncio
async def test_llm_alias_is_normalized_to_image_copy_workflow():
    router = WorkflowRouter(AliasProvider(), WorkflowRegistry(), fallback=None)
    request = await router.route(
        r'đưa nội dung hình "C:\Users\me\diagram.png" sang WPS sheet'
    )
    assert request.workflow == "COPY_IMAGE_CONTENT_TO_WPS"
    assert request.router_source == "llm_alias_normalizer"
    assert request.parameters["image_path"].endswith("diagram.png")


@pytest.mark.asyncio
async def test_llm_alias_without_path_asks_for_image_path():
    router = WorkflowRouter(AliasProvider(), WorkflowRegistry(), fallback=None)
    request = await router.route("lấy nội dung ảnh vào WPS")
    assert request.status == "CLARIFY"
    assert "đường dẫn" in (request.clarification_question or "")
