import pytest

from relkit.hooks import call_hook, required_params
from relkit.versions import is_newer, latest


def test_is_newer_compares_numerically():
    assert is_newer("1.10.0", "1.9.2")
    assert not is_newer("2.0.0", "2.0.0")
    assert not is_newer("0.9", "0.10")


def test_latest():
    assert latest(["1.2.0", "1.10.1", "1.9.9"]) == "1.10.1"
    with pytest.raises(ValueError):
        latest([])


def test_required_params_skips_defaults():
    def hook(service, region, dry_run=False):
        pass

    assert required_params(hook) == ["service", "region"]


def test_call_hook_passes_only_required_context():
    def notify(service, channel="#deploys"):
        return f"{service} -> {channel}"

    assert call_hook(notify, {"service": "api", "region": "eu"}) == "api -> #deploys"
    with pytest.raises(KeyError):
        call_hook(notify, {"region": "eu"})
