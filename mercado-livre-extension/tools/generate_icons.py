#!/usr/bin/env python3
"""Gera os ícones PNG da extensão (icons/icon16.png, icon48.png, icon128.png).

Não há dependências externas (sem Pillow). Rode uma vez após clonar o
repositório, antes de carregar a extensão como "unpacked" no Chrome:

    python3 mercado-livre-extension/tools/generate_icons.py
"""
import struct
import zlib
from pathlib import Path

YELLOW = (255, 213, 0, 255)
BLUE = (45, 62, 122, 255)
WHITE = (255, 255, 255, 255)


def make_png(path: Path, size: int) -> None:
    pixels = [[YELLOW for _ in range(size)] for _ in range(size)]

    cx, cy = size / 2, size / 2
    r_outer = size * 0.36
    r_inner = size * 0.10

    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= r_outer:
                pixels[y][x] = BLUE
            if dist <= r_inner:
                pixels[y][x] = WHITE

    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filtro "none" no início de cada linha
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

    path.write_bytes(png)


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "icons"
    out_dir.mkdir(exist_ok=True)
    for size in (16, 48, 128):
        make_png(out_dir / f"icon{size}.png", size)
        print(f"gerado {out_dir / f'icon{size}.png'}")


if __name__ == "__main__":
    main()
