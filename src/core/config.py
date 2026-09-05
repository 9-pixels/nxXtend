import os
import toml
from pathlib import Path

# User config directory and file location
_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
CONFIG_DIR = Path(f"/home/{_user}") / ".config" / "nx"
CONFIG_FILE = CONFIG_DIR / "config.toml"

def save_config(mode: int, use_flakes: bool, config_path: str):
    """Save user preferences to ~/.config/nx/config.toml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = {
        "setup": {
            "mode": mode,
            "use_flakes": use_flakes,
            "config_path": config_path
        },
        "meta": {
            "setup_done": True
        }
    }
    CONFIG_FILE.write_text(toml.dumps(config))

def load_config() -> dict:
    """Load user preferences from ~/.config/nx/config.toml."""
    return toml.loads(CONFIG_FILE.read_text())

def is_setup_done() -> bool:
    """Check if the user has completed initial setup."""
    return CONFIG_FILE.exists()