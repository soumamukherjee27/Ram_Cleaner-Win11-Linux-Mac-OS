# ram_cleaner

Cross-platform RAM cleaner & monitor (Windows / Linux / macOS)

A lightweight Python utility that continuously monitors system memory usage and triggers a platform-appropriate cleanup when memory usage crosses a configured threshold. The tool logs before/after statistics so you can **prove the effect** and use it as a demo project for interviews.

---

## Features
- Cross-platform detection (Windows / Linux / macOS)
- Configurable threshold and intervals (via CLI)
- Logging of before/after memory usage (persistent `ram_cleaner.log`)
- `--once` mode for single-run testing
- Examples and instructions for running at startup (Task Scheduler, systemd, launchd)

---

## What it does (short)
- Monitors RAM usage (using `psutil`).
- When usage ≥ threshold, performs a cleaning action:
  - **Windows:** trims working set using Windows APIs (safe, non-killing).
  - **Linux:** writes `3` to `/proc/sys/vm/drop_caches` (requires root) to drop caches.
  - **macOS:** runs `purge` (requires admin).
- Logs the action and the before/after stats.

---

## Quick start

### 1. Clone repository
```bash
git clone https://github.com/soumamukherjee27/Ram_Cleaner-Win11-Linux-Mac-OS.git
