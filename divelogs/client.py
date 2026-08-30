"""HTTP REST API client for Divelogs.org / Divelogs.de."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import requests

from divelogs.config import DivelogsConfig
from divelogs.exceptions import (
    DivelogsAuthError,
    DivelogsError,
    DivelogsUploadError,
)

logger = logging.getLogger(__name__)


class DivelogsClient:
    """REST API Client for Divelogs.org."""

    def __init__(self, config: Optional[DivelogsConfig] = None):
        """Initialize client with configuration and HTTP session."""
        self.config = config or DivelogsConfig.from_env()
        self.session = requests.Session()
        self._bearer_token: Optional[str] = self.config.bearer_token or None

        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "divelog-sync/0.1.0",
        })

        if self._bearer_token:
            self.session.headers["Authorization"] = f"Bearer {self._bearer_token}"

    def authenticate(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """Authenticate with Divelogs.org using POST /login to obtain JWT bearer token."""
        user = username or self.config.username
        pwd = password or self.config.password

        if not user or not pwd:
            raise DivelogsAuthError("Both username and password are required to login to Divelogs.org")

        login_url = f"{self.config.api_url}/login"
        payload = {"user": user, "pass": pwd}

        logger.info("Authenticating with Divelogs.org as %s...", user)
        try:
            # Login endpoint expects application/x-www-form-urlencoded
            resp = self.session.post(
                login_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.config.timeout,
            )
        except requests.exceptions.RequestException as e:
            raise DivelogsError(f"Network error connecting to Divelogs.org: {e}") from e

        if resp.status_code == 401 or resp.status_code == 403:
            raise DivelogsAuthError("Invalid username or password for Divelogs.org", status_code=resp.status_code)

        if resp.status_code != 200:
            raise DivelogsError(
                f"Login failed on Divelogs.org",
                status_code=resp.status_code,
                details=resp.text,
            )

        data = resp.json()
        token = data.get("bearer_token") or data.get("token")
        if not token:
            raise DivelogsAuthError("No bearer_token found in login response", details=resp.text)

        self._bearer_token = token
        self.session.headers["Authorization"] = f"Bearer {token}"
        logger.info("Successfully authenticated with Divelogs.org!")
        return token

    def ensure_authenticated(self) -> None:
        """Ensure bearer token is present or login."""
        if not self._bearer_token:
            self.authenticate()

    def get_divelist(self) -> List[Dict[str, Any]]:
        """Retrieve existing dive summary list from Divelogs.org for deduplication."""
        self.ensure_authenticated()

        url = f"{self.config.api_url}/divelist"
        logger.info("Fetching existing dive list from Divelogs.org...")

        try:
            resp = self.session.get(url, timeout=self.config.timeout)
            if resp.status_code == 401:
                # Token might have expired, try re-authenticating once
                logger.info("Token expired, re-authenticating with Divelogs.org...")
                self.authenticate()
                resp = self.session.get(url, timeout=self.config.timeout)

            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("dives", [])
        except requests.exceptions.RequestException as e:
            logger.warning("Could not fetch /divelist from Divelogs.org: %s", e)
            return []

    def get_user_profile(self) -> Dict[str, Any]:
        """Fetch current user profile details."""
        self.ensure_authenticated()
        url = f"{self.config.api_url}/user"
        try:
            resp = self.session.get(url, timeout=self.config.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise DivelogsError(f"Failed to fetch user profile: {e}") from e

    def post_dive(self, dive_data: Dict[str, Any]) -> Dict[str, Any]:
        """Upload a single dive to Divelogs.org."""
        self.ensure_authenticated()

        url = f"{self.config.api_url}/dive"
        logger.debug("Posting dive for %s %s to Divelogs.org...", dive_data.get("date"), dive_data.get("time"))

        try:
            resp = self.session.post(url, json=dive_data, timeout=self.config.timeout)
            if resp.status_code == 401:
                self.authenticate()
                resp = self.session.post(url, json=dive_data, timeout=self.config.timeout)

            if resp.status_code not in (200, 201):
                raise DivelogsUploadError(
                    f"Failed to upload dive on {dive_data.get('date')} {dive_data.get('time')}",
                    status_code=resp.status_code,
                    details=resp.text,
                )
            return resp.json() if resp.text else {"status": "success"}

        except requests.exceptions.RequestException as e:
            raise DivelogsUploadError(f"Network failure uploading dive: {e}") from e

    def update_dive(self, dive_id: str | int, dive_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing dive on Divelogs.org."""
        self.ensure_authenticated()

        url = f"{self.config.api_url}/dive/{dive_id}"
        logger.debug("Updating dive %s on Divelogs.org...", dive_id)

        try:
            resp = self.session.put(url, json=dive_data, timeout=self.config.timeout)
            if resp.status_code == 401:
                self.authenticate()
                resp = self.session.put(url, json=dive_data, timeout=self.config.timeout)

            if resp.status_code not in (200, 201):
                raise DivelogsUploadError(
                    f"Failed to update dive {dive_id}",
                    status_code=resp.status_code,
                    details=resp.text,
                )
            return resp.json() if resp.text else {"status": "success"}

        except requests.exceptions.RequestException as e:
            raise DivelogsUploadError(f"Network failure updating dive {dive_id}: {e}") from e

    def post_dives(self, dives_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Batch upload multiple dives to Divelogs.org."""
        self.ensure_authenticated()

        url = f"{self.config.api_url}/dives"
        logger.info("Batch uploading %d dives to Divelogs.org...", len(dives_data))

        try:
            resp = self.session.post(url, json=dives_data, timeout=self.config.timeout * 2)
            if resp.status_code == 401:
                self.authenticate()
                resp = self.session.post(url, json=dives_data, timeout=self.config.timeout * 2)

            if resp.status_code not in (200, 201):
                raise DivelogsUploadError(
                    f"Failed batch dive upload",
                    status_code=resp.status_code,
                    details=resp.text,
                )
            return resp.json() if resp.text else {"status": "success"}

        except requests.exceptions.RequestException as e:
            raise DivelogsUploadError(f"Network failure during batch dive upload: {e}") from e
