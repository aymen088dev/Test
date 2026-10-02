"""Lecture du monde : pour chaque chunk, la surface des colonnes.

Format du payload envoye au serveur Node.js (JSON) :

    {
      "v": 1,
      "dim": "overworld",
      "cx": 3, "cz": -2,     # coordonnees du chunk
      "depth": 4,            # blocs solides max par colonne
      "palette": ["minecraft:stone", ...],
      "cells": [ [y, p, y, p, ...], ... ]   # 256 entrees, index = lz*16 + lx
    }

Chaque "cell" contient les paires (y, index_de_palette) allant du bloc le plus
haut vers le bas, en ignorant l'air. Avec ``depth = 1`` on obtient une simple
heightmap ; avec ``depth >= 3`` on recolte aussi les parois des falaises, ce qui
donne un rendu isometrique type BlueMap.
"""

from __future__ import annotations

from typing import Any, Optional

AIR = "minecraft:air"


def _block_id(block: Any) -> str:
    """Identifiant d'un bloc, tolerant aux versions d'Endstone.

    Endstone 0.11 expose ``Block.type`` comme une **chaine** (ex.
    ``"minecraft:grass_block"``). Lire ``block.type.id`` levait donc une
    AttributeError attrapee plus haut et faisait passer *chaque* colonne pour
    de l'air : les chunks partaient vides, sans erreur visible. On accepte
    aussi un objet BlockType (attribut ``id``) pour rester compatible.
    """
    try:
        block_type = block.type
    except Exception:  # noqa: BLE001
        return AIR
    if isinstance(block_type, str):
        return block_type
    return str(getattr(block_type, "id", block_type))

# Dimension "overworld" -> identifiant complet attendu par Endstone
DIMENSION_IDS = {
    "overworld": "minecraft:overworld",
    "nether": "minecraft:nether",
    "the_end": "minecraft:the_end",
    "minecraft:overworld": "minecraft:overworld",
    "minecraft:nether": "minecraft:nether",
    "minecraft:the_end": "minecraft:the_end",
}


def resolve_dimension_id(name: str) -> str:
    """Traduit 'overworld' -> 'minecraft:overworld' (et recoit l'inverse)."""
    return DIMENSION_IDS.get(str(name).lower().strip(), str(name).strip())


def get_dimension(level: Any, name: str) -> Any:
    """Recupere l'objet Dimension, ou None si elle n'existe pas."""
    dim_id = resolve_dimension_id(name)
    for candidate in (dim_id, dim_id.split(":", 1)[-1], name):
        try:
            dim = level.get_dimension(candidate)
        except Exception:  # noqa: BLE001 - API C++ susceptible de lever partout
            dim = None
        if dim is not None:
            return dim
    return None


def scan_chunk(
    dim: Any,
    dim_id: str,
    cx: int,
    cz: int,
    depth: int,
) -> Optional[dict[str, Any]]:
    """Lit les colonnes d'un chunk et renvoie le payload, ou None si vide."""
    if depth < 1:
        depth = 1

    palette: list[str] = []
    index: dict[str, int] = {}
    cells: list[list[int]] = []
    found_any = False

    base_x = cx << 4
    base_z = cz << 4

    for lz in range(16):
        for lx in range(16):
            x = base_x + lx
            z = base_z + lz
            cell: list[int] = []

            try:
                top = dim.get_highest_block_at(x, z)
            except Exception:  # noqa: BLE001
                top = None

            if top is not None:
                top_id = _block_id(top)
                if top_id and top_id != AIR:
                    top_y = int(top.y)
                    cell.append(top_y)
                    cell.append(_palette_index(palette, index, top_id))

                    # On descend pour recolter les parois visibles.
                    for offset in range(1, depth):
                        below_y = top_y - offset
                        try:
                            below = dim.get_block_at(x, below_y, z)
                        except Exception:  # noqa: BLE001
                            break
                        below_id = _block_id(below)
                        if not below_id or below_id == AIR:
                            break
                        cell.append(below_y)
                        cell.append(_palette_index(palette, index, below_id))

            if cell:
                found_any = True
            cells.append(cell)

    if not found_any:
        return None

    return {
        "v": 1,
        "dim": dim_id,
        "cx": cx,
        "cz": cz,
        "depth": depth,
        "palette": palette,
        "cells": cells,
    }


def _palette_index(palette: list[str], index: dict[str, int], block_id: str) -> int:
    idx = index.get(block_id)
    if idx is None:
        idx = len(palette)
        index[block_id] = idx
        palette.append(block_id)
    return idx


def build_queue(
    center_x: int,
    center_z: int,
    radius_chunks: int,
    dimensions: list[str],
) -> list[tuple[str, int, int]]:
    """Construit la liste (dim, cx, cz) a scanner autour d'un centre."""
    if radius_chunks < 1:
        radius_chunks = 1

    center_cx = center_x >> 4
    center_cz = center_z >> 4
    lo_x = center_cx - radius_chunks
    hi_x = center_cx + radius_chunks
    lo_z = center_cz - radius_chunks
    hi_z = center_cz + radius_chunks

    queue: list[tuple[str, int, int]] = []
    for name in dimensions:
        dim_id = resolve_dimension_id(name)
        # Tri par distance au centre : le coeur de la carte est pret en premier.
        ring = sorted(
            ((dx, dz) for dx in range(lo_x, hi_x + 1) for dz in range(lo_z, hi_z + 1)),
            key=lambda p: (p[0] - center_cx) ** 2 + (p[1] - center_cz) ** 2,
        )
        for cx, cz in ring:
            queue.append((dim_id, cx, cz))
    return queue
