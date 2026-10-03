"use strict";

/* ------------------------------------------------------------------ */
/*  Textures de blocs (issues de MipMap, MIT)                          */
/* ------------------------------------------------------------------ */
/*
 * MipMap recouvre chaque bloc de sa texture 16x16 (`assets/textures/blocks`)
 * et travaille en 16 px/bloc. Ce module les decode une fois, garde un
 * cache 16x16 RGBA et un cache des versions reduites (zoom arriere).
 *
 * Toutes les textures de MipMap decodent, mais beaucoup de blocs Bedrock
 * n'ont pas de fichier a leur nom (clotures, murs, vitres, portes, melon...).
 * MipMap les peignait en **magenta** ; ici on resout le meilleur fichier
 * possible, et a defaut on fabrique une texture unie avec la couleur du bloc
 * (`public/blocks.js`, repli deterministe) : plus de damier rose.
 *
 * Les textures animees des texture packs Bedrock sont des bandes
 * verticales (ex. 16x64) : on ne garde que la premiere image (16x16).
 */

const fs = require("fs");
const path = require("path");

const { decodePng } = require("./png");
const { blockColor } = require("./public/blocks");

const TEXTURES_DIR =
  process.env.MAP_TEXTURES_DIR ||
  path.join(__dirname, "assets", "textures", "blocks");
const BLOCK = 16; // taille de reference d'une texture de bloc

// Suffixes de blocs derives : on retombe sur leur materiau de base.
const DERIVED_SUFFIX = /(_fence_gate|_fence|_trapdoor|_door|_wall|_stairs|_slab|_pane|_bars|_carpet|_button|_pressure_plate)$/;

// Renommages connus (nom de bloc Bedrock -> fichier de texture).
const ALIASES = {
  grass_path: "dirt_path",
  reeds: "sugar_cane",
  tall_grass: "short_grass",
  wooden_door: "oak_door",
  fence_gate: "oak_fence_gate",
  lit_furnace: "furnace",
  burning_furnace: "furnace",
  redstone_wire: "redstone_dust",
  wooden_slab: "oak_slab",
  wooden_stairs: "oak_stairs",
  torchfire: "torch",
};

let available = null;

/** Liste des textures disponibles (chargee une fois). */
function availableTextures() {
  if (available) return available;
  available = new Set();
  try {
    for (const file of fs.readdirSync(TEXTURES_DIR)) {
      if (file.endsWith(".png")) available.add(file.slice(0, -4));
    }
  } catch (err) {
    console.warn(`[map] dossier de textures illisible : ${TEXTURES_DIR} (${err.message})`);
  }
  return available;
}

/** Noms candidats pour un bloc, du plus precis au plus generique. */
function candidates(slug) {
  const out = [slug];
  const m = slug.match(DERIVED_SUFFIX);
  if (m) {
    const base = slug.slice(0, -m[1].length);
    out.push(base, base + "_planks", base + "s", base + "_block");
  }
  out.push(slug + "_block", slug + "_top", slug + "_side");
  const alias = ALIASES[slug];
  if (alias) out.push(alias);
  return out;
}

const resolved = new Map(); // slug -> nom de fichier | null
const synthesized = new Set(); // blocs sans texture : couleur unie
const cache = new Map(); // nom de fichier -> Buffer(16*16*4) | null
const scaledCache = new Map(); // "fichier@px" -> Buffer(px*px*4)

/** Nom de fichier de texture a utiliser pour un bloc, ou null. */
function resolveFile(blockName) {
  const slug = String(blockName || "").replace(/^minecraft:/, "");
  if (resolved.has(slug)) return resolved.get(slug);
  const files = availableTextures();
  let found = null;
  for (const candidate of candidates(slug)) {
    if (files.has(candidate)) {
      found = candidate;
      break;
    }
  }
  resolved.set(slug, found);
  return found;
}

function hexToRgb(hex) {
  return [
    parseInt(hex.slice(1, 3), 16) || 0,
    parseInt(hex.slice(3, 5), 16) || 0,
    parseInt(hex.slice(5, 7), 16) || 0,
  ];
}

/** Texture unie 16x16 a partir de la couleur du bloc (jamais magenta). */
function colorTexture(blockName) {
  const rgb = hexToRgb(blockColor(blockName));
  const buf = Buffer.alloc(BLOCK * BLOCK * 4);
  for (let i = 0; i < BLOCK * BLOCK; i++) {
    buf[i * 4] = rgb[0];
    buf[i * 4 + 1] = rgb[1];
    buf[i * 4 + 2] = rgb[2];
    buf[i * 4 + 3] = 255;
  }
  return buf;
}

/** Recadre la premiere image d'une texture (bandes animees des texture packs). */
function firstFrame(img) {
  const w = Math.min(img.width, BLOCK);
  const h = Math.min(img.height, BLOCK);
  if (w === img.width && h === img.height) return img.data;
  const out = Buffer.alloc(BLOCK * BLOCK * 4);
  for (let y = 0; y < h; y++) {
    const src = y * img.width * 4;
    img.data.copy(out, y * BLOCK * 4, src, src + w * 4);
  }
  return out;
}

/**
 * Texture 16x16 RGBA d'un bloc : le fichier resolu, sinon une couleur unie.
 * Ne renvoie jamais null.
 */
function textureFor(blockName) {
  const file = resolveFile(blockName);
  if (!file) {
    const slug = String(blockName || "").replace(/^minecraft:/, "");
    if (!synthesized.has(slug)) {
      synthesized.add(slug);
      if (synthesized.size <= 12) {
        console.warn(`[map] pas de texture pour "${slug}" : couleur du bloc utilisee`);
      }
    }
    return colorTexture(blockName);
  }
  if (cache.has(file)) return cache.get(file);
  let data = null;
  try {
    data = firstFrame(decodePng(fs.readFileSync(path.join(TEXTURES_DIR, file + ".png"))));
  } catch (err) {
    console.warn(`[map] texture illisible : ${file}.png (${err.message})`);
  }
  if (!data) data = colorTexture(blockName);
  cache.set(file, data);
  return data;
}

/**
 * Texture reduite/agrandie a `px` pixels de cote (moyenne de boite en
 * reduction, plus proche voisin en agrandissement). Mise en cache.
 */
function scaledTexture(blockName, px) {
  const file = resolveFile(blockName);
  const key = (file || "color:" + String(blockName || "").replace(/^minecraft:/, "")) + "@" + px;
  const hit = scaledCache.get(key);
  if (hit) return hit;

  const src = textureFor(blockName);
  const out = Buffer.alloc(px * px * 4);

  if (px === BLOCK) {
    out.set(src);
  } else if (px > BLOCK) {
    for (let y = 0; y < px; y++) {
      const sy = Math.min(BLOCK - 1, Math.floor((y * BLOCK) / px));
      for (let x = 0; x < px; x++) {
        const sx = Math.min(BLOCK - 1, Math.floor((x * BLOCK) / px));
        const s = (sy * BLOCK + sx) * 4;
        const o = (y * px + x) * 4;
        out[o] = src[s];
        out[o + 1] = src[s + 1];
        out[o + 2] = src[s + 2];
        out[o + 3] = src[s + 3];
      }
    }
  } else {
    for (let y = 0; y < px; y++) {
      const y0 = Math.floor((y * BLOCK) / px);
      const y1 = Math.max(y0 + 1, Math.floor(((y + 1) * BLOCK) / px));
      for (let x = 0; x < px; x++) {
        const x0 = Math.floor((x * BLOCK) / px);
        const x1 = Math.max(x0 + 1, Math.floor(((x + 1) * BLOCK) / px));
        let r = 0;
        let g = 0;
        let b = 0;
        let a = 0;
        let n = 0;
        for (let sy = y0; sy < y1; sy++) {
          for (let sx = x0; sx < x1; sx++) {
            const s = (sy * BLOCK + sx) * 4;
            r += src[s];
            g += src[s + 1];
            b += src[s + 2];
            a += src[s + 3];
            n += 1;
          }
        }
        const o = (y * px + x) * 4;
        out[o] = Math.round(r / n);
        out[o + 1] = Math.round(g / n);
        out[o + 2] = Math.round(b / n);
        out[o + 3] = Math.round(a / n);
      }
    }
  }

  scaledCache.set(key, out);
  return out;
}

function stats() {
  return {
    dir: TEXTURES_DIR,
    available: availableTextures().size,
    loaded: cache.size,
    scaled: scaledCache.size,
    resolved: resolved.size,
    colorOnly: synthesized.size,
  };
}

function clear() {
  cache.clear();
  scaledCache.clear();
  resolved.clear();
  synthesized.clear();
}

module.exports = {
  TEXTURES_DIR,
  BLOCK,
  textureFor,
  scaledTexture,
  resolveFile,
  candidates,
  stats,
  clear,
};
