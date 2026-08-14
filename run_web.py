#!/usr/bin/env python3
"""[B] Start the FastAPI frontend. Phase 6.

    python run_web.py                 # http://127.0.0.1:8000
    python run_web.py --live          # boot straight into database-backed mode
    python run_web.py --reload        # restart on edit, for template work

Equivalent to `uvicorn web.main:app`, with the WEB_* variables in `.env`
already applied. The Streamlit app is unaffected and still starts with
`streamlit run app/main.py`.
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="override WEB_HOST")
    parser.add_argument("--port", type=int, help="override WEB_PORT")
    parser.add_argument("--reload", action="store_true", help="restart on file change")
    parser.add_argument(
        "--mode",
        choices=("demo", "live"),
        help="which data mode the app boots into (overrides WEB_DATA_MODE)",
    )
    parser.add_argument(
        "--live", action="store_const", const="live", dest="mode", help="shorthand for --mode live"
    )
    parser.add_argument(
        "--fixed",
        action="store_true",
        help="pin the shell to the mockup's 1440px art board (default is full width)",
    )
    args = parser.parse_args()

    # Set before importing web.settings, which caches on first read.
    if args.mode:
        os.environ["WEB_DATA_MODE"] = args.mode
    if args.fixed:
        os.environ["WEB_FLUID_WIDTH"] = "false"

    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is not installed. Run:\n\n    pip install -r requirements.txt\n",
            file=sys.stderr,
        )
        return 1

    from web.settings import get_web_settings

    settings = get_web_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    print(f"FinSight on http://{host}:{port}  ·  booting in {settings.default_data_mode} mode")
    uvicorn.run(
        "web.main:app",
        host=host,
        port=port,
        reload=args.reload or settings.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
