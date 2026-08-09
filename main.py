from src.core.manager import search
import curses
from src.ui.display import show_results

stable, unstable = search("steam")
selected = show_results(stable)
print(f"selected: {[p.name for p in selected]}")