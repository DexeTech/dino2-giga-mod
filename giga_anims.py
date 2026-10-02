"""Replace player T-Rex animation slots with the Giganotosaurus's own (E40) motions.

Used by pc_patch.py and psx_patch.py unless --trex-anims is given. Edit MAPPING to change
which Giga animation plays in which player slot; slots not listed keep the (root-scaled)
T-Rex motion.

Frame layout: u16 time, u16 duration, s16 root pose offset x, y, z, then 21 triplets.
Triplet 0 is NOT a rotation: it is the cumulative root motion the game moves the character by
(walk +215/frame, run +600/frame, deaths slide sideways). Triplets 1..20 rotate parts 0..19.

Roles were matched from root motion, hit spheres (bone 3 = head bite, bones 10/14 = toe stomp)
and sound cues (0x30/0x31 footsteps, 0x38 and 0x42-0x44 roars). The player slot keeps its own
frame count, timing, hit spheres and root motion, so movement speed and distances stay exactly
as the game expects; the pose comes from the Giga, resampled to fit. When both animations have
a hit window, the Giga motion is time-warped so its strike lands in the slot's.

Sound cues come from the Giga animation too, retimed with the same warp so each sound lands on
the same pose as in the Giga's own animation. A cue list (the animation's first event pointer)
is u32 count, then (u16 time, u16 cue) pairs; time is in the frames' time units (frame f starts
at f * duration) and cue - 0x30 is an event number in the character's sound event table. The
Giga's roars pick their pitch through these events (its one roar sample at a different rate
per event) and layer growls on top, so keeping the T-Rex's cues gave the wrong roar. When the
Giga animation has no cues (its death sounds come from game code), the slot's own are kept.
With the T-Rex's sounds (copy_cues=False) the slot's own cues are kept as well, since the
Giga's cues use events the T-Rex's sound table does not have.
"""
import struct

FRAME_SIZE = 0x88
SOUND_CUES = range(0x30, 0x30 + 23)       # cue values that play sound events 0..22

# player slot -> E40 animation, or a tuple of E40 animations played one after another and
# squeezed into the slot's frame count, e.g. 24: (23, 24, 25, 26)
MAPPING = {
    0: 0,     # walk (+215/frame)            <- Giga walk (+267/frame)
    1: 5,     # walk backwards (-175/frame)  <- Giga walk backwards (-214/frame)
    2: 2,     # run, toe stomps (+600/frame) <- Giga run (+650/frame)
    4: 1,     # roar (one-shot, no hit)      <- Giga roar (176 ticks, cue 0x38)
    7: 27,    # death, falls to -x           <- Giga death (falls to -x)
    21: 21,   # roar while backing off       <- Giga roar while backing off
    22: 22,   # roar while backing off       <- Giga roar (variant)
    24: 26,   # long roar                    <- Giga roar (cue 0x44)
    25: 26,   # long roar (variant)          <- Giga roar (cue 0x44)
}
# Slots 3 and 4 come from the T-Rex's move code (the second type-7 block of WEP_PR10): it plays
# slot 3 for the special attack (which also spawns an effect) and slot 4 for the roar. Slot 3
# keeps the T-Rex animation, since the Giga roar made the special start late. That code never
# plays slots 21/22/24/25; slot 23 is a hit stagger, like 5.
# Giga roars in E40: 1 the real roar (cue 0x38); 21/22 long roar while backing off (29 frames,
# cue 0x42); 23/24 short roar (11 frames, 0x42); 25 medium roar (12 frames, 0x43); 26 big roar
# and a step (17 frames, 0x44).
# Not mapped (T-Rex motion, root-scaled): 3 special, 8-12 bites, 13/14 running bites, 5/23
# staggers, 6 death to +x (the Giga's only death falls the other way), 15/18 hop back,
# 16/17/19/20 flinches. The bites keep the T-Rex's motion so the head still reaches the ground
# (the Giga's own bites are E40 animations 7, 8, 12 and 20).


def parse_map(flags, mapping=MAPPING):
    """MAPPING with the command line overrides applied: --map=SLOT:GIGA[+GIGA...],... sets
    slots (A+B+C chains Giga animations) and --trex-slots=SLOT,... leaves slots on T-Rex motion."""
    mp = dict(mapping)
    for f in flags:
        if f.startswith('--trex-slots='):
            for s in f.split('=', 1)[1].split(','):
                mp.pop(int(s), None)
        elif f.startswith('--map='):
            for item in f.split('=', 1)[1].split(','):
                slot, val = item.split(':')
                parts = tuple(int(x) for x in val.split('+'))
                mp[int(slot)] = parts if len(parts) > 1 else parts[0]
    return mp


def _anims(blk, base, anim_ofs, limit):
    offs, o = [], anim_ofs
    while True:
        v = struct.unpack_from('<I', blk, o)[0]
        if not base + anim_ofs <= v < base + limit:
            return offs
        offs.append(v - base)
        o += 4


def _frames(blk, a):
    n = struct.unpack_from('<I', blk, a)[0]
    return [struct.unpack_from('<2H66h', blk, a + 0x14 + f * FRAME_SIZE) for f in range(n)]


def _hit_window(blk, a, base, frames):
    """(first, last) frame index of the earliest hit sphere window, or None."""
    p1, p2 = [(p - base if p else 0) for p in struct.unpack_from('<2I', blk, a + 8)]
    if not p1 or not frames:
        return None
    dur = frames[0][1] or 1
    wins = [struct.unpack_from('<2B', blk, p + 8) for p in range(p1, p2, 16)]
    return min(w[0] for w in wins) / dur, max(w[1] for w in wins) / dur


def _warp(t, n_dst, n_src, dst_win, src_win):
    """Map destination frame t to a fractional source frame."""
    if not dst_win or not src_win:
        return t * (n_src - 1) / max(1, n_dst - 1)
    pts = [(0, 0), (dst_win[0], src_win[0]), (dst_win[1], src_win[1]), (n_dst - 1, n_src - 1)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if t <= x1 or (x1, y1) == pts[-1]:
            return y0 if x1 == x0 else y0 + (t - x0) * (y1 - y0) / (x1 - x0)


def _unwarp(s, n_dst, n_src, dst_win, src_win):
    """Destination frame (fractional) that _warp maps to source frame s; _warp is monotonic."""
    lo, hi = 0.0, float(max(0, n_dst - 1))
    for _ in range(40):
        mid = (lo + hi) / 2
        if _warp(mid, n_dst, n_src, dst_win, src_win) < s:
            lo = mid
        else:
            hi = mid
    return hi


def _cues(blk, a, base):
    """(offset of the cue list or None, [(time, cue), ...]) of the animation at `a`."""
    p = struct.unpack_from('<I', blk, a + 4)[0]
    if not p:
        return None, []
    p -= base
    n = struct.unpack_from('<I', blk, p)[0]
    return p, [struct.unpack_from('<2H', blk, p + 4 + 4 * k) for k in range(n)]


def _copy_cues(blk, a, base, dst, eblk, ebase, srcs, dwin, gwin):
    """Give the slot at `a` the sound cues of the Giga animations `srcs` ((offset, frames) each,
    played one after another), retimed onto the slot's frames. The list is rewritten in place
    when it fits, otherwise appended to the end of `blk` (a bytearray) and the animation's
    pointer moved there. Returns the new cue count or None."""
    dp, dcues = _cues(blk, a, base)
    gcues, first = [], 0                      # (fractional frame of the chained animation, cue)
    for ga, frames in srcs:
        gdur = frames[0][1] or 1
        gcues += [(first + min(time / gdur, len(frames) - 1), cue)
                  for time, cue in _cues(eblk, ga, ebase)[1]]
        first += len(frames)
    if not gcues:
        return None
    ddur, last = dst[0][1] or 1, (len(dst) - 1) * (dst[0][1] or 1)
    new = []
    for s, cue in gcues:
        t = _unwarp(s, len(dst), first, dwin, gwin)
        new.append((max(0, min(last, round(t * ddur))), cue))
    new += [c for c in dcues if c[1] not in SOUND_CUES]      # keep any non-sound cues
    data = struct.pack('<I', len(new)) + b''.join(struct.pack('<2H', *c) for c in new)
    if dp is not None and len(data) <= 4 + 4 * len(dcues):
        blk[dp:dp + len(data)] = data
    else:
        blk.extend(b'\0' * (-len(blk) % 4))
        struct.pack_into('<I', blk, a + 4, base + len(blk))
        blk.extend(data)
    return len(new)


def _lerp_angle(a, b, f):
    d = (b - a + 2048) % 4096 - 2048
    return a + d * f


def _sample(frames, s):
    s = max(0.0, min(len(frames) - 1, s))
    i = int(s)
    j = min(i + 1, len(frames) - 1)
    f = s - i
    A, B = frames[i], frames[j]
    root = [round(A[2 + k] + (B[2 + k] - A[2 + k]) * f) for k in range(3)]
    rots = [round(_lerp_angle(A[5 + k], B[5 + k], f)) for k in range(63)]
    return [max(-32768, min(32767, v)) for v in root + rots]


def apply_giga_anims(blk, base, anim_ofs, limit, eblk, ebase, mapping=MAPPING, copy_cues=True):
    """Overwrite mapped slots' frame data (and sound cues) in `blk` (a bytearray; relocated
    cue lists are appended to it). Returns (report, set of slot offsets)."""
    slots = _anims(blk, base, anim_ofs, limit)
    src = _anims(eblk, ebase, _anim_ofs_of(eblk, ebase), len(eblk))
    done, lines = set(), []
    for slot, gi in sorted(mapping.items()):
        a = slots[slot]
        dst = _frames(blk, a)
        gis = tuple(gi) if isinstance(gi, (tuple, list)) else (gi,)
        srcs = [(src[x], _frames(eblk, src[x])) for x in gis]
        g = [f for _, frames in srcs for f in frames]
        assert g, 'Giga animation %s is empty' % (gi,)
        dwin = _hit_window(blk, a, base, dst)
        gwin = _hit_window(eblk, src[gis[0]], ebase, g) if len(gis) == 1 else None
        for t in range(len(dst)):
            vals = _sample(g, _warp(t, len(dst), len(g), dwin, gwin))
            p = a + 0x14 + t * FRAME_SIZE
            struct.pack_into('<3h', blk, p + 4, *vals[:3])        # root pose offset
            struct.pack_into('<60h', blk, p + 16, *vals[6:])      # part rotations
            # p + 10: the slot's own root motion is kept
        cues = _copy_cues(blk, a, base, dst, eblk, ebase, srcs, dwin, gwin) if copy_cues else None
        done.add(a)
        lines.append('%d<-%s%s%s' % (slot, '+'.join(map(str, gis)),
                                     ' (hit-aligned)' if dwin and gwin else '',
                                     '' if cues is None else ' %d cues' % cues))
    return 'Giga animations: ' + ', '.join(lines), done


def _anim_ofs_of(eblk, ebase):
    """E40 blocks keep the animation table right after the model (end of the quad table)."""
    end = struct.unpack_from('<I', eblk, 0x24 + 19 * 0x14 + 4)[0] - ebase
    return end
