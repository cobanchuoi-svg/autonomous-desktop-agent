from PIL import Image

from agent.vision.roi import ScreenRegion, crop_region, translate_elements
from agent.vision.parser import UIElement


def test_target_roi_returns_desktop_coordinates_after_offset():
    frame = Image.new("RGB", (800, 600), "white")
    crop, region = crop_region(frame, ScreenRegion(100, 50, 500, 400))
    assert crop.size == (400, 350)
    element = UIElement(text="Filter", bbox=(20, 30, 80, 50), center_x=50, center_y=40)
    screen_element = translate_elements([element], region, surface="foreground_window", container_id="hwnd_1")[0]
    assert screen_element.bbox == (120, 80, 180, 100)
    assert (screen_element.center_x, screen_element.center_y) == (150, 90)
    assert screen_element.container_id == "hwnd_1"
