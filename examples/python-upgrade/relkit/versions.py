"""Release-version helpers used by the deploy tooling."""

from distutils.version import LooseVersion


def is_newer(candidate: str, current: str) -> bool:
    """True if `candidate` is a strictly newer release than `current`."""
    return LooseVersion(candidate) > LooseVersion(current)


def latest(versions: list[str]) -> str:
    """Return the newest version string from a list."""
    if not versions:
        raise ValueError("no versions given")
    return max(versions, key=LooseVersion)
