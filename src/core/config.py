import toml
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nx"
CONFIG_FILE = CONFIG_DIR / "config.toml"

def save_config(mode: int, use_flakes: bool, config_path: str):
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
    return toml.loads(CONFIG_FILE.read_text())

def is_setup_done() -> bool:
    return CONFIG_FILE.exists()