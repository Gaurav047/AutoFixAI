"""Network guard for the sandbox user: block the cloud metadata service, private networks and localhost.

On cloud VMs the metadata service (169.254.169.254) can hand out the VM's service-account token to any
local process. Visitor code runs as the `sandbox` user, so before visitor repos are enabled the server
(root, in the container) installs owner-matched firewall rules for that user and then verifies them.
If the container isn't allowed to change the firewall (no NET_ADMIN), or the check fails, visitor repos
stay off. DNS stays open so `pip install` keeps working.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from dataclasses import dataclass

from .workspace import SANDBOX_USER

BLOCKED_V4 = ["169.254.0.0/16", "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"]
BLOCKED_V6 = ["fe80::/10", "fc00::/7", "::1/128"]


@dataclass
class GuardStatus:
    ok: bool
    reason: str


def _run(argv: list[str]) -> tuple[bool, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return p.returncode == 0, (p.stderr or p.stdout).strip()[:200]


def _rules(tool: str, ranges: list[str]) -> list[list[str]]:
    owner = ["-m", "owner", "--uid-owner", SANDBOX_USER]
    rules = [[tool, "-A", "OUTPUT", *owner, "-p", proto, "--dport", "53", "-j", "ACCEPT"] for proto in ("udp", "tcp")]
    rules += [[tool, "-A", "OUTPUT", *owner, "-d", net, "-j", "REJECT"] for net in ranges]
    return rules


def install(run=_run) -> GuardStatus:
    """Add the firewall rules. Returns ok only if every IPv4 rule was installed."""
    if not shutil.which("iptables"):
        return GuardStatus(False, "iptables is not installed in this image")
    for rule in _rules("iptables", BLOCKED_V4):
        ok, err = run(rule)
        if not ok:
            return GuardStatus(False, f"can't set firewall rules here (the container likely lacks NET_ADMIN): {err}")
    if shutil.which("ip6tables"):
        for rule in _rules("ip6tables", BLOCKED_V6):
            ok, err = run(rule)
            if not ok and socket.has_ipv6:
                return GuardStatus(False, f"IPv6 firewall rules failed: {err}")
    return GuardStatus(True, "firewall rules installed")


BLOCKED_EXIT = 3  # the probe's exit code when its connection was refused or timed out


def probe_localhost(port: int) -> int:
    """Exit code of a connection attempt to this server, made as the sandbox user."""
    probe = ("import socket,sys\n"
             "s=socket.socket();s.settimeout(3)\n"
             f"sys.exit(0 if s.connect_ex(('127.0.0.1',{port}))==0 else {BLOCKED_EXIT})")
    try:
        return subprocess.run(["setpriv", f"--reuid={SANDBOX_USER}", f"--regid={SANDBOX_USER}", "--clear-groups",
                               "--no-new-privs", "--", "python3", "-c", probe],
                              capture_output=True, timeout=20).returncode
    except (OSError, subprocess.TimeoutExpired):
        return -1


def verify(port: int, probe=probe_localhost) -> GuardStatus:
    """As the sandbox user, try to reach this server on localhost. The rules must make that fail.

    Localhost is a reliable probe: without the rules the connection always succeeds (the server is
    listening), so a refusal proves the owner-matched rules are active for the sandbox user. Anything
    other than a clean refusal (the probe couldn't run, say) counts as a failed check.
    """
    code = probe(port)
    if code == BLOCKED_EXIT:
        return GuardStatus(True, "the sandbox can't reach link-local, private or loopback addresses")
    if code == 0:
        return GuardStatus(False, "firewall check failed: the sandbox user could still reach localhost")
    return GuardStatus(False, f"firewall check couldn't run (exit code {code})")


def setup(port: int) -> GuardStatus:
    if os.geteuid() != 0:
        return GuardStatus(False, "the server isn't running as root, so it can't set firewall rules")
    status = install()
    if not status.ok:
        return status
    return verify(port)
