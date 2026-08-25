from src.core.writer import remove_package
from pathlib import Path

config = Path("/etc/nixos-test/configuration.nix")
content = config.read_text()
new_content, found = remove_package(content, "flatpak", config.parent)
print(f"found: {found}")
config.write_text(new_content)
print(new_content)