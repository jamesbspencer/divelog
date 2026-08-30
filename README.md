# divelog: DiveCloud.net ➔ Divelogs.org One-Way Sync

A Python toolkit for session-based automation, dive log extraction, UDDF conversion, and one-way synchronization from **[divecloud.net](https://divecloud.net)** to **[divelogs.org](https://divelogs.org)** (divelogs.de).

---

## 🎯 Features

- **DiveCloud Session Automation**: Automated 3-step authentication handshake (`checkReg.py` -> `init.py` -> `/logincheck`) with session token extraction and cookie management.
- **Latency & Timeout Resilience**: Configured with generous timeouts, exponential backoff retries on transient errors (`429`, `5xx`), and request pacing to handle slow server response times.
- **UDDF 3.2.0 Conversion**: Parse `.zxu` binary/XML archives and export to standardized **Universal Dive Data Format (UDDF)** with full telemetry (depth curves, water temperature, tank pressure, breathing gases).
- **One-Way Sync Engine**: Synchronize new dives from DiveCloud directly to Divelogs.org via its REST API (`POST /api/dive(s)`), with automated duplicate detection (`GET /api/divelist`) and `--dry-run` preview.
- **CLI Utility**: Test credentials, inspect account status, list dive files, download logs, convert to UDDF, and execute syncs directly from the terminal.

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.9+

### 2. Installation
```bash
# Clone repository
git clone https://github.com/jamesbspencer/divelog.git
cd divelog

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy the sample environment file and set your credentials:
```bash
cp .env.example .env
```

Edit `.env`:
```ini
# DiveCloud Source
DIVECLOUD_API_URL=https://divecloud.net
DIVECLOUD_USERNAME=your_email@example.com
DIVECLOUD_PASSWORD=your_divecloud_password
DIVECLOUD_TIMEOUT=45
DIVECLOUD_MAX_RETRIES=3
DIVECLOUD_REQUEST_DELAY=1.0

# Divelogs.org Destination
DIVELOGS_API_URL=https://divelogs.de/api
DIVELOGS_USERNAME=your_divelogs_username
DIVELOGS_PASSWORD=your_divelogs_password
```

---

## 💻 CLI Usage

### Test Login & Credentials
```bash
python -m divecloud.cli test-login
```

### Download Dive Logs from DiveCloud
```bash
# Download all dives from account
python -m divecloud.cli download-all -o ./downloads
```

### Convert to Universal Dive Data Format (UDDF)
```bash
# Convert all .zxu files in ./downloads to individual .uddf files in ./exports/uddf/
python -m divecloud.cli convert downloads/ -o exports/uddf/

# Convert and combine all dives into a single all_dives.uddf logbook
python -m divecloud.cli convert downloads/ -o exports/ --combined
```

### One-Way Sync to Divelogs.org
```bash
# Dry run: preview which dives will be transformed and uploaded without mutating
python -m divecloud.cli sync --dry-run

# Live one-way sync (downloads from DiveCloud, deduplicates against Divelogs.org, and uploads new dives)
python -m divecloud.cli sync
```

---

## 🧪 Running Tests

Run the full test suite with `pytest`:
```bash
pytest -v
```

---

## 📁 Repository Structure

```
divelog/
├── AGENTS.md             # Agent guidelines & synchronization protocols
├── README.md             # Project documentation
├── .env.example          # Template environment configuration
├── pyproject.toml        # Project metadata & build settings
├── requirements.txt      # Dependency specification
├── divecloud/
│   ├── __init__.py       # Package exports
│   ├── client.py         # DiveCloudClient with 3-step auth & retries
│   ├── config.py         # DiveCloud config loader
│   ├── exceptions.py     # DiveCloud exception hierarchy
│   ├── parser.py         # ZXUParser for dive profiles & telemetry
│   ├── uddf.py           # UDDFExporter for UDDF 3.2.0 XML generation
│   ├── sync.py           # OneWaySyncEngine & deduplication logic
│   └── cli.py            # CLI commands (login, list, download, convert, sync)
├── divelogs/
│   ├── __init__.py       # Package exports
│   ├── client.py         # DivelogsClient REST adapter
│   ├── config.py         # Divelogs config loader
│   ├── exceptions.py     # Divelogs exception hierarchy
│   └── transformer.py    # DiveTransformer (DiveRecord -> Divelogs JSON schema)
└── tests/
    ├── test_client.py    # Unit tests for DiveCloud web client
    ├── test_uddf.py      # Unit tests for ZXU parser & UDDF exporter
    └── test_sync.py      # Unit tests for Divelogs client, transformer & sync engine
```
