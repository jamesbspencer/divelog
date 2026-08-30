"""DiveCloud session-based web automation client."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from divecloud.config import DiveCloudConfig
from divecloud.exceptions import (
    DiveCloudAuthError,
    DiveCloudError,
    DiveCloudNetworkError,
    DiveCloudParseError,
    DiveCloudTimeoutError,
)

logger = logging.getLogger(__name__)


class DiveCloudClient:
    """Session-based HTTP automation client for divecloud.net."""

    DEVICE_ID: str = "DC_WEB"
    DEVICE_TYPE: str = "1"
    APP_ID: str = "DIVECLOUD"

    def __init__(self, config: Optional[DiveCloudConfig] = None):
        """Initialize the client with configuration and HTTP session."""
        self.config = config or DiveCloudConfig.from_env()
        self.session = requests.Session()
        self._session_token: Optional[str] = None
        self._is_authenticated: bool = False

        # Setup custom headers
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })

        # Configure retry strategy with exponential backoff for slow server responses
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _pace(self) -> None:
        """Pace requests to respect server performance."""
        if self.config.request_delay > 0:
            time.sleep(self.config.request_delay)

    def _extract_brackets(self, text: str) -> List[str]:
        """Extract all bracketed tokens e.g. '{YES}', '{SESSION=xyz}'."""
        return re.findall(r"\{([^}]+)\}", text)

    def check_registration(self, email: Optional[str] = None) -> Dict[str, Any]:
        """Check if an email is registered and active on DiveCloud."""
        target_email = email or self.config.username
        if not target_email:
            raise DiveCloudAuthError("Email/username is required to check registration")

        url = f"{self.config.base_url}/checkReg.py"
        params = {"EML": target_email, "CHECKREG": "1"}

        logger.debug("Checking registration for %s", target_email)
        self._pace()

        try:
            response = self.session.get(url, params=params, timeout=self.config.timeout)
            response.raise_for_status()
            text = response.text.strip()
        except requests.exceptions.Timeout as exc:
            raise DiveCloudTimeoutError(
                f"Timeout checking registration after {self.config.timeout}s"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise DiveCloudNetworkError(
                f"Network failure during registration check: {exc}"
            ) from exc

        tokens = self._extract_brackets(text)
        if not tokens:
            raise DiveCloudParseError("Unexpected response from checkReg.py", details=text)

        status = tokens[0]
        account_type = tokens[1] if len(tokens) > 1 else "UNKNOWN"
        account_state = tokens[2] if len(tokens) > 2 else "UNKNOWN"

        if status == "NO":
            raise DiveCloudAuthError("Account does not exist on DiveCloud", details=text)
        if status == "YES NOT YET VERIFIED":
            raise DiveCloudAuthError("Account exists but is not yet verified", details=text)

        return {
            "status": status,
            "account_type": account_type,
            "account_state": account_state,
            "raw": text,
        }

    def authenticate(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """Perform the 3-step authentication handshake with DiveCloud.

        Step 1: checkReg.py (verify registration)
        Step 2: init.py (generate server session)
        Step 3: /logincheck (authorize web session)
        """
        target_email = email or self.config.username
        target_pass = password or self.config.password

        if not target_email or not target_pass:
            raise DiveCloudAuthError("Both username/email and password must be provided")

        logger.info("Starting DiveCloud authentication for %s...", target_email)

        # Step 1: Verification
        reg_info = self.check_registration(target_email)
        logger.debug("Account verified: type=%s, state=%s", reg_info["account_type"], reg_info["account_state"])

        # Step 2: Session generation via init.py
        init_url = f"{self.config.base_url}/init.py"
        init_payload = {
            "EML": target_email,
            "PASS": target_pass,
            "DEVICE_ID": self.DEVICE_ID,
            "DEVICE_TYPE": self.DEVICE_TYPE,
            "APP_ID": self.APP_ID,
        }

        self._pace()
        try:
            init_resp = self.session.post(
                init_url,
                data=init_payload,
                timeout=self.config.timeout,
            )
            init_resp.raise_for_status()
            init_text = init_resp.text.strip()
        except requests.exceptions.Timeout as exc:
            raise DiveCloudTimeoutError(
                f"Timeout calling init.py after {self.config.timeout}s"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise DiveCloudNetworkError(
                f"Network failure during session initialization: {exc}"
            ) from exc

        tokens = self._extract_brackets(init_text)
        if not tokens or tokens[0] != "YES":
            raise DiveCloudAuthError(
                "Authentication failed during session generation (init.py)",
                details=init_text,
            )

        # Parse SESSION token from {SESSION=...}
        session_token = None
        for tok in tokens:
            if tok.startswith("SESSION="):
                session_token = tok.split("=", 1)[1]
                break

        if not session_token:
            raise DiveCloudParseError(
                "No session token returned in init.py response",
                details=init_text,
            )

        self._session_token = session_token
        logger.debug("Obtained session token: %s...", session_token[:8])

        # Step 3: Web session login via /logincheck
        logincheck_url = f"{self.config.base_url}/logincheck"
        logincheck_payload = {
            "EML": target_email,
            "PASS": target_pass,
            "DEVICE_ID": self.DEVICE_ID,
            "SESSION": self._session_token,
        }

        self._pace()
        try:
            login_resp = self.session.post(
                logincheck_url,
                data=logincheck_payload,
                timeout=self.config.timeout,
            )
            login_resp.raise_for_status()
            login_text = login_resp.text.strip()
        except requests.exceptions.Timeout as exc:
            raise DiveCloudTimeoutError(
                f"Timeout calling /logincheck after {self.config.timeout}s"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise DiveCloudNetworkError(
                f"Network failure during /logincheck: {exc}"
            ) from exc

        if "success" not in login_text.lower():
            raise DiveCloudAuthError(
                "Web login verification failed (/logincheck)",
                details=login_text,
            )

        self._is_authenticated = True
        logger.info("Successfully authenticated with DiveCloud!")
        return True

    def ensure_authenticated(self) -> None:
        """Verify authentication status and authenticate if needed."""
        if not self._is_authenticated:
            self.authenticate()

    def get_dives_summary(self) -> Dict[str, int]:
        """Get dive statistics summary from /getdivesinfo."""
        self.ensure_authenticated()
        url = f"{self.config.base_url}/getdivesinfo"
        self._pace()
        try:
            resp = self.session.get(url, timeout=self.config.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("Could not fetch getdivesinfo: %s", exc)
            return {}

    def list_files(self) -> List[Dict[str, Any]]:
        """List dive log files and archives available in the user account."""
        self.ensure_authenticated()

        files_url = f"{self.config.base_url}/files"
        logger.info("Fetching file list from DiveCloud...")

        self._pace()
        try:
            resp = self.session.get(files_url, timeout=self.config.timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise DiveCloudTimeoutError(
                f"Timeout retrieving /files after {self.config.timeout}s"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise DiveCloudNetworkError(
                f"Network failure retrieving /files: {exc}"
            ) from exc

        soup = BeautifulSoup(resp.text, "html.parser")
        files: List[Dict[str, Any]] = []

        # 1. Parse from #files_list <li> items (primary format on DiveCloud)
        items = soup.select("#files_list > li")
        for item in items:
            duid = item.get("duid") or ""
            name = item.get("name") or (f"{duid}.zxu" if duid else "")
            dive_type = item.get("dive") or "DLOG"
            
            # Find title / human readable label
            title_elem = item.select_one(".file_name, .name, .title, strong")
            title = title_elem.get_text(strip=True) if title_elem else (name or duid)

            if duid or name:
                files.append({
                    "duid": duid,
                    "name": name,
                    "title": title,
                    "dive_type": dive_type,
                    "download_url": f"{self.config.base_url}/download.py",
                })

        # 2. Fallback: Parse from any standard anchor links
        if not files:
            for row in soup.find_all("tr"):
                links = row.find_all("a", href=True)
                for link in links:
                    href = link["href"]
                    text = link.get_text(strip=True)
                    if any(ext in text.lower() or ext in href.lower() for ext in [".zxu", ".xml", ".dl7", ".uddf"]):
                        files.append({
                            "duid": Path(href).stem,
                            "name": text or Path(href).name,
                            "title": text,
                            "dive_type": "DLOG",
                            "download_url": href if href.startswith("http") else f"{self.config.base_url}{href}",
                        })

        logger.info("Found %d dive file(s) on DiveCloud.", len(files))
        return files

    def download_file(
        self,
        duid_or_name: str,
        destination_path: Path | str,
        folder: str = "ALL",
        skip_existing: bool = True,
        chunk_size: int = 8192,
    ) -> Path:
        """Download a dive file from DiveCloud by DUID or filename."""
        self.ensure_authenticated()

        duid = duid_or_name.replace(".zxu", "")
        filename = f"{duid}.zxu" if not duid_or_name.endswith(".zxu") else duid_or_name
        dest = Path(destination_path)

        if skip_existing and dest.exists() and dest.stat().st_size > 0:
            logger.debug("File %s already exists locally (%d bytes), skipping download.", dest.name, dest.stat().st_size)
            return dest

        dest.parent.mkdir(parents=True, exist_ok=True)

        url = f"{self.config.base_url}/download.py"
        params = {
            "FOLDER": folder,
            "DUID": duid,
            "FILENAME": filename,
            "EML": self.config.username,
            "SESSION": self._session_token,
            "DEVICE_ID": self.DEVICE_ID,
        }

        logger.info("Downloading %s from DiveCloud...", filename)
        self._pace()
        try:
            with self.session.get(url, params=params, stream=True, timeout=self.config.timeout) as resp:
                resp.raise_for_status()

                # Check if DiveCloud returned an error payload instead of file binary
                content_type = resp.headers.get("Content-Type", "")
                if "text" in content_type and b"{NO}" in resp.content[:64]:
                    raise DiveCloudError(
                        f"DiveCloud rejected download for {filename}",
                        details=resp.text.strip(),
                    )

                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)

        except requests.exceptions.Timeout as exc:
            raise DiveCloudTimeoutError(
                f"Timeout while downloading file {filename}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise DiveCloudNetworkError(
                f"Failed to download file {filename}: {exc}"
            ) from exc

        logger.info("Downloaded %s successfully (%d bytes).", dest.name, dest.stat().st_size)
        return dest

    def download_all(self, destination_dir: Path | str, skip_existing: bool = True) -> List[Path]:
        """Download all dive files in the account into destination_dir."""
        self.ensure_authenticated()
        dest_dir = Path(destination_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        files = self.list_files()
        downloaded: List[Path] = []

        for idx, file_info in enumerate(files, 1):
            name = file_info["name"]
            duid = file_info["duid"]
            out_file = dest_dir / (name if name.endswith(".zxu") else f"{duid}.zxu")
            self.download_file(duid, out_file, skip_existing=skip_existing)
            downloaded.append(out_file)

        return downloaded
