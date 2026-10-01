"""Transport HTTP : envoie les payloads au serveur Node.js.

Le scan lui-meme doit tourner sur le *thread principal* du serveur (l'API
Endstone l'exige), alors que l'envoi HTTP peut bloquer. On separe donc les
deux : le scanner pousse les payloads dans une file, et un thread daemon les
POSTe une par une.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional


class MapSender:
    """File d'attente + thread d'envoi HTTP."""

    def __init__(
        self,
        endpoint: str,
        api_key: str = "",
        delay_ms: int = 50,
        logger: Optional[Callable[[str], None]] = None,
        max_queue: int = 50000,
    ) -> None:
        base = (endpoint or "").strip().rstrip("/")
        self.url = base + "/api/chunk" if base else ""
        self.api_key = (api_key or "").strip()
        self.delay = max(0, delay_ms) / 1000.0
        self._log = logger
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="worldmap-sender", daemon=True
        )
        self._thread.start()

        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self.last_error: Optional[str] = None

    # --- API publique ---------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def submit(self, payload: dict[str, Any]) -> bool:
        """Met un payload en file. Renvoie False si la file est pleine."""
        if not self.url:
            return False
        try:
            self._queue.put_nowait(payload)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def stats(self) -> dict[str, Any]:
        return {
            "queued": self._queue.qsize(),
            "sent": self.sent,
            "failed": self.failed,
            "dropped": self.dropped,
            "last_error": self.last_error,
            "endpoint": self.url,
        }

    def stop(self) -> None:
        """Arrete proprement le thread d'envoi."""
        self._stop.set()
        self._thread.join(timeout=2.0)

    # --- internes -------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._send_once(payload)
            if self.delay:
                time.sleep(self.delay)

    def _send_once(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        request = urllib.request.Request(
            self.url, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read()
            self.sent += 1
            self.last_error = None
        except urllib.error.HTTPError as exc:
            # 401/403 = mauvaise cle : inutile de reessayer en boucle.
            self.failed += 1
            self.last_error = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - reseau, DNS, timeout...
            self.failed += 1
            self.last_error = str(exc)
