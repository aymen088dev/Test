"use strict";

/* ------------------------------------------------------------------ */
/*  Textures de blocs (issues de MipMap, MIT)                          */
/* ------------------------------------------------------------------ */
/*
 * MipMap recouvre chaque bloc de sa texture 16x16 (`assets/textures/blocks`)
 * et travaille en 16 px/bloc. Ce module les decode une fois, garde un
 * cache 16x16 RGBA et un cache des versions reduites (zoom arriere).
 *
 * Les textures animees des textures packs Bedrock sont des bandes
 * verticales (ex. 16x64) : on ne garde que la premiere image (16x16).
 */

const fs = require("fs");
const path = require("path");

const { decodePng } = require("./png");

const TEXTURES_DIR =
  process.env.MAP_TEXTURES_DIR ||
  path.join(__dirname, "assets", "textures", "blocks");
const BLOCK = 16; // taille de reference d'une texture de bloc

const cache = new Map(); // nom -> Buffer(16*16*4) | null
const scaledCache = new Map(); // "nom@px" -> Buffer(px*px*4)

let missingLogged = 0;

function fileNameFor(name) {
  return String(name || "").replace(/^minecraft:/, "") + ".png";
}

function magenta(size) {
  const buf = Buffer.alloc(size * size * 4);
  for (let i = 0; i < buf.length; i += 4) {
    buf[i] = 255;
    buf[i + 1] = 0;
    buf[i + 2] = 255;
    buf[i + 3] = 255;
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

/** Texture 16x16 RGBA d'un bloc (cache). Jamais null : repli magenta. */
function textureFor(name) {
  const key = fileNameFor(name);
  if (cache.has(key)) return cache.get(key);
  let data = null;
  try {
    const img = decodePng(fs.readFileSync(path.join(TEXTURES_DIR, key)));
    data = firstFrame(img);
  } catch (err) {
    if (missingLogged < 5) {
      missingLogged += 1;
      console.warn(`[map] texture indisponible : ${key} (${err.message})`);
    }
  }
  cache.set(key, data);
  return data;
}

/**
 * Texture reduite/agrandie a `px` pixels de cote (moyenne de boite en
 * reduction, plus proche voisin en agrandissement). Mise en cache.
 */
function scaledTexture(name, px) {
  const key = fileNameFor(name) + "@" + px;
  const hit = scaledCache.get(key);
  if (hit) return hit;

  const src = textureFor(name);
  const out = Buffer.alloc(px * px * 4);
  if (!src) {
    out.set(magenta(px));
    scaledCache.set(key, out);
    return out;
  }

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
    loaded: cache.size,
    scaled: scaledCache.size,
  };
}

function clear() {
  cache.clear();
  scaledCache.clear();
}

module.exports = {
  TEXTURES_DIR,
  BLOCK,
  textureFor,
  scaledTexture,
  stats,
  clear,
};
