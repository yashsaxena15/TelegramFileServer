# src/Backend/modules/torrent_manager.py

import os
import re
import time
import signal
import shutil
import logging
import asyncio
import subprocess
import threading
from typing import Optional, Dict, Any, List, Callable

from .priority_manager import priority_manager

logger = logging.getLogger("torrent_manager")

PUBLIC_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.moeking.me:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "udp://explodie.org:6969/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
    "udp://open.tracker.cl:1337/announce",
]

def bdecode(data: bytes) -> Any:
    """Fast pure-Python bencode decoder."""
    def decode_item(idx: int):
        char = data[idx:idx+1]
        if char == b'i':
            end = data.index(b'e', idx)
            return int(data[idx+1:end]), end + 1
        elif char == b'l':
            idx += 1
            res = []
            while data[idx:idx+1] != b'e':
                item, idx = decode_item(idx)
                res.append(item)
            return res, idx + 1
        elif char == b'd':
            idx += 1
            res = {}
            while data[idx:idx+1] != b'e':
                key, idx = decode_item(idx)
                val, idx = decode_item(idx)
                key_str = key.decode('utf-8', 'replace') if isinstance(key, bytes) else str(key)
                res[key_str] = val
            return res, idx + 1
        elif char.isdigit():
            colon = data.index(b':', idx)
            length = int(data[idx:colon])
            start = colon + 1
            end = start + length
            return data[start:end], end
        raise ValueError(f"Invalid bencode at offset {idx}: {char}")

    return decode_item(0)[0]

def parse_torrent_bytes(data: bytes) -> Dict[str, Any]:
    """
    Parses bencoded .torrent data to extract root name, files list, and total size.
    Handles both single-file and multi-file torrents.
    """
    decoded = bdecode(data)
    info = decoded.get("info", {})
    raw_name = info.get("name", b"")
    name = raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name or "Torrent")

    files = []
    if "files" in info and isinstance(info["files"], list):
        # Multi-file torrent
        for idx, f in enumerate(info["files"], start=1):
            path_parts = []
            for p in f.get("path", []):
                part_str = p.decode("utf-8", "replace") if isinstance(p, bytes) else str(p)
                path_parts.append(part_str)

            rel_path = os.path.join(*path_parts) if path_parts else f"file_{idx}"
            full_rel_path = os.path.join(name, rel_path) if name else rel_path
            f_size = int(f.get("length", 0))

            files.append({
                "index": idx,
                "name": path_parts[-1] if path_parts else f"file_{idx}",
                "rel_path": rel_path,
                "full_rel_path": full_rel_path,
                "size": f_size
            })
    else:
        # Single-file torrent
        f_size = int(info.get("length", 0))
        files.append({
            "index": 1,
            "name": name,
            "rel_path": name,
            "full_rel_path": name,
            "size": f_size
        })

    return {
        "name": name,
        "is_multi_file": "files" in info and isinstance(info["files"], list),
        "total_size": sum(f["size"] for f in files),
        "files": files
    }

class TorrentManager:
    """
    Manages BitTorrent downloads via aria2c.
    Provides metadata resolution for magnet links, selective single-file downloads,
    real-time progress monitoring, QoS priority pausing, and cancellation.
    """
    def __init__(self):
        self.tracker_arg = ",".join(PUBLIC_TRACKERS)

    def _get_base_aria_args(self) -> List[str]:
        return [
            "aria2c",
            "--enable-dht=true",
            "--enable-peer-exchange=true",
            "--bt-enable-lpd=true",
            "--bt-max-peers=60",
            "--max-connection-per-server=16",
            "--split=16",
            "--seed-time=0",
            "--file-allocation=none",
            "--max-overall-upload-limit=1K",
            f"--bt-tracker={self.tracker_arg}",
            "--dht-file-path=/app/cache/dht.dat",
            "--dht-file-path6=/app/cache/dht6.dat",
        ]

    def resolve_magnet_metadata(
        self,
        magnet_uri: str,
        work_dir: str,
        cancel_event: threading.Event,
        progress_cb: Optional[Callable[[str], None]] = None,
        timeout_seconds: int = 180
    ) -> str:
        """
        Connects to DHT/trackers, downloads only metadata, and saves the .torrent file.
        Returns the path to the saved .torrent file.
        """
        os.makedirs(work_dir, exist_ok=True)
        logger.info(f"Resolving magnet metadata in {work_dir}...")
        if progress_cb:
            progress_cb("Connecting to peers & fetching torrent metadata...")

        cmd = self._get_base_aria_args() + [
            "--bt-metadata-only=true",
            "--bt-save-metadata=true",
            f"--dir={work_dir}",
            "--summary-interval=1",
            magnet_uri
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        start_time = time.time()
        last_log = time.time()

        try:
            while proc.poll() is None:
                if cancel_event.is_set():
                    proc.terminate()
                    raise InterruptedError("Cancelled by user")

                if time.time() - start_time > timeout_seconds:
                    proc.terminate()
                    raise TimeoutError(f"Failed to find peers for magnet link within {timeout_seconds} seconds. Please verify the magnet has active seeders.")

                # Read stdout line if available
                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    line = line.strip()
                    if "CN:" in line:
                        cn_match = re.search(r'CN:(\d+)', line)
                        peers = cn_match.group(1) if cn_match else "0"
                        if time.time() - last_log >= 2.0:
                            if progress_cb:
                                progress_cb(f"Connecting to peers: {peers} active connection(s)...")
                            last_log = time.time()

                time.sleep(0.1)

            ret = proc.wait()
            if ret != 0 and not cancel_event.is_set():
                raise RuntimeError(f"aria2c failed to download metadata (exit code {ret})")

            # Find the saved .torrent file in work_dir
            for fname in os.listdir(work_dir):
                if fname.endswith(".torrent"):
                    return os.path.join(work_dir, fname)

            raise FileNotFoundError("aria2c finished but no .torrent metadata file was found in directory.")

        except Exception:
            if proc.poll() is None:
                proc.kill()
            raise

    def download_file_selective(
        self,
        torrent_file_path: str,
        file_index: int,
        work_dir: str,
        cancel_event: threading.Event,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_pause_cb: Optional[Callable[[bool], None]] = None
    ) -> None:
        """
        Downloads a specific file by its 1-based index from the torrent.
        Monitors progress, handles priority auto-pausing via SIGSTOP/SIGCONT, and checks cancel_event.
        """
        os.makedirs(work_dir, exist_ok=True)
        cmd = self._get_base_aria_args() + [
            f"--select-file={file_index}",
            f"--dir={work_dir}",
            "--summary-interval=1",
            torrent_file_path
        ]

        logger.info(f"Starting selective download for file #{file_index} into {work_dir}")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        is_currently_paused = False
        multipliers = {
            'B': 1,
            'KB': 1024,
            'KIB': 1024,
            'MB': 1024**2,
            'MIB': 1024**2,
            'GB': 1024**3,
            'GIB': 1024**3
        }

        try:
            while proc.poll() is None:
                if cancel_event.is_set():
                    proc.terminate()
                    raise InterruptedError("Cancelled by user")

                # QoS Priority Check: If user upload is active, freeze aria2c with SIGSTOP
                if priority_manager.is_user_upload_active():
                    if not is_currently_paused:
                        is_currently_paused = True
                        try:
                            os.kill(proc.pid, signal.SIGSTOP)
                        except Exception:
                            pass
                        if on_pause_cb:
                            on_pause_cb(True)

                    while priority_manager.is_user_upload_active() and not cancel_event.is_set():
                        time.sleep(1.0)

                    if cancel_event.is_set():
                        proc.terminate()
                        raise InterruptedError("Cancelled by user")

                    # Resume aria2c with SIGCONT
                    if is_currently_paused:
                        is_currently_paused = False
                        try:
                            os.kill(proc.pid, signal.SIGCONT)
                        except Exception:
                            pass
                        if on_pause_cb:
                            on_pause_cb(False)

                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    line = line.strip()
                    # Example line: "[#2089b0 400.0KiB/33.2MiB(1%) CN:18 SD:6 DL:4.2MiB ETA:4m20s]"
                    if "CN:" in line or "DL:" in line:
                        pct_m = re.search(r'\((\d+(?:\.\d+)?)%\)', line)
                        pct = float(pct_m.group(1)) if pct_m else 0.0

                        dl_m = re.search(r'DL:([0-9.]+)([KMGTP]?i?B)', line)
                        speed_bps = 0
                        if dl_m:
                            val = float(dl_m.group(1))
                            unit = dl_m.group(2).upper()
                            speed_bps = int(val * multipliers.get(unit, 1024**2))

                        cn_m = re.search(r'CN:(\d+)', line)
                        peers = int(cn_m.group(1)) if cn_m else 0

                        sd_m = re.search(r'SD:(\d+)', line)
                        seeders = int(sd_m.group(1)) if sd_m else 0

                        eta_m = re.search(r'ETA:([0-9a-zA-Z]+)', line)
                        eta_str = eta_m.group(1) if eta_m else ""

                        if progress_cb:
                            progress_cb({
                                "progress": pct,
                                "speed_bps": speed_bps,
                                "peers": peers,
                                "seeders": seeders,
                                "eta_str": eta_str,
                            })

                time.sleep(0.05)

            ret = proc.wait()
            if ret != 0 and not cancel_event.is_set():
                raise RuntimeError(f"aria2c file #{file_index} download exited with code {ret}")

        except Exception:
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            raise

# Singleton instance
torrent_manager = TorrentManager()
