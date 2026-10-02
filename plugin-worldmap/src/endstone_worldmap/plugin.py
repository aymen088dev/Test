"""WorldMap - scanne le monde et pousse la carte en direct vers Node.js.

Commandes :
    /map          etat du scan et de la connexion au serveur de carte
    /mapscan      lance (ou relance) le scan
    /mapstop      arrete le scan

Le scan tourne sur le thread principal du serveur (contrainte de l'API
Endstone) ; l'envoi HTTP part dans un thread a part entiere.
"""

import json
import urllib.error
import urllib.request
from collections import deque
from typing import Any, Deque, Optional, Tuple

from endstone import ColorFormat
from endstone.command import Command, CommandSender
from endstone.event import PlayerQuitEvent, event_handler
from endstone.plugin import Plugin
from typing_extensions import override

from .scanner import build_queue, get_dimension, resolve_dimension_id, scan_chunk
from .sender import MapSender

QueueItem = Tuple[str, int, int]


class WorldMapPlugin(Plugin):
    prefix = "WorldMap"

    # Doit correspondre a la version majeure.mineure de l'API Endstone ciblee.
    api_version = "0.11"

    commands = {
        "map": {
            "description": "Affiche l'etat de la carte en direct",
            "usages": ["/map"],
            "permissions": ["worldmap.command.map"],
        },
        "mapscan": {
            "description": "Scanne le monde et l'envoie a la carte web",
            "usages": ["/mapscan", "/mapscan [radius: int]"],
            "permissions": ["worldmap.command.mapscan"],
        },
        "mapstop": {
            "description": "Arrete le scan en cours",
            "usages": ["/mapstop"],
            "permissions": ["worldmap.command.mapstop"],
        },
        "maptest": {
            "description": "Teste la connexion et la cle d'API du serveur de carte",
            "usages": ["/maptest"],
            "permissions": ["worldmap.command.maptest"],
        },
    }

    permissions = {
        "worldmap.command.map": {
            "description": "Permet d'utiliser /map",
            "default": True,
        },
        "worldmap.command.mapscan": {
            "description": "Permet d'utiliser /mapscan",
            "default": "op",
        },
        "worldmap.command.mapstop": {
            "description": "Permet d'utiliser /mapstop",
            "default": "op",
        },
        "worldmap.command.maptest": {
            "description": "Permet d'utiliser /maptest",
            "default": "op",
        },
    }

    # --- etat -----------------------------------------------------------

    _queue: Deque[QueueItem] = deque()
    _dims: dict[str, Any] = {}
    _sender: Optional[MapSender] = None
    _scanning = False
    _total = 0
    _processed = 0
    _errors = 0
    _empty = 0
    _logged = 0

    # --- cycle de vie ----------------------------------------------------

    @override
    def on_enable(self) -> None:
        # Copie config.toml dans le dossier du plugin au premier demarrage.
        self.save_default_config()
        # Endstone met la config en cache des le chargement du plugin : sans ce
        # rechargement, le tout premier demarrage (celui qui vient d'ecrire le
        # config.toml) tourne encore avec une config vide -> api_key vide ->
        # tous les envois refuses en 401. On force la relecture du fichier.
        try:
            self.reload_config()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"Rechargement de la config impossible : {exc}")
        self.logger.info(f"Configuration : {self.data_folder / 'config.toml'}")

        self._queue = deque()
        self._dims = {}
        self._scanning = False
        self._total = 0
        self._processed = 0
        self._errors = 0
        self._empty = 0
        self._logged = 0

        self._sender = MapSender(
            endpoint=self._cfg_str("endpoint", ""),
            api_key=self._cfg_str("api_key", ""),
            delay_ms=self._cfg_int("send_delay_ms", 50),
            logger=self.logger.info,
        )

        if not self._sender.configured:
            self.logger.error(
                "Aucun endpoint configure : mets 'endpoint' dans config.toml."
            )
        else:
            self.logger.info(f"Serveur de carte : {self._sender.url}")
            self.logger.info(
                f"Cle d'API chargee : {len(self._sender.api_key)} caracteres"
            )
            if not self._sender.api_key:
                self.logger.warning(
                    "api_key vide : si le serveur exige une cle, tous les "
                    "envois seront refuses en HTTP 401."
                )

        # Le plugin porte un @event_handler (PlayerQuitEvent) -> on l'enregistre.
        self.register_events(self)

        if self._cfg_bool("auto_scan", True):
            self._begin_scan(None)

        self.logger.info("WorldMap active.")

    @override
    def on_disable(self) -> None:
        self._scanning = False
        if self._sender is not None:
            self._sender.stop()
            self._sender = None
        self.logger.info("WorldMap desactive.")

    @override
    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name == "map":
            self._cmd_status(sender)
            return True
        if command.name == "mapscan":
            radius: Optional[int] = None
            if args:
                try:
                    radius = int(args[0])
                except ValueError:
                    sender.send_error_message("Usage: /mapscan [radius]")
                    return False
            self._begin_scan(sender, radius)
            return True
        if command.name == "mapstop":
            self._cmd_stop(sender)
            return True
        if command.name == "maptest":
            self._cmd_test(sender)
            return True
        return False

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        """Stoppe le scan quand plus personne n'est en ligne (option)."""
        if not self._scanning or not self._cfg_bool("stop_when_empty", False):
            return
        if not self.server.online_players:
            self._scanning = False
            self.logger.info("Plus personne en ligne : scan en pause.")

    # --- commandes -------------------------------------------------------

    def _cmd_status(self, sender: CommandSender) -> None:
        key_len = len(self._sender.api_key) if self._sender else 0
        sender.send_message(
            f"{ColorFormat.GOLD}Carte{ColorFormat.RESET} : "
            f"{ColorFormat.WHITE}{self._endpoint()} "
            f"{ColorFormat.GRAY}cle {ColorFormat.WHITE}{key_len}"
            f"{ColorFormat.GRAY} caracteres"
        )
        state = f"{self._processed}/{self._total}" if self._scanning else "arrete"
        sender.send_message(
            f"{ColorFormat.GRAY}Scan {ColorFormat.WHITE}{state} "
            f"{ColorFormat.GRAY}chunks | erreurs {ColorFormat.WHITE}{self._errors} "
            f"{ColorFormat.GRAY}| vides {ColorFormat.WHITE}{self._empty}"
        )
        stats = self._sender.stats() if self._sender else {}
        error = stats.get("last_error")
        sender.send_message(
            f"{ColorFormat.GRAY}Envoyes {ColorFormat.WHITE}{stats.get('sent', 0)} "
            f"{ColorFormat.GRAY}| en file {ColorFormat.WHITE}{stats.get('queued', 0)} "
            f"{ColorFormat.GRAY}| echecs {ColorFormat.WHITE}{stats.get('failed', 0)} "
            f"{ColorFormat.GRAY}| perdus {ColorFormat.WHITE}{stats.get('dropped', 0)}"
        )
        if error:
            sender.send_message(f"{ColorFormat.RED}Derniere erreur : {error}")

    def _cmd_test(self, sender: CommandSender) -> None:
        """Envoie un payload volontairement invalide pour tester la cle / l'URL.

        Le serveur valide la cle AVANT le corps : si la cle est bonne il
        repond 422 (payload invalide) sans rien stocker ; si elle est fausse
        il repond 401. Ca teste donc la connexion sans polluer la carte.
        """
        if self._sender is None or not self._sender.configured:
            sender.send_error_message("Aucun endpoint configure (config.toml).")
            return

        url = self._sender.url
        key_len = len(self._sender.api_key)
        sender.send_message(
            f"{ColorFormat.GOLD}Test{ColorFormat.RESET} -> {ColorFormat.WHITE}{url}"
            f" {ColorFormat.GRAY}(cle {ColorFormat.WHITE}{key_len}"
            f"{ColorFormat.GRAY} caracteres)"
        )

        headers = {"Content-Type": "application/json"}
        if self._sender.api_key:
            headers["X-Api-Key"] = self._sender.api_key
        body = json.dumps({"dim": "worldmap-selftest"}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                code = response.status
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                text = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                text = ""
        except Exception as exc:  # noqa: BLE001 - reseau, DNS, timeout...
            sender.send_message(f"{ColorFormat.RED}Echec reseau : {exc}")
            return

        color = ColorFormat.GREEN if code == 422 else ColorFormat.RED
        sender.send_message(
            f"{color}HTTP {code}{ColorFormat.RESET} {ColorFormat.GRAY}{text}"
        )
        if code == 422:
            sender.send_message(
                f"{ColorFormat.GREEN}La cle est ACCEPTEE par le serveur."
            )
        elif code == 401:
            sender.send_message(
                f"{ColorFormat.RED}Cle REFUSEE : la valeur du plugin ne "
                f"correspond pas a la cle du serveur de carte."
            )

    def _cmd_stop(self, sender: CommandSender) -> None:
        if not self._scanning:
            sender.send_message(f"{ColorFormat.GRAY}Aucun scan en cours.")
            return
        self._scanning = False
        sender.send_message(
            f"{ColorFormat.YELLOW}Scan arrete ({self._processed}/{self._total})."
        )

    def _begin_scan(
        self,
        sender: Optional[CommandSender],
        radius: Optional[int] = None,
    ) -> None:
        if self._sender is None or not self._sender.configured:
            if sender:
                sender.send_error_message("Aucun endpoint configure (config.toml).")
            return

        level = getattr(self.server, "level", None)
        if level is None:
            if sender:
                sender.send_error_message("Aucun monde charge.")
            return

        # Dimensions demandees
        dims: dict[str, Any] = {}
        missing: list[str] = []
        for name in self._cfg_list("dimensions", ["overworld"]):
            dim_id = resolve_dimension_id(name)
            dim = get_dimension(level, name)
            if dim is None:
                missing.append(name)
            else:
                dims[dim_id] = dim

        if not dims:
            if sender:
                sender.send_error_message(f"Dimensions introuvables : {missing}")
            return

        center_x, center_z = self._center(level)
        if radius is None:
            radius = self._cfg_int("radius_chunks", 32)

        queue = build_queue(center_x, center_z, radius, list(dims.keys()))

        self._dims = dims
        self._queue = deque(queue)
        self._total = len(queue)
        self._processed = 0
        self._errors = 0
        self._empty = 0
        self._logged = 0
        self._scanning = True

        # On purge un eventuel scan precedent en planifiant une seule tache.
        self._schedule_next(delay=1)

        message = (
            f"{ColorFormat.GREEN}Scan lance : {ColorFormat.WHITE}{self._total} "
            f"{ColorFormat.GRAY}chunks ({ColorFormat.WHITE}rayon {radius}"
            f"{ColorFormat.GRAY}) vers {ColorFormat.WHITE}{self._endpoint()}"
        )
        if missing:
            message += f"\n{ColorFormat.YELLOW}Dimensions ignorees : {missing}"
        if sender:
            sender.send_message(message)
        self.logger.info(
            f"Scan lance : {self._total} chunks, rayon {radius}, "
            f"dims {sorted(dims)} -> {center_x}, {center_z}"
        )

    # --- boucle de scan --------------------------------------------------

    def _schedule_next(self, delay: int = 1) -> None:
        if not self._scanning:
            return
        try:
            self.server.scheduler.run_task(self, self._scan_step, delay=delay)
        except Exception as exc:  # noqa: BLE001
            self._scanning = False
            self.logger.error(f"Impossible de planifier le scan : {exc}")

    def _scan_step(self) -> None:
        """Traite quelques chunks, puis se replanifie au tick suivant."""
        if not self._scanning:
            return

        if not self._queue:
            self._scanning = False
            stats = self._sender.stats() if self._sender else {}
            self.logger.info(
                f"Scan termine : {self._processed} chunks | "
                f"vides {self._empty} | envoyes {stats.get('sent', 0)} | "
                f"echecs {stats.get('failed', 0)} | "
                f"erreur {stats.get('last_error') or '-'}"
            )
            return

        budget = max(1, self._cfg_int("chunks_per_tick", 2))
        depth = self._cfg_int("depth", 4)
        done = 0

        # Le budget compte CHAQUE chunk retire de la file : meme si la lecture
        # echoue on ne traite jamais plus de `budget` chunks par tick (sinon la
        # boucle peut vider toute la file d'un coup et figer le serveur).
        while done < budget and self._queue:
            dim_id, cx, cz = self._queue.popleft()
            done += 1

            dim = self._dims.get(dim_id)
            if dim is None:
                continue

            try:
                # On lit les colonnes directement : BDS charge le chunk au
                # besoin (comme BlueMap). L'API Endstone 0.11 n'expose PAS de
                # is_chunk_generated ; l'appeler faisait echouer chaque chunk.
                payload = scan_chunk(dim, dim_id, cx, cz, depth)
            except Exception as exc:  # noqa: BLE001
                self._errors += 1
                if self._errors <= 3:
                    self.logger.warning(f"Chunk {cx},{cz} ({dim_id}) : {exc}")
                continue

            self._processed += 1
            if payload is None:
                # Chunk lu mais sans aucun bloc : rien a envoyer. On le compte
                # a part pour ne pas le confondre avec un envoi qui a marche.
                self._empty += 1
            elif self._sender is not None:
                self._sender.submit(payload)

        # Trace de progression : permet de voir si les envois partent vraiment.
        if self._processed - self._logged >= 250:
            self._logged = self._processed
            stats = self._sender.stats() if self._sender else {}
            self.logger.info(
                f"Scan {self._processed}/{self._total} | "
                f"envoyes {stats.get('sent', 0)} | "
                f"echecs {stats.get('failed', 0)} | "
                f"file {stats.get('queued', 0)} | "
                f"erreur {stats.get('last_error') or '-'}"
            )

        self._schedule_next(delay=1)

    # --- helpers ---------------------------------------------------------

    def _endpoint(self) -> str:
        if self._sender is None:
            return "(non configure)"
        return self._sender.url or "(non configure)"

    def _center(self, level: Any) -> Tuple[int, int]:
        """Centre du scan : config si renseignee, sinon le spawn du monde."""
        center_x = self._cfg_int("center_x", 0)
        center_z = self._cfg_int("center_z", 0)
        if center_x != 0 or center_z != 0:
            return center_x, center_z

        spawn = getattr(level, "spawn", None)
        spawn_x = getattr(spawn, "x", None)
        spawn_z = getattr(spawn, "z", None)
        if spawn_x is not None and spawn_z is not None:
            return int(spawn_x), int(spawn_z)
        return 0, 0

    def _cfg_str(self, key: str, default: str) -> str:
        try:
            value = self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default
        return default if value is None else str(value)

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _cfg_bool(self, key: str, default: bool) -> bool:
        try:
            value = self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _cfg_list(self, key: str, default: list[str]) -> list[str]:
        try:
            value = self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default
        if isinstance(value, str):
            return [part for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        return default
