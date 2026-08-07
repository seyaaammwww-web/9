"""Persistent Mage.space session pool — storage_state + metadata on disk."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


def _safe_filename(username: str) -> str:
    return re.sub(r"[^\w@.-]", "_", username)


@dataclass
class AccountSession:
    username: str
    credentials: dict = field(default_factory=dict)
    cookie_file: Optional[Path] = None
    storage_state_file: Optional[Path] = None
    last_refresh: float = 0.0
    logged_in: bool = False
    in_use: bool = False
    in_use_since: float = 0.0
    gems: int = 0
    consumed: bool = False
    # Builder-quality hint only — model picker state is NOT in storage_state; always DOM-verify at runtime.
    guava_ready: bool = False
    owner_user_id: Optional[int] = None  # Telegram user this pooled session belongs to
    session: Any = field(default=None, repr=False, compare=False)

    def meta_path(self) -> Path:
        assert self.cookie_file is not None
        return self.cookie_file

    def save(self) -> None:
        if self.cookie_file is None:
            return
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "username": self.username,
            "credentials": self.credentials,
            "cookie_file": str(self.cookie_file),
            "storage_state_file": str(self.storage_state_file) if self.storage_state_file else None,
            "last_refresh": self.last_refresh,
            "logged_in": self.logged_in,
            "in_use": self.in_use,
            "in_use_since": self.in_use_since,
            "gems": self.gems,
            "consumed": self.consumed,
            "guava_ready": self.guava_ready,
            "owner_user_id": self.owner_user_id,
        }
        tmp = self.cookie_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.cookie_file)

    @classmethod
    def load(cls, path: Path) -> Optional["AccountSession"]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            storage = data.get("storage_state_file")
            return cls(
                username=data["username"],
                credentials=data.get("credentials") or {},
                cookie_file=path,
                storage_state_file=Path(storage) if storage else None,
                last_refresh=float(data.get("last_refresh") or 0),
                logged_in=bool(data.get("logged_in")),
                in_use=bool(data.get("in_use")),
                in_use_since=float(data.get("in_use_since") or 0),
                gems=int(data.get("gems") or 0),
                consumed=bool(data.get("consumed")),
                guava_ready=bool(data.get("guava_ready")),
                owner_user_id=data.get("owner_user_id"),
            )
        except Exception:
            return None


class SessionManager:
    def __init__(self, data_dir: str, max_workers: int = 2):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers
        self._lock = threading.RLock()
        self._accounts: dict[str, AccountSession] = {}

    def storage_state_path(self, username: str) -> Path:
        return self.data_dir / f"{_safe_filename(username)}.storage.json"

    def _meta_path(self, username: str) -> Path:
        return self.data_dir / f"{_safe_filename(username)}.json"

    def _is_ready(self, acct: AccountSession, owner_user_id: Optional[int] = None) -> bool:
        if not acct.logged_in or acct.in_use or acct.consumed:
            return False
        if owner_user_id is not None and acct.owner_user_id != owner_user_id:
            return False
        storage = acct.storage_state_file
        return bool(storage and storage.exists() and storage.stat().st_size > 0)

    def count_ready(self, owner_user_id: Optional[int] = None) -> int:
        with self._lock:
            return sum(
                1 for a in self._accounts.values()
                if self._is_ready(a, owner_user_id=owner_user_id)
            )

    def list_ready_sessions(self, owner_user_id: Optional[int] = None) -> list[AccountSession]:
        """Ready pooled sessions, guava_ready + freshest first."""
        with self._lock:
            ready = [
                a for a in self._accounts.values()
                if self._is_ready(a, owner_user_id=owner_user_id)
            ]
        ready.sort(key=lambda a: (not a.guava_ready, -(a.last_refresh or 0)))
        return ready

    def pool_stats(self) -> dict[str, int]:
        with self._lock:
            ready = in_use = total = 0
            for acct in self._accounts.values():
                if acct.consumed:
                    continue
                total += 1
                if acct.in_use:
                    in_use += 1
                elif self._is_ready(acct):
                    ready += 1
            return {"ready": ready, "in_use": in_use, "total": total}

    def acquire_session(
        self, wait: float = 0, owner_user_id: Optional[int] = None
    ) -> Optional[AccountSession]:
        deadline = time.time() + max(0.0, wait)
        while True:
            with self._lock:
                for acct in self._accounts.values():
                    if self._is_ready(acct, owner_user_id=owner_user_id):
                        acct.in_use = True
                        acct.in_use_since = time.time()
                        acct.save()
                        return acct
            if wait <= 0 or time.time() >= deadline:
                return None
            time.sleep(0.15)

    def release_session(self, username: str, gems: Optional[int] = None) -> None:
        with self._lock:
            acct = self._accounts.get(username)
            if not acct or acct.consumed:
                return
            acct.in_use = False
            acct.in_use_since = 0.0
            if gems is not None:
                acct.gems = gems
            acct.last_refresh = time.time()
            acct.save()

    def mark_consumed(self, username: str) -> None:
        with self._lock:
            acct = self._accounts.pop(username, None)
            if not acct:
                return
            acct.consumed = True
            acct.in_use = False
            for path in (acct.cookie_file, acct.storage_state_file):
                if path and path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def discard_session(self, username: str) -> None:
        self.mark_consumed(username)

    def add_accounts(self, mapping: dict) -> None:
        with self._lock:
            for username, creds in mapping.items():
                if username in self._accounts:
                    continue
                meta = self._meta_path(username)
                storage = self.storage_state_path(username)
                acct = AccountSession(
                    username=username,
                    credentials=creds if isinstance(creds, dict) else {"username": username},
                    cookie_file=meta,
                    storage_state_file=storage if storage.exists() else None,
                    logged_in=storage.exists(),
                )
                if meta.exists():
                    loaded = AccountSession.load(meta)
                    if loaded:
                        acct = loaded
                self._accounts[username] = acct

    def load_existing_sessions(self) -> int:
        loaded = 0
        with self._lock:
            for path in self.data_dir.glob("*.json"):
                if path.name.endswith(".storage.json"):
                    continue
                acct = AccountSession.load(path)
                if acct and not acct.consumed:
                    if acct.storage_state_file is None:
                        acct.storage_state_file = self.storage_state_path(acct.username)
                    self._accounts[acct.username] = acct
                    loaded += 1
        return loaded

    def assign_legacy_owners(self, user_ids: list[int]) -> int:
        """Tag pooled sessions that predate per-user ownership (round-robin)."""
        if not user_ids:
            return 0
        assigned = 0
        with self._lock:
            legacy = [
                a for a in self._accounts.values()
                if a.owner_user_id is None and not a.consumed and self._is_ready(a)
            ]
            for idx, acct in enumerate(legacy):
                acct.owner_user_id = user_ids[idx % len(user_ids)]
                acct.save()
                assigned += 1
        return assigned

    def reset_in_use_on_boot(self) -> int:
        reset = 0
        with self._lock:
            for acct in self._accounts.values():
                if acct.in_use and not acct.consumed:
                    acct.in_use = False
                    acct.in_use_since = 0.0
                    acct.save()
                    reset += 1
        return reset

    def purge_invalid(self) -> int:
        purged = 0
        with self._lock:
            stale: list[str] = []
            for username, acct in self._accounts.items():
                storage = acct.storage_state_file or self.storage_state_path(username)
                if acct.consumed or not storage.exists() or storage.stat().st_size == 0:
                    stale.append(username)
            for username in stale:
                self.mark_consumed(username)
                purged += 1
        return purged

    def purge_all_sessions(self) -> int:
        """Discard every pooled session — used for fresh-pool boot on localhost."""
        with self._lock:
            usernames = list(self._accounts.keys())
        purged = 0
        for username in usernames:
            self.mark_consumed(username)
            purged += 1
        return purged

    def sweep_stale_in_use(self, stale_sec: int) -> int:
        recovered = 0
        cutoff = time.time() - stale_sec
        with self._lock:
            for acct in self._accounts.values():
                if acct.in_use and not acct.consumed and acct.in_use_since and acct.in_use_since < cutoff:
                    acct.in_use = False
                    acct.in_use_since = 0.0
                    acct.save()
                    recovered += 1
        return recovered
