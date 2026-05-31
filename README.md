# 💾 Disk Space Maintenance & Monitor

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Version](https://img.shields.io/badge/Version-2.0.0-orange?style=flat-square)

A professional, cross-platform **disk space monitoring and maintenance script** written in Python. Monitor all mounted partitions, receive instant warnings when thresholds are exceeded, and generate detailed reports in multiple formats — all from a single script with zero mandatory dependencies.

> **Author:** Mahmoud Eltayeb

---

## ✨ Features

| Feature | Details |
|---|---|
| 📊 **Multi-partition monitoring** | Scans every mounted disk automatically |
| 🚦 **Three-tier alerts** | WARNING → CRITICAL → EMERGENCY thresholds |
| 📄 **Four report formats** | TXT · HTML · JSON · CSV |
| 📧 **Email notifications** | SMTP with TLS support |
| 🖥️ **Desktop notifications** | Native pop-ups on Linux, macOS, Windows |
| 🔍 **Large-file scanner** | Lists top-N files and directories consuming space |
| 🔄 **Rotating log files** | Auto-truncated logs with configurable retention |
| ⚙️ **JSON config file** | Full customization without touching source code |
| 🕐 **Cron / Task Scheduler** | Ready for automated scheduled runs |
| 🐍 **Zero hard dependencies** | Works with stdlib only (psutil optional) |

---

## 📂 Project Structure

```
disk-monitor/
│
├── disk_monitor.py          # Main script
├── disk_monitor_config.json # Auto-generated config (after --init-config)
│
├── reports/                 # Generated reports (auto-created)
│   ├── disk_report_YYYYMMDD_HHMMSS.txt
│   ├── disk_report_YYYYMMDD_HHMMSS.html
│   ├── disk_report_YYYYMMDD_HHMMSS.json
│   └── disk_report_YYYYMMDD_HHMMSS.csv
│
├── logs/                    # Rotating log files (auto-created)
│   └── disk_monitor.log
│
├── requirements.txt         # Optional dependencies
└── README.md
```

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/disk-monitor.git
cd disk-monitor
```

### 2. (Optional) Install psutil for richer partition info

```bash
pip install psutil
```

### 3. Run immediately

```bash
python disk_monitor.py
```

That's it. Reports land in `./reports/` and logs in `./logs/`.

---

## ⚙️ Configuration

### Generate a default config file

```bash
python disk_monitor.py --init-config
```

This creates `disk_monitor_config.json`. Edit it to suit your environment:

```json
{
    "thresholds": {
        "warning_percent": 75,
        "critical_percent": 90,
        "emergency_percent": 95
    },
    "notifications": {
        "enable_email": false,
        "enable_desktop": true,
        "enable_log": true,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "you@gmail.com",
        "smtp_password": "your_app_password",
        "email_from": "you@gmail.com",
        "email_to": ["admin@example.com"]
    },
    "report": {
        "output_dir": "./reports",
        "formats": ["txt", "html", "json", "csv"],
        "top_n_items": 20,
        "scan_paths": [],
        "exclude_paths": ["/proc", "/sys", "/dev", "/run"]
    },
    "logging": {
        "log_file": "./logs/disk_monitor.log",
        "log_level": "INFO",
        "max_log_size_mb": 10,
        "backup_count": 5
    }
}
```

### Configuration Reference

| Key | Default | Description |
|---|---|---|
| `thresholds.warning_percent` | `75` | % used that triggers WARNING |
| `thresholds.critical_percent` | `90` | % used that triggers CRITICAL |
| `thresholds.emergency_percent` | `95` | % used that triggers EMERGENCY |
| `notifications.enable_email` | `false` | Send email alerts |
| `notifications.enable_desktop` | `true` | Send desktop pop-up alerts |
| `report.output_dir` | `./reports` | Where to save reports |
| `report.formats` | `["txt","html","json","csv"]` | Which formats to generate |
| `report.top_n_items` | `20` | How many large files/dirs to list |
| `report.scan_paths` | `[]` | Specific paths to scan (empty = all) |
| `report.exclude_paths` | `/proc`, `/sys`… | Paths to skip |
| `logging.max_log_size_mb` | `10` | Max size before log rotation |
| `logging.backup_count` | `5` | Number of rotated log files kept |

---

## 🖥️ CLI Usage

```
usage: disk_monitor.py [-h] [--config CONFIG] [--warn WARN] [--crit CRIT]
                       [--emer EMER] [--top TOP]
                       [--formats {txt,html,json,csv} [...]]
                       [--output-dir OUTPUT_DIR] [--email] [--no-desktop]
                       [--init-config] [--quiet]
```

### Examples

```bash
# Basic run with all defaults
python disk_monitor.py

# Override thresholds on the fly
python disk_monitor.py --warn 70 --crit 85 --emer 95

# Generate only HTML and JSON reports
python disk_monitor.py --formats html json

# Show top 30 largest files/dirs
python disk_monitor.py --top 30

# Use a custom config file
python disk_monitor.py --config /etc/disk_monitor/prod.json

# Enable email alerts for this run
python disk_monitor.py --email

# Suppress console output (log file only)
python disk_monitor.py --quiet

# Save reports to a custom directory
python disk_monitor.py --output-dir /var/reports/disk

# Write the default config and exit
python disk_monitor.py --init-config
```

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | All partitions are OK |
| `1` | One or more WARNING partitions |
| `2` | One or more CRITICAL or EMERGENCY partitions |

This makes the script **CI/CD and shell-script friendly**:

```bash
python disk_monitor.py || echo "Disk issue detected! Exit code: $?"
```

---

## 📊 Sample Output

### Console / TXT Report

```
======================================================================
  DISK SPACE MONITORING REPORT
  Host      : myserver
  Platform  : Linux 5.15.0
  Generated : 2025-01-15 09:30:00
======================================================================

─── DISK PARTITIONS ──────────────────────────────────────────────────

  ✅ /  [OK]
     Device   : /dev/sda1  (ext4)
     Usage    : [████████░░░░░░░░░░░░░░░░░░░░░░]  28.3%
     Total    : 500.00 GB
     Used     : 141.50 GB
     Free     : 358.50 GB

  🟡 /home  [WARNING]
     Device   : /dev/sda2  (ext4)
     Usage    : [████████████████████████░░░░░░]  78.9%
     Total    : 1000.00 GB
     Used     : 789.00 GB
     Free     : 211.00 GB

  🔴 /var  [EMERGENCY]
     Device   : /dev/sdb1  (ext4)
     Usage    : [█████████████████████████████░]  96.1%
     Total    : 100.00 GB
     Used     : 96.10 GB
     Free     : 3.90 GB
```

### Alert Levels

| Emoji | Label | Default Threshold |
|---|---|---|
| ✅ | OK | < 75% |
| 🟡 | WARNING | ≥ 75% |
| 🟠 | CRITICAL | ≥ 90% |
| 🔴 | EMERGENCY | ≥ 95% |

---

## 🕐 Scheduling (Automated Runs)

### Linux / macOS — cron

```bash
# Open crontab
crontab -e

# Run every hour and email on failure
0 * * * * /usr/bin/python3 /opt/disk-monitor/disk_monitor.py --quiet

# Run daily at 7 AM and alert via email
0 7 * * * /usr/bin/python3 /opt/disk-monitor/disk_monitor.py --email --quiet
```

### Windows — Task Scheduler

```powershell
schtasks /create /tn "DiskMonitor" /tr "python C:\disk-monitor\disk_monitor.py" /sc HOURLY /f
```

---

## 📧 Email Setup (Gmail)

1. Enable **2-Step Verification** on your Google account.
2. Create an **App Password**: Google Account → Security → App Passwords.
3. Update `disk_monitor_config.json`:

```json
"notifications": {
    "enable_email": true,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "you@gmail.com",
    "smtp_password": "xxxx xxxx xxxx xxxx",
    "email_from": "you@gmail.com",
    "email_to": ["admin@yourcompany.com"]
}
```

---

## 📦 Optional Dependencies

The script runs with **zero dependencies**. Install `psutil` for richer partition metadata:

```bash
pip install psutil
```

**`requirements.txt`**
```
psutil>=5.9.0
```

---

## 🔒 Security Notes

- Store `disk_monitor_config.json` with restricted permissions if it contains SMTP credentials:
  ```bash
  chmod 600 disk_monitor_config.json
  ```
- Consider using environment variables for passwords in production:
  ```bash
  export SMTP_PASSWORD="your_password"
  ```

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add some feature'`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 👤 Author

**Mahmoud Eltayeb**


---

*If this project helped you, please consider giving it a ⭐ on GitHub!*
