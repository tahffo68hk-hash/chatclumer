#!/usr/bin/env python3
"""Start and stop the chat room as one process session.

The marker is placed only on the launched process, after setsid. Stop kills
that process and its descendants. It never signals whatever else is listening.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

MARKER = "CHAT_ROOM_RUN"


def listener_pid(port: int) -> int | None:
    inodes: set[str] = set()
    hex_port = f":{port:04X}"
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(name).read_text().splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 10 or parts[3] != "0A":
                continue
            local_port = parts[1].rsplit(":", 1)[-1].upper()
            if local_port == hex_port[1:]:
                inodes.add(parts[9])
    if not inodes:
        return None
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in inodes:
                return int(entry.name)
    return None


def cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip()


def has_marker(pid: int, token: str) -> bool:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return False
    wanted = f"{MARKER}={token}".encode()
    return wanted in raw.split(b"\0")


def ppid(pid: int) -> int:
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return 0
    for line in text.splitlines():
        if line.startswith("PPid:"):
            return int(line.split()[1])
    return 0


def owns(pid: int, token: str) -> bool:
    """True when this pid or one of its ancestors carries the launch marker."""
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        if has_marker(pid, token):
            return True
        pid = ppid(pid)
    return False


def child_map() -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / "status").read_text()
        except OSError:
            continue
        ppid = None
        for line in text.splitlines():
            if line.startswith("PPid:"):
                ppid = int(line.split()[1])
                break
        if ppid is not None:
            children.setdefault(ppid, []).append(int(entry.name))
    return children


def descendants(roots: list[int]) -> list[int]:
    children = child_map()
    seen = set(roots)
    stack = list(roots)
    while stack:
        parent = stack.pop()
        for child in children.get(parent, []):
            if child not in seen and child > 1:
                seen.add(child)
                stack.append(child)
    return sorted(seen, key=lambda pid: pid, reverse=True)


def marked_pids(token: str) -> list[int]:
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid > 1 and has_marker(pid, token):
            found.append(pid)
    return found


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def launch(pidfile: Path, logfile: Path, cwd: Path, token: str, cmd: list[str]) -> int:
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    logfile.parent.mkdir(parents=True, exist_ok=True)
    if pidfile.exists():
        pidfile.unlink()
    child = os.fork()
    if child > 0:
        for _ in range(100):
            if pidfile.exists() and pidfile.stat().st_size > 0:
                return 0
            waited, _ = os.waitpid(child, os.WNOHANG)
            if waited == child:
                return 1
            time.sleep(0.05)
        return 1
    os.setsid()
    os.chdir(cwd)
    os.environ[MARKER] = token
    pidfile.write_text(str(os.getpid()))
    log_fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    if log_fd > 2:
        os.close(log_fd)
    devnull = os.open("/dev/null", os.O_RDONLY)
    os.dup2(devnull, 0)
    if devnull > 2:
        os.close(devnull)
    try:
        os.execvp(cmd[0], cmd)
    except OSError as exc:
        sys.stderr.write(f"无法执行 {' '.join(cmd)}: {exc}\n")
        os._exit(127)


def signal_pids(pids: list[int], sig: int) -> None:
    for pid in pids:
        if pid <= 1:
            continue
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            continue


def stop(token: str, ports: list[int]) -> int:
    roots = marked_pids(token) if token else []
    targets = descendants(roots) if roots else []
    if targets:
        signal_pids(targets, 15)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not any(alive(pid) for pid in targets):
                break
            time.sleep(0.1)
        remaining = [pid for pid in targets if alive(pid)]
        if remaining:
            signal_pids(remaining, 9)
            time.sleep(0.2)
    busy = False
    for port in ports:
        pid = listener_pid(port)
        if pid is None:
            continue
        busy = True
        print(
            f"端口 {port} 仍由 PID {pid} 占用（{cmdline(pid) or '无法读取命令'}）。"
            "停止脚本没有结束该进程。",
            file=sys.stderr,
        )
    if busy:
        return 1
    print("stopped")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: roomctl.py listener|has-marker|launch|stop", file=sys.stderr)
        return 2
    command = argv[1]
    if command == "listener":
        pid = listener_pid(int(argv[2]))
        if pid is not None:
            print(pid)
        return 0
    if command == "cmdline":
        print(cmdline(int(argv[2])))
        return 0
    if command == "has-marker":
        return 0 if has_marker(int(argv[2]), argv[3]) else 1
    if command == "owns":
        return 0 if owns(int(argv[2]), argv[3]) else 1
    if command == "launch":
        # launch --pidfile P --logfile L --cwd C --token T -- cmd...
        args = argv[2:]
        values: dict[str, str] = {}
        if "--" not in args:
            print("launch 需要 -- 命令", file=sys.stderr)
            return 2
        split = args.index("--")
        flags = args[:split]
        cmd = args[split + 1 :]
        index = 0
        while index < len(flags):
            values[flags[index][2:]] = flags[index + 1]
            index += 2
        return launch(
            Path(values["pidfile"]),
            Path(values["logfile"]),
            Path(values["cwd"]),
            values["token"],
            cmd,
        )
    if command == "stop":
        token = ""
        ports: list[int] = []
        args = argv[2:]
        index = 0
        while index < len(args):
            if args[index] == "--token":
                token = args[index + 1]
                index += 2
            elif args[index] == "--token-file":
                path = Path(args[index + 1])
                token = path.read_text().strip() if path.exists() else ""
                index += 2
            elif args[index] == "--port":
                ports.append(int(args[index + 1]))
                index += 2
            else:
                print(f"未知参数 {args[index]}", file=sys.stderr)
                return 2
        return stop(token, ports)
    print(f"未知命令 {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
