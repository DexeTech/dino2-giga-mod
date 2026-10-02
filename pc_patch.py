"""Patch Dino Crisis 2 (PC): the Giganotosaurus replaces the playable T-Rex.

Usage:  python pc_patch.py <game Data folder> [--out DIR] [--install | --restore]
            [--trex-anims] [--keep-trex-sounds] [--no-root-scale]
            [--no-hitbox-scale | --scale-hitboxes] [--no-menu] [--no-duel]
            [--normal-face | --burnt-face | --face-tex=FILE] [--wav-map-roars] [--ultra-raptor]
            [--map=SLOT:GIGA[+GIGA...],...] [--trex-slots=SLOT,...]

Everything is built from the game's own files (E40.DAT is the Giganotosaurus), so no game data
ships with the patcher. By default the patched files are written to ./output; --install also
copies them into the Data folder after backing up the originals to <Data>/giga_mod_backup, and
--restore puts those originals back.

Files built:
  WEP_PR10.DAT   Colosseum T-Rex    -> Giga model, texture, sounds, animations, hit spheres
  KOF_P10P.DAT   Dino Duel player 1 -> same
  KOF_P11P.DAT   Dino Duel player 2 -> same
  M_TITLE.DAT    selection-screen preview model
  M_E10.TEX      selection-screen preview texture
  WEP_PR0D.DAT   Colosseum raptor   -> texture + CLUT of KOF_P01P.DAT, the Dino Duel Ultra
  M_E00.TEX      raptor preview        Raptor (same mesh and UVs); only with --ultra-raptor
"""
import argparse, os, shutil, struct, sys

import character as g
import menu_preview as m

CHARACTERS = {
    # file name: end limit of the model block in memory
    'WEP_PR10.DAT': 0x67C500,    # WEP_SUB buffer
    'KOF_P10P.DAT': 0x67C500,
    'KOF_P11P.DAT': 0x662500,    # player 1's block
}
MENU, MENU_TEX = 'M_TITLE.DAT', 'M_E10.TEX'
FACE = 'E41.TEX'                 # the Giga's burnt face (texture + CLUT)
RAPTOR, RAPTOR_MENU_TEX = 'WEP_PR0D.DAT', 'M_E00.TEX'
RAPTOR_SKIN = 'KOF_P01P.DAT'     # Dino Duel Ultra Raptor: its texture + CLUT become the raptor's
BACKUP = 'giga_mod_backup'
TREX_HIP_Y = -3293


def model_block(dat):
    _, w, off, size = g.section(g.sections(dat), 5)
    return g.lz_decompress(dat[off:off + size]), w[2]


def anim_table_offset(blk, base):
    """Model end (last part record's quad pointer), skipping 0xCD padding if present."""
    o = struct.unpack_from('<I', blk, 0x24 + 19 * 0x14 + 4)[0] - base
    while blk[o] == 0xCD:
        o += 1
    return o


def build_character(target, e40, limit, flags, face=None):
    tblk, base = model_block(target)
    eblk, ebase = model_block(e40)
    anim_ofs = anim_table_offset(tblk, base)
    end = len(tblk)

    blk = g.transplant_model(tblk, eblk, ebase, base, anim_ofs, limit)
    scale = g.model_scale(tblk, eblk)
    report, native = [], set()
    if '--trex-anims' not in flags:
        from giga_anims import apply_giga_anims, parse_map
        line, native = apply_giga_anims(blk, base, anim_ofs, end, eblk, ebase, parse_map(flags),
                                        copy_cues='--keep-trex-sounds' not in flags)
        report.append(line)
    if '--no-root-scale' not in flags:
        g.scale_root_positions(blk, base, anim_ofs, end, scale, skip=native)
        report.append('root position scale %.4f' % scale)
    report.append(g.fix_hitboxes(blk, tblk, base, anim_ofs, end, scale, flags))
    assert base + len(blk) <= limit, 'block would overrun its slot (%#x > %#x)' % (base + len(blk), limit)
    out, sound_log = g.assemble(target, e40, bytes(blk), '--keep-trex-sounds' not in flags, flags, face)
    report.append(sound_log)
    report.append('model block %#x..%#x (limit %#x)' % (base, base + len(blk), limit))
    return out, report


def is_unpatched(name, data, e40, faces, skin):
    if name in CHARACTERS:
        blk, _ = model_block(data)
        return struct.unpack_from('<h', blk, 0x1E)[0] == TREX_HIP_Y
    if name == MENU:
        return m.is_unpatched_title(data)
    if name == MENU_TEX:
        return all(data[0x800:0x10800] != tex for tex, _ in faces)
    if name in (RAPTOR, RAPTOR_MENU_TEX):
        return g.main_texture(data)[0] != skin[0]
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('data', help='the game\'s Data folder, e.g. "...\\english\\Data"')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output'),
                    help='where to write the patched files (default: ./output)')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--install', action='store_true', help='back up the originals and copy the patched files into Data')
    mode.add_argument('--restore', action='store_true', help='put the backed-up original files back into Data')
    for flag, text in [('--trex-anims', 'keep the T-Rex animations (scaled) instead of the Giga\'s own'),
                       ('--keep-trex-sounds', 'keep the T-Rex sounds'),
                       ('--no-root-scale', 'keep the T-Rex animations\' body height (the Giga sinks into the floor)'),
                       ('--no-hitbox-scale', 'keep the T-Rex hit spheres unchanged'),
                       ('--scale-hitboxes', 'scale hit spheres by the size ratio (reaches past enemies)'),
                       ('--no-menu', 'leave the selection-screen preview alone'),
                       ('--no-duel', 'leave the Dino Duel files alone')]:
        ap.add_argument(flag, action='store_true', help=text)
    face_group = ap.add_mutually_exclusive_group()
    face_group.add_argument('--normal-face', action='store_true', help="the Giga's normal face texture (default)")
    face_group.add_argument('--burnt-face', action='store_true', help="the Giga's burnt face texture (E41.TEX)")
    face_group.add_argument('--face-tex', metavar='FILE', help='the face texture from another E41.TEX-style file')
    ap.add_argument('--wav-map-roars', action='store_true',
                    help="send the roars through character.REX_TO_GIGA too, instead of the Giga's own roar")
    ap.add_argument('--ultra-raptor', action='store_true',
                    help='give the Colosseum raptor the Dino Duel Ultra Raptor skin')
    ap.add_argument('--map', metavar='SLOT:GIGA[+GIGA...],...',
                    help='play these Giga animations in these slots (overrides giga_anims.MAPPING)')
    ap.add_argument('--trex-slots', metavar='SLOT,...', help='keep the T-Rex animation in these slots')
    args = ap.parse_args()
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    data = os.path.abspath(args.data)
    backup = os.path.join(data, BACKUP)
    if not os.path.exists(os.path.join(data, 'E40.DAT')):
        sys.exit('E40.DAT not found in %s: pass the game\'s Data folder' % data)

    names = [n for n in CHARACTERS if not (args.no_duel and n.startswith('KOF_'))]
    if not args.no_menu:
        names += [MENU, MENU_TEX]
    if args.ultra_raptor:
        names += [RAPTOR, RAPTOR_MENU_TEX]

    if args.restore:
        if not os.path.isdir(backup):
            sys.exit('no backup found in ' + backup)
        for name in sorted(os.listdir(backup)):
            shutil.copy2(os.path.join(backup, name), os.path.join(data, name))
            print('restored', name)
        return

    e40 = open(os.path.join(data, 'E40.DAT'), 'rb').read()
    normal = g.main_texture(open(os.path.join(data, 'E40.TEX'), 'rb').read())
    burnt = g.main_texture(open(os.path.join(data, FACE), 'rb').read())
    skin = g.main_texture(open(os.path.join(data, RAPTOR_SKIN), 'rb').read())
    face = None
    if args.burnt_face or args.face_tex:
        face = g.main_texture(open(args.face_tex or os.path.join(data, FACE), 'rb').read())
        print('face texture:', args.face_tex or FACE)
    originals = {}
    for name in names:
        saved = os.path.join(backup, name)
        path = saved if os.path.exists(saved) else os.path.join(data, name)
        originals[name] = open(path, 'rb').read()
        if not is_unpatched(name, originals[name], e40, (normal, burnt, face or normal), skin):
            sys.exit('%s is already modified and there is no backup of the original. Restore the '
                     'original file (on Steam: Properties > Installed Files > Verify integrity of game '
                     'files) and run again.' % path)

    new = {}
    for name in names:
        if name in CHARACTERS:
            new[name], report = build_character(originals[name], e40, CHARACTERS[name], flags, face)
        elif name in (RAPTOR, RAPTOR_MENU_TEX):
            new[name], report = g.with_texture(originals[name], skin), ['Ultra Raptor skin']
        elif name == MENU:
            new[name], report = m.build_title(originals[name], e40), ['selection-screen preview model']
        else:
            new[name], report = m.build_tex(originals[name], e40, face), ['selection-screen preview texture']
        print(name)
        for line in report:
            print('   ' + line)

    os.makedirs(args.out, exist_ok=True)
    for name, blob in new.items():
        open(os.path.join(args.out, name), 'wb').write(blob)
    print('wrote %d files to %s' % (len(new), args.out))

    if args.install:
        os.makedirs(backup, exist_ok=True)
        for name, blob in new.items():
            saved = os.path.join(backup, name)
            if not os.path.exists(saved):
                open(saved, 'wb').write(originals[name])
            open(os.path.join(data, name), 'wb').write(blob)
        print('installed into %s (originals backed up in %s)' % (data, backup))


if __name__ == '__main__':
    main()
