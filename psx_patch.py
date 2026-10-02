"""Patch a Dino Crisis 2 PlayStation disc image: the Giganotosaurus replaces the playable T-Rex,
and optionally the Colosseum raptor gets the Dino Duel "Ultra Raptor" skin.

Usage:  python psx_patch.py <disc .cue or track-1 .bin> [output .bin]
            [--trex-anims] [--keep-trex-sounds] [--no-root-scale]
            [--no-hitbox-scale | --scale-hitboxes] [--no-menu] [--no-duel] [--ultra-raptor]
            [--normal-face | --burnt-face | --face-tex=<E41.TEX file>] [--wav-map-roars]
            [--map=SLOT:GIGA[+GIGA...],...] [--trex-slots=SLOT,...]

Everything is built from the input disc's own data (E40.DAT is the Giganotosaurus), so no game
data ships with the patcher. The input is never modified: the patched track 1 is written to a
new track-1 .bin next to the original and, when a .cue was given, a new .cue that uses it
together with the original audio track (default names: "<game> (Giga) (Track 1).bin" and
"<game> (Giga).cue"). Verified on the USA release (SLUS-01279); other releases are found by
file name through the disc's file system and should work if their data matches.

  --normal-face      the Giga's normal face texture (E40.DAT; the default)
  --burnt-face       its burnt face texture (E41.TEX) for the character and the
                     selection-screen preview; --face-tex=<file> reads an E41-style file instead
  --wav-map-roars    send the roar events through character.REX_TO_GIGA too (by default they
                     keep the Giga's own roar)
  --map, --trex-slots  override giga_anims.MAPPING for one run (see giga_anims.parse_map)
  --ultra-raptor     give the Colosseum raptor the Dino Duel Ultra Raptor skin

Needs the other modules in this folder: character.py, menu_preview.py, giga_anims.py,
skeleton_fk.py, cdimage.py.

Files rewritten in place on the disc (same sectors, same recorded sizes, EDC/ECC regenerated):
  /PSX/DATA/WEP_PR10.DAT   Colosseum T-Rex    -> Giga model, texture, sounds, animations, hits
  /PSX/DATA/KOF_P10P.DAT   Dino Duel player 1 -> same
  /PSX/DATA/KOF_P11P.DAT   Dino Duel player 2 -> same
  /PSX/DATA/M_TITLE.DAT    selection-screen preview model
  /PSX/DATA/M_E10.TEX      selection-screen preview texture
  /PSX/DATA/WEP_PR0D.DAT   Colosseum raptor   -> texture + CLUT of KOF_P01P.DAT (Ultra Raptor,
  /PSX/DATA/M_E00.TEX      raptor preview        same mesh and UVs); only with --ultra-raptor

The PlayStation files hold the same data as the PC port (see character.py) with these
differences: entries are always 0x20 bytes; the model/animation block is type 7 (loaded at the
PC address + 0x7FB00000, e.g. 0x80162500); a second type-7 block is the character's MIPS code
and is left alone; sounds are a 'Gian' tone header (type 3) plus SPU sample data (type 4), both
uploaded to the target's SPU address (entry field 2).

Sound layout (worked out from the files): the type-3 header is 0x50 bytes of header followed by
16-byte tone records. Record bytes 14-15 (little endian) are the sample's SPU address / 8, so
every distinct value is one wav; sorting them gives the wav numbers (Giga: 7, T-Rex: 9), which
match the PC's wav ids. The type-0 event table (8 bytes per game event) picks a tone with
(bytes 2-3 big endian) >> 4, and tone numbers match the PC's sfx slots.
The sample addresses are absolute: E40's point into its own SPU area (0x68A60...), so they are
moved to the target's area along with the samples.
"""
import os, shutil, struct, sys

import character as g
import menu_preview as m
from cdimage import Disc

E40 = '/PSX/DATA/E40.DAT'
FACE = '/PSX/DATA/E41.TEX'          # burnt face texture (type 1 + type 2 entries, same layout as E40)
CHARACTERS = {
    # disc path: end limit of the model block in PlayStation RAM
    '/PSX/DATA/WEP_PR10.DAT': 0x8017C500,    # WEP_SUB buffer
    '/PSX/DATA/KOF_P10P.DAT': 0x8017C500,
    '/PSX/DATA/KOF_P11P.DAT': 0x80162500,    # player 1's block
}
MENU, MENU_TEX = '/PSX/DATA/M_TITLE.DAT', '/PSX/DATA/M_E10.TEX'
RAPTOR, RAPTOR_MENU_TEX = '/PSX/DATA/WEP_PR0D.DAT', '/PSX/DATA/M_E00.TEX'
RAPTOR_SKIN = '/PSX/DATA/KOF_P01P.DAT'      # Dino Duel Ultra Raptor: its texture + CLUT become the raptor's

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


# ---------------------------------------------------------------- face texture

def load_face(disc, flags):
    """(texture, clut) of the burnt face (--burnt-face, --face-tex=FILE), or None for the
    normal E40 face (the default, or --normal-face)."""
    override = [f.split('=', 1)[1] for f in flags if f.startswith('--face-tex=')]
    picked = ('--normal-face' in flags) + ('--burnt-face' in flags) + bool(override)
    if picked > 1:
        raise SystemExit('choose one of --normal-face, --burnt-face and --face-tex=FILE')
    if '--burnt-face' not in flags and not override:
        return None
    if override:
        data = open(override[0], 'rb').read()
        src = override[0]
    elif FACE.upper() in disc.files:
        data = disc.read(FACE)
        src = FACE
    else:
        raise SystemExit('%s is not on this disc; pass --face-tex=<path to E41.TEX>, or '
                         '--normal-face to keep the normal face' % FACE)
    ents = parse(data)
    tex, clut = first(ents, 1, 0x10000)[2], first(ents, 2, 0x200)[2]
    print('face texture:', src)
    return tex, clut


# ---------------------------------------------------------------- sounds

def tone_wavs(hdr):
    """{tone index: wav number (1.., SPU order)} from a type-3 'Gian' header."""
    recs = [hdr[o:o + 16] for o in range(0x50, len(hdr) - 15, 16)]
    used = [i for i, r in enumerate(recs) if any(r[:10])]          # all-zero records are padding
    refs = sorted({struct.unpack_from('<H', recs[i], 14)[0] for i in used})
    return {i: refs.index(struct.unpack_from('<H', recs[i], 14)[0]) + 1 for i in used}


def relocate_header(hdr, delta):
    """Shift every tone's sample address (record bytes 14-15, SPU address / 8) by delta."""
    hdr = bytearray(hdr)
    for o in range(0x50, len(hdr) - 15, 16):
        if any(hdr[o:o + 10]):                        # all-zero records are padding
            v = struct.unpack_from('<H', hdr, o + 14)[0] + delta
            assert 0 <= v <= 0xFFFF, 'relocated sample address out of range'
            struct.pack_into('<H', hdr, o + 14, v)
    return bytes(hdr)


def build_sounds(tents, eents, flags=()):
    """Giga tone header + samples, with an event table in the target's layout (see
    character.map_events: tones play the role of the PC's sfx slots). Sample addresses are moved
    to the target's SPU address."""
    t3, t4, t0 = first(tents, 3), first(tents, 4), first(tents, 0)
    e3, e4_, e0 = first(eents, 3), first(eents, 4), first(eents, 0)
    assert e3[2][:4] == b'Gian', 'unexpected sound header'
    table, log = g.map_events(t0[2], e0[2], tone_wavs(t3[2]), tone_wavs(e3[2]), flags)
    table += t0[2][len(table):]

    delta = (t4[1][2] - e4_[1][2]) // 8             # target SPU address - Giga SPU address, /8
    if len(e4_[2]) > t4[1][1]:
        raise ValueError('Giga samples (%#x bytes) do not fit the target\'s sample area (%#x)'
                         % (len(e4_[2]), t4[1][1]))
    t3[2], t4[2], t0[2] = relocate_header(e3[2], delta), e4_[2], bytes(table)
    return 'sounds (samples moved %+#x bytes to SPU %#x): ' % (delta * 8, t4[1][2]) + ', '.join(log)


# ---------------------------------------------------------------- builders

def build_character(target, e40, limit, flags, face):
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
        from giga_anims import apply_giga_anims, parse_map
        line, native = apply_giga_anims(blk, base, anim_ofs, end, bytes(eblk), ebase,
                                        parse_map(flags), copy_cues='--keep-trex-sounds' not in flags)
        report.append(line)
    if '--no-root-scale' not in flags:
        g.scale_root_positions(blk, base, anim_ofs, end, scale, skip=native)
        report.append('root position scale %.4f' % scale)
    report.append(g.fix_hitboxes(blk, orig, base, anim_ofs, end, scale, flags))
    assert base + len(blk) <= limit, 'block would overrun its slot (%#x > %#x)' % (base + len(blk), limit)

    comp = g.lz_compress(bytes(blk))
    assert g.lz_decompress(comp) == bytes(blk), 'compressor round-trip failed'
    first(tents, 7)[2] = comp
    tex, clut = face if face else (first(eents, 1, 0x10000)[2], first(eents, 2, 0x200)[2])
    first(tents, 1, 0x10000)[2] = tex                               # texture
    first(tents, 2, 0x200)[2] = clut                                # CLUT
    if '--keep-trex-sounds' not in flags:
        report.append(build_sounds(tents, eents, flags))
    report.append('model block %#x..%#x (limit %#x)' % (base, base + len(blk), limit))
    return assemble(target, tents), report


def build_raptor(target, skin):
    """Raptor file with the KOF ultra raptor texture and palette (same sizes, so same sectors)."""
    ents, sents = parse(target), parse(skin)
    first(ents, 1, 0x10000)[2] = first(sents, 1, 0x10000)[2]
    first(ents, 2, 0x200)[2] = first(sents, 2, 0x200)[2]
    return assemble(target, ents)


def build_raptor_menu_tex(tex, skin):
    sents = parse(skin)
    out = bytearray(tex)
    out[0x800:0x10800] = first(sents, 1, 0x10000)[2]
    out[0x10800:0x10A00] = first(sents, 2, 0x200)[2]
    return bytes(out)


def build_menu(title, e40):
    ents = parse(title)
    blk, base = model_block(ents)
    eblk, ebase = model_block(parse(e40))
    m.giga_preview(blk, bytes(eblk), ebase, base)
    comp = g.lz_compress(bytes(blk))
    assert g.lz_decompress(comp) == bytes(blk), 'compressor round-trip failed'
    first(ents, 7)[2] = comp
    return assemble(title, ents)


def build_menu_tex(tex, e40, face):
    out = bytearray(tex)
    t, c = face if face else (first(parse(e40), 1, 0x10000)[2], first(parse(e40), 2, 0x200)[2])
    out[0x800:0x10800] = t
    out[0x10800:0x10A00] = c
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
    face = load_face(disc, flags)

    new = {}
    for path, limit in CHARACTERS.items():
        if '--no-duel' in flags and 'KOF_' in path:
            continue
        new[path], report = build_character(disc.read(path), e40, limit, flags, face)
        print(path)
        for line in report:
            print('   ' + line)
    if '--no-menu' not in flags:
        new[MENU] = build_menu(disc.read(MENU), e40)
        new[MENU_TEX] = build_menu_tex(disc.read(MENU_TEX), e40, face)
        print(MENU, '+', MENU_TEX, ': selection-screen preview')
    if '--ultra-raptor' in flags:
        skin = disc.read(RAPTOR_SKIN)
        new[RAPTOR] = build_raptor(disc.read(RAPTOR), skin)
        new[RAPTOR_MENU_TEX] = build_raptor_menu_tex(disc.read(RAPTOR_MENU_TEX), skin)
        print(RAPTOR, '+', RAPTOR_MENU_TEX, ': Ultra Raptor skin')
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
        # Copy the cue byte for byte, changing only the track 1 file name: some emulators'
        # cue parsers (e.g. ePSXe) fail on a cue whose CR LF line endings became LF.
        text = open(cue, 'rb').read()
        first_name = text.split(b'FILE "', 1)[1].split(b'"', 1)[0]
        out_cue = (os.path.splitext(cue)[0] + ' (Giga).cue' if len(args) == 1
                   else os.path.splitext(out_bin)[0] + '.cue')
        text = text.replace(b'"%s"' % first_name, b'"%s"' % os.path.basename(out_bin).encode('latin1'), 1)
        if os.path.dirname(os.path.abspath(out_cue)) != os.path.dirname(os.path.abspath(cue)):
            print('note: copy the other track files next to', out_cue)
        open(out_cue, 'wb').write(text)
        print('wrote', out_cue)


if __name__ == '__main__':
    main()
