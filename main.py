from src.core.manager import search
import curses
from src.ui.display import show_results

rr = input("what is the rep : ")
stable, unstable = search(rr)
selected = show_results(stable)
print(f"selected: {[p.name for p in selected]}")