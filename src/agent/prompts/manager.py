"""
manager.py — PromptManager

Loads prompt templates from .txt files at runtime.
To change prompts for Hospital B → just swap the prompt folder.
To add Telugu → add prompts/te/ folder. No code changes.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

# Default prompt directory (next to this file)
_DEFAULT_DIR = Path(__file__).parent


class PromptManager:
    """Loads .txt prompt templates from a directory and fills placeholders."""

    def __init__(self, prompt_dir: str | Path = _DEFAULT_DIR):
        self._dir = Path(prompt_dir)

    @lru_cache(maxsize=16)
    def _load(self, name: str) -> str:
        """Read and cache a .txt prompt file by name."""
        path = self._dir / f"{name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def get(self, name: str, **kwargs) -> str:
        """
        Load a prompt by name and fill {placeholders} with kwargs.

        Usage:
            pm = PromptManager()
            prompt = pm.get("intent", message="book a doctor")
        """
        template = self._load(name)
        return template.format(**kwargs)

    def list_prompts(self) -> list[str]:
        """List all available prompt template names."""
        return [p.stem for p in self._dir.glob("*.txt")]
