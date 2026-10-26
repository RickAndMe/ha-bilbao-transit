#!/usr/bin/env python3
"""Genera los assets de marca (icon.png y logo.png) sin dependencias externas."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ORANGE = (255, 101, 5, 255)
DARK = (24, 32, 41, 255)
BLUE = (0, 122, 154, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


class Canvas:
    def __init__(self, width: int, height: int, bg: tuple = CLEAR) -> None:
        self.w = width
        self.h = height
        self.px = bytearray(bytes(bg) * (width * height))

    def _set(self, x: int, y: int, color: tuple) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 4
            self.px[i : i + 4] = bytes(color)

    def round_rect(self, x0: int, y0: int, x1: int, y1: int, radius: int, color: tuple) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                # esquinas redondeadas
                cx = x0 + radius if x < x0 + radius else (x1 - radius if x > x1 - radius else x)
                cy = y0 + radius if y < y0 + radius else (y1 - radius if y > y1 - radius else y)
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2 or (
                    x0 + radius <= x <= x1 - radius or y0 + radius <= y <= y1 - radius
                ):
                    self._set(x, y, color)

    def circle(self, cx: int, cy: int, r: int, color: tuple) -> None:
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r**2:
                    self._set(x, y, color)

    def line(self, x0: int, y0: int, x1: int, y1: int, width: int, color: tuple) -> None:
        steps = max(abs(x1 - x0), abs(y1 - y0)) * 2 or 1
        half = width // 2
        for step in range(steps + 1):
            t = step / steps
            x = round(x0 + (x1 - x0) * t)
            y = round(y0 + (y1 - y0) * t)
            self.round_rect(x - half, y - half, x + half, y + half, half, color)

    def paste(self, other: "Canvas", ox: int, oy: int) -> None:
        for y in range(other.h):
            for x in range(other.w):
                i = (y * other.w + x) * 4
                if other.px[i + 3] > 0:
                    self._set(ox + x, oy + y, tuple(other.px[i : i + 4]))

    def save(self, path: Path) -> None:
        raw = b"".join(
            b"\x00" + bytes(self.px[y * self.w * 4 : (y + 1) * self.w * 4])
            for y in range(self.h)
        )

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )
        path.write_bytes(png)


def draw_icon(size: int = 256) -> Canvas:
    c = Canvas(size, size)
    scale = size / 256

    def s(v: float) -> int:
        return int(round(v * scale))

    c.round_rect(0, 0, size - 1, size - 1, s(56), ORANGE)
    c.round_rect(s(40), s(62), s(216), s(176), s(26), WHITE)
    c.round_rect(s(60), s(84), s(118), s(132), s(10), BLUE)
    c.round_rect(s(138), s(84), s(196), s(132), s(10), BLUE)
    # faros en la parte baja, en vez de una franja que parecía una boca
    c.round_rect(s(64), s(148), s(92), s(160), s(5), BLUE)
    c.round_rect(s(164), s(148), s(192), s(160), s(5), BLUE)
    c.circle(s(84), s(186), s(17), DARK)
    c.circle(s(172), s(186), s(17), DARK)
    c.round_rect(s(30), s(214), s(226), s(222), s(4), WHITE)
    c.line(s(110), s(60), s(136), s(40), s(7), WHITE)
    c.line(s(136), s(40), s(162), s(60), s(7), WHITE)
    return c


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "custom_components" / "bilbao_transit" / "brand"
    out.mkdir(parents=True, exist_ok=True)

    icon = draw_icon(256)
    icon.save(out / "icon.png")

    logo = Canvas(512, 256)
    logo.paste(draw_icon(192), 32, 32)
    logo.save(out / "logo.png")

    for name in ("icon.png", "logo.png"):
        print(f"{name}: {(out / name).stat().st_size} bytes")


if __name__ == "__main__":
    main()
