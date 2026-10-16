"""
Interactive configuration.

The interactive loop is intentionally configurable via a single object so it can be used by:
- CLI scripts (examples)
- external apps embedding AutoSkill
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import default_store_path


@dataclass
class InteractiveConfig:
    store_dir: str = field(default_factory=default_store_path)
    user_id: str = "u1"

    history_turns: int = 100
    ingest_window: int = 6

    # Extraction timing signals:
    # In "auto" mode, attempt extraction once every N turns (N=extract_turn_limit).
    # Set N=1 to attempt extraction every turn.
    extract_turn_limit: int = 1

    extract_mode: str = "auto"  # auto|always|never

    assistant_temperature: float = 0.2

    def normalize(self) -> "InteractiveConfig":
        """Run normalize."""
        self.store_dir = str(self.store_dir or default_store_path()).strip() or default_store_path()

        self.extract_mode = (self.extract_mode or "auto").strip().lower()
        if self.extract_mode not in {"auto", "always", "never"}:
            self.extract_mode = "auto"

        self.history_turns = max(0, int(self.history_turns))
        self.ingest_window = max(2, int(self.ingest_window))
        self.extract_turn_limit = max(1, int(self.extract_turn_limit))
        return self
