"""Small Windows UI Automation bridge for exact, named desktop controls."""

import base64
import json
import re
import subprocess
import time

from agent.actions.base import ActionResult, ActionType
from agent.vision.parser import UIElement


_READ_FOREGROUND_CONTROLS = r'''
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ForegroundWindowHandle {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
}
'@
    $handle = [ForegroundWindowHandle]::GetForegroundWindow()
    if ($handle -eq [IntPtr]::Zero) { Write-Output '[]'; exit 0 }
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $stack = [System.Collections.Generic.Stack[System.Windows.Automation.AutomationElement]]::new()
    $stack.Push($root)
    $queued = 1
    $visited = 0
    $items = [System.Collections.Generic.List[object]]::new()
    $allowedTypes = @(
        'ControlType.Button', 'ControlType.Edit', 'ControlType.MenuItem',
        'ControlType.ListItem', 'ControlType.CheckBox', 'ControlType.RadioButton',
        'ControlType.ComboBox', 'ControlType.TabItem', 'ControlType.Hyperlink',
        'ControlType.TreeItem', 'ControlType.DataItem')
    while ($stack.Count -gt 0 -and $visited -lt 250) {
        $node = $stack.Pop()
        $visited++
        try {
            $current = $node.Current
            $controlType = $current.ControlType.ProgrammaticName
            $name = $current.Name
            $rect = $current.BoundingRectangle
            if ($allowedTypes -contains $controlType -and $current.IsEnabled -and
                -not [string]::IsNullOrWhiteSpace($name) -and $rect.Width -gt 1 -and $rect.Height -gt 1) {
                $index = $items.Count
                $items.Add([PSCustomObject]@{
                    element_id = "uia_$index"
                    text = $name.Trim()
                    confidence = 1.0
                    control_type = $controlType.Replace('ControlType.', '')
                    source = 'uia'
                    bbox = @([int][math]::Floor($rect.Left), [int][math]::Floor($rect.Top),
                             [int][math]::Ceiling($rect.Right), [int][math]::Ceiling($rect.Bottom))
                })
            }
        } catch { }
        try {
            $child = $walker.GetFirstChild($node)
            while ($null -ne $child -and $queued -lt 250) {
                $stack.Push($child)
                $queued++
                $child = $walker.GetNextSibling($child)
            }
        } catch { }
    }
    ConvertTo-Json -InputObject @($items.ToArray()) -Depth 4 -Compress
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 10
}
'''


_READ_FOREGROUND_TEXT = r'''
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $handle = [IntPtr]([long]__TARGET_HWND__)
    if ($handle -eq [IntPtr]::Zero) { '{"text":""}'; exit 0 }
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
    $nodes = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    $bestText = ''
    $visited = 0
    foreach ($node in $nodes) {
        if ($visited -ge 600) { break }
        $visited++
        try {
            $pattern = $null
            if ($node.TryGetCurrentPattern(
                [System.Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {
                $candidate = $pattern.DocumentRange.GetText(100000)
                if ($candidate.Length -gt $bestText.Length) { $bestText = $candidate }
            }
        } catch { }
        try {
            $pattern = $null
            if ($node.TryGetCurrentPattern(
                [System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
                $candidate = $pattern.Current.Value
                if ($candidate.Length -gt $bestText.Length) { $bestText = $candidate }
            }
        } catch { }
    }
    ConvertTo-Json -InputObject @{ text = $bestText } -Compress
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 10
}
'''


_OPEN_APP_DETAIL_BUTTON = r'''
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SearchForegroundWindow {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extraInfo);
}
'@
    $appName = [System.Text.Encoding]::Unicode.GetString(
        [System.Convert]::FromBase64String('__APP_NAME_B64__'))
    $normalizedTarget = [regex]::Replace($appName.ToLowerInvariant(), '[^a-z0-9]+', ' ').Trim()
    $handle = [SearchForegroundWindow]::GetForegroundWindow()
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    if (__VERIFY_ONLY__) {
        $windowCondition = [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Window)
        $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition)
        foreach ($window in $windows) {
            try {
                if ($window.Current.IsOffscreen) { continue }
                $processName = (Get-Process -Id $window.Current.ProcessId -ErrorAction Stop).ProcessName
                if ($processName -in @('SearchHost', 'SearchApp', 'SearchUI', 'StartMenuExperienceHost')) { continue }
                $windowName = [regex]::Replace($window.Current.Name.ToLowerInvariant(), '[^a-z0-9]+', ' ').Trim()
                $normalizedProcess = [regex]::Replace($processName.ToLowerInvariant(), '[^a-z0-9]+', ' ').Trim()
                if ($windowName.Contains($normalizedTarget) -or $normalizedProcess.Contains($normalizedTarget)) {
                    Write-Output '__APP_WINDOW_VERIFIED__'
                    exit 0
                }
            } catch { continue }
        }
        Write-Output '__APP_ENTER_FALLBACK_UNVERIFIED__'
        exit 5
    }
    $topWindows = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition)
    $nameProperty = [System.Windows.Automation.AutomationElement]::NameProperty
    $typeProperty = [System.Windows.Automation.AutomationElement]::ControlTypeProperty
    $descendants = [System.Windows.Automation.TreeScope]::Descendants
    $targetName = [System.Windows.Automation.PropertyCondition]::new(
        $nameProperty, $appName,
        [System.Windows.Automation.PropertyConditionFlags]::IgnoreCase)
    $openName = [System.Windows.Automation.PropertyCondition]::new(
        $nameProperty, 'Open',
        [System.Windows.Automation.PropertyConditionFlags]::IgnoreCase)
    # Search is not always the foreground HWND once the PowerShell helper is
    # started. Check that HWND first, then visible top-level windows, and only
    # accept a window containing the exact requested app title. Windows Search
    # may expose the visual "App" subtitle as part of another UIA node or omit it.
    $candidateWindows = [System.Collections.Generic.List[System.Windows.Automation.AutomationElement]]::new()
    if ($handle -ne [IntPtr]::Zero) {
        try { $candidateWindows.Add([System.Windows.Automation.AutomationElement]::FromHandle($handle)) } catch { }
    }
    foreach ($window in $topWindows) {
        try {
            if ($window.Current.IsOffscreen) { continue }
            if ($handle -ne [IntPtr]::Zero -and $window.Current.NativeWindowHandle -eq $handle.ToInt32()) { continue }
            $candidateWindows.Add($window)
        } catch { }
    }
    $searchWindow = $null
    foreach ($candidate in $candidateWindows) {
        try {
            $appTitle = $candidate.FindFirst($descendants, $targetName)
            if ($null -eq $appTitle) { continue }
            $searchWindow = $candidate
            break
        } catch { continue }
    }
    if ($null -eq $searchWindow) {
        Write-Output '__APP_SEARCH_WINDOW_NOT_FOUND__'
        exit 3
    }
    # Match the visible action keyword only; Search may expose it as Text,
    # Hyperlink, Custom, or Button, and does not consistently expose Options.
    $openControl = $searchWindow.FindFirst($descendants, $openName)
    $usedEnterFallback = $false
    if ($null -eq $openControl) {
        # The requested app title is present in Search; activate the default
        # result with Enter when this Search provider omits an Open control.
        $usedEnterFallback = $true
        [SearchForegroundWindow]::keybd_event(0x0D, 0, 0, [UIntPtr]::Zero)
        [SearchForegroundWindow]::keybd_event(0x0D, 0, 2, [UIntPtr]::Zero)
    } else {
        $target = $openControl
        $pattern = $null
        $invokable = $false
        try {
            $invokable = $target.TryGetCurrentPattern(
                [System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)
        } catch { }
        if ($invokable) {
            $pattern.Invoke()
        } else {
            $rect = $target.Current.BoundingRectangle
            if ($rect.Width -le 1 -or $rect.Height -le 1) {
                Write-Output '__APP_OPEN_KEYWORD_NO_BOUNDS__'
                exit 4
            }
            $x = [int][math]::Round($rect.Left + ($rect.Width / 2))
            $y = [int][math]::Round($rect.Top + ($rect.Height / 2))
            if (-not [SearchForegroundWindow]::SetCursorPos($x, $y)) {
                Write-Output '__APP_OPEN_KEYWORD_CLICK_FAILED__'
                exit 4
            }
            [SearchForegroundWindow]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
            [SearchForegroundWindow]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
        }
    }
    Start-Sleep -Milliseconds 1400

    $windowCondition = [System.Windows.Automation.PropertyCondition]::new(
        $typeProperty, [System.Windows.Automation.ControlType]::Window)
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition)
    foreach ($window in $windows) {
        $windowName = [regex]::Replace($window.Current.Name.ToLowerInvariant(), '[^a-z0-9]+', ' ').Trim()
        if (-not $window.Current.IsOffscreen -and $windowName.Contains($normalizedTarget)) {
            Write-Output '__APP_WINDOW_VERIFIED__'
            exit 0
        }
    }
    # A matching process may already be running in the background. It does
    # not prove that the app window was opened, so do not treat it as success.
    if ($usedEnterFallback) {
        Write-Output '__APP_ENTER_FALLBACK_UNVERIFIED__'
        exit 5
    }
    Write-Output '__APP_OPEN_CLICKED_UNVERIFIED__'
    exit 5
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 10
}
'''


class WindowsUIAutomationController:
    """Search Windows, invoke a named app result, and verify it opened."""

    @classmethod
    def _window_matches_target(cls, window: object, app_name: str, window_title: str | None = None) -> bool:
        title = str(getattr(window, "title", "") or "")
        if cls._window_title_matches(title, app_name, window_title):
            return True
        if window_title:
            return False
        # Modern Notepad can expose only the active tab's document name as its
        # HWND title. Identify it by owning process when the title omits the app.
        try:
            import ctypes
            import psutil

            hwnd = int(getattr(window, "_hWnd"))
            process_id = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            process_name = psutil.Process(process_id.value).name().casefold()
        except Exception:
            return False

        normalized_app = re.sub(r"[^a-z0-9]+", "", app_name.casefold())
        normalized_process = re.sub(r"[^a-z0-9]+", "", process_name)
        process_aliases = {
            "notepad": ("notepad",),
            "notepad++": ("notepadplusplus",),
            "wps": ("wps", "et", "wpp"),
            "wpsoffice": ("wps", "et", "wpp"),
            "word": ("winword",),
            "code": ("code",),
            "vscode": ("code",),
            "visualstudiocode": ("code",),
        }
        aliases = process_aliases.get(normalized_app, (normalized_app,))
        return any(alias and alias in normalized_process for alias in aliases)

    @staticmethod
    def _window_title_matches(title: str, app_name: str, window_title: str | None = None) -> bool:
        import re

        normalized = re.sub(r"[^a-z0-9]+", "", title.casefold())
        app = re.sub(r"[^a-z0-9]+", "", app_name.casefold())
        requested_title = re.sub(r"[^a-z0-9]+", "", (window_title or "").casefold())
        app_match = (
            app in normalized
            or (app in {"wps", "wpsoffice"} and "wps" in normalized)
            or (app in {"code", "vscode", "visualstudiocode"} and "visualstudiocode" in normalized)
        )
        title_match = not requested_title or requested_title in normalized
        return bool(app_match and title_match)

    def is_app_window_foreground(self, app_name: str, window_title: str | None = None) -> bool:
        """Return true only when the requested app/document is the active window."""
        try:
            import pygetwindow

            active = pygetwindow.getActiveWindow()
            return bool(active and self._window_matches_target(active, app_name, window_title))
        except Exception:
            return False

    def activate_app_window(self, app_name: str, window_title: str | None = None, timeout: float = 3.0) -> bool:
        """Bring a uniquely matching app/document window forward and verify focus."""
        try:
            import pygetwindow

            deadline = time.monotonic() + max(0.2, timeout)
            while time.monotonic() < deadline:
                matches = [
                    window for window in pygetwindow.getAllWindows()
                    if self._window_matches_target(window, app_name, window_title)
                ]
                if matches:
                    if window_title and len(matches) > 1:
                        # An explicit document title must identify one safe target.
                        return False
                    active = pygetwindow.getActiveWindow()
                    active_handle = getattr(active, "_hWnd", None) if active else None
                    window = next((item for item in matches if getattr(item, "_hWnd", None) == active_handle), matches[0])
                    if window.isMinimized:
                        window.restore()
                    window.activate()
                    time.sleep(0.2)
                    return self.is_app_window_foreground(app_name, window_title)
                time.sleep(0.1)
        except Exception:
            return False
        return False

    def get_foreground_controls(self, timeout: float = 4.0) -> list[UIElement]:
        """Read named interactive controls from only the current foreground window."""
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", _READ_FOREGROUND_CONTROLS],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        stdout = completed.stdout or ""
        if completed.returncode != 0 or not stdout.strip():
            return []
        try:
            raw_items = json.loads(stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return []
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        elements = []
        for item in raw_items or []:
            try:
                x0, y0, x1, y1 = (int(value) for value in item["bbox"])
                elements.append(UIElement(
                    text=str(item["text"]),
                    confidence=float(item.get("confidence", 1.0)),
                    bbox=(x0, y0, x1, y1),
                    center_x=(x0 + x1) // 2,
                    center_y=(y0 + y1) // 2,
                    element_id=str(item["element_id"]),
                    control_type=str(item.get("control_type", "")),
                    source="uia",
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return elements

    def get_foreground_text(self, timeout: float = 6.0) -> str:
        """Read accessible text from the foreground app without OCR."""
        try:
            import ctypes

            hwnd = int(ctypes.windll.user32.GetForegroundWindow())
            if not hwnd:
                return ""
            script = _READ_FOREGROUND_TEXT.replace("__TARGET_HWND__", str(hwnd))
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        stdout = completed.stdout or ""
        if completed.returncode != 0 or not stdout.strip():
            return ""
        try:
            payload = json.loads(stdout.strip().splitlines()[-1])
            return str(payload.get("text", "")) if isinstance(payload, dict) else ""
        except (json.JSONDecodeError, IndexError, AttributeError):
            return ""

    def open_app_from_search(self, app_name: str, timeout: float = 12.0) -> ActionResult:
        try:
            import pyautogui

            pyautogui.hotkey("win", "s")
            time.sleep(0.8)
            pyautogui.write(app_name, interval=0.04)
            time.sleep(1.5)
            # Send Enter from the agent process while Search still has focus;
            # a child PowerShell process can otherwise send it to the wrong window.
            pyautogui.press("enter")
            time.sleep(1.8)
            encoded_name = base64.b64encode(app_name.encode("utf-16-le")).decode("ascii")
            script = _OPEN_APP_DETAIL_BUTTON.replace("__APP_NAME_B64__", encoded_name)
            script = script.replace("__VERIFY_ONLY__", "$true")
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ActionResult(
                success=False,
                action_type=ActionType.LAUNCH_APP,
                error=f"Windows Search UI Automation timed out while checking '{app_name}'.",
                data={"target": app_name, "method": "windows_search_uia", "verified": False},
            )
        except (ImportError, OSError) as exc:
            return ActionResult(
                success=False,
                action_type=ActionType.LAUNCH_APP,
                error=f"Windows Search/UI Automation could not open '{app_name}': {exc}",
                data={"target": app_name, "method": "windows_search_uia"},
            )

        output = (completed.stdout or "").strip()
        error = (completed.stderr or "").strip()
        verified = "__APP_WINDOW_VERIFIED__" in output
        if verified:
            return ActionResult(
                success=True,
                action_type=ActionType.LAUNCH_APP,
                message=f"Opened '{app_name}' from Windows Search and verified its window is visible.",
                data={
                    "target": app_name,
                    "method": "windows_search_uia",
                    "verified": True,
                    "verification": "visible_window_title",
                },
            )

        if "__APP_SEARCH_RESULT_NOT_FOUND__" in output:
            reason = f"Windows Search did not expose an enabled app result for '{app_name}'."
        elif "__APP_DETAIL_NOT_FOUND__" in output:
            reason = f"Windows Search did not show an App detail panel for '{app_name}'."
        elif "__APP_OPEN_BUTTON_NOT_FOUND__" in output:
            reason = f"The '{app_name}' result was found, but its Open keyword was not exposed to UI Automation."
        elif "__APP_OPEN_BUTTON_NOT_INVOKABLE__" in output:
            reason = f"The Open keyword for '{app_name}' could not be invoked."
        elif "__APP_OPEN_KEYWORD_NO_BOUNDS__" in output:
            reason = f"The Open keyword for '{app_name}' was found but has no clickable screen bounds."
        elif "__APP_OPEN_KEYWORD_CLICK_FAILED__" in output:
            reason = f"Could not move the pointer to the Open keyword for '{app_name}'."
        elif "__APP_WEB_SEARCH_ONLY__" in output:
            reason = f"Windows Search returned only a Web search result for '{app_name}'; no app was opened."
        elif "__APP_SEARCH_RESULT_NOT_INVOKABLE__" in output:
            reason = f"The Windows Search result for '{app_name}' does not expose an invoke action."
        elif "__APP_OPEN_CLICKED_UNVERIFIED__" in output:
            reason = f"The Open action was invoked, but '{app_name}' was not verified as visible."
        elif "__APP_ENTER_FALLBACK_UNVERIFIED__" in output:
            reason = f"Enter was sent to the selected '{app_name}' result, but its window was not verified as visible."
        else:
            reason = error or output or f"UI Automation exited with code {completed.returncode}."

        return ActionResult(
            success=False,
            action_type=ActionType.LAUNCH_APP,
            error=reason,
            data={"target": app_name, "method": "windows_search_uia", "verified": False},
        )
