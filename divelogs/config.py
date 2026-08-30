"""Configuration loader for Divelogs.org API client."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class DivelogsConfig:
    """Configuration parameters for Divelogs.org API."""
    api_url: str = "https://divelogs.de/api"
    username: str = ""
    password: str = ""
    bearer_token: str = ""
    timeout: float = 30.0

    @classmethod
    def from_env(cls, env_path: Path | str | None = None) -> DivelogsConfig:
        """Load configuration from environment variables or .env file."""
        if env_path:
            load_dotenv(dotenv_path=env_path)
        else:
            load_dotenv()

        api_url = (
            os.getenv("DIVELOGS_API_URL")
            or os.getenv("DIVELOG_API_URL")
            or "https://divelogs.de/api"
        ).rstrip("/")

        username = (
            os.getenv("DIVELOGS_USERNAME")
            or os.getenv("DIVELOG_USERNAME")
            or ""
        ).strip()

        password = (
            os.getenv("DIVELOGS_PASSWORD")
            or os.getenv("DIVELOG_PASSWORD")
            or ""
        ).strip()

        bearer_token = os.getenv("DIVELOGS_BEARER_TOKEN", "").strip()

        return cls(
            api_url=api_url,
            username=username,
            password=password,
            bearer_token=bearer_token,
        )
