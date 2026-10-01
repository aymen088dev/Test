"""Petit serveur HTTP interne.

Il sert deux choses :

* les fichiers statiques du dossier ``web/`` (le dashboard HTML/CSS/JS) ;
* ``GET /api/status`` -> un JSON construit par le plugin (joueurs, TPS, etc.).

Le serveur tourne dans un thread daemon : il ne bloque pas le thread principal
du serveur Minecraft et s'arrete avec le process.
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional, Tuple


class _Handler(SimpleHTTPRequestHandler):
    """Sert ``directory`` en statique, plus ``/api/status`` en JSON."""

    def __init__(
        self,
        *args: Any,
        directory: Optional[str] = None,
        status_provider: Optional[Callable[[], dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        self._status_provider = status_provider
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 (nom impose par la stdlib)
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        if route == "/api/status" and self._status_provider is not None:
            self._send_json(self._status_provider())
            return
        super().do_GET()

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # noqa: D401
        """Silencieux : on ne pollue pas la console du serveur Minecraft."""
        return


def start(
    host: str,
    port: int,
    directory: Any,
    status_provider: Callable[[], dict[str, Any]],
) -> Tuple[ThreadingHTTPServer, threading.Thread]:
    """Demarre le serveur web et renvoie ``(httpd, thread)``.

    Leve ``OSError`` si le port est deja pris ou non autorise.
    """
    handler = partial(_Handler, directory=str(directory), status_provider=status_provider)
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="endstone-webui", daemon=True)
    thread.start()
    return httpd, thread
