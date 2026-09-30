"""Patch a Dino Crisis 2 PlayStation disc image: the Giganotosaurus replaces the playable T-Rex.

Usage:  python psx_patch.py <disc .cue or track-1 .bin> [output .bin]
            [--trex-anims] [--keep-trex-sounds] [--no-root-scale]
            [--no-hitbox-scale | --scale-hitboxes] [--no-menu] [--no-duel]

Everything is built from the input disc's own data (E40.DAT is the Giganotosaurus), so no game
data ships with the patcher. The input is never modified: the patched track 1 is written to a
new track-1 .bin next to the original and, when a .cue was given, a new .cue that uses it
together with the original audio track (default names: "<game> (Giga) (Track 1).bin" and
"<game> (Giga).cue"). Verified on the USA release (SLUS-01279); other releases are found by
file name through the disc's file system and should work if their data matches.

Needs the other modules in this folder: character.py, menu_preview.py, giga_anims.py,
skeleton_fk.py, cdimage.py.

Files rewritten in place on the disc (same sectors, same recorded sizes, EDC/ECC regenerated):
  /PSX/DATA/WEP_PR10.DAT   Colosseum T-Rex    -> Giga model, texture, sounds, animations, hits
  /PSX/DATA/KOF_P10P.DAT   Dino Duel player 1 -> same
  /PSX/DATA/KOF_P11P.DAT   Dino Duel player 2 -> same
  /PSX/DATA/M_TITLE.DAT    selection-screen preview model
  /PSX/DATA/M_E10.TEX      selection-screen preview texture

The PlayStation files hold the same data as the PC port (see character.py) with these
differences: entries are always 0x20 bytes; the model/animation block is type 7 (loaded at the
PC address + 0x7FB00000, e.g. 0x80162500); a second type-7 block is the character's MIPS code
and is left alone; sounds are a 'Gian' tone header (type 3, one 16-byte record per SFX slot,
slot count at +8) plus SPU sample data (type 4), both uploaded to the target's SPU address.
"""
import os, shutil, struct, sys

import character as g
import menu_preview as m
from cdimage import Disc

E40 = '/PSX/DATA/E40.DAT'
CHARACTERS = {
    # disc path: end limit of the model block in PlayStation RAM
    '/PSX/DATA/WEP_PR10.DAT': 0x8017C500,    # WEP_SUB buffer
    '/PSX/DATA/KOF_P10P.DAT': 0x8017C500,
    '/PSX/DATA/KOF_P11P.DAT': 0x80162500,    # player 1's block
}
MENU, MENU_TEX = '/PSX/DATA/M_TITLE.DAT', '/PSX/DATA/M_E10.TEX'
EVENT_TABLE_SIZE = 0xB8


# ---------------------------------------------------------------- PSX .DAT container

def parse(dat):
    """[header offset, [type, size, a, b], payload] per entry."""
    ents, o, off = [], 0, 0x800
    while o < 0x800 and dat[o:o + 5] != b'dummy':
        w = list(struct.unpack_from('<4I', dat, o))
        if w[0] > 8:
            break
        ents.append([o, w, dat[off:off + w[1]]])
        off += (w[1] + 0x7FF) & ~0x7FF
        o += 0x20
    return ents


def assemble(dat, ents):
    """Rebuild the file keeping every entry's sector footprint. The loader (0x8001FB5C) is
    driven by the file-table size: it hands each 0x800-byte sector to the current entry and,
    when that entry's size runs out, steps to the next 0x20-byte header slot with no end check.
    A shorter entry therefore makes it walk into the 'dummy header' filler (type 0x6D6D7564),
    which raises its load error and re-reads the file forever. Shorter payloads are padded
    with zeros up to the original size; for type 7 zero bytes decode as distance-0 copies,
    which rewrite each byte with itself, and for sound data they are silence inside the
    target's own SPU area."""
    orig = {ho: w[1] for ho, w, _ in parse(dat)}
    out = bytearray(dat[:0x800])
    for ho, w, payload in ents:
        size = orig[ho]
        if len(payload) < size:
            payload = payload + b'\0' * (size - len(payload))
        elif (len(payload) + 0x7FF) // 0x800 != (size + 0x7FF) // 0x800:
            raise ValueError('entry %#x grew from %#x to %#x bytes (%d more sectors); the loader '
                             'needs the original sector count' % (ho, size, len(payload),
                             (len(payload) + 0x7FF) // 0x800 - (size + 0x7FF) // 0x800))
        struct.pack_into('<I', out, ho + 4, len(payload))
        out += g.pad(payload)
    orig_end = 0x800 + sum((s + 0x7FF) & ~0x7FF for s in orig.values())
    assert len(out) == orig_end, 'sector layout changed (%#x != %#x)' % (len(out), orig_end)
    return bytes(out)


def first(ents, typ, size=None):
    return [e for e in ents if e[1][0] == typ and (size is None or e[1][1] == size)][0]


def model_block(ents):
    e = first(ents, 7)
    return bytearray(g.lz_decompress(e[2])), e[1][2]


def anim_table_offset(blk, base):
    """Model end (last part record's quad pointer), skipping 0xCD padding if present."""
    o = struct.unpack_from('<I', blk, 0x24 + 19 * 0x14 + 4)[0] - base
    while blk[o] == 0xCD:
        o += 1
    return o


# ---------------------------------------------------------------- builders

def build_sounds(tents, eents):
    """Giga tone header + samples, event table kept in the target's layout and bank slot;
    events the Giga leaves unassigned (or pointing past its SFX slots) get a valid sound."""
    t3, t4, t0 = first(tents, 3), first(tents, 4), first(tents, 0)
    e3, e4_, e0 = first(eents, 3), first(eents, 4), first(eents, 0)
    assert e3[2][:4] == b'Gian', 'unexpected sound header'
    nslots = struct.unpack_from('<H', e3[2], 8)[0]
    pev, gev = t0[2], e0[2]
    table = bytearray(pev)
    fallback, log = None, []
    for i in range(0, EVENT_TABLE_SIZE, 8):
        p, q = pev[i:i + 8], gev[i:i + 8]
        ok = q[0] != 0xFF and (q[2] << 8 | q[3]) >> 4 < nslots
        if ok:
            fallback = q[2:4]
        if p[0] == 0xFF:
            continue
        ref = q[2:4] if ok else fallback
        table[i + 2:i + 4] = ref
        log.append('%d->%d%s' % (i // 8, (ref[0] << 8 | ref[1]) >> 4, '' if ok else '*'))
    t3[2], t4[2], t0[2] = e3[2], e4_[2], bytes(table)       # SPU address / slot fields stay
    return 'sounds: Giga (* = fallback) ' + ', '.join(log)


def build_character(target, e40, limit, flags):
    tents, eents = parse(target), parse(e40)
    tblk, base = model_block(tents)
    eblk, ebase = model_block(eents)
    orig = bytes(tblk)
    anim_ofs = anim_table_offset(tblk, base)
    end = len(tblk)

    blk = g.transplant_model(orig, bytes(eblk), ebase, base, anim_ofs, limit)
    scale = g.model_scale(orig, eblk)
    report, native = [], set()
    if '--trex-anims' not in flags:
        from giga_anims import apply_giga_anims
        line, native = apply_giga_anims(blk, base, anim_ofs, end, bytes(eblk), ebase)
        report.append(line)
    if '--no-root-scale' not in flags:
        g.scale_root_positions(blk, base, anim_ofs, end, scale, skip=native)
        report.append('root position scale %.4f' % scale)
    report.append(g.fix_hitboxes(blk, orig, base, anim_ofs, end, scale, flags))

    comp = g.lz_compress(bytes(blk))
    assert g.lz_decompress(comp) == bytes(blk), 'compressor round-trip failed'
    first(tents, 7)[2] = comp
    first(tents, 1, 0x10000)[2] = first(eents, 1, 0x10000)[2]      # texture
    first(tents, 2, 0x200)[2] = first(eents, 2, 0x200)[2]          # CLUT
    if '--keep-trex-sounds' not in flags:
        report.append(build_sounds(tents, eents))
    report.append('model block %#x..%#x (limit %#x)' % (base, base + len(blk), limit))
    return assemble(target, tents), report


def build_menu(title, e40):
    ents = parse(title)
    blk, base = model_block(ents)
    eblk, ebase = model_block(parse(e40))
    m.giga_preview(blk, bytes(eblk), ebase, base)
    comp = g.lz_compress(bytes(blk))
    assert g.lz_decompress(comp) == bytes(blk), 'compressor round-trip failed'
    first(ents, 7)[2] = comp
    return assemble(title, ents)


def build_menu_tex(tex, e40):
    eents = parse(e40)
    out = bytearray(tex)
    out[0x800:0x10800] = first(eents, 1, 0x10000)[2]
    out[0x10800:0x10A00] = first(eents, 2, 0x200)[2]
    return bytes(out)


def is_unpatched(disc):
    blk, base = model_block(parse(disc.read('/PSX/DATA/WEP_PR10.DAT')))
    return struct.unpack_from('<h', blk, 0x1E)[0] == -3293


# ---------------------------------------------------------------- main

def track1_from(path):
    if not path.lower().endswith('.cue'):
        return path, None
    cue = open(path, encoding='latin1').read()
    name = cue.split('FILE "', 1)[1].split('"', 1)[0]
    return os.path.join(os.path.dirname(path), name), path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(1)
    src_bin, cue = track1_from(args[0])
    if len(args) > 1:
        out_bin = args[1]
    elif cue:           # "<game> (Giga) (Track 1).bin" + "<game> (Giga).cue" beside the original
        out_bin = os.path.splitext(cue)[0] + ' (Giga) (Track 1).bin'
    else:
        out_bin = os.path.splitext(src_bin)[0] + ' (Giga).bin'
    assert os.path.abspath(out_bin) != os.path.abspath(src_bin), 'output must differ from input'

    disc = Disc(src_bin)
    boot = disc.read('/SYSTEM.CNF').split(b'\r\n')[0].decode('latin1', 'replace')
    print('disc:', boot)
    assert E40.upper() in disc.files, 'not a Dino Crisis 2 disc (no %s)' % E40
    assert is_unpatched(disc), 'this image already contains the Giga patch'
    e40 = disc.read(E40)

    new = {}
    for path, limit in CHARACTERS.items():
        if '--no-duel' in flags and 'KOF_' in path:
            continue
        new[path], report = build_character(disc.read(path), e40, limit, flags)
        print(path)
        for line in report:
            print('   ' + line)
    if '--no-menu' not in flags:
        new[MENU] = build_menu(disc.read(MENU), e40)
        new[MENU_TEX] = build_menu_tex(disc.read(MENU_TEX), e40)
        print(MENU, '+', MENU_TEX, ': selection-screen preview')
    for path, data in new.items():
        size = disc.files[path.upper()][1]
        assert len(data) <= size, '%s grew past its disc allocation (%#x > %#x)' % (path, len(data), size)
    disc.close()

    shutil.copyfile(src_bin, out_bin)
    out = Disc(out_bin, writable=True)
    for path, data in new.items():
        out.write(path, data)
    for path, data in new.items():                      # read back
        assert out.read(path)[:len(data)] == data, 'verification failed for ' + path
    out.close()
    print('wrote', out_bin)

    if cue:
        text = open(cue, encoding='latin1').read()
        first_name = text.split('FILE "', 1)[1].split('"', 1)[0]
        out_cue = (os.path.splitext(cue)[0] + ' (Giga).cue' if len(args) == 1
                   else os.path.splitext(out_bin)[0] + '.cue')
        text = text.replace('"%s"' % first_name, '"%s"' % os.path.basename(out_bin), 1)
        if os.path.dirname(os.path.abspath(out_cue)) != os.path.dirname(os.path.abspath(cue)):
            print('note: copy the other track files next to', out_cue)
        open(out_cue, 'w', encoding='latin1', newline='').write(text)
        print('wrote', out_cue)


if __name__ == '__main__':
    main()
