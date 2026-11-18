"""
myhistory.py - remember how many times you used each item, so the favourites come first.

The memory is one small JSON file (by default in ~/Library/Application Support/mylauncher/usage.json,
NOT inside the project: it is personal data and the project is a public git repository):

    {"version": 1, "counts": {"app:Obsidian": 14, "cmd:shutdown": 2, "link:yt": 5}}

How it is used (see mysearch.rank): every item gets a small BONUS in its score, `count * boost_per_use`,
never more than `max_boost`. The bonus is smaller than the gap between two match kinds (20 points),
so a better match always wins; but among items that match equally well (and when nothing is typed),
the most used comes first.

Safety rules: a missing or damaged file is simply "no history" (the launcher must never refuse to
start because of its memory), and a write that fails (disk full, read-only folder) is ignored.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class History:
    def __init__(self, path, enabled: bool = True):
        self.path, self.enabled = Path(path), enabled

    def counts(self) -> dict:
        """{item id: times used}. Empty when disabled, missing or damaged."""
        if not self.enabled:
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            counts = data["counts"]
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        if not isinstance(counts, dict):
            return {}
        return {k: v for k, v in counts.items() if isinstance(k, str) and isinstance(v, int) and v > 0}

    def _write(self, counts: dict) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(json.dumps({"version": 1, "counts": counts}, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self.path)  # atomic: a crash can never leave a half-written file
            return True
        except OSError:
            return False

    def record(self, item_id: str) -> bool:
        """Count one more use. Returns False when nothing was saved (disabled, or the write failed)."""
        if not self.enabled:
            return False
        counts = self.counts()
        counts[item_id] = counts.get(item_id, 0) + 1
        return self._write(counts)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def top(self, limit: int = 20) -> list:
        """[(item id, count)], most used first (ties alphabetical)."""
        return sorted(self.counts().items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
