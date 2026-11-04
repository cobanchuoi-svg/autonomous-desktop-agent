"""
Application controller for discovering, launching, and managing desktop processes on Windows.
Includes Windows Registry inspection, multi-path discovery (Chrome, VS Code, Notepad),
URI fallbacks, and process/window verification.
"""

import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Dict, List, Optional
import winreg

from agent.actions.base import ActionResult, ActionType
from agent.logger import logger


class WindowsAppResolver:
    """Discovers installed Windows executables via Registry and standard filesystem paths."""

    # Explicit lookup aliases and known filesystem search paths
    WELL_KNOWN_PATHS: Dict[str, List[str]] = {
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        ],
        "google chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ],
        "edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "microsoft edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "msedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "code": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft VS Code\Code.exe"),
        ],
        "vscode": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
        ],
        "code.exe": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
        ],
        "visual studio code": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
        ],
        "notepad": [
            r"C:\Windows\System32\notepad.exe",
            r"C:\Windows\notepad.exe",
            os.path.expandvars(r"%SYSTEMROOT%\System32\notepad.exe"),
        ],
        "notepad.exe": [
            r"C:\Windows\System32\notepad.exe",
            r"C:\Windows\notepad.exe",
        ],
        "calc": [
            r"C:\Windows\System32\calc.exe",
        ],
        "calculator": [
            r"C:\Windows\System32\calc.exe",
        ],
        "explorer": [
            r"C:\Windows\explorer.exe",
        ],
    }

    # Registry subkeys to probe per application
    REGISTRY_MAP: Dict[str, List[str]] = {
        "chrome": ["chrome.exe", "Chrome.exe"],
        "google chrome": ["chrome.exe", "Chrome.exe"],
        "edge": ["msedge.exe"],
        "microsoft edge": ["msedge.exe"],
        "msedge": ["msedge.exe"],
        "code": ["Code.exe", "code.exe"],
        "vscode": ["Code.exe", "code.exe"],
        "visual studio code": ["Code.exe", "code.exe"],
        "notepad": ["notepad.exe"],
    }

    @classmethod
    def resolve_from_registry(cls, app_name: str) -> Optional[str]:
        """Query HKLM and HKCU App Paths for registered executable paths."""
        target_lower = app_name.lower().strip()
        search_keys = cls.REGISTRY_MAP.get(target_lower, [target_lower, f"{target_lower}.exe"])

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in search_keys:
                key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{sub}"
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        val, _ = winreg.QueryValueEx(key, "")
                        if val and Path(val).exists():
                            logger.info(f"[WindowsAppResolver] Found '{app_name}' in registry: {val}")
                            return str(Path(val).resolve())
                except OSError:
                    continue
        return None

    @classmethod
    def resolve(cls, app_name: str) -> Optional[str]:
        """
        Locate executable on system using:
        1. Explicit path (if already valid)
        2. Windows Registry App Paths (HKLM & HKCU)
        3. Well-known standard installation paths (Program Files, LocalAppData)
        4. System PATH via shutil.which (code, Code.exe, chrome.exe)
        """
        target = app_name.strip().strip('"').strip("'")
        target_lower = target.lower()

        # 1. Direct path check
        if Path(target).is_file() and Path(target).exists():
            return str(Path(target).resolve())

        # 2. Registry lookup
        reg_result = cls.resolve_from_registry(target_lower)
        if reg_result:
            return reg_result

        # 3. Known paths lookup
        known_list = cls.WELL_KNOWN_PATHS.get(target_lower, [])
        for candidate in known_list:
            if candidate and Path(candidate).is_file() and Path(candidate).exists():
                logger.info(f"[WindowsAppResolver] Found '{app_name}' in known paths: {candidate}")
                return str(Path(candidate).resolve())

        # 4. System PATH lookup (including explicit .exe extensions)
        path_candidates = [target]
        if not target.lower().endswith(".exe"):
            path_candidates.append(f"{target}.exe")
        if target_lower in ("code", "vscode"):
            path_candidates.extend(["Code.exe", "code.cmd", "code.exe"])

        for cand in path_candidates:
            which_result = shutil.which(cand)
            if which_result:
                logger.info(f"[WindowsAppResolver] Found '{app_name}' in PATH as '{cand}': {which_result}")
                return str(Path(which_result).resolve())

        logger.warning(f"[WindowsAppResolver] Could not locate executable for '{app_name}'")
        return None


class ApplicationController:
    """Launches and terminates desktop applications with process verification."""

    def __init__(self):
        self.resolver = WindowsAppResolver()

    def is_process_running(self, process_identifier: str) -> bool:
        """Check if process is active in Windows process table using psutil with tasklist fallback."""
        proc_name = Path(process_identifier).name.lower()
        if not proc_name.endswith(".exe"):
            proc_name = f"{proc_name}.exe"

        # Special alias mappings for process names
        alias_map = {
            "code.exe": "code.exe",
            "vscode.exe": "code.exe",
            "google chrome.exe": "chrome.exe",
        }
        proc_name = alias_map.get(proc_name, proc_name)

        # 1. Fast kernel snapshot via psutil
        try:
            import psutil
            for p in psutil.process_iter(["name"]):
                try:
                    if p.info["name"] and p.info["name"].lower() == proc_name:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[ApplicationController] psutil check error: {e}")

        # 2. Fallback to tasklist
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {proc_name}"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            return proc_name in res.stdout.lower()
        except Exception as e:
            logger.error(f"[ApplicationController] Process check failed: {e}")
            return False

    def is_window_visible(self, title_keyword: str) -> bool:
        """Verify window presence via PyGetWindow if available."""
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(title_keyword)
            return len(windows) > 0 and any(w.visible for w in windows)
        except Exception:
            return False

    def launch_app(self, app_name: str, args: Optional[List[str]] = None) -> ActionResult:
        """Resolve executable path, launch process, and verify execution."""
        start = time.perf_counter()
        normalized_name = app_name.strip()
        lower_name = normalized_name.lower()

        # 1. Resolve executable path
        resolved_exe = self.resolver.resolve(normalized_name)

        # 2. Fallback: URI launch method if executable path not directly found
        if not resolved_exe:
            if lower_name in ("chrome", "google chrome"):
                logger.info("[ApplicationController] Executable path not found. Attempting URI launch for Chrome...")
                try:
                    # Windows URI protocol launch for default/web browser
                    os.startfile("https://www.google.com")
                    time.sleep(1.0)
                    if self.is_process_running("chrome.exe"):
                        return ActionResult(
                            success=True,
                            action_type=ActionType.LAUNCH_APP,
                            message="Successfully launched Chrome via URI fallback",
                            execution_time=time.perf_counter() - start,
                        )
                except Exception as e:
                    logger.warning(f"[ApplicationController] URI launch failed: {e}")

            elif lower_name in ("code", "vscode", "visual studio code"):
                logger.info("[ApplicationController] Executable path not found. Attempting URI launch for VS Code...")
                try:
                    os.startfile("vscode://")
                    time.sleep(1.0)
                    if self.is_process_running("code.exe"):
                        return ActionResult(
                            success=True,
                            action_type=ActionType.LAUNCH_APP,
                            message="Successfully launched VS Code via URI protocol",
                            execution_time=time.perf_counter() - start,
                        )
                except Exception as e:
                    logger.warning(f"[ApplicationController] VS Code URI launch failed: {e}")

            elapsed = time.perf_counter() - start
            err_msg = (
                f"Application '{normalized_name}' could not be located. "
                f"Searched Registry App Paths, standard locations, and system PATH."
            )
            logger.error(f"[ApplicationController] {err_msg}")
            return ActionResult(
                success=False,
                action_type=ActionType.LAUNCH_APP,
                error=err_msg,
                execution_time=elapsed,
            )

        # 3. Launch using absolute executable path directly (NO raw 'chrome' command)
        cmd = [resolved_exe] + (args or [])
        try:
            logger.info(f"[ApplicationController] Launching executable path: {resolved_exe}")
            proc = subprocess.Popen(
                cmd,
                shell=False,
                creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0,
            )

            # Brief pause to verify process didn't instantly exit with error code
            time.sleep(0.5)
            exit_code = proc.poll()
            if exit_code is not None and exit_code != 0:
                elapsed = time.perf_counter() - start
                err_msg = f"Process '{resolved_exe}' exited immediately with code {exit_code}"
                logger.error(f"[ApplicationController] {err_msg}")
                return ActionResult(
                    success=False,
                    action_type=ActionType.LAUNCH_APP,
                    error=err_msg,
                    execution_time=elapsed,
                )

            # 4. Process table verification (Goal validation)
            is_running = self.is_process_running(resolved_exe)
            elapsed = time.perf_counter() - start

            if not is_running and proc.poll() is not None:
                err_msg = f"Process '{resolved_exe}' was spawned (PID: {proc.pid}) but is not active in process table."
                logger.error(f"[ApplicationController] {err_msg}")
                return ActionResult(
                    success=False,
                    action_type=ActionType.LAUNCH_APP,
                    error=err_msg,
                    execution_time=elapsed,
                )

            logger.info(f"[ApplicationController] Successfully verified running '{resolved_exe}' (PID: {proc.pid})")
            return ActionResult(
                success=True,
                action_type=ActionType.LAUNCH_APP,
                message=f"Successfully launched and verified '{Path(resolved_exe).name}' (PID: {proc.pid})",
                data={"pid": proc.pid, "executable_path": resolved_exe},
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error(f"[ApplicationController] Failed to launch '{resolved_exe}': {e}")
            return ActionResult(
                success=False,
                action_type=ActionType.LAUNCH_APP,
                error=str(e),
                execution_time=elapsed,
            )

    def kill_app(self, process_name: str) -> ActionResult:
        """Terminate a desktop process by name."""
        start = time.perf_counter()
        proc_target = process_name if process_name.lower().endswith(".exe") else f"{process_name}.exe"
        try:
            res = subprocess.run(
                ["taskkill", "/IM", proc_target, "/F"],
                capture_output=True,
                text=True,
                shell=True,
            )
            elapsed = time.perf_counter() - start
            if res.returncode == 0:
                return ActionResult(
                    success=True,
                    action_type=ActionType.KILL_APP,
                    message=f"Terminated '{proc_target}'",
                    execution_time=elapsed,
                )
            else:
                return ActionResult(
                    success=False,
                    action_type=ActionType.KILL_APP,
                    error=res.stderr or res.stdout,
                    execution_time=elapsed,
                )
        except Exception as e:
            elapsed = time.perf_counter() - start
            return ActionResult(
                success=False,
                action_type=ActionType.KILL_APP,
                error=str(e),
                execution_time=elapsed,
            )
