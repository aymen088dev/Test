"use strict";

/* ------------------------------------------------------------------ */
/*  Relief vu de dessus (rendu cote serveur)                           */
/* ------------------------------------------------------------------ */
/*
 * A partir des chunks stockes (un bloc de surface par colonne), on
 * construit une grille hauteur + couleur, puis on l'eclaire comme une
 * carte de relief : normale calculee par gradient, lumiere du nord-ouest,
 * teinte d'altitude. Le resultat est un PNG RGBA servi par le serveur —
 * le navigateur n'a qu'a l'afficher.
 *
 * Zero dependance : l'encodeur PNG maison s'appuie sur `zlib` (integre a
 * Node).
 */

const { encodePng } = require("./png");
const { blockColor } = require("./public/blocks");

const MAX_SIDE = Math.max(256, Number(process.env.MAP_RELIEF_MAX_SIDE || 4096));
const MAX_PIXELS = 12e6;
const DEFAULT_EXAGGERATION = Number(process.env.MAP_RELIEF_EXAGGERATION || 1.5);

// Lumiere : nord-ouest et au-dessus (azimut ~315 deg, altitude ~50 deg).
// Le vecteur pointe de la surface vers la source lumineuse.
const LIGHT = (() => {
  const x = -0.6;
  const y = 0.75;
  const z = -0.6;
  const n = Math.sqrt(x * x + y * y + z * z);
  return [x / n, y / n, z / n];
})();

const rgbCache = new Map();

function hexToRgb(hex) {
  let out = rgbCache.get(hex);
  if (out) return out;
  out = [
    parseInt(hex.slice(1, 3), 16) || 0,
    parseInt(hex.slice(3, 5), 16) || 0,
    parseInt(hex.slice(5, 7), 16) || 0,
  ];
  rgbCache.set(hex, out);
  return out;
}

/** Bornes de chunks couvertes par une liste de chunks. */
function boundsOf(chunks) {
  let minCx = Infinity;
  let maxCx = -Infinity;
  let minCz = Infinity;
  let maxCz = -Infinity;
  for (const c of chunks) {
    if (!c) continue;
    if (c.cx < minCx) minCx = c.cx;
    if (c.cx > maxCx) maxCx = c.cx;
    if (c.cz < minCz) minCz = c.cz;
    if (c.cz > maxCz) maxCz = c.cz;
  }
  if (!isFinite(minCx)) return null;
  return { minCx: minCx, maxCx: maxCx, minCz: minCz, maxCz: maxCz };
}

/**
 * Grille de relief : hauteur du bloc de surface + couleur, 1 pixel par bloc
 * (ou 1 pixel par cellule quand le monde depasse MAX_SIDE / MAX_PIXELS).
 * Sous-echantillonnage par hauteur maximale : on garde les reliefs visibles.
 */
function buildGrid(chunks) {
  const bounds = boundsOf(chunks);
  if (!bounds) return null;

  const baseX = bounds.minCx * 16;
  const baseZ = bounds.minCz * 16;
  const blocksW = (bounds.maxCx - bounds.minCx + 1) * 16;
  const blocksH = (bounds.maxCz - bounds.minCz + 1) * 16;

  let stride = 1;
  while (
    stride < 64 &&
    (Math.max(blocksW, blocksH) / stride > MAX_SIDE ||
      Math.ceil(blocksW / stride) * Math.ceil(blocksH / stride) > MAX_PIXELS)
  ) {
    stride += 1;
  }

  const width = Math.max(1, Math.ceil(blocksW / stride));
  const height = Math.max(1, Math.ceil(blocksH / stride));
  const y = new Float32Array(width * height);
  const r = new Uint8Array(width * height);
  const g = new Uint8Array(width * height);
  const b = new Uint8Array(width * height);
  const mask = new Uint8Array(width * height);

  for (const chunk of chunks) {
    if (!chunk || !Array.isArray(chunk.cells)) continue;
    const palette = chunk.palette || [];
    const bx0 = chunk.cx * 16 - baseX;
    const bz0 = chunk.cz * 16 - baseZ;
    for (let iz = 0; iz < 16; iz++) {
      for (let ix = 0; ix < 16; ix++) {
        const cell = chunk.cells[(iz << 4) | ix];
        if (!cell || cell.length < 2) continue;
        const blockY = cell[0];
        if (typeof blockY !== "number" || !isFinite(blockY)) continue;
        const px = Math.floor((bx0 + ix) / stride);
        const pz = Math.floor((bz0 + iz) / stride);
        if (px < 0 || pz < 0 || px >= width || pz >= height) continue;
        const di = pz * width + px;
        // Le bloc le plus haut gagne : silhouette du relief.
        if (!mask[di] || blockY > y[di]) {
          mask[di] = 1;
          y[di] = blockY;
          const rgb = hexToRgb(blockColor(palette[cell[1]] || ""));
          r[di] = rgb[0];
          g[di] = rgb[1];
          b[di] = rgb[2];
        }
      }
    }
  }

  return {
    width: width,
    height: height,
    stride: stride,
    minX: baseX,
    minZ: baseZ,
    y: y,
    r: r,
    g: g,
    b: b,
    mask: mask,
  };
}

/** Eclaire la grille (relief ombre) et renvoie un buffer RGBA. */
function shadeGrid(grid, exaggeration) {
  const width = grid.width;
  const height = grid.height;
  const stride = grid.stride;
  const y = grid.y;
  const r = grid.r;
  const g = grid.g;
  const b = grid.b;
  const mask = grid.mask;
  const rgba = Buffer.alloc(width * height * 4);

  let yMin = Infinity;
  let yMax = -Infinity;
  for (let i = 0; i < mask.length; i++) {
    if (!mask[i]) continue;
    if (y[i] < yMin) yMin = y[i];
    if (y[i] > yMax) yMax = y[i];
  }
  const span = Math.max(1, yMax - yMin);
  const e = exaggeration;
  const lx = LIGHT[0];
  const ly = LIGHT[1];
  const lz = LIGHT[2];

  for (let z = 0; z < height; z++) {
    for (let x = 0; x < width; x++) {
      const i = z * width + x;
      const o = i * 4;
      if (!mask[i]) {
        rgba[o + 3] = 0; // zone non cartographiee : transparente
        continue;
      }
      const h = y[i];

      const li = x > 0 ? i - 1 : -1;
      const ri = x < width - 1 ? i + 1 : -1;
      const ui = z > 0 ? i - width : -1;
      const di = z < height - 1 ? i + width : -1;
      const hl = li >= 0 && mask[li] ? y[li] : h;
      const hr = ri >= 0 && mask[ri] ? y[ri] : h;
      const hu = ui >= 0 && mask[ui] ? y[ui] : h;
      const hd = di >= 0 && mask[di] ? y[di] : h;

      // Gradient par differences centrees, ramene a l'unite de bloc.
      const dhx = (hr - hl) / (2 * stride);
      const dhz = (hd - hu) / (2 * stride);

      // Normale de la surface : n = (-dhx, 1, -dhz), exageree verticalement.
      const nx = -dhx * e;
      const nz = -dhz * e;
      const ny = 1;
      const invLen = 1 / Math.sqrt(nx * nx + ny * ny + nz * nz);
      let illum = (nx * lx + ny * ly + nz * lz) * invLen;
      if (illum < 0) illum = 0;

      // Ambiante + diffus, puis legere teinte d'altitude (sommets plus clairs).
      let shade = 0.32 + 0.98 * illum;
      shade *= 0.9 + 0.22 * ((h - yMin) / span);
      if (shade < 0.16) shade = 0.16;
      if (shade > 1.4) shade = 1.4;

      const cr = r[i] * shade;
      const cg = g[i] * shade;
      const cb = b[i] * shade;
      rgba[o] = cr > 255 ? 255 : cr | 0;
      rgba[o + 1] = cg > 255 ? 255 : cg | 0;
      rgba[o + 2] = cb > 255 ? 255 : cb | 0;
      rgba[o + 3] = 255;
    }
  }
  return rgba;
}

/**
 * Rend le relief d'une dimension en PNG.
 * `chunks` : payloads internes de la dimension.
 * Retourne { buffer, width, height, stride, minX, minZ } ou null.
 */
function renderReliefPng(chunks, opts = {}) {
  const grid = buildGrid(chunks);
  if (!grid) return null;
  const exaggeration =
    typeof opts.exaggeration === "number" && opts.exaggeration > 0
      ? opts.exaggeration
      : DEFAULT_EXAGGERATION;
  const rgba = shadeGrid(grid, exaggeration);
  const buffer = encodePng(grid.width, grid.height, rgba);
  return {
    buffer: buffer,
    width: grid.width,
    height: grid.height,
    stride: grid.stride,
    minX: grid.minX,
    minZ: grid.minZ,
  };
}

module.exports = { renderReliefPng, buildGrid, boundsOf, LIGHT };
