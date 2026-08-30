"""CLI tool for interacting with DiveCloud, exporting to UDDF, and syncing to Divelogs.org."""

from __future__ import annotations

import argparse
import glob
import logging
import sys
from pathlib import Path

from divecloud.client import DiveCloudClient
from divecloud.config import DiveCloudConfig
from divecloud.exceptions import DiveCloudAuthError, DiveCloudError, DiveCloudTimeoutError
from divecloud.parser import ZXUParser
from divecloud.sync import OneWaySyncEngine
from divecloud.uddf import UDDFExporter
from divelogs.client import DivelogsClient
from divelogs.config import DivelogsConfig


def setup_logging(verbose: bool = False) -> None:
    """Setup console logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_test_login(args: argparse.Namespace) -> int:
    """Test login credentials against DiveCloud and Divelogs.org."""
    # 1. Test DiveCloud
    dc_config = DiveCloudConfig.from_env(args.env)
    if args.username:
        dc_config.username = args.username
    if args.password:
        dc_config.password = args.password

    if not dc_config.username or not dc_config.password:
        print("❌ Error: DiveCloud username and password must be provided via .env or CLI flags.")
        return 1

    print(f"Connecting to DiveCloud at {dc_config.base_url}...")
    print(f"Checking DiveCloud account: {dc_config.username}")

    dc_client = DiveCloudClient(dc_config)
    try:
        reg_info = dc_client.check_registration()
        print(f"✅ DiveCloud Account: {reg_info['status']} (Type: {reg_info['account_type']}, State: {reg_info['account_state']})")

        print("Authenticating session...")
        dc_client.authenticate()
        print("🎉 DiveCloud Login successful! Active session established.")

        summary = dc_client.get_dives_summary()
        if summary:
            print(f"📊 Account Summary: Total Dives = {summary.get('TOTAL', 'N/A')}")

    except DiveCloudAuthError as e:
        print(f"❌ DiveCloud Authentication Failed: {e}")
        return 2
    except DiveCloudTimeoutError as e:
        print(f"⏱️ DiveCloud Request Timed Out: {e}")
        return 3
    except DiveCloudError as e:
        print(f"❌ DiveCloud Error: {e}")
        return 4

    # 2. Test Divelogs.org if credentials provided
    dl_config = DivelogsConfig.from_env(args.env)
    if dl_config.username and dl_config.password:
        print(f"\nConnecting to Divelogs.org at {dl_config.api_url}...")
        print(f"Checking Divelogs account: {dl_config.username}")
        dl_client = DivelogsClient(dl_config)
        try:
            dl_client.authenticate()
            print("🎉 Divelogs.org Login successful! Bearer token obtained.")
        except Exception as e:
            print(f"⚠️ Divelogs.org Login failed: {e}")

    return 0


def cmd_list_files(args: argparse.Namespace) -> int:
    """List files in DiveCloud account."""
    config = DiveCloudConfig.from_env(args.env)
    client = DiveCloudClient(config)

    try:
        files = client.list_files()
        if not files:
            print("No dive files found in the account.")
            return 0

        print(f"Found {len(files)} dive file(s):")
        for idx, file in enumerate(files, 1):
            print(f"  [{idx}] {file['name']} (DUID: {file['duid']}, Label: {file['title']})")
        return 0

    except DiveCloudError as e:
        print(f"❌ Error listing files: {e}")
        return 1


def cmd_download(args: argparse.Namespace) -> int:
    """Download a specific dive file from DiveCloud."""
    config = DiveCloudConfig.from_env(args.env)
    client = DiveCloudClient(config)

    dest = Path(args.output)
    try:
        result = client.download_file(args.duid, dest)
        print(f"✅ Saved dive log to: {result}")
        return 0
    except DiveCloudError as e:
        print(f"❌ Download failed: {e}")
        return 1


def cmd_download_all(args: argparse.Namespace) -> int:
    """Download all dive files from DiveCloud."""
    config = DiveCloudConfig.from_env(args.env)
    client = DiveCloudClient(config)

    dest_dir = Path(args.output_dir)
    try:
        print(f"Downloading all dive files to '{dest_dir}'...")
        downloaded = client.download_all(dest_dir)
        print(f"🎉 Successfully downloaded {len(downloaded)} dive file(s) to {dest_dir}!")
        return 0
    except DiveCloudError as e:
        print(f"❌ Batch download failed: {e}")
        return 1


def cmd_convert(args: argparse.Namespace) -> int:
    """Convert .zxu files to UDDF (Universal Dive Data Format)."""
    input_paths = []
    for pattern in args.inputs:
        p = Path(pattern)
        if p.is_dir():
            input_paths.extend(sorted(p.glob("*.zxu")))
        else:
            for match in glob.glob(pattern):
                input_paths.append(Path(match))

    if not input_paths:
        print("❌ Error: No .zxu files found matching input paths.")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Converting {len(input_paths)} .zxu file(s) to UDDF 3.2.0...")
    dives = []
    for f in input_paths:
        try:
            dive = ZXUParser.parse_file(f)
            dives.append(dive)
        except Exception as e:
            print(f"  ❌ Error parsing {f.name}: {e}")

    # Propagate location for dives in the same trip missing GPS
    for d in dives:
        if not d.location:
            for other in dives:
                if other.location and other.start_time and d.start_time:
                    diff_days = abs((d.start_time.date() - other.start_time.date()).days)
                    if diff_days <= 1:
                        d.location = other.location
                        d.latitude = other.latitude
                        d.longitude = other.longitude
                        break

    if not args.combined:
        for dive in dives:
            out_file = out_dir / f"{dive.duid}.uddf"
            UDDFExporter.export_single_dive(dive, out_file)
            loc_label = f" [{dive.location}]" if dive.location else ""
            print(f"  ✅ Converted {dive.duid}.zxu -> {out_file.name} (Dive #{dive.dive_number}, {len(dive.samples)} samples{loc_label})")
        print(f"\n🎉 Successfully exported {len(dives)} individual UDDF file(s) into: {out_dir}")
    elif args.combined and dives:
        combined_file = out_dir / "all_dives.uddf"
        UDDFExporter.export_dives(dives, combined_file)
        print(f"\n🎉 Successfully exported all {len(dives)} dives into: {combined_file}")

    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Execute one-way sync from DiveCloud.net to Divelogs.org."""
    dc_config = DiveCloudConfig.from_env(args.env)
    dl_config = DivelogsConfig.from_env(args.env)

    dry_run = args.dry_run

    print("=" * 60)
    print(" 🚀 One-Way Dive Sync: DiveCloud.net ➔ Divelogs.org")
    print(f" Mode: {'[DRY RUN - Preview Only]' if dry_run else '[LIVE SYNC]'}")
    print(f" Source: {dc_config.username} @ {dc_config.base_url}")
    print(f" Destination: {dl_config.username or '(Not configured)'} @ {dl_config.api_url}")
    print("=" * 60)

    if not dry_run and (not dl_config.username or not dl_config.password):
        print("\n❌ Error: DIVELOGS_USERNAME and DIVELOGS_PASSWORD must be configured in .env for live sync.")
        print("Tip: Run with '--dry-run' to test parsing and preview transformations without credentials.")
        return 1

    dc_client = DiveCloudClient(dc_config)
    dl_client = DivelogsClient(dl_config)
    engine = OneWaySyncEngine(divecloud_client=dc_client, divelogs_client=dl_client)

    result = engine.sync(
        local_dir=args.local_dir,
        download_from_cloud=not args.no_download,
        dry_run=dry_run,
    )

    print("\n" + "=" * 60)
    print(" 📊 Synchronization Summary")
    print("=" * 60)
    print(f"  Total Dives Found:       {result.total_found}")
    print(f"  Dives Uploaded/Ready:    {result.synced}")
    print(f"  Duplicates Skipped:      {result.skipped_duplicates}")
    print(f"  Failures:                {result.failed}")

    if result.synced_dives:
        print(f"\n  Synced / Ready Dives ({len(result.synced_dives)}):")
        for d in result.synced_dives:
            print(f"    - {d}")

    if result.skipped_dives:
        print(f"\n  Skipped Duplicates ({len(result.skipped_dives)}):")
        for d in result.skipped_dives:
            print(f"    - {d}")

    if result.failed_dives:
        print(f"\n  Failed Dives ({len(result.failed_dives)}):")
        for d in result.failed_dives:
            print(f"    - {d}")

    print("=" * 60)
    return 0 if result.failed == 0 else 1


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="DiveCloud session automation, UDDF export, & Divelogs.org sync CLI"
    )
    parser.add_argument("--env", type=str, default=None, help="Path to custom .env file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # test-login
    p_login = subparsers.add_parser("test-login", help="Test credentials and login handshake")
    p_login.add_argument("-u", "--username", help="DiveCloud username/email")
    p_login.add_argument("-p", "--password", help="DiveCloud password")

    # list-files
    subparsers.add_parser("list-files", help="List dive files stored in DiveCloud")

    # download
    p_dl = subparsers.add_parser("download", help="Download a dive file from DiveCloud")
    p_dl.add_argument("duid", help="DUID or filename (e.g. 7165_4515_20240712141100_1)")
    p_dl.add_argument("-o", "--output", required=True, help="Destination file path")

    # download-all
    p_dl_all = subparsers.add_parser("download-all", help="Download all dive logs from DiveCloud")
    p_dl_all.add_argument("-o", "--output-dir", default="./downloads", help="Destination folder (default: ./downloads)")

    # convert
    p_conv = subparsers.add_parser("convert", help="Convert .zxu files to Universal Dive Data Format (UDDF)")
    p_conv.add_argument("inputs", nargs="+", help="Files or directory containing .zxu files (e.g. ./downloads/)")
    p_conv.add_argument("-o", "--output-dir", default="./exports", help="Output directory for UDDF files (default: ./exports)")
    p_conv.add_argument("--combined", action="store_true", help="Combine all dives into a single all_dives.uddf logbook file")

    # sync
    p_sync = subparsers.add_parser("sync", help="One-way sync from DiveCloud.net to Divelogs.org")
    p_sync.add_argument("--dry-run", action="store_true", help="Preview synchronization without uploading")
    p_sync.add_argument("--no-download", action="store_true", help="Use local downloaded files without re-downloading from cloud")
    p_sync.add_argument("--local-dir", default="./downloads", help="Directory for downloaded dive files (default: ./downloads)")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "test-login":
        sys.exit(cmd_test_login(args))
    elif args.command == "list-files":
        sys.exit(cmd_list_files(args))
    elif args.command == "download":
        sys.exit(cmd_download(args))
    elif args.command == "download-all":
        sys.exit(cmd_download_all(args))
    elif args.command == "convert":
        sys.exit(cmd_convert(args))
    elif args.command == "sync":
        sys.exit(cmd_sync(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
