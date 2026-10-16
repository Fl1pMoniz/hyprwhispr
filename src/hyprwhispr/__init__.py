"""hyprwhispr - a local, hold-to-talk desktop assistant for Hyprland.

Speech recognition (whisper.cpp) and language inference (Ollama) run entirely on
the local machine. The only network access is an explicitly requested web search,
which opens the user's browser.
"""

from .config import VERSION

__all__ = ["VERSION"]
__version__ = VERSION
