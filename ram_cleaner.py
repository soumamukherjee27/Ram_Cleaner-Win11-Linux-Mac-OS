#!/usr/bin/env python3
"""
ram_cleaner.py
Cross-platform RAM cleaner that monitors memory usage and triggers a cleaning action
when usage crosses a configured threshold.

Supports:
- Windows: trims working set via Windows APIs
- Linux: drops pagecache / dentries / inodes via write to /proc/sys/vm/drop_caches (requires root)
- macOS: runs 'purge' (requires admin / may need Xcode dev tools)

Usage:
    python ram_cleaner.py --threshold 60 --check-interval 10 --after-clean 60
    python ram_cleaner.py --once --threshold 50   # run single check & clean (for testing)
"""

import argparse
import logging
import platform
import time
import psutil
import sys
import subprocess
import os

# Windows-specific imports attempted lazily (only import/use when on Windows)
try:
    import ctypes
    from ctypes import wintypes
except Exception:
    ctypes = None

# ----------------------------- Config/Defaults -----------------------------
DEFAULT_THRESHOLD = 60
DEFAULT_CHECK_INTERVAL = 10
DEFAULT_AFTER_CLEAN = 60
DEFAULT_LOGFILE = "ram_cleaner.log"

# ----------------------------- OS helpers ---------------------------------
def is_root():
    """Return True if running as root/administrator"""
    if os.name == 'nt':
        # On Windows, check for admin using shell call
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        return os.geteuid() == 0

# ----------------------------- Cleaning functions --------------------------
def clean_memory_windows(logger):
    """Trim the working set for *this* process. Requires kernel32 & psapi."""
    if ctypes is None:
        logger.error("ctypes not available — cannot run Windows-specific code.")
        return False

    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.restype = wintypes.BOOL
        kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL

        hProc = kernel32.GetCurrentProcess()
        ok1 = bool(psapi.EmptyWorkingSet(hProc))
        ok2 = bool(kernel32.SetProcessWorkingSetSize(hProc,
                                                    ctypes.c_size_t(-1),
                                                    ctypes.c_size_t(-1)))
        logger.info(f"Windows clean: EmptyWorkingSet={ok1} SetProcessWorkingSetSize={ok2}")
        return ok1 or ok2
    except Exception as e:
        logger.exception("Windows memory-clean failed")
        return False

def clean_memory_linux(logger):
    """
    Clear caches on Linux by writing to /proc/sys/vm/drop_caches.
    WARNING: This requires root privileges. Use with care.
    """
    try:
        # Ensure sync first
        subprocess.run(["/bin/sync"], check=True)
        # Need to echo to file as root. Using shell for the echo operation.
        cmd = "echo 3 > /proc/sys/vm/drop_caches"
        subprocess.run(cmd, shell=True, check=True, executable="/bin/bash")
        logger.info("Linux clean: wrote '3' to /proc/sys/vm/drop_caches")
        return True
    except subprocess.CalledProcessError as e:
        logger.exception("Linux drop_caches failed (requires root)")
        return False
    except Exception:
        logger.exception("Linux memory-clean failed")
        return False

def clean_memory_mac(logger):
    """
    macOS memory cleaning via 'purge' command.
    May require installation of developer tools or privileges.
    """
    try:
        # purge is a built-in tool on many macOS versions; requires sudo
        subprocess.run(["/usr/bin/sudo", "purge"], check=True)
        logger.info("macOS clean: executed 'purge'")
        return True
    except subprocess.CalledProcessError:
        logger.exception("macOS 'purge' failed (may require sudo or not available)")
        return False
    except Exception:
        logger.exception("macOS memory-clean failed")
        return False

# ----------------------------- Utility functions ---------------------------
def current_ram_percent():
    return psutil.virtual_memory().percent

def bytes_used():
    return psutil.virtual_memory().used

# ----------------------------- Main loop ----------------------------------
def main(argv):
    parser = argparse.ArgumentParser(description="Cross-platform RAM Cleaner Service")
    parser.add_argument("--threshold", "-t", type=int, default=DEFAULT_THRESHOLD,
                        help=f"RAM percent threshold to trigger cleaning (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--check-interval", "-i", type=int, default=DEFAULT_CHECK_INTERVAL,
                        help=f"Seconds between checks when below threshold (default: {DEFAULT_CHECK_INTERVAL})")
    parser.add_argument("--after-clean", "-a", type=int, default=DEFAULT_AFTER_CLEAN,
                        help=f"Seconds to wait after a cleanup (default: {DEFAULT_AFTER_CLEAN})")
    parser.add_argument("--logfile", "-l", default=DEFAULT_LOGFILE, help="Log file path")
    parser.add_argument("--once", action="store_true", help="Run one check & exit (useful for testing)")
    parser.add_argument("--verbose", action="store_true", help="Print extra output to stdout")
    args = parser.parse_args(argv)

    # Setup logging
    logging.basicConfig(filename=args.logfile,
                        level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")
    logger = logging.getLogger("ram_cleaner")

    if args.verbose:
        # Add console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(ch)

    system_name = platform.system().lower()
    logger.info(f"Starting ram_cleaner on {system_name}. Threshold={args.threshold}%")

    # Identify clean function
    if system_name == "windows":
        cleaner = clean_memory_windows
    elif system_name == "linux":
        cleaner = clean_memory_linux
    elif system_name == "darwin":
        cleaner = clean_memory_mac
    else:
        logger.error(f"Unsupported OS: {system_name}")
        sys.exit(1)

    # On Linux/macOS we should warn user if not root (since cleaning usually needs root)
    if system_name in ("linux", "darwin") and not is_root():
        logger.warning("Not running as root — cleaning may fail (needs sudo/root).")

    start_time = time.time()

    def log_status(before, after, success):
        freed_bytes = max(0, before - after)
        before_pct = (before / psutil.virtual_memory().total) * 100
        after_pct = (after / psutil.virtual_memory().total) * 100
        logger.info(f"RAM bytes before: {before} | after: {after} | freed: {freed_bytes} | success: {success}")
        # extra human-friendly line
        logger.info(f"RAM percent before: {psutil.virtual_memory().percent}% (after: {after_pct:.1f}%)")

    # Single-run mode
    if args.once:
        ram_before = bytes_used()
        pct_before = current_ram_percent()
        logger.info(f"Single-run test: RAM {pct_before}% before")
        success = cleaner(logger)
        time.sleep(1)  # short wait for system to settle
        ram_after = bytes_used()
        pct_after = current_ram_percent()
        log_status(ram_before, ram_after, success)
        return 0

    # Continuous mode
    try:
        while True:
            pct = current_ram_percent()
            uptime = int(time.time() - start_time)
            logger.info(f"Uptime: {uptime}s - RAM usage: {pct}% (threshold {args.threshold}%)")
            if pct >= args.threshold:
                logger.info("Threshold exceeded -> attempting cleaning")
                before_bytes = bytes_used()
                success = cleaner(logger)
                time.sleep(1)  # small settle pause
                after_bytes = bytes_used()
                log_status(before_bytes, after_bytes, success)
                # cooldown
                time.sleep(args.after_clean)
            else:
                time.sleep(args.check_interval)
    except KeyboardInterrupt:
        logger.info("ram_cleaner interrupted by user (KeyboardInterrupt)")
    except Exception:
        logger.exception("ram_cleaner crashed")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
