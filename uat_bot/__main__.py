from __future__ import annotations

import uvicorn

from uat_bot.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "uat_bot.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.uat_port,
    )


if __name__ == "__main__":
    main()
