from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from backend.app.core.config import EnvironmentSettings
from backend.app.testing import create_e2e_test_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live E2E backend app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--frontend-origin", default="http://127.0.0.1:5173")
    parser.add_argument(
        "--runtime-root",
        default=".runtime/e2e-live",
        help="Runtime data directory for live Playwright backend state.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = (repo_root / args.runtime_root).resolve()
    project_root = repo_root.resolve()
    app = create_e2e_test_app(
        EnvironmentSettings(
            platform_runtime_root=runtime_root,
            default_project_root=project_root,
            backend_cors_origins=(
                args.frontend_origin,
                args.frontend_origin.replace("127.0.0.1", "localhost"),
            ),
        )
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
