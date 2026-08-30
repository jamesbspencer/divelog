# AGENTS.md

## Project Overview
This repository (`divelog`) is a testbed and development workspace for prototyping and implementing data synchronization between **[divecloud.net](https://divecloud.net)** and **[divelog.org](https://divelog.org)**.

The primary objective is to enable seamless, reliable, and bidirectional or unidirectional sync of scuba diving logs, telemetry profiles (depth, time, temperature, tank pressures, gas switches), equipment setups, and dive site metadata between both platforms.

---

## Core Objectives & Scope
1. **API Integration & Exploration**:
   - Investigate and interface with the REST/GraphQL APIs or export/import endpoints for both `divecloud.net` and `divelog.org`.
   - Implement robust authentication handling (OAuth2, session tokens, API keys) via secure environment variables.
2. **Data Model Translation & Mapping**:
   - Map DiveCloud data schemas to Divelog.org formats and open dive log standards (e.g., UDDF / Universal Dive Data Format, Dan DL7, CSV, JSON).
   - Normalize dive profile time-series data (depth curves, deco stops, ascent rates, SAC rates).
3. **Synchronization Logic & Safety**:
   - **Non-Destructive Guarantee**: NEVER delete, overwrite, or mutate existing dive logs in either platform. Synchronization is strictly additive (new dives only).
   - Deduplication: Identify previously synced dives across platforms using UTC timestamps and dive duration. Existing logs found on Divelogs.org are strictly skipped.
   - Read-Only Master: Operations against DiveCloud.net are strictly read-only (downloads only).
   - Rate limiting, retry with exponential backoff, and pagination for batch sync operations.
4. **Testing & Simulation**:
   - Build offline mock servers and sample dive fixtures to validate sync logic without hitting live endpoints during development.

---

## Agent Guidelines & Workflow Rules

### 1. Security & Credentials
- **NEVER** commit live credentials, API keys, passwords, or personal authentication tokens to git.
- Use `.env` files (ignored by git) and environment variable loaders (e.g., `python-dotenv`) for local secrets.
- Always provide `.env.example` templates with placeholder values for required configurations.

### 2. Code Quality & Conventions
- **Language & Style**: Python 3.10+ is the preferred language. Adhere to PEP 8, use explicit type hints (`typing`), and include concise docstrings for all modules and sync handlers.
- **Error Handling**: Handle network failures, schema mismatches, and API errors gracefully. Provide informative logging rather than unhandled exceptions.
- **Modularity**: Separate client adapters (e.g., `divecloud_client`, `divelog_client`) from the core synchronization engine and data transformation layers.

### 3. Testing & Validation
- Write automated unit and integration tests using `pytest`.
- Use recorded mocks or fixture data for API responses to ensure reproducible, fast test suites.
- When adding new sync features or format transformers, include accompanying test cases with edge-case dive profiles (e.g., repetitive dives, multi-tank profiles, altitude dives).

### 4. Git & Documentation
- Keep commit messages concise, descriptive, and imperative (e.g., `feat: add UDDF parser for divecloud export`).
- Update `README.md` and relevant documentation whenever adding new tools, scripts, or sync workflows.
