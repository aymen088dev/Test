"""WebUI - commande ``/test`` : menu in-game + acces au tableau de bord web.

Rappel : Minecraft Bedrock ne peut pas afficher de HTML directement en jeu.
Le plugin ouvre donc un *menu natif* en jeu, et peut aussi donner au joueur un
lien vers un vrai dashboard HTML/CSS/JS servi par le serveur web interne.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from endstone import ColorFormat, Player
from endstone.command import Command, CommandSender
from endstone.form import ActionForm
from endstone.plugin import Plugin
from typing_extensions import override

from . import server as web_server

WEB_DIR = Path(__file__).parent / "web"


class WebUIPlugin(Plugin):
    prefix = "WebUI"

    # Doit correspondre a la version majeure.mineure de l'API Endstone ciblee.
    api_version = "0.11"

    commands = {
        "test": {
            "description": "Ouvre le menu du serveur (et le tableau de bord web)",
            "usages": ["/test", "/test [action: str]"],
            "permissions": ["webui.command.test"],
        },
    }

    permissions = {
        "webui.command.test": {
            "description": "Autorise la commande /test",
            "default": True,
        },
    }

    _httpd: Any = None
    _thread: Any = None

    # --- cycle de vie ----------------------------------------------------

    @override
    def on_enable(self) -> None:
        self.save_default_config()
        self._start_web()
        self.logger.info("WebUI active.")

    @override
    def on_disable(self) -> None:
        self._stop_web()
        self.logger.info("WebUI desactive.")

    # --- serveur web -----------------------------------------------------

    def _start_web(self) -> None:
        host = str(self.config.get("web_host", "0.0.0.0"))
        port = self._config_int("web_port", 8090)
        try:
            self._httpd, self._thread = web_server.start(host, port, WEB_DIR, self._status)
        except OSError as exc:
            self._httpd = None
            self.logger.error(
                f"Interface web indisponible sur {host}:{port} ({exc}). "
                "Le port est-il bien alloue et libre ?"
            )
            return
        self.logger.info(f"Interface web -> http://{host}:{port}/")

    def _stop_web(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def _config_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    # --- donnees exposees par /api/status --------------------------------

    def _status(self) -> dict[str, Any]:
        server = self.server
        players = [self._player_info(p) for p in server.online_players]
        return {
            "server_name": server.name,
            "software": server.version,
            "minecraft_version": str(server.minecraft_version),
            "players_online": len(players),
            "max_players": int(server.max_players),
            "players": players,
            "tps": round(float(server.average_tps), 2),
            "mspt": round(float(server.average_mspt), 2),
            "uptime_seconds": self._uptime_seconds(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _player_info(self, player: Player) -> dict[str, Any]:
        return {
            "name": player.name,
            "ping": int(player.ping),
            "device": str(player.device_os),
            "gamemode": str(player.game_mode),
            "op": bool(player.is_op),
        }

    def _uptime_seconds(self) -> Optional[int]:
        started = getattr(self.server, "start_time", None)
        if started is None:
            return None
        now = datetime.now(started.tzinfo) if started.tzinfo else datetime.now()
        return max(0, int((now - started).total_seconds()))

    def _public_url(self) -> str:
        """URL affichee aux joueurs (a configurer dans config.toml)."""
        url = str(self.config.get("public_url", "") or "").strip()
        if url:
            return url.rstrip("/") + "/"
        port = self._config_int("web_port", 8090)
        return f"http://<IP_DU_SERVEUR>:{port}/"

    # --- commande --------------------------------------------------------

    @override
    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name != "test":
            return False

        if not isinstance(sender, Player):
            self.logger.info(f"Tableau de bord web : {self._public_url()}")
            return True

        action = args[0].lower() if args else ""
        if action in ("web", "url", "lien"):
            self._send_link(sender)
        else:
            self._open_menu(sender)
        return True

    def _open_menu(self, player: Player) -> None:
        form = ActionForm(
            title="§lInterface du serveur",
            content="§7Menus, infos et tableau de bord web.\n§8Bienvenue " + player.name,
        )
        form.add_button(text="§bTableau de bord web", on_click=self._send_link)
        form.add_button(text="§aMon profil", on_click=self._profil)
        form.add_button(text="§eJoueurs en ligne", on_click=self._joueurs)
        form.add_button(text="§7Infos serveur", on_click=self._infos)
        form.add_divider()
        form.add_button(text="§8Fermer", on_click=lambda p: p.close_form())
        player.send_form(form)

    def _send_link(self, player: Player) -> None:
        url = self._public_url()
        player.send_message(
            f"{ColorFormat.GREEN}Tableau de bord : {ColorFormat.AQUA}{url}"
            f"{ColorFormat.RESET}{ColorFormat.GRAY} (a ouvrir dans ton navigateur)"
        )
        player.send_tip(f"Tableau de bord : {url}")

    def _profil(self, player: Player) -> None:
        player.send_message(
            f"{ColorFormat.YELLOW}{player.name}{ColorFormat.RESET}"
            f"{ColorFormat.GRAY} | gamemode {ColorFormat.WHITE}{player.game_mode}"
            f"{ColorFormat.GRAY} | ping {ColorFormat.WHITE}{player.ping} ms"
            f"{ColorFormat.GRAY} | appareil {ColorFormat.WHITE}{player.device_os}"
        )

    def _joueurs(self, player: Player) -> None:
        names = [p.name for p in self.server.online_players]
        player.send_message(
            f"{ColorFormat.GREEN}{len(names)} joueur(s) en ligne{ColorFormat.RESET}"
            f"{ColorFormat.GRAY} : {ColorFormat.WHITE}{', '.join(names) or '-'}"
        )

    def _infos(self, player: Player) -> None:
        server = self.server
        player.send_message(
            f"{ColorFormat.GOLD}{server.name}{ColorFormat.RESET}"
            f"{ColorFormat.GRAY} | {server.version} | MC {server.minecraft_version}"
            f"{ColorFormat.GRAY} | TPS {ColorFormat.WHITE}{server.average_tps:.1f}"
            f"{ColorFormat.GRAY} | {ColorFormat.WHITE}{len(server.online_players)}"
            f"{ColorFormat.GRAY}/{ColorFormat.WHITE}{server.max_players}§7 joueurs"
        )
