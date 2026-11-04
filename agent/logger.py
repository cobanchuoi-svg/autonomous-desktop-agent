"""
Centralized logging configuration using loguru with standard logging fallback.
"""

import sys
import os
from datetime import datetime
from pathlib import Path

try:
    from loguru import logger
    LOGURU_AVAILABLE = True
except ImportError:
    import logging
    LOGURU_AVAILABLE = False
    logger = logging.getLogger("desktop_ai_agent")

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def _find_file_owners(log_file: Path):
    """Best-effort list of processes that currently have the log file open."""
    try:
        import psutil
    except ImportError:
        return []

    target = os.path.normcase(os.path.realpath(str(log_file)))
    owners = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if any(
                os.path.normcase(os.path.realpath(open_file.path)) == target
                for open_file in process.open_files()
            ):
                info = process.info
                owners.append(f"{info.get('name') or 'process'} (pid {info['pid']})")
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            continue
    return owners


def _owner_description(log_file: Path) -> str:
    owners = _find_file_owners(log_file)
    return ", ".join(owners) if owners else "owner unavailable (process inspection unsupported or access denied)"


def setup_logger(log_level: str = "INFO"):
    """Configure log outputs, formatting, and file rotation."""
    if LOGURU_AVAILABLE:
        logger.remove()
        # Console output
        logger.add(
            sys.stdout,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True,
        )
        # File output with daily rotation
        log_file = LOG_DIR / "agent_{time:YYYY-MM-DD}.log"
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            logger.add(
                str(log_file),
                rotation="10 MB",
                retention="7 days",
                level="DEBUG",
                compression="zip",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            )
        except Exception as exc:
            # Keep the stdout sink configured so a locked/inaccessible log cannot
            # prevent the application from starting.
            current_log_file = LOG_DIR / f"agent_{datetime.now():%Y-%m-%d}.log"
            owner = _owner_description(current_log_file)
            logger.warning(f"File logging unavailable at {log_file}: {exc}; open-file owner: {owner}. Continuing with stdout logging.")
            try:
                fallback = LOG_DIR / f"agent_{datetime.now():%Y-%m-%d_%H-%M-%S_%f}.log"
                logger.add(
                    str(fallback), level="DEBUG",
                    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                )
            except Exception as fallback_exc:
                logger.warning(f"Timestamped file fallback unavailable: {fallback_exc}. Continuing with stdout logging only.")
    else:
        logger.handlers.clear()
        logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        logger.addHandler(stream)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as exc:
            owner = _owner_description(LOG_DIR / "agent.log")
            logger.warning("File logging unavailable at %s: %s; open-file owner: %s. Continuing with stdout logging.", LOG_DIR / "agent.log", exc, owner)


__all__ = ["logger", "setup_logger"]
