"""The network guard must only report success when the rules are installed AND verified."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from autofix import netguard  # noqa: E402


def test_rules_allow_dns_first_then_reject_metadata_private_and_loopback():
    rules = netguard._rules("iptables", netguard.BLOCKED_V4)
    assert all("--uid-owner" in r and "sandbox" in r for r in rules)
    assert rules[0][-1] == "ACCEPT" and rules[1][-1] == "ACCEPT"   # DNS before the rejects
    rejected = {r[r.index("-d") + 1] for r in rules if r[-1] == "REJECT"}
    assert {"169.254.0.0/16", "127.0.0.0/8", "10.0.0.0/8"} <= rejected


def test_install_fails_without_firewall_permission(monkeypatch):
    monkeypatch.setattr(netguard.shutil, "which", lambda tool: "/usr/sbin/" + tool)
    status = netguard.install(run=lambda argv: (False, "Permission denied (you must be root)"))
    assert not status.ok and "NET_ADMIN" in status.reason


def test_install_fails_without_iptables(monkeypatch):
    monkeypatch.setattr(netguard.shutil, "which", lambda tool: None)
    assert not netguard.install(run=lambda argv: (True, "")).ok


def test_verify_requires_a_clean_refusal():
    assert netguard.verify(8000, probe=lambda port: netguard.BLOCKED_EXIT).ok
    assert not netguard.verify(8000, probe=lambda port: 0).ok       # sandbox reached localhost
    assert not netguard.verify(8000, probe=lambda port: 1).ok       # probe crashed: not proof of a block
    assert not netguard.verify(8000, probe=lambda port: -1).ok      # probe couldn't start
