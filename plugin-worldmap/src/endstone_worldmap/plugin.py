"""WorldMap - scanne le monde et pousse la carte en direct vers Node.js.

Commandes :
    /map          etat du scan et de la connexion au serveur de carte
    /mapscan      scanne une fois les chunks charges autour des joueurs
    /mapfollow    suit les joueurs en continu (carte "live")
    /mapstop      arrete tout

Principe cle : le serveur Bedrock ne garde en memoire que les chunks qui
entourent les joueurs (view-distance). L'API Endstone ne peut pas lire un
chunk non charge. Le plugin ne met donc en file QUE les chunks reellement
charges, centres sur la position des joueurs connectes.

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

from .scanner import (
    AIR,
    _block_id,
    build_queue_loaded,
    get_dimension,
    resolve_dimension_id,
    scan_chunk,
)
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
            "description": "Scanne les chunks charges autour des joueurs connectes",
            "usages": ["/mapscan", "/mapscan [radius: int]"],
            "permissions": ["worldmap.command.mapscan"],
        },
        "mapfollow": {
            "description": "Suit les joueurs en continu pour une carte live",
            "usages": ["/mapfollow"],
            "permissions": ["worldmap.command.mapfollow"],
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
        "worldmap.command.mapfollow": {
            "description": "Permet d'utiliser /mapfollow",
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
    _loaded: dict[str, set] = {}
    _sender: Optional[MapSender] = None
    _scanning = False
    _total = 0
    _processed = 0
    _errors = 0
    _empty = 0
    _non_charge = 0
    _popped = 0
    _logged = 0
    _following = False
    _seen: set = set()

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
        self._non_charge = 0
        self._popped = 0
        self._logged = 0
        self._following = False
        self._seen = set()

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

        auto_scan = self._cfg_bool("auto_scan", False)
        auto_follow = self._cfg_bool("auto_follow", True)
        if auto_follow:
            # Le suivi est prioritaire : au demarrage il n'y a aucun joueur,
            # donc un scan ponctuel ne pourrait rien produire de toute facon.
            # Il attend le premier joueur et construit la carte ensuite.
            self._start_follow(log=True)
        elif auto_scan:
            self._begin_scan(None)

        self.logger.info("WorldMap active.")

    @override
    def on_disable(self) -> None:
        self._scanning = False
        self._following = False
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
        if command.name == "mapfollow":
            self._cmd_follow(sender)
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
        """Le dernier joueur part -> plus aucun chunk charge, la carte gele.

        On ne coupe surtout pas le suivi : il repartira tout seul des que
        quelqu'un se reconnectera.
        """
        try:
            remaining = list(self.server.online_players or [])
        except Exception:  # noqa: BLE001
            remaining = []
        if not remaining and self._following:
            self.logger.info(
                "Plus personne en ligne : suivi en pause (reprise automatique)."
            )

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
        if self._following:
            state += " (suivi actif)"
        players = self._players()
        if players:
            where = ", ".join(f"{name} @ {x},{z}" for name, x, z in players[:3])
            loaded = sum(len(s) for s in self._loaded.values())
            sender.send_message(
                f"{ColorFormat.GRAY}Joueurs {ColorFormat.WHITE}{len(players)} "
                f"{ColorFormat.GRAY}({where}) | chunks charges "
                f"{ColorFormat.WHITE}{loaded}"
            )
        else:
            sender.send_message(
                f"{ColorFormat.RED}Aucun joueur connecte : BDS ne charge aucun "
                f"chunk, la carte ne peut pas avancer."
            )
        sender.send_message(
            f"{ColorFormat.GRAY}Scan {ColorFormat.WHITE}{state} "
            f"{ColorFormat.GRAY}chunks | erreurs {ColorFormat.WHITE}{self._errors} "
            f"{ColorFormat.GRAY}| vides {ColorFormat.WHITE}{self._empty} "
            f"{ColorFormat.GRAY}| non charges {ColorFormat.WHITE}{self._non_charge}"
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

        self._probe_world(sender)

    def _probe_world(self, sender: CommandSender) -> None:
        """Diagnostique le cote monde : centre, dimension, chunks charges."""
        level = getattr(self.server, "level", None)
        if level is None:
            sender.send_message(f"{ColorFormat.RED}Monde : aucun niveau charge.")
            return

        cx, cz, source = self._center(level)
        sender.send_message(
            f"{ColorFormat.GOLD}Monde{ColorFormat.RESET} centre "
            f"{ColorFormat.WHITE}{cx},{cz} "
            f"{ColorFormat.GRAY}({source})"
        )
        players = self._players()
        if players:
            sender.send_message(
                f"{ColorFormat.GRAY}Joueurs : "
                + ", ".join(
                    f"{ColorFormat.WHITE}{name} {ColorFormat.GRAY}@ {x},{z}"
                    for name, x, z in players
                )
            )
        else:
            sender.send_message(
                f"{ColorFormat.RED}Aucun joueur connecte."
            )

        base_cx, base_cz = cx >> 4, cz >> 4
        for name in self._cfg_list("dimensions", ["overworld"]):
            dim_id = resolve_dimension_id(name)
            dim = get_dimension(level, name)
            if dim is None:
                sender.send_message(
                    f"{ColorFormat.RED}dimension introuvable : {name}"
                )
                continue

            try:
                loaded = list(dim.loaded_chunks or [])
            except Exception as exc:  # noqa: BLE001
                loaded = []
                sender.send_message(
                    f"{ColorFormat.RED}loaded_chunks impossible : {exc}"
                )
            sender.send_message(
                f"{ColorFormat.GRAY}dim {ColorFormat.WHITE}{dim_id} "
                f"{ColorFormat.GRAY}| nom {ColorFormat.WHITE}"
                f"{getattr(dim, 'name', '?')} "
                f"{ColorFormat.GRAY}| chunks charges "
                f"{ColorFormat.WHITE}{len(loaded)}"
            )
            self._loaded[dim_id] = {(int(c.x), int(c.z)) for c in loaded}

            filled = 0
            first = ""
            for i in range(64):
                bx = base_cx + (i % 8) - 4
                bz = base_cz + (i // 8) - 4
                try:
                    block = dim.get_highest_block_at((bx << 4) + 8, (bz << 4) + 8)
                except Exception as exc:  # noqa: BLE001
                    sender.send_message(f"{ColorFormat.RED}exception : {exc}")
                    return
                if block is not None:
                    bid = _block_id(block)
                    if bid and bid != AIR:
                        filled += 1
                        if not first:
                            first = f"{bid} y={block.y}"
            sender.send_message(
                f"{ColorFormat.GRAY}64 chunks testes -> "
                f"{ColorFormat.WHITE}{filled} {ColorFormat.GRAY}avec blocs "
                f"{ColorFormat.GRAY}| {first or 'aucun'}"
            )

    def _cmd_stop(self, sender: CommandSender) -> None:
        if not self._scanning and not self._following:
            sender.send_message(f"{ColorFormat.GRAY}Aucun scan en cours.")
            return
        was_following = self._following
        self._scanning = False
        self._following = False
        sender.send_message(
            f"{ColorFormat.YELLOW}Scan arrete ({self._processed}/{self._total})"
            f"{ColorFormat.GRAY}, suivi {'actif -> coupe' if was_following else ''}"
        )

    def _cmd_follow(self, sender: CommandSender) -> None:
        if self._following:
            self._following = False
            sender.send_message(
                f"{ColorFormat.YELLOW}Suivi desactive"
                f"{ColorFormat.GRAY} (le scan en cours continue)."
            )
            return
        self._start_follow(log=True)
        interval = self._cfg_int("follow_interval_seconds", 10)
        sender.send_message(
            f"{ColorFormat.GREEN}Suivi actif{ColorFormat.RESET} : "
            f"{ColorFormat.GRAY}les nouveaux chunks charges autour des joueurs "
            f"sont envoyes toutes les {ColorFormat.WHITE}{interval}s"
        )

    def _start_follow(self, log: bool = False) -> None:
        """Active le mode suivi (carte live) et planifie la premiere passe."""
        if self._sender is None or not self._sender.configured:
            if log:
                self.logger.error("Suivi impossible : aucun endpoint configure.")
            return
        if getattr(self.server, "level", None) is None:
            if log:
                self.logger.error("Suivi impossible : aucun monde charge.")
            return
        self._following = True
        self._scanning = True
        self._seen = set()
        self._queue = deque()
        self._total = 0
        self._processed = 0
        self._errors = 0
        self._empty = 0
        self._non_charge = 0
        self._popped = 0
        self._logged = 0
        if not self._dims:
            self._dims = self._collect_dimensions()
        self._loaded = self._refresh_loaded()
        self._schedule_next(delay=2)
        if log:
            self.logger.info("Suivi des joueurs active.")

    def _players(self) -> list[tuple[str, int, int]]:
        """(nom, x, z) des joueurs connectes."""
        try:
            online = list(self.server.online_players or [])
        except Exception:  # noqa: BLE001
            return []

        out: list[tuple[str, int, int]] = []
        for player in online:
            loc = getattr(player, "location", None)
            if loc is None:
                loc = getattr(player, "position", None)
            x = getattr(loc, "x", None)
            z = getattr(loc, "z", None)
            if x is None:
                x = getattr(player, "x", None)
            if z is None:
                z = getattr(player, "z", None)
            if x is None or z is None:
                continue
            try:
                name = str(getattr(player, "name", "?"))
                out.append((name, int(x), int(z)))
            except Exception:  # noqa: BLE001
                continue
        return out

    def _collect_dimensions(self) -> dict[str, Any]:
        """Dimension configurees -> {dim_id: objet Dimension}."""
        level = getattr(self.server, "level", None)
        dims: dict[str, Any] = {}
        if level is None:
            return dims
        for name in self._cfg_list("dimensions", ["overworld"]):
            dim_id = resolve_dimension_id(name)
            dim = get_dimension(level, name)
            if dim is not None:
                dims[dim_id] = dim
        return dims

    def _follow_delay(self) -> int:
        """Attente en ticks entre deux passes de suivi."""
        seconds = max(1, self._cfg_int("follow_interval_seconds", 10))
        return seconds * 20

    def _refill(self) -> int:
        """Ajoute en file les chunks charges qui n'ont pas encore ete envoyes."""
        players = self._players()
        if not players:
            return 0
        if not self._dims:
            self._dims = self._collect_dimensions()
        self._loaded = self._refresh_loaded()
        fresh = build_queue_loaded(
            [(x, z) for _name, x, z in players],
            self._cfg_int("radius_chunks", 0),
            list(self._dims.keys()),
            self._loaded,
            seen=self._seen,
        )
        if fresh:
            self._queue.extend(fresh)
            self._total += len(fresh)
        return len(fresh)

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

        dims = self._collect_dimensions()
        if not dims:
            if sender:
                sender.send_error_message(
                    "Dimensions introuvables : "
                    f"{self._cfg_list('dimensions', ['overworld'])}"
                )
            return

        if radius is None:
            radius = self._cfg_int("radius_chunks", 0)

        players = self._players()
        self._dims = dims
        self._loaded = self._refresh_loaded()
        loaded_total = sum(len(s) for s in self._loaded.values())

        # Sans joueur connecte, BDS ne charge aucun chunk : on le dit clairement
        # plutot que de lancer un scan qui ne peut rien produire.
        if not players:
            msg = (
                f"{ColorFormat.RED}Aucun joueur connecte.{ColorFormat.RESET} "
                f"{ColorFormat.GRAY}Le serveur Bedrock ne charge que les chunks "
                f"autour des joueurs ({loaded_total} charges actuellement). "
                f"Connecte-toi puis relance /mapscan."
            )
            if sender:
                sender.send_message(msg)
            else:
                self.logger.warning(msg)
            return

        queue = build_queue_loaded(
            [(x, z) for _name, x, z in players],
            radius,
            list(dims.keys()),
            self._loaded,
        )

        self._following = False
        self._seen = set()
        self._queue = deque(queue)
        self._total = len(queue)
        self._processed = 0
        self._errors = 0
        self._empty = 0
        self._non_charge = 0
        self._popped = 0
        self._logged = 0
        self._scanning = True

        # On purge un eventuel scan precedent en planifiant une seule tache.
        self._schedule_next(delay=1)

        where = ", ".join(f"{name} @ {x},{z}" for name, x, z in players)
        message = (
            f"{ColorFormat.GREEN}Scan lance : {ColorFormat.WHITE}{self._total} "
            f"{ColorFormat.GRAY}chunks charges vers "
            f"{ColorFormat.WHITE}{self._endpoint()}\n"
            f"{ColorFormat.GRAY}Joueurs : {ColorFormat.WHITE}{where} "
            f"{ColorFormat.GRAY}| chunks charges en memoire : "
            f"{ColorFormat.WHITE}{loaded_total}"
            + (
                f"\n{ColorFormat.GRAY}Rayon limite a {ColorFormat.WHITE}{radius}"
                f"{ColorFormat.GRAY} chunks autour de chaque joueur."
                if radius > 0
                else ""
            )
        )
        if sender:
            sender.send_message(message)
        self.logger.info(
            f"Scan lance : {self._total} chunks charges sur {loaded_total}, "
            f"rayon {radius}, dims {sorted(dims)}, joueurs {where}"
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
            if self._following:
                # Mode carte live : on cherche les nouveaux chunks charges.
                found = self._refill()
                if not found:
                    self._schedule_next(delay=self._follow_delay())
                    return
            else:
                self._scanning = False
                self._log_end()
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
            self._popped += 1
            if self._popped % 200 == 0:
                self._loaded = self._refresh_loaded()

            dim = self._dims.get(dim_id)
            if dim is None:
                continue

            # Filet de securite : BDS peut decharger un chunk entre la mise en
            # file et son traitement. On ne produit alors pas de chunk vide.
            loaded = self._loaded.get(dim_id)
            if loaded is not None and (cx, cz) not in loaded:
                self._non_charge += 1
                continue

            try:
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
            else:
                if len(self._seen) > 400000:
                    self._seen.clear()
                self._seen.add((dim_id, cx, cz))
                if self._sender is not None:
                    self._sender.submit(payload)

        # Trace de progression : permet de voir si les envois partent vraiment.
        if self._processed - self._logged >= 250:
            self._logged = self._processed
            self._log_progress()

        self._schedule_next(delay=1)

    def _log_progress(self) -> None:
        stats = self._sender.stats() if self._sender else {}
        self.logger.info(
            f"Scan {self._processed}/{self._total} | "
            f"envoyes {stats.get('sent', 0)} | "
            f"echecs {stats.get('failed', 0)} | "
            f"file {stats.get('queued', 0)} | "
            f"erreur {stats.get('last_error') or '-'}"
        )

    def _log_end(self) -> None:
        stats = self._sender.stats() if self._sender else {}
        self.logger.info(
            f"Scan termine : {self._processed} chunks | "
            f"vides {self._empty} | non charges {self._non_charge} | "
            f"envoyes {stats.get('sent', 0)} | "
            f"echecs {stats.get('failed', 0)} | "
            f"erreur {stats.get('last_error') or '-'}"
        )

    # --- helpers ---------------------------------------------------------

    def _endpoint(self) -> str:
        if self._sender is None:
            return "(non configure)"
        return self._sender.url or "(non configure)"

    def _center(self, level: Any) -> Tuple[int, int, str]:
        """Centre du scan : config -> joueur en ligne -> spawn -> 0,0.

        Important : sur Endstone 0.11 ``Level`` n'expose PAS d'attribut
        ``spawn``. Sans joueur en ligne on retombait donc sur (0,0), souvent
        hors des chunks charges -> tout le scan sortait vide ("vides 4225").
        """
        center_x = self._cfg_int("center_x", 0)
        center_z = self._cfg_int("center_z", 0)
        if center_x != 0 or center_z != 0:
            return center_x, center_z, "config"

        try:
            players = list(self.server.online_players or [])
        except Exception:  # noqa: BLE001
            players = []
        for player in players:
            loc = getattr(player, "location", None)
            if loc is None:
                loc = getattr(player, "position", None)
            x = getattr(loc, "x", None)
            z = getattr(loc, "z", None)
            if x is None:
                x = getattr(player, "x", None)
            if z is None:
                z = getattr(player, "z", None)
            if x is not None and z is not None:
                try:
                    return int(x), int(z), "joueur"
                except Exception:  # noqa: BLE001
                    pass

        spawn = getattr(level, "spawn", None)
        x = getattr(spawn, "x", None)
        z = getattr(spawn, "z", None)
        if x is not None and z is not None:
            try:
                return int(x), int(z), "spawn"
            except Exception:  # noqa: BLE001
                pass

        return 0, 0, "origine"

    def _refresh_loaded(self) -> dict[str, set]:
        """Coordonnees (cx, cz) des chunks actuellement charges par BDS."""
        out: dict[str, set] = {}
        for dim_id, dim in self._dims.items():
            coords: set = set()
            try:
                for chunk in dim.loaded_chunks or []:
                    coords.add((int(chunk.x), int(chunk.z)))
            except Exception:  # noqa: BLE001 - API C++ variable
                coords = set()
            out[dim_id] = coords
        return out

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
