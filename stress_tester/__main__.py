from __future__ import annotations

import uvicorn

from stress_tester.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "stress_tester.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.stress_tester_port,
    )


if __name__ == "__main__":
    main()
