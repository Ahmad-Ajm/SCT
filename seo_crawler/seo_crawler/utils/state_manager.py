"""
utils/state_manager.py
=======================
إدارة حفظ واستئناف حالة الزحف.

يحفظ:
- URLs التي تمت زيارتها (visited)
- قائمة الانتظار (queue)
- النتائج المُجمَّعة حتى الآن (results)

يتيح:
- استئناف الزحف بعد انقطاع
- مراجعة تقدم الزحف
"""

import json
import time
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

log = get_logger(__name__)


class StateManager:
    """
    مدير حالة الزحف — يحفظ ويستعيد التقدم.

    Example:
        >>> state = StateManager("./state")
        >>> if state.has_saved_session():
        ...     visited, queue = state.load()
        >>> state.save(visited_set, queue_list)
    """

    def __init__(self, state_dir: str = "./state"):
        """
        Args:
            state_dir: المجلد لحفظ ملفات الحالة
        """
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.visited_file = self.state_dir / "visited.json"
        self.queue_file = self.state_dir / "queue.json"
        self.meta_file = self.state_dir / "meta.json"

    def has_saved_session(self) -> bool:
        """التحقق هل توجد جلسة محفوظة قابلة للاستئناف."""
        return self.visited_file.exists() and self.queue_file.exists()

    def save(
        self,
        visited: set[str],
        queue: list[str],
        extra_meta: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        حفظ حالة الزحف الحالية.

        Args:
            visited: مجموعة URLs المزحوفة
            queue: قائمة URLs في الانتظار
            extra_meta: بيانات إضافية (اختياري)
        """
        try:
            # حفظ visited (set → list للـ JSON)
            with open(self.visited_file, "w", encoding="utf-8") as f:
                json.dump(list(visited), f, ensure_ascii=False, indent=2)

            # حفظ queue
            with open(self.queue_file, "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False, indent=2)

            # حفظ meta
            meta = {
                "last_saved": time.time(),
                "last_saved_readable": time.strftime("%Y-%m-%d %H:%M:%S"),
                "visited_count": len(visited),
                "queue_count": len(queue),
            }
            if extra_meta:
                meta.update(extra_meta)

            with open(self.meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            log.debug(f"تم حفظ الحالة: {len(visited)} مزحوف، {len(queue)} في الانتظار")

        except Exception as e:
            log.error(f"فشل حفظ الحالة: {e}")

    def load(self) -> tuple[set[str], list[str]]:
        """
        استرجاع حالة الزحف المحفوظة.

        Returns:
            tuple: (visited_set, queue_list)
        """
        visited: set[str] = set()
        queue: list[str] = []

        try:
            if self.visited_file.exists():
                with open(self.visited_file, "r", encoding="utf-8") as f:
                    visited = set(json.load(f))

            if self.queue_file.exists():
                with open(self.queue_file, "r", encoding="utf-8") as f:
                    queue = json.load(f)

            log.info(
                f"تم استرجاع الحالة: {len(visited)} مزحوف، {len(queue)} في الانتظار"
            )

        except Exception as e:
            log.error(f"فشل استرجاع الحالة: {e}")

        return visited, queue

    def load_meta(self) -> dict[str, Any]:
        """استرجاع بيانات meta للجلسة المحفوظة."""
        if not self.meta_file.exists():
            return {}

        try:
            with open(self.meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"فشل قراءة meta: {e}")
            return {}

    def clear(self) -> None:
        """مسح الحالة المحفوظة (بدء جديد)."""
        for f in [self.visited_file, self.queue_file, self.meta_file]:
            if f.exists():
                f.unlink()
        log.info("تم مسح الحالة المحفوظة")
