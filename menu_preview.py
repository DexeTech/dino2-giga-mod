"""Character-select preview: show the Giganotosaurus instead of the T-Rex.
Used by pc_patch.py and psx_patch.py.

M_TITLE.DAT's type-5 block (LZSS, loaded at 0x5E0000) packs three preview models back to back
with no free space; the T-Rex one sits at a fixed offset the menu code addresses directly.
Memory past the end of the block is NOT free: data appended there crashed the preview, most
likely because M_E10.TEX is read into a buffer right after the block when the character is
selected. So the Giga must fit in the T-Rex's 0x2C84 bytes, but it is 0xC00 bytes larger.
To fit, the preview copy
  - points the normal table at the vertex table (saves 0xBE8; affects lighting only), and
  - drops the last 2 of the jaw's duplicated back faces (mouth interior; saves 0x18).
The preview draws the bind pose, which already has the Giga's hip height.
M_E10.TEX is the preview texture (same pixels as the in-game T-Rex) -> E40 pixels and CLUT.
"""
import struct
from character import lz_compress, lz_decompress, pad

BASE = 0x5E0000
TREX_HDR = 0x19CF4               # T-Rex preview model header inside the decompressed block
TREX_END = 0x1C978               # next preview model starts here
TREX_HIP_Y = -3293
JAW_PART = 4
JAW_BACKFACES_DROPPED = 2


def walk(dat):
    """(header offset, entry, file offset) per payload; type 3 is followed by an extra sector."""
    res, o, off = [], 0, 0x800
    while o < 0x800:
        w = list(struct.unpack_from('<4I', dat, o))
        if not 1 <= w[0] <= 9 or dat[o:o + 4] == b'dumm':
            break
        res.append((o, w, off))
        off += (w[1] + 0x7FF) & ~0x7FF
        if w[0] == 3:
            off += 0x800
            o += 0x40
        else:
            o += 0x20
    return res


def type5(dat):
    return [(ho, w, off) for ho, w, off in walk(dat) if w[0] == 5][0]


def is_unpatched_title(dat):
    _, w, off = type5(dat)
    blk = lz_decompress(dat[off:off + w[1]])
    return struct.unpack_from('<h', blk, TREX_HDR + 0x1E)[0] == TREX_HIP_Y


def read_model(blk, hdr, base):
    """Split a model into its tables: verts, normals, per-part (triangles, quads)."""
    p = lambda k: struct.unpack_from('<I', blk, hdr + 4 * k)[0] - base
    head = bytearray(blk[hdr:hdr + 0x1AC])
    verts = blk[p(0):p(1)]
    normals = blk[p(1):p(2)]
    parts = []
    for k in range(20):
        r = hdr + 0x24 + k * 0x14
        a, b = (x - base for x in struct.unpack_from('<II', blk, r))
        nC, nD = struct.unpack_from('<2h', blk, r + 8)
        parts.append([blk[a:a + 12 * nC], blk[b:b + 16 * nD]])
    return head, verts, normals, parts


def write_model(head, verts, normals, parts, hdr, base=BASE):
    """Lay a model out as header, verts, [normals], triangles, quads at `hdr` in a block loaded
    at `base`, all pointers absolute. normals=None shares the vertex table."""
    head = bytearray(head)
    body = bytearray()
    at = lambda: base + hdr + 0x1AC + len(body)
    vptr = at(); body += verts
    nptr = vptr
    if normals is not None:
        nptr = at(); body += normals
    tri_base = at()
    for t, _ in parts:
        body += t
    qbase = at()
    for _, q in parts:
        body += q
    struct.pack_into('<4I', head, 0, vptr, nptr, tri_base, qbase)
    ta, qa = tri_base, qbase
    for k, (t, q) in enumerate(parts):
        r = 0x24 + k * 0x14
        struct.pack_into('<II', head, r, ta, qa)
        struct.pack_into('<2h', head, r + 8, len(t) // 12, len(q) // 16)
        ta += len(t); qa += len(q)
    struct.pack_into('<2h', head, 0x10, sum(len(t) for t, _ in parts) // 12,
                     sum(len(q) for _, q in parts) // 16)
    return bytes(head) + bytes(body)


def giga_preview(blk, eblk, ebase, base):
    """Replace the T-Rex preview model inside menu block `blk` (bytearray, loaded at `base`)
    with the Giga model from `eblk`, fitted into the T-Rex's slot (see module docstring)."""
    assert struct.unpack_from('<h', blk, TREX_HDR + 0x1E)[0] == TREX_HIP_Y, 'T-Rex preview not found'
    slot = TREX_END - TREX_HDR
    head, verts, normals, parts = read_model(eblk, 0, ebase)
    head[0x18:0x1C] = blk[TREX_HDR + 0x18:TREX_HDR + 0x1C]      # menu tpage/CLUT
    parts[JAW_PART][0] = parts[JAW_PART][0][:-12 * JAW_BACKFACES_DROPPED]
    model = write_model(head, verts, None, parts, TREX_HDR, base=base)
    assert len(model) <= slot, 'Giga preview model is %#x bytes, slot is %#x' % (len(model), slot)
    blk[TREX_HDR:TREX_HDR + len(model)] = model
    blk[TREX_HDR + len(model):TREX_END] = b'\0' * (slot - len(model))


def build_title(title, e4):
    """PC M_TITLE.DAT with the Giga preview model."""
    ho, w, off = type5(title)
    blk = bytearray(lz_decompress(title[off:off + w[1]]))
    _, ew, eoff = type5(e4)
    giga_preview(blk, lz_decompress(e4[eoff:eoff + ew[1]]), ew[2], BASE)
    blk = bytes(blk)
    comp = lz_compress(blk)
    assert lz_decompress(comp) == blk, 'compressor round-trip failed'
    assert off + ((w[1] + 0x7FF) & ~0x7FF) == len(title), 'type-5 block is not last in M_TITLE'
    out = bytearray(title[:off]) + pad(comp)
    struct.pack_into('<I', out, ho + 4, len(comp))
    return bytes(out)


def build_tex(tex, e4, face=None):
    """PC M_E10.TEX with the Giga's texture page and CLUT, or `face` ((texture, CLUT))."""
    if face is None:
        walked = walk(e4)
        t_off = [off for _, w, off in walked if w[0] == 1][0]
        c_off = [off for _, w, off in walked if w[0] == 2][0]
        face = e4[t_off:t_off + 0x10000], e4[c_off:c_off + 0x200]
    out = bytearray(tex)
    out[0x800:0x10800] = face[0]
    out[0x10800:0x10A00] = face[1]
    return bytes(out)
