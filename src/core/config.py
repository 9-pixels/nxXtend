# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import os
import re
import toml
from pathlib import Path

# User config directory and file location
# Uses SUDO_USER if available (when running with sudo), otherwise falls back to USER.
# This ensures the config is stored in the actual user's home, not root's.
_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
CONFIG_DIR = Path(f"/home/{_user}") / ".config" / "nx"
CONFIG_FILE = CONFIG_DIR / "config.toml"


CONFIG_TEMPLATE = """# nx configuration
# This file contains user-configurable settings for nx.
# Changes to this file may affect how nx reads and writes your NixOS setup.


# ─────────────────────────────────────────────
# NixOS setup
# ─────────────────────────────────────────────


[setup]

configuration_path = "{configuration_path}"

flake_enabled = {flake_enabled}
flake_path = "{flake_path}"

home_manager_enabled = {home_manager_enabled}
home_manager_path = "{home_manager_path}"

unstable_variable = "{unstable_variable}"

# ─────────────────────────────────────────────
# Future features
# ─────────────────────────────────────────────

[future]

# Features planned for future nx versions.
# These options are currently informational only.

# Remote Flake metadata registry.
# remote_registry = false

# Package file shortcuts.
[shortcuts]
# Nothing yet

# Adding integration with nh
# nh_integration = false

# ─────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────

[meta]

# Internal state managed by nx.
# Do not edit these values manually.

setup_done = {setup_done}
"""


SETUP_DEFAULTS = {
    "configuration_path": "/etc/nixos/configuration.nix",
    "flake_enabled": False,
    "flake_path": "/etc/nixos/flake.nix",
    "home_manager_enabled": False,
    "home_manager_path": "/etc/nixos/home.nix",
    "unstable_variable": "unstable",
}


def validate_setup_value(key: str, value) -> bool:
    """Validate a single setup value. Returns True if valid."""
    if key == "configuration_path":
        return isinstance(value, str) and len(value) > 0
    elif key in ("flake_enabled", "home_manager_enabled"):
        return isinstance(value, bool)
    elif key in ("flake_path", "home_manager_path"):
        return isinstance(value, str) and len(value) > 0
    elif key == "unstable_variable":
        return isinstance(value, str) and bool(re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', value))
    return False


def validate_and_repair():
    """Validate and repair config.toml on every load.
    
    This function is deliberately conservative. It only repairs individual
    missing or invalid keys — it never removes user-added keys or rewrites
    sections that are already valid. The template is the source of truth for
    the final file structure, so any key that passes validation preserves
    its user-set value.
    
    setup_done defaults to False (never True) when missing or invalid.
    This is a safety decision: assuming setup is done when we have no proof
    could allow users to skip the wizard and end up with a misconfigured system.
    """
    existing = {}
    
    if CONFIG_FILE.exists():
        try:
            existing = toml.loads(CONFIG_FILE.read_text())
        except toml.TomlDecodeError:
            existing = {}
    
    # Validate [setup]
    setup = existing.get("setup", {})
    validated_setup = {}
    
    for key, default in SETUP_DEFAULTS.items():
        val = setup.get(key)
        validated_setup[key] = val if validate_setup_value(key, val) else default
    
    # Validate [meta]
    meta = existing.get("meta", {})
    setup_done_val = meta.get("setup_done")
    
    # Preserve valid existing value; only repair if missing/invalid
    if isinstance(setup_done_val, bool):
        setup_done = setup_done_val
    else:
        setup_done = False  # safe default — never assume setup is done
    
    # Build repaired config from template
    content = CONFIG_TEMPLATE.format(
        configuration_path=validated_setup["configuration_path"],
        flake_enabled=str(validated_setup["flake_enabled"]).lower(),
        flake_path=validated_setup["flake_path"],
        home_manager_enabled=str(validated_setup["home_manager_enabled"]).lower(),
        home_manager_path=validated_setup["home_manager_path"],
        unstable_variable=validated_setup["unstable_variable"],
        setup_done=str(setup_done).lower(),
    )
    
    CONFIG_FILE.write_text(content)


def create_fresh_config():
    """Create new config.toml with all defaults and setup_done=false."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    content = CONFIG_TEMPLATE.format(
        configuration_path=SETUP_DEFAULTS["configuration_path"],
        flake_enabled=str(SETUP_DEFAULTS["flake_enabled"]).lower(),
        flake_path=SETUP_DEFAULTS["flake_path"],
        home_manager_enabled=str(SETUP_DEFAULTS["home_manager_enabled"]).lower(),
        home_manager_path=SETUP_DEFAULTS["home_manager_path"],
        unstable_variable=SETUP_DEFAULTS["unstable_variable"],
        setup_done="false",
    )
    CONFIG_FILE.write_text(content)


def load_config() -> dict:
    """Load and validate config.toml, repairing if necessary."""
    if not CONFIG_FILE.exists():
        create_fresh_config()
    
    validate_and_repair()
    return toml.loads(CONFIG_FILE.read_text())


def is_setup_done() -> bool:
    """Check if the user has completed initial setup."""
    if not CONFIG_FILE.exists():
        return False
    
    try:
        config = toml.loads(CONFIG_FILE.read_text())
        setup_done = config.get("meta", {}).get("setup_done")
        if isinstance(setup_done, bool):
            return setup_done
        return False
    except toml.TomlDecodeError:
        return False


def mark_setup_complete():
    """Mark setup as complete after successful nx setup."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if not CONFIG_FILE.exists():
        create_fresh_config()
    
    try:
        existing = toml.loads(CONFIG_FILE.read_text())
    except toml.TomlDecodeError:
        existing = {}
    
    if "meta" not in existing:
        existing["meta"] = {}
    existing["meta"]["setup_done"] = True
    
    CONFIG_FILE.write_text(toml.dumps(existing))


def save_config(**kwargs):
    """Save user preferences to config.toml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    configuration_path = kwargs.get("configuration_path") or SETUP_DEFAULTS["configuration_path"]
    flake_enabled = kwargs.get("flake_enabled")
    if flake_enabled is None:
        flake_enabled = SETUP_DEFAULTS["flake_enabled"]
    flake_path = kwargs.get("flake_path") or SETUP_DEFAULTS["flake_path"]
    home_manager_enabled = kwargs.get("home_manager_enabled")
    if home_manager_enabled is None:
        home_manager_enabled = SETUP_DEFAULTS["home_manager_enabled"]
    home_manager_path = kwargs.get("home_manager_path") or SETUP_DEFAULTS["home_manager_path"]
    unstable_variable = kwargs.get("unstable_variable") or SETUP_DEFAULTS["unstable_variable"]
    
    content = CONFIG_TEMPLATE.format(
        configuration_path=configuration_path,
        flake_enabled=str(flake_enabled).lower(),
        flake_path=flake_path,
        home_manager_enabled=str(home_manager_enabled).lower(),
        home_manager_path=home_manager_path,
        unstable_variable=unstable_variable,
        setup_done="true",
    )
    CONFIG_FILE.write_text(content)
