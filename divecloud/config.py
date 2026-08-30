"""Configuration loader for DiveCloud client."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class DiveCloudConfig:
    """Configuration parameters for DiveCloud client."""
    base_url: str = "https://divecloud.net"
    username: str = ""
    password: str = ""
    timeout: float = 45.0
    max_retries: int = 3
    request_delay: float = 1.0

    @classmethod
    def from_env(cls, env_path: Path | str | None = None) -> DiveCloudConfig:
        """Load configuration from environment variables or .env file."""
        if env_path:
            load_dotenv(dotenv_path=env_path)
        else:
            load_dotenv()

        base_url = os.getenv("DIVECLOUD_API_URL", "https://divecloud.net").rstrip("/")
        username = os.getenv("DIVECLOUD_USERNAME", "").strip()
        password = os.getenv("DIVECLOUD_PASSWORD", "").strip()

        try:
            timeout = float(os.getenv("DIVECLOUD_TIMEOUT", "45.0"))
        except ValueError:
            timeout = 45.0

        try:
            max_retries = int(os.getenv("DIVECLOUD_MAX_RETRIES", "3"))
        except ValueError:
            max_retries = 3

        try:
            request_delay = float(os.getenv("DIVECLOUD_REQUEST_DELAY", "1.0"))
        except ValueError:
            request_delay = 1.0

        return cls(
            base_url=base_url,
            username=username,
            password=password,
            timeout=timeout,
            max_retries=max_retries,
            request_delay=request_delay,
        )
