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

module.exports = { encodePng, crc32, PNG_SIGNATURE };
