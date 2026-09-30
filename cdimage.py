"""Minimal PlayStation disc-image access: ISO9660 file lookup and in-place file rewriting on a
MODE2/2352 BIN, with EDC/ECC regenerated for every rewritten Form 1 sector."""
import struct

SECTOR = 2352
USER = 2048
DATA_OFS = 24          # 12 sync + 4 header + 8 subheader

# ---------------------------------------------------------------- EDC / ECC tables
_EDC = []
for i in range(256):
    e = i
    for _ in range(8):
        e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
    _EDC.append(e)
_ECC_F = [0] * 256
_ECC_B = [0] * 256
for i in range(256):
    j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
    _ECC_F[i] = j
    _ECC_B[i ^ j] = i


def edc(data):
    e = 0
    for b in data:
        e = (e >> 8) ^ _EDC[(e ^ b) & 0xFF]
    return e


def _ecc_block(sec, major_count, minor_count, major_mult, minor_inc, dest):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = sec[0xC + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = _ECC_F[a]
        a = _ECC_B[_ECC_F[a] ^ b]
        sec[dest + major] = a
        sec[dest + major + major_count] = a ^ b


def fix_form1(sec):
    """Recompute EDC and ECC of a Mode 2 Form 1 sector (bytearray of 2352) in place."""
    struct.pack_into('<I', sec, 0x818, edc(sec[0x10:0x818]))
    header = bytes(sec[0xC:0x10])
    sec[0xC:0x10] = b'\0\0\0\0'                      # Mode 2 ECC treats the header as zero
    _ecc_block(sec, 86, 24, 2, 86, 0x81C)            # P parity
    _ecc_block(sec, 52, 43, 86, 88, 0x8C8)           # Q parity
    sec[0xC:0x10] = header


# ---------------------------------------------------------------- image access
class Disc:
    def __init__(self, path, writable=False):
        self.f = open(path, 'r+b' if writable else 'rb')
        self.files = self._scan()

    def raw(self, lba):
        self.f.seek(lba * SECTOR)
        return bytearray(self.f.read(SECTOR))

    def user(self, lba):
        return bytes(self.raw(lba)[DATA_OFS:DATA_OFS + USER])

    def _scan(self):
        pvd = self.user(16)
        assert pvd[1:6] == b'CD001', 'not an ISO9660 data track'
        root = pvd[156:190]
        out = {}
        self._walk(struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0], '', out)
        return out

    def _walk(self, lba, size, path, out):
        data = b''.join(self.user(lba + i) for i in range((size + USER - 1) // USER))
        o = 0
        while o < len(data):
            n = data[o]
            if n == 0:
                o = (o // USER + 1) * USER
                continue
            ext, sz = struct.unpack_from('<I', data, o + 2)[0], struct.unpack_from('<I', data, o + 10)[0]
            flags, nl = data[o + 25], data[o + 32]
            name = data[o + 33:o + 33 + nl].decode('latin1')
            if name not in ('\0', '\1'):
                p = path + '/' + name.split(';')[0]
                if flags & 2:
                    self._walk(ext, sz, p, out)
                else:
                    out[p.upper()] = (ext, sz)
            o += n

    def read(self, path):
        lba, size = self.files[path.upper()]
        return b''.join(self.user(lba + i) for i in range((size + USER - 1) // USER))[:size]

    def write(self, path, data):
        """Overwrite a file in place (same sectors, same recorded size). Data may be shorter
        than the file; the rest is zero-filled."""
        lba, size = self.files[path.upper()]
        assert len(data) <= size, '%s: new data %#x exceeds file size %#x' % (path, len(data), size)
        data = data + b'\0' * (size - len(data))
        for i in range((size + USER - 1) // USER):
            sec = self.raw(lba + i)
            assert sec[0x12] & 0x20 == 0, 'sector is not Form 1'
            chunk = data[i * USER:(i + 1) * USER]
            sec[DATA_OFS:DATA_OFS + len(chunk)] = chunk
            fix_form1(sec)
            self.f.seek((lba + i) * SECTOR)
            self.f.write(sec)

    def close(self):
        self.f.close()
