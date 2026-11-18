"""Multi-package install.

`nx -i a b c` resolves every name in one source and installs them together.
The interactive per-package browser is gone: a name either resolves to
exactly one package by its canonical attribute, or it is reported missing
and the whole operation is abandoned — a partial install would leave the
configuration in a state the user did not ask for.
"""
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.manager import resolve_packages
from models.package import Package

import main as main_mod


SYS = '{  environment.systemPackages = with pkgs; [\n    hello\n  ];\n}'


def _pkg(attribute, source="stable", pname=None):
    return Package(name=pname or attribute, version="1.0", description="d",
                   source=source, type=None, attribute=attribute)


def _config(tmp_path):
    config_nix = tmp_path / "configuration.nix"
    config_nix.write_text(SYS)
    return {"setup": {"configuration_path": str(config_nix),
                      "flake_enabled": False,
                      "home_manager_enabled": False,
                      "unstable_variable": "unstable"}}


def _install(config, names, resolved, missing):
    """Run handle_install with the source menu and resolver mocked."""
    with patch("main.show_source_select", return_value=1), \
         patch("main.resolve_packages", return_value=(resolved, missing)), \
         patch("main.show_summary", return_value=True), \
         patch("main.backup_files") as backup, \
         patch("main.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        main_mod.handle_install(names, config)
    return backup, run


# ── the whole set is installed together ─────────────────────────────────────

def test_several_packages_install_together(tmp_path):
    config = _config(tmp_path)
    pkgs = [_pkg("btop"), _pkg("firefox"), _pkg("git")]
    _install(config, ["btop", "firefox", "git"], pkgs, [])

    content = (tmp_path / "configuration.nix").read_text()
    for name in ("btop", "firefox", "git"):
        assert name in content, f"{name} was not installed"


def test_one_operation_means_one_rebuild(tmp_path):
    config = _config(tmp_path)
    _, run = _install(config, ["btop", "firefox"], [_pkg("btop"), _pkg("firefox")], [])
    assert run.call_count == 1, "the whole set is rebuilt once"


def test_duplicate_names_are_collapsed():
    """A repeated name is searched once and installed once."""
    pkg = _pkg("btop")
    with patch("core.manager.stable_search", return_value=[pkg]) as fetch:
        resolved, missing = resolve_packages("stable", ["btop", "btop"])
    assert fetch.call_count == 1
    assert resolved == [pkg] and missing == []


# ── a missing name abandons everything ──────────────────────────────────────

def test_missing_package_aborts_the_whole_operation(tmp_path):
    config = _config(tmp_path)
    buf = io.StringIO()
    with patch("main.show_source_select", return_value=1), \
         patch("main.resolve_packages", return_value=([_pkg("btop")], ["ghost"])), \
         patch("main.backup_files") as backup, \
         patch("main.subprocess.run") as run, \
         redirect_stdout(buf):
        main_mod.handle_install(["btop", "ghost"], config)

    out = buf.getvalue()
    assert "ghost" in out, out
    backup.assert_not_called(), "nothing may be backed up for an aborted install"
    run.assert_not_called(), "no rebuild may run for an aborted install"
    assert "btop" not in (tmp_path / "configuration.nix").read_text(), \
        "a partial install must not be written"


def test_every_missing_name_is_reported(tmp_path):
    config = _config(tmp_path)
    buf = io.StringIO()
    with patch("main.show_source_select", return_value=1), \
         patch("main.resolve_packages", return_value=([], ["ghost", "phantom"])), \
         patch("main.backup_files"), patch("main.subprocess.run"), \
         redirect_stdout(buf):
        main_mod.handle_install(["ghost", "phantom"], config)

    out = buf.getvalue()
    assert "ghost" in out and "phantom" in out, out


# ── resolution is by exact identity, never by hit count ─────────────────────

def test_fuzzy_hits_do_not_resolve_a_name():
    """A nonsense query returns hundreds of hits; none of them is evidence."""
    fuzzy = [_pkg("btop-rocm"), _pkg("btop-cuda")]
    with patch("core.manager.stable_search", return_value=fuzzy):
        resolved, missing = resolve_packages("stable", ["btop"])
    assert resolved == [] and missing == ["btop"]


def test_pname_resolves_to_the_canonical_attribute():
    """The upstream pname is a lookup key; the attribute is what installs."""
    pkg = _pkg("nxXtend", pname="nx")
    with patch("core.manager.stable_search", return_value=[pkg]):
        resolved, missing = resolve_packages("stable", ["nx"])
    assert resolved == [pkg] and missing == []


def test_exact_attribute_wins_over_a_pname_match():
    exact = _pkg("btop")
    other = _pkg("btop-rocm", pname="btop")
    with patch("core.manager.stable_search", return_value=[other, exact]):
        resolved, _ = resolve_packages("stable", ["btop"])
    assert resolved == [exact]


def test_resolution_stops_at_the_first_exact_match():
    first = _pkg("git")
    second = _pkg("git", source="stable")
    with patch("core.manager.stable_search", return_value=[first, second]):
        resolved, _ = resolve_packages("stable", ["git"])
    assert resolved == [first]


# ── the browser is gone, the flake browser is not ────────────────────────────

def test_the_package_browser_is_gone():
    assert not hasattr(main_mod, "show_results")
    assert not hasattr(main_mod, "show_no_results")


def test_the_flake_browser_is_untouched():
    assert hasattr(main_mod, "show_results_flake")
