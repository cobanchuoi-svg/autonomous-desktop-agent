"""
Main entry point for Local Desktop AI Agent.
Supports both CLI autonomous runs and CustomTkinter GUI mode.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.config import settings
from agent.logger import setup_logger, logger
from agent.core.engine import AgentEngine
from agent.llm.factory import create_llm_provider
from agent.brain.brain_client import BrainClient, QwenClient


def parse_args():
    parser = argparse.ArgumentParser(description="Local Desktop AI Agent")
    parser.add_argument("--goal", type=str, default="Open VS Code", help="Goal for the agent to achieve")
    parser.add_argument("--gui", action="store_true", help="Launch CustomTkinter desktop GUI")
    parser.add_argument("--provider", type=str, choices=["ollama", "gemini", "gemini_cli", "llamacpp", "transformers", "mock"], default=None, help="Force specific LLM provider")
    parser.add_argument("--steps", type=int, default=10, help="Maximum execution cycles before stopping")
    parser.add_argument("--check", action="store_true", help="Perform health check of all subsystems and exit")
    return parser.parse_args()


async def run_health_check(provider_choice: str = None) -> bool:
    """Verify Vision (MSS), selected OCR backend, OCR Worker Process, DB, and LLM backends."""
    logger.info("==========================================")
    logger.info("    DESKTOP AI AGENT - HEALTH CHECK       ")
    logger.info("==========================================")

    all_passed = True

    # 1. Screen capture (MSS)
    try:
        import mss
        with mss.mss() as sct:
            monitors = sct.monitors
            num_monitors = len(monitors) - 1 if len(monitors) > 1 else len(monitors)
            logger.info(f"[OK] MSS Screen Capture: AVAILABLE ({num_monitors} monitor(s) detected)")
    except Exception as e:
        all_passed = False
        logger.error(f"[FAIL] MSS Screen Capture: FAILED ({e})")

    # 2. Configured OCR backend (model loading remains lazy until a screen is read)
    try:
        from agent.vision.factory import create_ocr_processor
        ocr_backend = create_ocr_processor(settings.ocr_engine)
        if ocr_backend.is_available():
            logger.info(f"[OK] OCR backend '{settings.ocr_engine}': AVAILABLE")
        else:
            all_passed = False
            logger.error(f"[FAIL] OCR backend '{settings.ocr_engine}' dependencies are unavailable")
    except Exception as e:
        all_passed = False
        logger.error(f"[FAIL] OCR backend '{settings.ocr_engine}' failed ({e})")

    # 3. OCR Worker Process Pool
    try:
        if settings.ocr_engine.casefold() in {"paddle", "paddleocr"}:
            from agent.vision.ocr_worker import IsolatedOCRClient
            client = IsolatedOCRClient()
            pool = client._ensure_pool()
            if pool is not None:
                logger.info("[OK] OCR Worker Process Pool: AVAILABLE (multiprocessing spawn ready)")
            client.shutdown()
        else:
            logger.info(f"[INFO] OCR Worker Process Pool: not used by {settings.ocr_engine}")
    except Exception as e:
        all_passed = False
        logger.error(f"[FAIL] OCR Worker Process Pool: FAILED ({e})")

    # 4. SQLite DB
    try:
        from agent.memory.db import DatabaseManager
        db = DatabaseManager()
        logger.info(f"[OK] SQLite Database: AVAILABLE ({db.db_path})")
    except Exception as e:
        all_passed = False
        logger.error(f"[FAIL] SQLite Database: FAILED ({e})")

    # 5. LLM Backend
    try:
        provider = await create_llm_provider(settings.llm, preferred_provider=provider_choice)
        is_healthy = await provider.health_check()
        logger.info(f"[OK] LLM Provider ({provider.provider_name}): {'ONLINE' if is_healthy else 'FALLBACK'}")
    except Exception as e:
        all_passed = False
        logger.error(f"[FAIL] LLM Provider: FAILED ({e})")

    logger.info("==========================================")
    if all_passed:
        logger.info("Health Check Result: ALL SYSTEMS OPERATIONAL")
    else:
        logger.warning("Health Check Result: SUBSYSTEM DEFICIENCY DETECTED")
    logger.info("==========================================")
    return all_passed


async def main_async(args):
    setup_logger(settings.log_level)

    if args.check:
        passed = await run_health_check(args.provider)
        if not passed:
            sys.exit(1)
        return

    # Validate the OCR backend selected in config.  Do not hard-code PaddleOCR:
    # the default backend is the Windows OCR/Gemini hybrid.
    from agent.vision.factory import create_ocr_processor
    ocr_backend = create_ocr_processor(settings.ocr_engine)
    if not ocr_backend.is_available():
        logger.critical(
            "CRITICAL: Autonomous execution refused because configured OCR backend "
            f"'{settings.ocr_engine}' is unavailable. Install/enable that backend "
            "before allowing desktop perception."
        )
        sys.exit(1)

    if args.gui:
        logger.info("Launching CustomTkinter GUI Dashboard...")
        from agent.ui.dashboard import AgentDashboard
        from agent.core.container import container
        engine = await container.create_engine()
        dashboard = AgentDashboard(engine=engine)
        dashboard.run()
        return

    logger.info(f"Starting Agent Engine with Goal: '{args.goal}'")
    from agent.core.container import container
    if args.provider:
        provider = await create_llm_provider(settings.llm, preferred_provider=args.provider)
        container.set_llm(provider)

    engine = await container.create_engine()
    success = await engine.run_goal(args.goal, max_steps=args.steps)
    if success:
        logger.info(f"Agent finished goal '{args.goal}' successfully.")
    else:
        logger.error(f"Goal validation failed: '{args.goal}' was not completed.")
        sys.exit(1)


def run_cli():
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    run_cli()
