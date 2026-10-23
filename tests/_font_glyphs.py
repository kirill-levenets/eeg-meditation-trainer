"""The characters a TrueType font has glyphs for, read from its cmap: what isn't there renders as an empty box (tofu)."""
import pathlib
import struct


def _format4(data: bytes, at: int) -> set[int]:
    segs = struct.unpack_from(">H", data, at + 6)[0] // 2
    ends_at = at + 14
    starts_at = ends_at + 2 * segs + 2
    deltas_at = starts_at + 2 * segs
    offsets_at = deltas_at + 2 * segs
    points = set()
    for i in range(segs):
        end, start = struct.unpack_from(">H", data, ends_at + 2 * i)[0], struct.unpack_from(">H", data, starts_at + 2 * i)[0]
        delta = struct.unpack_from(">h", data, deltas_at + 2 * i)[0]
        offset = struct.unpack_from(">H", data, offsets_at + 2 * i)[0]
        for c in range(start, end + 1):
            if offset == 0:
                glyph = (c + delta) & 0xFFFF
            else:
                glyph = struct.unpack_from(">H", data, offsets_at + 2 * i + offset + 2 * (c - start))[0]
                glyph = (glyph + delta) & 0xFFFF if glyph else 0
            if glyph:  # glyph 0 is the missing-glyph box
                points.add(c)
    return points


def _format12(data: bytes, at: int) -> set[int]:
    points = set()
    for i in range(struct.unpack_from(">I", data, at + 12)[0]):
        start, end, glyph = struct.unpack_from(">III", data, at + 16 + 12 * i)
        points.update(c for c in range(start, end + 1) if glyph + c - start)
    return points


def font_codepoints(path: pathlib.Path) -> set[int]:
    data = path.read_bytes()
    tables = {data[12 + 16 * i:16 + 16 * i]: struct.unpack_from(">I", data, 20 + 16 * i)[0]
              for i in range(struct.unpack_from(">H", data, 4)[0])}
    cmap = tables[b"cmap"]
    points: set[int] = set()
    for i in range(struct.unpack_from(">H", data, cmap + 2)[0]):
        platform, encoding, offset = struct.unpack_from(">HHI", data, cmap + 4 + 8 * i)
        fmt = struct.unpack_from(">H", data, cmap + offset)[0]
        if fmt == 4 and (platform, encoding) in ((3, 1), (0, 3)):
            points |= _format4(data, cmap + offset)
        elif fmt == 12 and (platform, encoding) in ((3, 10), (0, 4)):
            points |= _format12(data, cmap + offset)
    return points
