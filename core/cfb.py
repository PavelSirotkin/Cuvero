"""Reader of Compound File Binary containers (the OLE storage format of .PcbDoc).

Only reading is needed. The layout follows the public [MS-CFB] specification:
a header, a sector allocation table (FAT), a directory of storages and streams,
and a mini stream for small streams.
"""

from struct import unpack_from

SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
FREE, END_OF_CHAIN = 0xFFFFFFFF, 0xFFFFFFFE
NO_STREAM = 0xFFFFFFFF
STORAGE, STREAM, ROOT = 1, 2, 5


class CfbError(ValueError):
    pass


class CompoundFile:
    """Streams of a compound file by path, like "Pads6/Data"."""

    def __init__(self, data: bytes):
        if data[:8] != SIGNATURE:
            raise CfbError("Это не составной файл (OLE)")
        self.data = data
        self.sector_size = 1 << unpack_from("<H", data, 30)[0]
        self.mini_size = 1 << unpack_from("<H", data, 32)[0]
        (fat_sectors, first_dir, _, self.cutoff, first_mini_fat, mini_fat_sectors) = unpack_from(
            "<IIIIII", data, 44
        )
        first_difat, difat_sectors = unpack_from("<II", data, 68)
        difat = list(unpack_from("<109I", data, 76))
        sector = first_difat
        for _ in range(difat_sectors):
            if sector in (FREE, END_OF_CHAIN):
                break
            count = self.sector_size // 4
            values = unpack_from(f"<{count}I", data, self._offset(sector))
            difat += values[:-1]
            sector = values[-1]
        self.fat: list[int] = []
        for fat_sector in difat[:fat_sectors]:
            count = self.sector_size // 4
            self.fat += unpack_from(f"<{count}I", data, self._offset(fat_sector))
        directory = self._chain(first_dir)
        self.entries = []
        for pos in range(0, len(directory) - 127, 128):
            name_length = unpack_from("<H", directory, pos + 64)[0]
            name = directory[pos : pos + max(name_length - 2, 0)].decode("utf-16-le", "replace")
            kind = directory[pos + 66]
            left, right, child = unpack_from("<III", directory, pos + 68)
            start, size = unpack_from("<IQ", directory, pos + 116)
            if self.sector_size == 512:
                size &= 0xFFFFFFFF
            self.entries.append((name, kind, left, right, child, start, size))
        root = self.entries[0]
        self.mini_stream = self._chain(root[5])[: root[6]]
        self.mini_fat: list[int] = []
        if mini_fat_sectors:
            raw = self._chain(first_mini_fat)
            self.mini_fat = list(unpack_from(f"<{len(raw) // 4}I", raw))
        self.paths: dict[str, int] = {}
        self._walk(root[4], "")

    def _offset(self, sector: int) -> int:
        return (sector + 1) * self.sector_size

    def _chain(self, start: int) -> bytes:
        parts, sector, seen = [], start, set()
        while sector not in (FREE, END_OF_CHAIN) and sector < len(self.fat):
            if sector in seen:
                raise CfbError("Повреждённая цепочка секторов")
            seen.add(sector)
            offset = self._offset(sector)
            parts.append(self.data[offset : offset + self.sector_size])
            sector = self.fat[sector]
        return b"".join(parts)

    def _mini_chain(self, start: int, size: int) -> bytes:
        parts, sector, seen = [], start, set()
        while sector not in (FREE, END_OF_CHAIN) and sector < len(self.mini_fat):
            if sector in seen:
                raise CfbError("Повреждённая цепочка мини-секторов")
            seen.add(sector)
            offset = sector * self.mini_size
            parts.append(self.mini_stream[offset : offset + self.mini_size])
            sector = self.mini_fat[sector]
        return b"".join(parts)[:size]

    def _walk(self, index: int, prefix: str) -> None:
        stack = [index]
        while stack:
            i = stack.pop()
            if i == NO_STREAM or i >= len(self.entries):
                continue
            name, kind, left, right, child, _, _ = self.entries[i]
            stack += [left, right]
            path = f"{prefix}{name}"
            if kind == STREAM:
                self.paths[path] = i
            elif kind == STORAGE:
                self._walk(child, path + "/")

    def stream(self, path: str) -> bytes:
        """Contents of a stream; KeyError when there is none."""
        _, _, _, _, _, start, size = self.entries[self.paths[path]]
        if size < self.cutoff:
            return self._mini_chain(start, size)
        return self._chain(start)[:size]

    def has(self, path: str) -> bool:
        return path in self.paths
