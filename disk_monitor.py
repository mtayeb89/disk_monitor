#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              Disk Space Maintenance & Monitoring Script                      ║
║              Author  : Mahmoud Eltayeb                                       ║
║              Version : 2.0.0                                                 ║
║              License : MIT                                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

A professional, cross-platform disk space monitoring tool that:
  - Monitors disk usage across all mounted partitions
  - Sends warnings when thresholds are exceeded
  - Generates detailed HTML and plain-text reports
  - Supports email, desktop, and log-based notifications
  - Identifies the largest files/directories consuming space
  - Can run as a scheduled cron job / Windows Task
"""

import os
import sys
import shutil
import logging
import platform
import smtplib
import argparse
import json
import csv
import hashlib
import socket
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "thresholds": {
        "warning_percent": 75,
        "critical_percent": 90,
        "emergency_percent": 95,
    },
    "notifications": {
        "enable_email": False,
        "enable_desktop": True,
        "enable_log": True,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "email_from": "",
        "email_to": [],
    },
    "report": {
        "output_dir": "./reports",
        "formats": ["txt", "html", "json", "csv"],
        "top_n_items": 20,
        "scan_paths": [],           # Empty = scan all mounted partitions
        "exclude_paths": [
            "/proc", "/sys", "/dev", "/run",
            "/snap", "/boot/efi",
        ],
    },
    "logging": {
        "log_file": "./logs/disk_monitor.log",
        "log_level": "INFO",
        "max_log_size_mb": 10,
        "backup_count": 5,
    },
}

CONFIG_FILE = Path("disk_monitor_config.json")

# ──────────────────────────────────────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DiskEntry:
    """Represents usage statistics for a single partition."""
    device: str
    mountpoint: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float
    status: str = "OK"            # OK | WARNING | CRITICAL | EMERGENCY
    status_emoji: str = "✅"

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024 ** 3)

    @property
    def used_gb(self) -> float:
        return self.used_bytes / (1024 ** 3)

    @property
    def free_gb(self) -> float:
        return self.free_bytes / (1024 ** 3)

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "mountpoint": self.mountpoint,
            "fstype": self.fstype,
            "total_gb": round(self.total_gb, 2),
            "used_gb": round(self.used_gb, 2),
            "free_gb": round(self.free_gb, 2),
            "percent_used": round(self.percent_used, 1),
            "status": self.status,
        }


@dataclass
class FileEntry:
    """Represents a large file or directory found during scan."""
    path: str
    size_bytes: int
    is_dir: bool
    last_modified: str

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024 ** 3)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 ** 2)


@dataclass
class MonitorReport:
    """Full monitoring report produced by one run."""
    hostname: str
    platform: str
    timestamp: str
    disks: list = field(default_factory=list)
    top_files: list = field(default_factory=list)
    top_dirs: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Logger Setup
# ──────────────────────────────────────────────────────────────────────────────

def setup_logger(log_file: str, log_level: str, max_mb: int, backup: int) -> logging.Logger:
    """Configure rotating file + console logger."""
    import logging.handlers

    logger = logging.getLogger("DiskMonitor")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler
    fh = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_mb * 1024 * 1024,
        backupCount=backup,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ──────────────────────────────────────────────────────────────────────────────
# Config Loader
# ──────────────────────────────────────────────────────────────────────────────

def load_config(path: Optional[Path] = None) -> dict:
    """Load config from JSON file, merging with defaults."""
    config = DEFAULT_CONFIG.copy()
    target = path or CONFIG_FILE

    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            # Deep merge
            for section, values in user_config.items():
                if section in config and isinstance(config[section], dict):
                    config[section].update(values)
                else:
                    config[section] = values
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[WARN] Could not load config file ({exc}). Using defaults.")
    return config


def save_default_config():
    """Write a default config file so users can customise it."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    print(f"[INFO] Default config written to {CONFIG_FILE}")


# ──────────────────────────────────────────────────────────────────────────────
# Core Monitoring
# ──────────────────────────────────────────────────────────────────────────────

class DiskMonitor:
    """Main monitoring engine."""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.thr = config["thresholds"]
        self.exclude = set(config["report"].get("exclude_paths", []))

    # ── Partition discovery ──────────────────────────────────────────────────

    def _get_partitions(self) -> list:
        """Return a list of (device, mountpoint, fstype) for real disks."""
        partitions = []
        scan_paths = self.config["report"].get("scan_paths", [])

        if scan_paths:
            # User-specified paths
            for p in scan_paths:
                partitions.append(("custom", p, "unknown"))
            return partitions

        try:
            import psutil
            for part in psutil.disk_partitions(all=False):
                if any(part.mountpoint.startswith(ex) for ex in self.exclude):
                    continue
                partitions.append((part.device, part.mountpoint, part.fstype))
        except ImportError:
            # Fallback without psutil
            self.logger.warning("psutil not found – using shutil fallback (limited info).")
            if platform.system() == "Windows":
                import string
                for letter in string.ascii_uppercase:
                    mp = f"{letter}:\\"
                    if os.path.exists(mp):
                        partitions.append((mp, mp, "NTFS"))
            else:
                for line in Path("/proc/mounts").read_text().splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        dev, mp, fs = parts[0], parts[1], parts[2]
                        if fs in ("tmpfs", "devtmpfs", "sysfs", "proc", "cgroup"):
                            continue
                        if any(mp.startswith(ex) for ex in self.exclude):
                            continue
                        partitions.append((dev, mp, fs))
        return partitions

    # ── Disk usage ───────────────────────────────────────────────────────────

    def _classify(self, pct: float) -> tuple[str, str]:
        """Return (status_label, emoji) based on percent used."""
        if pct >= self.thr["emergency_percent"]:
            return "EMERGENCY", "🔴"
        if pct >= self.thr["critical_percent"]:
            return "CRITICAL", "🟠"
        if pct >= self.thr["warning_percent"]:
            return "WARNING", "🟡"
        return "OK", "✅"

    def collect_disk_info(self) -> list[DiskEntry]:
        """Collect usage data for every relevant partition."""
        entries = []
        for device, mountpoint, fstype in self._get_partitions():
            try:
                usage = shutil.disk_usage(mountpoint)
                pct = (usage.used / usage.total * 100) if usage.total > 0 else 0.0
                status, emoji = self._classify(pct)
                entry = DiskEntry(
                    device=device,
                    mountpoint=mountpoint,
                    fstype=fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent_used=round(pct, 2),
                    status=status,
                    status_emoji=emoji,
                )
                entries.append(entry)
                self.logger.info(
                    f"[{status}] {mountpoint:30s} {pct:5.1f}% used  "
                    f"({entry.free_gb:.1f} GB free / {entry.total_gb:.1f} GB total)"
                )
            except (PermissionError, FileNotFoundError, OSError) as exc:
                self.logger.warning(f"Skipping {mountpoint}: {exc}")
        return entries

    # ── Large-file scanner ───────────────────────────────────────────────────

    def find_top_items(self, paths: list[str], top_n: int = 20) -> tuple[list, list]:
        """Walk *paths* and return (top_n_files, top_n_dirs) by size."""
        files: list[FileEntry] = []
        dirs: list[FileEntry] = []

        scanned = 0
        for root_path in paths:
            try:
                for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
                    # Skip excluded dirs in-place
                    dirnames[:] = [
                        d for d in dirnames
                        if not any(
                            os.path.join(dirpath, d).startswith(ex)
                            for ex in self.exclude
                        )
                    ]
                    # Files
                    for fname in filenames:
                        fp = os.path.join(dirpath, fname)
                        try:
                            stat = os.stat(fp, follow_symlinks=False)
                            mtime = datetime.fromtimestamp(stat.st_mtime).strftime(
                                "%Y-%m-%d %H:%M"
                            )
                            files.append(
                                FileEntry(fp, stat.st_size, False, mtime)
                            )
                            scanned += 1
                        except OSError:
                            continue
                    # Directory itself
                    try:
                        stat = os.stat(dirpath, follow_symlinks=False)
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                        # Approximate dir size as sum of direct children
                        dir_size = sum(
                            os.path.getsize(os.path.join(dirpath, f))
                            for f in filenames
                            if os.path.isfile(os.path.join(dirpath, f))
                        )
                        dirs.append(FileEntry(dirpath, dir_size, True, mtime))
                    except OSError:
                        continue
            except PermissionError:
                self.logger.warning(f"Permission denied scanning {root_path}")

        self.logger.info(f"Scanned {scanned:,} files across {len(paths)} path(s).")

        top_files = sorted(files, key=lambda x: x.size_bytes, reverse=True)[:top_n]
        top_dirs = sorted(dirs, key=lambda x: x.size_bytes, reverse=True)[:top_n]
        return top_files, top_dirs

    # ── Build report ─────────────────────────────────────────────────────────

    def build_report(self) -> MonitorReport:
        """Run full collection and return a MonitorReport."""
        self.logger.info("=" * 70)
        self.logger.info("Disk Space Monitoring — Starting Run")
        self.logger.info("=" * 70)

        disks = self.collect_disk_info()
        alerts = [d for d in disks if d.status != "OK"]

        scan_paths = [
            d.mountpoint for d in disks
            if d.status != "OK"
        ] or [d.mountpoint for d in disks]

        top_n = self.config["report"].get("top_n_items", 20)
        top_files, top_dirs = self.find_top_items(scan_paths, top_n)

        summary = {
            "total_partitions": len(disks),
            "ok_count": sum(1 for d in disks if d.status == "OK"),
            "warning_count": sum(1 for d in disks if d.status == "WARNING"),
            "critical_count": sum(1 for d in disks if d.status == "CRITICAL"),
            "emergency_count": sum(1 for d in disks if d.status == "EMERGENCY"),
            "total_space_gb": round(sum(d.total_gb for d in disks), 2),
            "used_space_gb": round(sum(d.used_gb for d in disks), 2),
            "free_space_gb": round(sum(d.free_gb for d in disks), 2),
        }

        report = MonitorReport(
            hostname=socket.gethostname(),
            platform=f"{platform.system()} {platform.release()}",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            disks=disks,
            top_files=top_files,
            top_dirs=top_dirs,
            alerts=alerts,
            summary=summary,
        )

        self.logger.info(
            f"Summary → {summary['total_partitions']} partitions | "
            f"⚠ {summary['warning_count']} warnings | "
            f"🔴 {summary['critical_count']} critical | "
            f"💾 {summary['free_space_gb']} GB free"
        )
        return report


# ──────────────────────────────────────────────────────────────────────────────
# Report Writers
# ──────────────────────────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 30) -> str:
    """ASCII progress bar."""
    filled = int(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:5.1f}%"


def write_txt_report(report: MonitorReport, out_dir: Path) -> Path:
    """Plain-text report."""
    lines = [
        "=" * 72,
        "  DISK SPACE MONITORING REPORT",
        f"  Host      : {report.hostname}",
        f"  Platform  : {report.platform}",
        f"  Generated : {report.timestamp}",
        "=" * 72,
        "",
        "─── DISK PARTITIONS ───────────────────────────────────────────────────",
    ]
    for d in report.disks:
        lines += [
            f"",
            f"  {d.status_emoji} {d.mountpoint}  [{d.status}]",
            f"     Device   : {d.device}  ({d.fstype})",
            f"     Usage    : {_bar(d.percent_used)}",
            f"     Total    : {d.total_gb:.2f} GB",
            f"     Used     : {d.used_gb:.2f} GB",
            f"     Free     : {d.free_gb:.2f} GB",
        ]

    lines += [
        "",
        "─── SUMMARY ────────────────────────────────────────────────────────────",
        f"  Partitions : {report.summary['total_partitions']}",
        f"  OK         : {report.summary['ok_count']}",
        f"  Warning    : {report.summary['warning_count']}",
        f"  Critical   : {report.summary['critical_count']}",
        f"  Emergency  : {report.summary['emergency_count']}",
        f"  Total Space: {report.summary['total_space_gb']} GB",
        f"  Free Space : {report.summary['free_space_gb']} GB",
        "",
        "─── TOP FILES BY SIZE ──────────────────────────────────────────────────",
    ]
    for i, f in enumerate(report.top_files, 1):
        size = f"{f.size_gb:.3f} GB" if f.size_gb >= 1 else f"{f.size_mb:.1f} MB"
        lines.append(f"  {i:3}. {size:>10}  {f.path}")

    lines += [
        "",
        "─── TOP DIRECTORIES BY SIZE ────────────────────────────────────────────",
    ]
    for i, d in enumerate(report.top_dirs, 1):
        size = f"{d.size_gb:.3f} GB" if d.size_gb >= 1 else f"{d.size_mb:.1f} MB"
        lines.append(f"  {i:3}. {size:>10}  {d.path}")

    lines += ["", "=" * 72, "  End of Report", "=" * 72]

    out_path = out_dir / f"disk_report_{datetime.now():%Y%m%d_%H%M%S}.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_html_report(report: MonitorReport, out_dir: Path) -> Path:
    """Self-contained HTML report with colour-coded status."""
    status_colors = {
        "OK":        ("#22c55e", "#f0fdf4"),
        "WARNING":   ("#f59e0b", "#fffbeb"),
        "CRITICAL":  ("#ef4444", "#fef2f2"),
        "EMERGENCY": ("#7c3aed", "#faf5ff"),
    }

    def disk_rows():
        rows = []
        for d in report.disks:
            color, bg = status_colors.get(d.status, ("#64748b", "#f8fafc"))
            bar_w = int(d.percent_used)
            bar_color = color
            rows.append(f"""
        <tr style="background:{bg}">
          <td><strong>{d.mountpoint}</strong><br><small style="color:#64748b">{d.device} · {d.fstype}</small></td>
          <td>
            <div class="bar-wrap">
              <div class="bar-fill" style="width:{bar_w}%;background:{bar_color}"></div>
            </div>
            <small>{d.percent_used:.1f}%</small>
          </td>
          <td>{d.total_gb:.2f} GB</td>
          <td>{d.used_gb:.2f} GB</td>
          <td>{d.free_gb:.2f} GB</td>
          <td><span class="badge" style="background:{color}">{d.status_emoji} {d.status}</span></td>
        </tr>""")
        return "\n".join(rows)

    def file_rows(items, is_dir=False):
        rows = []
        for i, item in enumerate(items, 1):
            size = f"{item.size_gb:.3f} GB" if item.size_gb >= 1 else f"{item.size_mb:.1f} MB"
            kind = "📁" if is_dir else "📄"
            rows.append(f"""
        <tr>
          <td>{i}</td>
          <td>{kind} <code style="font-size:0.8em">{item.path}</code></td>
          <td style="font-weight:600">{size}</td>
          <td>{item.last_modified}</td>
        </tr>""")
        return "\n".join(rows)

    s = report.summary
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Disk Monitor Report — {report.timestamp}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}}
    h1{{font-size:1.8rem;font-weight:700;color:#f8fafc;margin-bottom:.25rem}}
    h2{{font-size:1.1rem;font-weight:600;color:#94a3b8;margin:2rem 0 .75rem;text-transform:uppercase;letter-spacing:.1em}}
    .meta{{color:#64748b;font-size:.85rem;margin-bottom:2rem}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:2rem}}
    .card{{background:#1e293b;border-radius:12px;padding:1.25rem;text-align:center;border:1px solid #334155}}
    .card-val{{font-size:2rem;font-weight:800;line-height:1}}
    .card-lbl{{font-size:.75rem;color:#94a3b8;margin-top:.25rem;text-transform:uppercase}}
    .ok{{color:#22c55e}}.warn{{color:#f59e0b}}.crit{{color:#ef4444}}.emer{{color:#a78bfa}}
    table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:12px;overflow:hidden;margin-bottom:2rem}}
    th{{background:#0f172a;padding:.75rem 1rem;text-align:left;font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b}}
    td{{padding:.7rem 1rem;border-top:1px solid #334155;font-size:.875rem;vertical-align:middle}}
    tr:hover td{{background:#263347}}
    .bar-wrap{{background:#334155;border-radius:999px;height:8px;width:100%;min-width:80px;overflow:hidden}}
    .bar-fill{{height:100%;border-radius:999px;transition:width .3s}}
    .badge{{display:inline-block;padding:.25rem .6rem;border-radius:999px;color:#fff;font-size:.75rem;font-weight:600}}
    code{{color:#7dd3fc;background:#0f172a;padding:.1rem .35rem;border-radius:4px;word-break:break-all}}
    .footer{{text-align:center;color:#475569;font-size:.8rem;margin-top:3rem;padding-top:1.5rem;border-top:1px solid #1e293b}}
  </style>
</head>
<body>
  <h1>💾 Disk Space Monitoring Report</h1>
  <p class="meta">Host: <strong>{report.hostname}</strong> &nbsp;·&nbsp; Platform: {report.platform} &nbsp;·&nbsp; Generated: {report.timestamp}</p>

  <div class="cards">
    <div class="card"><div class="card-val ok">{s['ok_count']}</div><div class="card-lbl">OK</div></div>
    <div class="card"><div class="card-val warn">{s['warning_count']}</div><div class="card-lbl">Warning</div></div>
    <div class="card"><div class="card-val crit">{s['critical_count']}</div><div class="card-lbl">Critical</div></div>
    <div class="card"><div class="card-val emer">{s['emergency_count']}</div><div class="card-lbl">Emergency</div></div>
    <div class="card"><div class="card-val" style="color:#38bdf8">{s['total_space_gb']}</div><div class="card-lbl">Total GB</div></div>
    <div class="card"><div class="card-val" style="color:#a78bfa">{s['free_space_gb']}</div><div class="card-lbl">Free GB</div></div>
  </div>

  <h2>Partitions</h2>
  <table>
    <thead><tr><th>Mount Point</th><th>Usage</th><th>Total</th><th>Used</th><th>Free</th><th>Status</th></tr></thead>
    <tbody>{disk_rows()}</tbody>
  </table>

  <h2>Top {len(report.top_files)} Largest Files</h2>
  <table>
    <thead><tr><th>#</th><th>Path</th><th>Size</th><th>Modified</th></tr></thead>
    <tbody>{file_rows(report.top_files)}</tbody>
  </table>

  <h2>Top {len(report.top_dirs)} Largest Directories</h2>
  <table>
    <thead><tr><th>#</th><th>Path</th><th>Size</th><th>Modified</th></tr></thead>
    <tbody>{file_rows(report.top_dirs, is_dir=True)}</tbody>
  </table>

  <div class="footer">Generated by Disk Monitor v2.0.0 · Mahmoud Eltayeb</div>
</body>
</html>"""

    out_path = out_dir / f"disk_report_{datetime.now():%Y%m%d_%H%M%S}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def write_json_report(report: MonitorReport, out_dir: Path) -> Path:
    """Machine-readable JSON report."""
    data = {
        "hostname": report.hostname,
        "platform": report.platform,
        "timestamp": report.timestamp,
        "summary": report.summary,
        "disks": [d.to_dict() for d in report.disks],
        "top_files": [
            {"path": f.path, "size_mb": round(f.size_mb, 2), "modified": f.last_modified}
            for f in report.top_files
        ],
        "top_dirs": [
            {"path": d.path, "size_mb": round(d.size_mb, 2), "modified": d.last_modified}
            for d in report.top_dirs
        ],
        "alerts": [d.to_dict() for d in report.alerts],
    }
    out_path = out_dir / f"disk_report_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def write_csv_report(report: MonitorReport, out_dir: Path) -> Path:
    """CSV report for spreadsheet import."""
    out_path = out_dir / f"disk_report_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["device", "mountpoint", "fstype",
                        "total_gb", "used_gb", "free_gb",
                        "percent_used", "status"],
        )
        writer.writeheader()
        for d in report.disks:
            writer.writerow(d.to_dict())
    return out_path


def save_reports(report: MonitorReport, config: dict, logger: logging.Logger) -> list[Path]:
    """Dispatch to each enabled report format."""
    out_dir = Path(config["report"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = config["report"].get("formats", ["txt", "html"])
    saved = []

    if "txt" in formats:
        p = write_txt_report(report, out_dir)
        saved.append(p)
        logger.info(f"TXT report → {p}")

    if "html" in formats:
        p = write_html_report(report, out_dir)
        saved.append(p)
        logger.info(f"HTML report → {p}")

    if "json" in formats:
        p = write_json_report(report, out_dir)
        saved.append(p)
        logger.info(f"JSON report → {p}")

    if "csv" in formats:
        p = write_csv_report(report, out_dir)
        saved.append(p)
        logger.info(f"CSV report → {p}")

    return saved


# ──────────────────────────────────────────────────────────────────────────────
# Notifications
# ──────────────────────────────────────────────────────────────────────────────

def send_email_alert(report: MonitorReport, config: dict, logger: logging.Logger):
    """Send an HTML email for any WARNING/CRITICAL/EMERGENCY disks."""
    notif = config["notifications"]
    if not notif.get("enable_email") or not report.alerts:
        return

    subject = (
        f"🚨 Disk Alert on {report.hostname} — "
        f"{len(report.alerts)} partition(s) need attention"
    )
    body_lines = [f"<b>Host:</b> {report.hostname}<br>",
                  f"<b>Time:</b> {report.timestamp}<br><br>",
                  "<table border='1' cellpadding='6' style='border-collapse:collapse'>",
                  "<tr><th>Mount</th><th>Used%</th><th>Free GB</th><th>Status</th></tr>"]
    for d in report.alerts:
        body_lines.append(
            f"<tr><td>{d.mountpoint}</td>"
            f"<td>{d.percent_used:.1f}%</td>"
            f"<td>{d.free_gb:.2f}</td>"
            f"<td>{d.status_emoji} {d.status}</td></tr>"
        )
    body_lines.append("</table>")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = notif["email_from"]
    msg["To"] = ", ".join(notif["email_to"])
    msg.attach(MIMEText("\n".join(body_lines), "html"))

    try:
        with smtplib.SMTP(notif["smtp_host"], notif["smtp_port"]) as server:
            server.starttls()
            server.login(notif["smtp_user"], notif["smtp_password"])
            server.sendmail(notif["email_from"], notif["email_to"], msg.as_string())
        logger.info(f"Email alert sent to: {notif['email_to']}")
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")


def send_desktop_notification(report: MonitorReport, config: dict, logger: logging.Logger):
    """Trigger a native OS desktop notification for alerts."""
    if not config["notifications"].get("enable_desktop") or not report.alerts:
        return

    title = f"Disk Alert — {report.hostname}"
    msgs = [f"{d.status_emoji} {d.mountpoint}: {d.percent_used:.1f}% used ({d.status})"
            for d in report.alerts]
    body = "\n".join(msgs)

    system = platform.system()
    try:
        if system == "Darwin":
            os.system(
                f'osascript -e \'display notification "{body}" with title "{title}"\''
            )
        elif system == "Linux":
            os.system(f'notify-send "{title}" "{body}"')
        elif system == "Windows":
            from ctypes import windll
            windll.user32.MessageBoxW(0, body, title, 0x30)
        logger.info("Desktop notification sent.")
    except Exception as exc:
        logger.warning(f"Desktop notification failed: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Disk Space Maintenance & Monitoring Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python disk_monitor.py                        # Run with default config
  python disk_monitor.py --config my.json       # Custom config file
  python disk_monitor.py --warn 70 --crit 85    # Override thresholds
  python disk_monitor.py --formats html json    # Only HTML + JSON output
  python disk_monitor.py --init-config          # Write default config file
  python disk_monitor.py --top 30               # Show 30 largest files
  python disk_monitor.py --email                # Enable email notifications
        """,
    )
    parser.add_argument("--config", type=Path, help="Path to JSON config file")
    parser.add_argument("--warn", type=float, help="Warning threshold %%  (default 75)")
    parser.add_argument("--crit", type=float, help="Critical threshold %% (default 90)")
    parser.add_argument("--emer", type=float, help="Emergency threshold %% (default 95)")
    parser.add_argument("--top", type=int, default=None, help="Top N files/dirs to list")
    parser.add_argument("--formats", nargs="+",
                        choices=["txt", "html", "json", "csv"],
                        help="Report formats to generate")
    parser.add_argument("--output-dir", type=Path, help="Directory for reports")
    parser.add_argument("--email", action="store_true", help="Enable email notifications")
    parser.add_argument("--no-desktop", action="store_true",
                        help="Disable desktop notifications")
    parser.add_argument("--init-config", action="store_true",
                        help="Write a default config.json and exit")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress console output (log file only)")
    return parser.parse_args()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    if args.init_config:
        save_default_config()
        sys.exit(0)

    config = load_config(args.config)

    # CLI overrides
    if args.warn:
        config["thresholds"]["warning_percent"] = args.warn
    if args.crit:
        config["thresholds"]["critical_percent"] = args.crit
    if args.emer:
        config["thresholds"]["emergency_percent"] = args.emer
    if args.top:
        config["report"]["top_n_items"] = args.top
    if args.formats:
        config["report"]["formats"] = args.formats
    if args.output_dir:
        config["report"]["output_dir"] = str(args.output_dir)
    if args.email:
        config["notifications"]["enable_email"] = True
    if args.no_desktop:
        config["notifications"]["enable_desktop"] = False

    log_cfg = config["logging"]
    logger = setup_logger(
        log_cfg["log_file"],
        log_cfg["log_level"],
        log_cfg.get("max_log_size_mb", 10),
        log_cfg.get("backup_count", 5),
    )

    if args.quiet:
        logger.handlers = [h for h in logger.handlers
                           if isinstance(h, logging.FileHandler)]

    monitor = DiskMonitor(config, logger)
    report = monitor.build_report()

    saved = save_reports(report, config, logger)
    send_email_alert(report, config, logger)
    send_desktop_notification(report, config, logger)

    # Exit code: 0 = all OK, 1 = warnings, 2 = critical/emergency
    if report.summary["emergency_count"] or report.summary["critical_count"]:
        sys.exit(2)
    if report.summary["warning_count"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
