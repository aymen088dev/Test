"use strict";

/* ------------------------------------------------------------------ */
/*  Encodeur PNG minimal (zero dependance)                             */
/* ------------------------------------------------------------------ */
/*
 * Node embarque `zlib` : il suffit d'ecrire l'entete, les chunks IHDR /
 * IDAT / IEND et un CRC32 pour produire un PNG RGBA valide, sans aucune
 * dependance externe (pas de canvas, pas de sharp).
 */

const zlib = require("zlib");

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

/** longueur (4 o) + type (4 o) + donnees + crc (4 o) */
function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, "latin1");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([length, typeBuf, data, crc]);
}

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/**
 * Encode un buffer RGBA (width * height * 4 octets) en PNG.
 * Filtre "Up" sur toutes les lignes : bon compromis taille / vitesse pour
 * une image de relief (degrade continu), filtre "None" pour la premiere.
 */
function encodePng(width, height, rgba) {
  width = Math.max(1, Math.floor(width));
  height = Math.max(1, Math.floor(height));
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);

  for (let y = 0; y < height; y++) {
    const off = y * (stride + 1);
    const row = y * stride;
    if (y === 0) {
      raw[off] = 0; // None
      rgba.copy(raw, off + 1, row, row + stride);
    } else {
      raw[off] = 2; // Up
      const prev = row - stride;
      for (let i = 0; i < stride; i++) {
        raw[off + 1 + i] = (rgba[row + i] - rgba[prev + i]) & 0xff;
      }
    }
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // profondeur de bit
  ihdr[9] = 6; // type de couleur : RGBA
  ihdr[10] = 0; // compression
  ihdr[11] = 0; // filtre
  ihdr[12] = 0; // non entrelace

  return Buffer.concat([
    PNG_SIGNATURE,
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/* ------------------------------------------------------------------ */
/*  Decodeur PNG minimal (textures de blocs + tuiles)                  */
/* ------------------------------------------------------------------ */
/*
 * Couvre ce que MipMap utilise : types couleur 0 (gris), 2 (RVB),
 * 3 (palette, avec tRNS) et 6 (RGBA), profondeurs 1/2/4/8/16 bits,
 * filtres 0..4. Pas d'entrelacement (les textures Bedrock n'en ont pas).
 */

const CHANNELS = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

/** Valeur brute d'un canal (profondeur 1/2/4/8/16) a l'indice donne. */
function rawChannel(row, index, bitDepth) {
  if (bitDepth === 8) return row[index];
  if (bitDepth === 16) return row[index * 2]; // on garde l'octet fort
  const perByte = 8 / bitDepth;
  const byte = row[Math.floor(index / perByte)];
  const shift = (perByte - 1 - (index % perByte)) * bitDepth;
  return (byte >> shift) & ((1 << bitDepth) - 1);
}

/** Ramene une valeur brute sur 0..255. */
function to8(value, bitDepth) {
  if (bitDepth === 8 || bitDepth === 16) return value;
  return Math.round((value * 255) / ((1 << bitDepth) - 1));
}

/**
 * Decode un PNG RGBA/gris/palette en RGBA 8 bits.
 * Retourne { width, height, data } (4 octets par pixel), ou lance une erreur.
 */
function decodePng(png) {
  if (!Buffer.isBuffer(png) || png.length < 8) throw new Error("PNG vide");
  if (!png.subarray(0, 8).equals(PNG_SIGNATURE)) throw new Error("signature PNG invalide");

  let width = 0;
  let height = 0;
  let bitDepth = 8;
  let colorType = 6;
  let interlace = 0;
  let palette = null;
  let transparency = null;
  const idat = [];

  let pos = 8;
  while (pos + 8 <= png.length) {
    const len = png.readUInt32BE(pos);
    const type = png.toString("latin1", pos + 4, pos + 8);
    const data = png.subarray(pos + 8, pos + 8 + len);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === "PLTE") {
      palette = data;
    } else if (type === "tRNS") {
      transparency = data;
    } else if (type === "IDAT") {
      idat.push(data);
    } else if (type === "IEND") {
      break;
    }
    pos += 12 + len;
  }

  if (!width || !height) throw new Error("IHDR manquante");
  if (interlace !== 0) throw new Error("PNG entrelace non supporte");
  const channels = CHANNELS[colorType];
  if (!channels) throw new Error("type couleur non supporte : " + colorType);
  if (![1, 2, 4, 8, 16].includes(bitDepth)) {
    throw new Error("profondeur non supportee : " + bitDepth);
  }

  const bitsPerPixel = channels * bitDepth;
  const bpp = Math.max(1, Math.ceil(bitsPerPixel / 8));
  const rowBytes = Math.ceil((width * bitsPerPixel) / 8);
  const raw = zlib.inflateSync(Buffer.concat(idat));
  if (raw.length < (rowBytes + 1) * height) throw new Error("IDAT tronquee");

  // Defiltrage ligne a ligne (filtres 0..4) dans un buffer continu.
  const pixels = Buffer.alloc(rowBytes * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (rowBytes + 1)];
    const src = raw.subarray(y * (rowBytes + 1) + 1, y * (rowBytes + 1) + 1 + rowBytes);
    const cur = pixels.subarray(y * rowBytes, (y + 1) * rowBytes);
    const prev = y > 0 ? pixels.subarray((y - 1) * rowBytes, y * rowBytes) : null;
    for (let i = 0; i < rowBytes; i++) {
      const a = i >= bpp ? cur[i - bpp] : 0;
      const b = prev ? prev[i] : 0;
      const c = prev && i >= bpp ? prev[i - bpp] : 0;
      let v = src[i];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) v += paeth(a, b, c);
      else if (filter !== 0) throw new Error("filtre PNG non supporte : " + filter);
      cur[i] = v & 0xff;
    }
  }

  // Conversion en RGBA 8 bits.
  const out = Buffer.alloc(width * height * 4);
  for (let y = 0; y < height; y++) {
    const row = pixels.subarray(y * rowBytes, (y + 1) * rowBytes);
    for (let x = 0; x < width; x++) {
      const o = (y * width + x) * 4;
      if (colorType === 3) {
        const idx = rawChannel(row, x, bitDepth);
        const p = idx * 3;
        out[o] = palette && p + 2 < palette.length ? palette[p] : 0;
        out[o + 1] = palette && p + 2 < palette.length ? palette[p + 1] : 0;
        out[o + 2] = palette && p + 2 < palette.length ? palette[p + 2] : 0;
        out[o + 3] = transparency && idx < transparency.length ? transparency[idx] : 255;
      } else if (colorType === 0) {
        const raw = rawChannel(row, x, bitDepth);
        const g = to8(raw, bitDepth);
        out[o] = out[o + 1] = out[o + 2] = g;
        out[o + 3] =
          transparency && transparency.length >= 2 && raw === transparency[1]
            ? transparency[0]
            : 255;
      } else if (colorType === 2) {
        const base = x * channels;
        out[o] = to8(rawChannel(row, base, bitDepth), bitDepth);
        out[o + 1] = to8(rawChannel(row, base + 1, bitDepth), bitDepth);
        out[o + 2] = to8(rawChannel(row, base + 2, bitDepth), bitDepth);
        out[o + 3] = 255;
      } else if (colorType === 4) {
        const base = x * channels;
        const g = to8(rawChannel(row, base, bitDepth), bitDepth);
        out[o] = out[o + 1] = out[o + 2] = g;
        out[o + 3] = to8(rawChannel(row, base + 1, bitDepth), bitDepth);
      } else {
        const base = x * channels;
        out[o] = to8(rawChannel(row, base, bitDepth), bitDepth);
        out[o + 1] = to8(rawChannel(row, base + 1, bitDepth), bitDepth);
        out[o + 2] = to8(rawChannel(row, base + 2, bitDepth), bitDepth);
        out[o + 3] = to8(rawChannel(row, base + 3, bitDepth), bitDepth);
      }
    }
  }

  return { width: width, height: height, data: out };
}

module.exports = { encodePng, decodePng, crc32, PNG_SIGNATURE };
