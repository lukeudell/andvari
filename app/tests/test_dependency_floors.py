# ============================================================
#  file:       app/tests/test_dependency_floors.py
#  purpose:    hold the demo's runtime dependencies at or above their CVE floors
#  owner:      Luke Udell
#  spdx:       none
#  std:        [STD-05] [STD-06]
#  adr:        none
#  ticket:     PER-144
#  created:    2026-10-27
# ============================================================
"""
Security floors for a demo that is publicly reachable on lukeudell.com.

The October 2026 sweep (PER-144) found these arriving transitively through
Streamlit at versions with 2026 CVEs: Pillow below 13.0.0 (image decoder
memory safety), GitPython below 3.1.59 (remote code execution via config
injection), and a certifi whose CA bundle still trusted the eMudhra (emSign)
roots after eight of their intermediates were found to have weak keys.
Nothing pinned them, so nothing would have lifted them. Raise a floor on the
next sweep, never lower it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import certifi
import pytest

FLOORS = {
    "pillow": (13, 0, 0),
    "certifi": (2026, 10, 19),
}


def _parse(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".")[:3])


@pytest.mark.parametrize("package,floor", sorted(FLOORS.items()))
def test_installed_version_meets_the_security_floor(package: str, floor: tuple[int, ...]) -> None:
    installed = _parse(version(package))
    assert installed >= floor, f"{package} {installed} is below the security floor {floor}"


def test_gitpython_is_absent_or_patched() -> None:
    # Streamlit 1.66 stopped depending on it; if anything brings it back it must be patched
    try:
        installed = _parse(version("GitPython"))
    except PackageNotFoundError:
        return
    assert installed >= (3, 1, 59), f"GitPython {installed} is below the security floor"


# The roots Mozilla withdrew over the weak intermediate keys. Mozilla kept emSign Root CA - G1,
# and certifi follows Mozilla, so the check is these three rather than every emSign label: a
# stricter rule would fail on the very release that carries the fix.
WITHDRAWN_ROOTS = ("emSign ECC Root CA - G3", "emSign Root CA - C1", "emSign ECC Root CA - C3")


def test_the_ca_bundle_does_not_trust_the_withdrawn_emsign_roots() -> None:
    # the version floor above is a proxy; this is the property it stands for
    with open(certifi.where(), encoding="utf-8") as bundle:
        text = bundle.read()
    assert "BEGIN CERTIFICATE" in text, "certifi bundle unreadable, so the check proves nothing"
    for label in WITHDRAWN_ROOTS:
        assert f'# Label: "{label}"' not in text, f"certifi still trusts {label}"


def test_parse_reads_major_minor_patch() -> None:
    assert _parse("2026.10.19") == (2026, 10, 19)
    assert _parse("2026.6.17") < (2026, 10, 19)
    assert _parse("12.3.0") < (13, 0, 0)
