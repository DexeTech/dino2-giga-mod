"""Character files: put the E40 Giganotosaurus model, texture and sounds into a T-Rex slot
(WEP_PR10.DAT Colosseum player, KOF_P10P.DAT / KOF_P11P.DAT Dino Duel players 1 and 2).
Used by pc_patch.py and psx_patch.py.

Dino Crisis 2 PC .DAT: a 0x800 header of 0x20-byte entries, payloads padded to 0x800.
  type 3   sound bank: 32-slot SFX table (wav id, volume/flags, pitch) + RIFF WAVs,
           followed by a sector holding the 0xB8-byte event table (23 x 8 bytes:
           flags, bank slot, sfx index << 4 | nibble) that game code triggers by event number
  type 1/2 texture + CLUT uploaded to VRAM at the header coordinates
  type 5   LZSS block decompressed to a fixed address (0x662500 for the player slot):
           0x00  P0..P3 region pointers (vertices, normals, triangles, quads)
           0x10  s16 tri total, quad total, u16 part count, pad, u32 tpage | clut << 16
           0x1C  20 part records of 0x14 bytes:
                 s16 x, y, z (offset from parent), u8 parent, u8 flags,
                 ptr triangles, ptr quads, s16 tri count, s16 quad count
           0x1AC mesh data, 0xCD padding up to 0x3800
           0x3800 animation pointer table; each animation is u32 frame count, 4 x u32 event
                  pointers, then 0x88-byte frames: u16 time, u16 duration, s16 root x, y, z,
                  21 x 3 s16 rotations
"""
import struct

PLAYER_BASE = 0x662500
PLAYER_LIMIT = 0x67C500          # WEP_SUB buffer starts here
ANIM_OFS = 0x3800                # animation table offset inside the player block
FRAME_SIZE = 0x88
EVENT_TABLE_SIZE = 0xB8


def lz_decompress(src):
    out = bytearray()
    i = 0
    while i < len(src):
        flags = src[i]; i += 1
        for bit in range(8):
            if i >= len(src):
                break
            if flags >> bit & 1:
                out.append(src[i]); i += 1
            else:
                t = src[i] | src[i + 1] << 8; i += 2
                dist, n = t & 0xFFF, (t >> 12) + 2
                for _ in range(n):
                    out.append(out[-dist])
    return bytes(out)


def lz_compress(data):
    """Greedy LZSS: flag byte LSB-first (1 = literal), token u16 = dist | (len-2) << 12.
    Distances are capped at 0xFEE, the largest the game's own files use."""
    out = bytearray()
    heads = {}
    i, n = 0, len(data)
    while i < n:
        flag_pos = len(out); out.append(0); flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len = best_dist = 0
            if i + 2 < n:
                for j in reversed(heads.get(data[i:i + 3], [])[-64:]):
                    d = i - j
                    if d > 0xFEE:
                        break
                    L = 0
                    while L < 17 and i + L < n and data[j + L] == data[i + L]:
                        L += 1
                    if L > best_len:
                        best_len, best_dist = L, d
                        if L == 17:
                            break
            if best_len < 2 and i + 1 < n:          # 2-byte matches via a short scan
                for d in range(1, min(i, 64) + 1):
                    if data[i - d] == data[i] and data[i - d + 1] == data[i + 1]:
                        best_len, best_dist = 2, d
                        break
            step = best_len if best_len >= 2 else 1
            if best_len >= 2:
                t = best_dist | (best_len - 2) << 12
                out += bytes((t & 0xFF, t >> 8))
            else:
                flags |= 1 << bit
                out.append(data[i])
            for k in range(i, i + step):
                if k + 2 < n:
                    heads.setdefault(data[k:k + 3], []).append(k)
            i += step
        out[flag_pos] = flags
    return bytes(out)


def entries(dat):
    """Header entries as (header offset, [type, size, a, b]); type 3 takes 0x40 bytes."""
    res, o = [], 0
    while o < 0x800:
        w = list(struct.unpack_from('<4I', dat, o))
        if w[0] not in (1, 2, 3, 5):
            break
        res.append((o, w))
        o += 0x40 if w[0] == 3 else 0x20
    return res


def sections(dat):
    """(header offset, entry, file offset, size) for every payload, in header order."""
    off, out = 0x800, []
    for ho, w in entries(dat):
        out.append((ho, w, off, w[1]))
        off += (w[1] + 0x7FF) & ~0x7FF
        if w[0] == 3:
            off += 0x800                      # event table sector follows the sound bank
    return out


def section(secs, typ, size=None):
    return [s for s in secs if s[1][0] == typ and (size is None or s[1][1] == size)][0]


def pad(b):
    return b + b'\0' * ((-len(b)) % 0x800)


# ---------------------------------------------------------------- model block

def model_regions(blk, base):
    """Split a model at offset 0 of `blk` into header (0x1AC bytes), vertex, normal,
    triangle and quad tables."""
    P = [struct.unpack_from('<I', blk, 4 * k)[0] - base for k in range(4)]
    nparts = struct.unpack_from('<H', blk, 0x14)[0]
    assert P[0] == 0x1AC and nparts == 20, 'not a 20-part model'
    rec = lambda k: 0x24 + k * 0x14
    ntri = sum(struct.unpack_from('<h', blk, rec(k) + 8)[0] for k in range(nparts))
    nquad = sum(struct.unpack_from('<h', blk, rec(k) + 10)[0] for k in range(nparts))
    nvert = (P[1] - P[0]) // 8
    regs = {'A': blk[P[0]:P[0] + 8 * nvert], 'B': blk[P[1]:P[1] + 8 * nvert],
            'C': blk[P[2]:P[2] + 12 * ntri], 'D': blk[P[3]:P[3] + 16 * nquad]}
    # the tables must be contiguous and in part order for the per-part pointers to be rebuilt
    for k in range(nparts):
        a, b = (x - base for x in struct.unpack_from('<II', blk, rec(k)))
        before_t = sum(struct.unpack_from('<h', blk, rec(j) + 8)[0] for j in range(k))
        before_q = sum(struct.unpack_from('<h', blk, rec(j) + 10)[0] for j in range(k))
        assert a == P[2] + 12 * before_t and b == P[3] + 16 * before_q, 'non-contiguous part tables'
    return bytearray(blk[:0x1AC]), regs


def transplant_model(tblk, eblk, ebase, base, anim_ofs, limit, force_tail=()):
    """Replace the model at the start of target block `tblk` (loaded at `base`, animation
    table at `anim_ofs`) with the model from `eblk`. Tables are packed below `anim_ofs` in
    order A,B,C,D while they fit; the rest (and any named in `force_tail`) go to the end of
    the block. Everything from `anim_ofs` on is left where it was. Returns the new block
    (tpage/CLUT kept from target)."""
    head, regs = model_regions(eblk, ebase)
    head[0x18:0x1C] = tblk[0x18:0x1C]
    blk = bytearray(tblk)
    at, tail = 0x1AC, len(blk)
    where = {}
    for name in 'ABCD':
        data = regs[name]
        if name not in force_tail and at + len(data) <= anim_ofs:
            where[name] = at
            blk[at:at + len(data)] = data
            at += len(data)
        else:
            tail = (tail + 0xF) & ~0xF
            where[name] = tail
            blk[len(blk):] = b'\0' * (tail - len(blk)) + data
            tail = len(blk)
    blk[at:anim_ofs] = b'\xCD' * (anim_ofs - at)
    assert base + len(blk) <= limit, 'block would overrun its slot (%#x > %#x)' % (base + len(blk), limit)

    struct.pack_into('<4I', head, 0, *(base + where[n] for n in 'ABCD'))
    ta, qa = base + where['C'], base + where['D']
    for k in range(20):
        r = 0x24 + k * 0x14
        nt, nq = struct.unpack_from('<2h', head, r + 8) if r + 12 <= 0x1AC else (0, 0)
        struct.pack_into('<II', head, r, ta, qa)
        ta += 12 * nt
        qa += 16 * nq
    blk[0:0x1AC] = head
    return blk


def model_scale(tblk, eblk):
    """Ratio of the two bind-pose hip heights (root part y). The Giga skeleton is the T-Rex
    skeleton scaled by this, so animation root positions and hit spheres scale with it."""
    return struct.unpack_from('<h', eblk, 0x1E)[0] / struct.unpack_from('<h', tblk, 0x1E)[0]


def anim_offsets(blk, base, anim_ofs, limit):
    offs, o = [], anim_ofs
    while True:
        v = struct.unpack_from('<I', blk, o)[0]
        if not base + anim_ofs <= v < base + limit:
            return offs
        offs.append(v - base)
        o += 4


def animations(blk, base, anim_ofs, limit):
    """(offset, frame count, [event ptr offsets or 0]) per animation."""
    res = []
    for a in anim_offsets(blk, base, anim_ofs, limit):
        n = struct.unpack_from('<I', blk, a)[0]
        ev = [(p - base if p else 0) for p in struct.unpack_from('<4I', blk, a + 4)]
        res.append((a, n, ev))
    return res


def _scaled(vals, scale):
    return [max(-32768, min(32767, round(v * scale))) for v in vals]


def scale_root_positions(blk, base, anim_ofs, limit, scale, skip=()):
    """Scale every frame's root position; `skip` holds animations already in Giga proportions."""
    offs = anim_offsets(blk, base, anim_ofs, limit)
    ends = offs[1:] + [limit]
    for a, e in zip(offs, ends):
        nframes = struct.unpack_from('<I', blk, a)[0]
        assert a + 0x14 + nframes * FRAME_SIZE <= e, 'unexpected animation layout'
        if a in skip:
            continue
        for f in range(nframes):
            p = a + 0x14 + f * FRAME_SIZE + 4
            struct.pack_into('<3h', blk, p, *_scaled(struct.unpack_from('<3h', blk, p), scale))


def place_hitboxes(blk, orig, base, anim_ofs, limit, radius_scale):
    """Put every hit sphere where the original T-Rex's sphere was in the world on the same
    frame, re-expressed relative to the new model's bone. Enemy approach distances are set in
    game code for the T-Rex's size, so enemies stand where the T-Rex's spheres were; spheres
    that simply scale with the Giga end up past them. Radii grow by `radius_scale` to reach
    towards the Giga's visibly longer jaw. `blk` must already hold its final frames (after
    root scaling / Giga animations); `orig` is the untouched T-Rex block. Returns a report."""
    import skeleton_fk as fk
    new_parts, old_parts = fk.skeleton(blk), fk.skeleton(orig)
    moved = []
    for a, n, ev in animations(blk, base, anim_ofs, limit):
        if not ev[1]:
            continue
        new_fr, old_fr = fk.frames(blk, a), fk.frames(orig, a)
        for p in range(ev[1], ev[2], 16):
            x, y, z, r = struct.unpack_from('<4h', blk, p)
            first, last, bone = blk[p + 8], blk[p + 9], blk[p + 10]
            mid = (first + last) / 2
            fi = min(range(len(old_fr)), key=lambda i: abs(old_fr[i][0] - mid))
            R, t = fk.pose(old_parts, old_fr[fi])[bone]
            centre = [t[i] + v for i, v in enumerate(fk.mv(R, (x, y, z)))]
            R, t = fk.pose(new_parts, new_fr[fi])[bone]
            local = fk.mtv(R, [centre[i] - t[i] for i in range(3)])
            struct.pack_into('<4h', blk, p, *_scaled(local, 1.0), *_scaled([r], radius_scale))
            moved.append(1)
    return 'hit spheres placed at T-Rex positions: %d (radius x %.2f)' % (len(moved), radius_scale)


def fix_hitboxes(blk, orig, base, anim_ofs, limit, scale, argv):
    """--no-hitbox-scale: leave T-Rex values; --scale-hitboxes: plain 1.38x scaling (older
    builds; overshoots enemies); default: place_hitboxes."""
    if '--no-hitbox-scale' in argv:
        return 'hit spheres: T-Rex values kept'
    if '--scale-hitboxes' in argv:
        return 'hit spheres scaled: %d x %.4f' % (scale_hitboxes(blk, base, anim_ofs, limit, scale), scale)
    return place_hitboxes(blk, orig, base, anim_ofs, limit, scale)


def scale_hitboxes(blk, base, anim_ofs, limit, scale):
    """Each animation's second event list holds 16-byte hit spheres:
    s16 x, y, z (offset from a bone), s16 radius, u8 first/last frame, u8 bone, u8 flag,
    u16 damage, pad. Offsets and radii scale with the skeleton. Returns the sphere count."""
    count = 0
    for a, n, ev in animations(blk, base, anim_ofs, limit):
        if not ev[1]:
            continue
        assert ev[2] > ev[1] and (ev[2] - ev[1]) % 16 == 0, 'unexpected hit list layout'
        for p in range(ev[1], ev[2], 16):
            struct.pack_into('<4h', blk, p, *_scaled(struct.unpack_from('<4h', blk, p), scale))
            count += 1
    return count


# ---------------------------------------------------------------- sounds

# T-Rex wav -> Giga wav that plays in its place, chosen by ear. Wavs are numbered from 1 in
# sample order: the PC SFX table's wav ids, which are the PlayStation samples in SPU order.
REX_TO_GIGA = {
    1: 6,
    2: 3,
    3: 5,
    4: 2,
    5: 7,
    6: 4,
    7: 4,
    8: 1,
    9: 2,
}
ROAR_EVENTS = (18, 19, 20)       # events of cues 0x42-0x44, the roars: they keep the Giga's own


def map_events(pev, gev, rex_wav, giga_wav, flags=()):
    """Event table for the Giga's sounds in the player's layout and bank slot.

    pev and gev are the player's and the Giga's event tables (8 bytes per event: flags, bank
    slot, sfx slot << 4 | nibble big endian, padding); rex_wav and giga_wav give the wav number
    of each one's sfx slots. A player event plays the Giga wav that REX_TO_GIGA gives for the
    T-Rex wav it played, through the slot the Giga's own events use for that wav. The roar
    events keep the Giga's own entry (unless --wav-map-roars is given), and events only the
    Giga uses (its animations cue them, see giga_anims.py) get its entry on the player's bank
    slot. Returns (table, log)."""
    for r, gw in REX_TO_GIGA.items():
        if r not in rex_wav.values() or gw not in giga_wav.values():
            raise ValueError('REX_TO_GIGA entry %d -> %d: no such T-Rex / Giga wav' % (r, gw))
    slot = lambda e: (e[2] << 8 | e[3]) >> 4
    giga_ref = {}                                  # Giga wav -> the entry its own events use
    for i in range(0, EVENT_TABLE_SIZE, 8):
        q = gev[i:i + 8]
        if q[0] != 0xFF and slot(q) in giga_wav:
            giga_ref.setdefault(giga_wav[slot(q)], q[2:4])
    for s, w in sorted(giga_wav.items()):          # wavs no event uses: their first slot
        giga_ref.setdefault(w, struct.pack('>H', s << 4 | 5))

    bank_slot = next(pev[i + 1] for i in range(0, EVENT_TABLE_SIZE, 8) if pev[i] != 0xFF)
    table, fallback, log = bytearray(pev[:EVENT_TABLE_SIZE]), None, []
    for i in range(0, EVENT_TABLE_SIZE, 8):
        p, q, ev = pev[i:i + 8], gev[i:i + 8], i // 8
        ok = q[0] != 0xFF and slot(q) in giga_wav
        if ok:
            fallback = q[2:4]
        if p[0] == 0xFF:
            if ok:                                 # an event only the Giga uses
                table[i:i + 8] = bytes((q[0], bank_slot)) + q[2:8]
                log.append('ev%d:giga only' % ev)
            continue
        rw = rex_wav.get(slot(p))
        if ev in ROAR_EVENTS and ok and '--wav-map-roars' not in flags:
            ref, tag = q[2:4], 'giga roar'
        elif rw in REX_TO_GIGA:
            ref, tag = giga_ref[REX_TO_GIGA[rw]], 'rex%d>giga%d' % (rw, REX_TO_GIGA[rw])
        else:
            ref, tag = (q[2:4], 'default') if ok else (fallback, 'fallback')
        table[i + 2:i + 4] = ref
        log.append('ev%d:%s' % (ev, tag))
    return bytes(table), log


def sfx_wavs(bank):
    """{sfx slot: wav id} of a PC sound bank's 32-slot SFX table (wav id 0 = empty slot)."""
    return {i: w for i in range(32) for w in struct.unpack_from('<H', bank, i * 8) if w}


def build_sounds(pr, psec, e4, esec, flags=()):
    """E40 sound bank with an event table in the player's layout (see map_events)."""
    _, _, poff, psize = psec
    _, _, eoff, esize = esec
    bank = e4[eoff:eoff + esize]
    pev = pr[poff + ((psize + 0x7FF) & ~0x7FF):][:0x800]
    eev = e4[eoff + ((esize + 0x7FF) & ~0x7FF):][:0x800]
    table, log = map_events(pev, eev, sfx_wavs(pr[poff:poff + psize]), sfx_wavs(bank), flags)
    return bank, table + pev[EVENT_TABLE_SIZE:], log


def main_texture(dat):
    """(texture, CLUT) of a file's main texture page, e.g. E41.TEX (the Giga's burnt face)."""
    secs = sections(dat)
    t, c = section(secs, 1, 0x10000), section(secs, 2, 0x200)
    return dat[t[2]:t[2] + 0x10000], dat[c[2]:c[2] + 0x200]


def with_texture(dat, texture):
    """`dat` with its main texture page and CLUT replaced by `texture` ((texture, CLUT))."""
    secs, out = sections(dat), bytearray(dat)
    for (typ, size), data in zip(((1, 0x10000), (2, 0x200)), texture):
        off = section(secs, typ, size)[2]
        out[off:off + size] = data
    return bytes(out)


def assemble(target, e4, blk, swap_sounds, flags=(), face=None):
    """Rebuild a character DAT: target header/layout, E40 texture + CLUT (or `face`, a
    (texture, CLUT) pair), optional E40 sound bank (see build_sounds), and the new model block."""
    ts, es = sections(target), sections(e4)
    comp = lz_compress(blk)
    assert lz_decompress(comp) == blk, 'compressor round-trip failed'
    out = bytearray(target[:0x800])
    log = 'sounds: T-Rex bank kept'
    for ho, w, off, size in ts:
        if w[0] == 3:
            if swap_sounds:
                bank, sector, ev = build_sounds(target, (ho, w, off, size), e4, section(es, 3), flags)
                struct.pack_into('<I', out, ho + 4, len(bank))
                log = 'sounds: Giga bank: ' + ', '.join(ev)
            else:
                bank = target[off:off + size]
                sector = target[off + ((size + 0x7FF) & ~0x7FF):][:0x800]
            out += pad(bank) + sector
        elif w[0] == 1 and w[1] == 0x10000:          # main texture -> E40 pixels
            eo = section(es, 1)[2]
            out += pad(face[0] if face else e4[eo:eo + 0x10000])
        elif w[0] == 2 and w[1] == 0x200:            # main CLUT -> E40 CLUT
            eo = section(es, 2)[2]
            out += pad(face[1] if face else e4[eo:eo + 0x200])
        elif w[0] == 5:
            struct.pack_into('<I', out, ho + 4, len(comp))
            out += pad(comp)
        else:
            out += pad(target[off:off + size])
    return bytes(out), log

