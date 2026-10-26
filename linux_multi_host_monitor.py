#!/usr/bin/env python3
 
import subprocess
import concurrent.futures
from datetime import datetime
 
# ============================================================
# CONFIGURATION
# ============================================================
 
HOSTS = [
    "host01",
    "host02",
    "host03",
    # "192.168.1.10",
]
 
# Services checked on every server.
# Change these to match your environment.
SERVICES = [
    "sshd",
    "keepalived",
    # "nginx",
    # "vpp",
    # "frr",
    # "sysrepod",
    # "netopeer2-server",
]
 
SSH_USER = "monitor"
 
MEMORY_WARNING = 80
MEMORY_CRITICAL = 90
 
SWAP_WARNING = 70
SWAP_CRITICAL = 90
 
DISK_WARNING = 80
DISK_CRITICAL = 90
 
SSH_TIMEOUT = 8
MAX_WORKERS = 10
 
 
# ============================================================
# SSH
# ============================================================
 
def ssh_command(host, command):
    """Run command on a remote host using SSH."""
 
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={SSH_TIMEOUT}",
                "-o", "StrictHostKeyChecking=accept-new",
                f"{SSH_USER}@{host}",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT + 5,
        )
 
        if result.returncode == 0:
            return result.stdout.strip()
 
        return None
 
    except (subprocess.TimeoutExpired, OSError):
        return None
 
 
# ============================================================
# HOST REACHABILITY
# ============================================================
 
def ping_host(host):
    """Check whether a host responds to ICMP."""
 
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
 
        return result.returncode == 0
 
    except (subprocess.TimeoutExpired, OSError):
        return False
 
 
# ============================================================
# THRESHOLD STATUS
# ============================================================
 
def threshold_status(value, warning, critical):
    if value >= critical:
        return "CRITICAL"
 
    if value >= warning:
        return "WARNING"
 
    return "OK"
 
 
# ============================================================
# MEMORY
# ============================================================
 
def get_memory(host):
 
    output = ssh_command(
        host,
        "free | awk '/Mem:/ {print $2,$3} /Swap:/ {print $2,$3}'"
    )
 
    if not output:
        return None
 
    try:
        lines = output.splitlines()
 
        mem_total, mem_used = map(float, lines[0].split())
        swap_total, swap_used = map(float, lines[1].split())
 
        memory_percent = (
            (mem_used / mem_total) * 100 if mem_total > 0 else 0
        )
 
        swap_percent = (
            (swap_used / swap_total) * 100 if swap_total > 0 else 0
        )
 
        return {
            "memory": round(memory_percent, 1),
            "swap": round(swap_percent, 1),
        }
 
    except (ValueError, IndexError):
        return None
 
 
# ============================================================
# UPTIME
# ============================================================
 
def get_uptime(host):
 
    output = ssh_command(host, "uptime -p")
 
    return output if output else "Unknown"
 
 
# ============================================================
# LOAD
# ============================================================
 
def get_load(host):
 
    output = ssh_command(host, "cat /proc/loadavg")
 
    if not output:
        return "Unknown"
 
    values = output.split()
 
    if len(values) < 3:
        return "Unknown"
 
    return f"{values[0]} {values[1]} {values[2]}"
 
 
# ============================================================
# DISK
# ============================================================
 
def get_disk(host):
 
    command = """
    df -P -x tmpfs -x devtmpfs |
    awk 'NR>1 {gsub("%","",$5); print $6 ":" $5}'
    """
 
    output = ssh_command(host, command)
 
    if not output:
        return []
 
    disks = []
 
    for line in output.splitlines():
 
        try:
            mount, percentage = line.rsplit(":", 1)
 
            value = int(percentage)
 
            disks.append({
                "mount": mount,
                "usage": value,
                "status": threshold_status(
                    value,
                    DISK_WARNING,
                    DISK_CRITICAL
                ),
            })
 
        except ValueError:
            continue
 
    return disks
 
 
# ============================================================
# SYSTEMD SERVICES
# ============================================================
 
def get_services(host):
 
    results = {}
 
    for service in SERVICES:
 
        command = (
            f"systemctl is-active {service} 2>/dev/null || true"
        )
 
        output = ssh_command(host, command)
 
        if not output:
            status = "UNKNOWN"
        else:
            status = output.strip().upper()
 
        results[service] = status
 
    return results
 
 
# ============================================================
# MONITOR SINGLE HOST
# ============================================================
 
def monitor_host(host):
 
    result = {
        "host": host,
        "ping": False,
        "ssh": False,
        "memory": None,
        "swap": None,
        "uptime": "Unknown",
        "load": "Unknown",
        "services": {},
        "disks": [],
    }
 
    # ICMP test
    result["ping"] = ping_host(host)
 
    # Test SSH independently.
    # A server may block ICMP while SSH still works.
    ssh_test = ssh_command(host, "echo OK")
 
    if ssh_test != "OK":
        return result
 
    result["ssh"] = True
 
    memory = get_memory(host)
 
    if memory:
        result["memory"] = memory["memory"]
        result["swap"] = memory["swap"]
 
    result["uptime"] = get_uptime(host)
    result["load"] = get_load(host)
    result["services"] = get_services(host)
    result["disks"] = get_disk(host)
 
    return result
 
 
# ============================================================
# DISPLAY
# ============================================================
 
def print_result(result):
 
    host = result["host"]
 
    print("\n" + "=" * 70)
    print(f"HOST: {host}")
    print("=" * 70)
 
    print(
        f"PING : {'UP' if result['ping'] else 'DOWN'}"
    )
 
    print(
        f"SSH  : {'UP' if result['ssh'] else 'DOWN'}"
    )
 
    if not result["ssh"]:
        print("Unable to collect Linux metrics.")
        return
 
    # Memory
 
    if result["memory"] is not None:
 
        status = threshold_status(
            result["memory"],
            MEMORY_WARNING,
            MEMORY_CRITICAL,
        )
 
        print(
            f"Memory : {result['memory']}% [{status}]"
        )
 
    else:
        print("Memory : Unknown")
 
    # Swap
 
    if result["swap"] is not None:
 
        status = threshold_status(
            result["swap"],
            SWAP_WARNING,
            SWAP_CRITICAL,
        )
 
        print(
            f"Swap   : {result['swap']}% [{status}]"
        )
 
    else:
        print("Swap   : Unknown")
 
    print(f"Uptime : {result['uptime']}")
    print(f"Load   : {result['load']}")
 
    # Services
 
    print("\nServices:")
 
    for service, status in result["services"].items():
 
        marker = "OK" if status == "ACTIVE" else "ALERT"
 
        print(
            f"  {service:<25} "
            f"{status:<12} "
            f"[{marker}]"
        )
 
    # Filesystems
 
    print("\nFilesystem:")
 
    for disk in result["disks"]:
 
        print(
            f"  {disk['mount']:<25} "
            f"{disk['usage']:>3}% "
            f"[{disk['status']}]"
        )
 
 
# ============================================================
# MAIN
# ============================================================
 
def main():
 
    print("=" * 70)
    print("LINUX MULTI-HOST HEALTH MONITOR")
    print("=" * 70)
 
    print(
        "Started:",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
 
    print(f"Monitoring {len(HOSTS)} hosts")
 
    results = []
 
    # Run hosts in parallel instead of checking sequentially.
 
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:
 
        futures = {
            executor.submit(monitor_host, host): host
            for host in HOSTS
        }
 
        for future in concurrent.futures.as_completed(futures):
 
            host = futures[future]
 
            try:
                results.append(future.result())
 
            except Exception as exc:
 
                results.append({
                    "host": host,
                    "ping": False,
                    "ssh": False,
                    "memory": None,
                    "swap": None,
                    "uptime": "Unknown",
                    "load": "Unknown",
                    "services": {},
                    "disks": [],
                })
 
                print(f"{host}: monitoring error: {exc}")
 
    # Keep display in configured host order.
 
    result_map = {
        result["host"]: result
        for result in results
    }
 
    for host in HOSTS:
 
        if host in result_map:
            print_result(result_map[host])
 
    print("\n" + "=" * 70)
    print("Monitoring completed")
    print("=" * 70)
 
 
if __name__ == "__main__":
    main()
