#!/usr/bin/env python3
"""Test d'integration : scan -> envoi HTTP -> serveur Node.js.

Ne necessite PAS Endstone : les modules scanner.py et sender.py sont charges
directement (ils n'importent que la bibliotheque standard).

    python3 test_pipeline.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src" / "endstone_worldmap"
MAPSERVER = HERE.parent / "mapserver"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scanner = load("ws_scanner", SRC / "scanner.py")
sender_mod = load("ws_sender", SRC / "sender.py")


# --- faux monde -------------------------------------------------------


class FakeBlock:
    def __init__(self, x: int, y: int, z: int, block_id: str) -> None:
        self.x, self.y, self.z = x, y, z
        # Endstone 0.11 : Block.type est une CHAINE, pas un objet BlockType.
        # Le test doit refleter l'API reelle pour attraper ce genre de bug.
        self.type = block_id


class FakeDimension:
    """Colonne de surface a y=64, avec 4 blocs de profondeur."""

    def __init__(self) -> None:
        self.surface = {}
        for x in range(0, 32):
            for z in range(0, 32):
                self.surface[(x, z)] = (64, "minecraft:grass_block")

    def is_chunk_generated(self, cx: int, cz: int) -> bool:
        return True

    def get_highest_block_at(self, x: int, z: int):
        top = self.surface.get((x, z))
        if not top:
            return None
        return FakeBlock(x, top[0], z, top[1])

    def get_block_at(self, x: int, y: int, z: int):
        top = self.surface.get((x, z))
        if not top or y > top[0]:
            return FakeBlock(x, y, z, "minecraft:air")
        depth = top[0] - y
        block_id = "minecraft:grass_block" if depth == 0 else "minecraft:stone"
        return FakeBlock(x, y, z, block_id)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> int:
    # 1) build_queue -----------------------------------------------------
    queue = scanner.build_queue(0, 0, 2, ["overworld"])
    assert len(queue) == 25, f"rayon 2 -> 25 chunks, obtenu {len(queue)}"
    assert scanner.resolve_dimension_id("overworld") == "minecraft:overworld"
    assert scanner.resolve_dimension_id("nether") == "minecraft:nether"
    print("[1/4] build_queue + dimensions            OK")

    # 2) scan_chunk ------------------------------------------------------
    dim = FakeDimension()
    dim_id = scanner.resolve_dimension_id("overworld")
    payload = scanner.scan_chunk(dim, dim_id, 0, 0, depth=4)
    assert payload is not None, "le chunk ne doit pas etre vide"
    assert len(payload["cells"]) == 256, "256 colonnes"
    cell = payload["cells"][0]
    assert len(cell) == 8, f"4 paires (y, palette), obtenu {len(cell)}"
    assert cell[0] == 64, "bloc du dessus a y=64"
    assert cell[2] == 63 and cell[4] == 62 and cell[6] == 61, "profondeur respectee"
    assert "minecraft:grass_block" in payload["palette"]
    assert "minecraft:stone" in payload["palette"]

    vide = scanner.scan_chunk(dim, dim_id, 10, 10, depth=4)
    assert vide is None, "hors surface -> pas de payload"
    print("[2/4] scan_chunk (surface, profondeur)     OK")

    # 3) serveur Node.js -------------------------------------------------
    port = free_port()
    env = dict(os.environ)
    env["PORT"] = str(port)
    env["MAP_API_KEY"] = "test-key"
    env["MAP_DATA_FILE"] = str(HERE / "_tmp_data.ndjson")
    proc = subprocess.Popen(
        ["node", str(MAPSERVER / "server.js")],
        cwd=str(MAPSERVER),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(80):
            try:
                status = http_get(base + "/api/status")
                break
            except Exception:
                time.sleep(0.1)
        else:
            out = proc.stdout.read().decode() if proc.stdout else ""
            raise AssertionError("serveur Node jamais pret : " + out)
        assert status["chunks"] == 0, "base de donnees vierge"

        # 4) envoi via MapSender -----------------------------------------
        sender = sender_mod.MapSender(base, api_key="test-key", delay_ms=10)
        # Mauvaise cle : on verifie que le serveur refuse.
        bad = sender_mod.MapSender(base, api_key="wrong", delay_ms=10)
        bad.submit(payload)
        for _ in range(100):
            if bad.failed or bad.sent:
                break
            time.sleep(0.05)
        assert bad.failed > 0, "une cle erronee doit etre refusee"
        bad.stop()

        assert sender.submit(payload), "le payload doit partir en file"
        for _ in range(120):
            status = http_get(base + "/api/status")
            if status["chunks"] >= 1:
                break
            time.sleep(0.05)
        assert status["chunks"] == 1, f"chunk recu, obtenu {status['chunks']}"

        meta = http_get(base + "/api/meta?dim=" + dim_id)
        assert meta["count"] == 1
        tile = http_get(base + "/api/tile/" + dim_id + "/0/0")
        assert len(tile["chunks"]) == 1
        one = http_get(base + "/api/chunk/" + dim_id + "/0/0")
        assert one["palette"] == payload["palette"]
        sender.stop()

        # Le serveur web sert l'interface.
        with urllib.request.urlopen(base + "/", timeout=5) as res:
            html = res.read().decode("utf-8")
        assert "<!DOCTYPE html>" in html
        for asset in ("/styles.css", "/map.js", "/blocks.js"):
            with urllib.request.urlopen(base + asset, timeout=5) as res:
                assert res.status == 200, asset
        print("[3/4] serveur Node + API                  OK")
        print("[4/4] MapSender HTTP + interface          OK")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        tmp = HERE / "_tmp_data.ndjson"
        if tmp.exists():
            tmp.unlink()

    print("\nTOUT EST VERT - scanner, envoi et serveur fonctionnent ensemble.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
