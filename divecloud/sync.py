"""One-way synchronization engine from DiveCloud.net to Divelogs.org."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from divecloud.client import DiveCloudClient
from divecloud.config import DiveCloudConfig
from divecloud.parser import DiveRecord, ZXUParser
from divelogs.client import DivelogsClient
from divelogs.config import DivelogsConfig
from divelogs.transformer import DiveTransformer

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Detailed summary of synchronization execution."""
    total_found: int = 0
    synced: int = 0
    skipped_duplicates: int = 0
    failed: int = 0
    synced_dives: List[str] = field(default_factory=list)
    skipped_dives: List[str] = field(default_factory=list)
    failed_dives: List[str] = field(default_factory=list)
    is_dry_run: bool = False


class OneWaySyncEngine:
    """Orchestrates one-way sync from DiveCloud to Divelogs.org."""

    def __init__(
        self,
        divecloud_client: Optional[DiveCloudClient] = None,
        divelogs_client: Optional[DivelogsClient] = None,
    ):
        """Initialize sync engine with clients."""
        self.divecloud = divecloud_client or DiveCloudClient()
        self.divelogs = divelogs_client or DivelogsClient()

    @staticmethod
    def _parse_divelogs_dt(dive_dict: Dict[str, Any]) -> Optional[datetime]:
        """Extract datetime from a Divelogs.org dive item."""
        date_val = dive_dict.get("date", "")
        time_val = dive_dict.get("time", "00:00:00")
        if not date_val:
            return None

        # Clean time if needed
        time_parts = time_val.split(":")
        if len(time_parts) == 2:
            time_val = f"{time_val}:00"

        try:
            return datetime.strptime(f"{date_val} {time_val}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def is_duplicate(
        self,
        record: DiveRecord,
        existing_divelist: List[Dict[str, Any]],
        tolerance_minutes: int = 3,
    ) -> bool:
        """Check if a DiveRecord matches an existing dive in Divelogs.org."""
        if not record.start_time:
            return False

        for existing in existing_divelist:
            existing_dt = self._parse_divelogs_dt(existing)
            if not existing_dt:
                continue

            # Check timestamp match within tolerance
            diff = abs((record.start_time - existing_dt).total_seconds())
            if diff <= (tolerance_minutes * 60):
                logger.debug(
                    "Duplicate match: DiveCloud %s matches Divelogs #%s (%s)",
                    record.start_time,
                    existing.get("id") or existing.get("number"),
                    existing_dt,
                )
                return True

        return False

    def sync(
        self,
        local_dir: Optional[Path | str] = None,
        download_from_cloud: bool = True,
        dry_run: bool = False,
    ) -> SyncResult:
        """Execute one-way sync from DiveCloud to Divelogs.org."""
        result = SyncResult(is_dry_run=dry_run)
        dest_dir = Path(local_dir or "./downloads")
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Download or locate .zxu files
        if download_from_cloud:
            logger.info("Connecting to DiveCloud to check for dive files...")
            try:
                self.divecloud.download_all(dest_dir)
            except Exception as e:
                logger.warning("Could not auto-download from DiveCloud: %s", e)

        zxu_files = sorted(dest_dir.glob("*.zxu"))
        result.total_found = len(zxu_files)
        logger.info("Found %d dive file(s) for synchronization.", len(zxu_files))

        if not zxu_files:
            return result

        # Step 2: Parse all dive files
        records: List[DiveRecord] = []
        for f in zxu_files:
            try:
                rec = ZXUParser.parse_file(f)
                records.append(rec)
            except Exception as e:
                logger.error("Failed to parse %s: %e", f.name, e)
                result.failed += 1
                result.failed_dives.append(f"{f.name} (parse error)")

        # Propagate location across same-trip dives if missing
        for rec in records:
            if not rec.location:
                for other in records:
                    if other.location and other.start_time and rec.start_time:
                        diff_days = abs((rec.start_time.date() - other.start_time.date()).days)
                        if diff_days <= 1:
                            rec.location = other.location
                            rec.latitude = other.latitude
                            rec.longitude = other.longitude
                            break

        # Step 3: Fetch existing dives on Divelogs.org for deduplication
        existing_divelist: List[Dict[str, Any]] = []
        if not dry_run or self.divelogs.config.username:
            try:
                existing_divelist = self.divelogs.get_divelist()
                logger.info("Retrieved %d existing dive(s) from Divelogs.org.", len(existing_divelist))
            except Exception as e:
                logger.warning("Could not retrieve divelist from Divelogs.org: %s", e)

        # Step 4: Process and upload unsynced dives
        for rec in records:
            dive_label = f"{rec.duid} ({rec.start_time.strftime('%Y-%m-%d %H:%M') if rec.start_time else 'No Date'})"

            if self.is_duplicate(rec, existing_divelist):
                logger.info("⏭️ Skipped duplicate: %s", dive_label)
                result.skipped_duplicates += 1
                result.skipped_dives.append(dive_label)
                continue

            # Transform to Divelogs schema
            payload = DiveTransformer.transform_dive(rec)

            if dry_run:
                logger.info("🔍 [DRY RUN] Would upload: %s (Max depth: %.1fm, Duration: %ds, %d samples)",
                            dive_label, payload["maxdepth"], payload["duration"], len(payload.get("sampledata", [])))
                result.synced += 1
                result.synced_dives.append(dive_label)
                continue

            # Upload to Divelogs.org
            try:
                logger.info("⬆️ Uploading to Divelogs.org: %s...", dive_label)
                self.divelogs.post_dive(payload)
                logger.info("✅ Successfully synced: %s", dive_label)
                result.synced += 1
                result.synced_dives.append(dive_label)
            except Exception as e:
                logger.error("❌ Failed to sync %s: %s", dive_label, e)
                result.failed += 1
                result.failed_dives.append(f"{dive_label}: {e}")

        return result
