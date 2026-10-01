"use strict";

const REFRESH_MS = 3000;

const $ = (id) => document.getElementById(id);

function formatUptime(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}j ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${seconds % 60}s`;
}

function pingClass(ping) {
  if (ping < 70) return "good";
  if (ping < 150) return "mid";
  return "bad";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

function renderPlayers(players) {
  const body = $("players-body");
  $("players-badge").textContent = String(players.length);

  if (!players.length) {
    body.innerHTML =
      '<tr class="empty"><td colspan="4">Aucun joueur connecté.</td></tr>';
    return;
  }

  body.innerHTML = players
    .map((p) => {
      const op = p.op ? '<span class="op" title="Opérateur">★ op</span>' : "";
      const ping = Number(p.ping) || 0;
      return `<tr>
        <td class="player">${escapeHtml(p.name)}${op}</td>
        <td><span class="ping ${pingClass(ping)}">${ping} ms</span></td>
        <td class="muted">${escapeHtml(p.device)}</td>
        <td class="muted">${escapeHtml(p.gamemode)}</td>
      </tr>`;
    })
    .join("");
}

function render(data) {
  $("server-name").textContent = data.server_name || "Serveur";
  $("software").textContent = data.software || "Endstone";
  $("mc-version").textContent = data.minecraft_version || "—";

  $("players-online").textContent = data.players_online ?? "—";
  $("max-players").textContent = data.max_players ?? "—";
  $("tps").textContent = (data.tps ?? 0).toFixed ? data.tps.toFixed(2) : data.tps;
  $("mspt").textContent = (data.mspt ?? 0).toFixed ? data.mspt.toFixed(2) : data.mspt;
  $("uptime").textContent = formatUptime(data.uptime_seconds);

  $("updated").textContent = "maj " + new Date().toLocaleTimeString("fr-FR");
  renderPlayers(data.players || []);
}

function setLive(online, label) {
  const dot = $("live-dot");
  dot.classList.toggle("online", online);
  dot.classList.toggle("offline", !online);
  $("live-label").textContent = label;
}

async function poll() {
  try {
    const res = await fetch("api/status", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    render(data);
    setLive(true, "En ligne");
  } catch (err) {
    setLive(false, "Hors ligne");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("refresh").addEventListener("click", poll);
  poll();
  setInterval(poll, REFRESH_MS);
});
