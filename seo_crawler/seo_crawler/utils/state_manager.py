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
            # v1.09-B7: كتابة atomic — Ctrl-C في منتصف الكتابة لا يجب أن يُتلف
            # ملفّ JSON ⇒ يُسقط الـloader التالي ويفقد المستخدم كل الحالة.
            self._atomic_json_write(self.visited_file, list(visited))
            self._atomic_json_write(self.queue_file, queue)
            meta = {
                "last_saved": time.time(),
                "last_saved_readable": time.strftime("%Y-%m-%d %H:%M:%S"),
                "visited_count": len(visited),
                "queue_count": len(queue),
            }
            if extra_meta:
                meta.update(extra_meta)
            self._atomic_json_write(self.meta_file, meta)
            log.debug(f"تم حفظ الحالة: {len(visited)} مزحوف، {len(queue)} في الانتظار")

        except Exception:
            log.exception("فشل حفظ الحالة")

    @staticmethod
    def _atomic_json_write(target, data) -> None:
        """v1.09-B7: temp + os.replace — يضمن إمّا الملفّ القديم سليم أو الجديد سليم،
        ولا يحدث أبداً نصف JSON مكسور."""
        import os
        from pathlib import Path as _P
        target = _P(target)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
        os.replace(tmp, target)

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

        except Exception:
            log.exception("فشل استرجاع الحالة")

        return visited, queue

    def load_meta(self) -> dict[str, Any]:
        """استرجاع بيانات meta للجلسة المحفوظة."""
        if not self.meta_file.exists():
            return {}

        try:
            with open(self.meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log.exception("فشل قراءة meta")
            return {}

    def clear(self) -> None:
        """مسح الحالة المحفوظة (بدء جديد)."""
        for f in [self.visited_file, self.queue_file, self.meta_file]:
            if f.exists():
                f.unlink()
        log.info("تم مسح الحالة المحفوظة")
