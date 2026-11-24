"""Shared pytest fixtures for the nxXtend test suite.

Only genuinely cross-file helpers live here. Per-file scenario data and
single-use helpers stay in their own test modules.
"""
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def cli_config():
    """A minimal, self-contained nx config used by CLI dispatch tests."""
    return {"setup": {
        "configuration_path": "/tmp/nx-test/configuration.nix",
        "flake_enabled": True,
        "flake_path": "/tmp/nx-test/flake.nix",
        "home_manager_enabled": True,
        "home_manager_path": "/tmp/nx-test/home.nix",
        "unstable_variable": "unstable",
    }}


@pytest.fixture
def backup_dir(tmp_path):
    """An isolated stand-in for the production /etc/nixos/.nx-backup.

    The writer's default backup location is a system directory owned by root.
    It does not exist on a GitHub runner, and even `mkdir(exist_ok=True)` there
    would fail for a non-root user. Creating this directory up front means
    tests never touch the real path, whichever call site forgets to pass it.
    """
    path = tmp_path / ".nx-backup"
    path.mkdir()
    return path


@pytest.fixture
def run_cli(cli_config):
    """Invoke ``main.main()`` with every handler and subprocess mocked.

    Returns ``(exit_code, handler_calls, mock_subprocess_run)`` where
    ``handler_calls`` is a list of ``(handler_name, args, kwargs)`` tuples and
    ``exit_code`` is ``None`` when ``main()`` returned normally.
    """
    def _run(argv):
        calls = []

        def rec(name):
            def f(*a, **k):
                calls.append((name, a, k))
            return f

        exit_code = None
        mock_sub = None
        try:
            with patch("main.handle_install", side_effect=rec("install")), \
                 patch("main.handle_remove", side_effect=rec("remove")), \
                 patch("main.handle_upgrade", side_effect=rec("upgrade")), \
                 patch("main.handle_flakes_install", side_effect=rec("flakes_install")), \
                 patch("main.handle_flakes_remove", side_effect=rec("flakes_remove")), \
                 patch("main.handle_flakes_upgrade", side_effect=rec("flakes_upgrade")), \
                 patch("main.subprocess.run") as mock_sub, \
                 patch("main.bootstrap", return_value=cli_config), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                mock_sub.return_value = MagicMock(returncode=0)
                sys.argv = argv
                import main
                main.main()
        except SystemExit as e:
            exit_code = e.code
        return exit_code, calls, mock_sub

    return _run
