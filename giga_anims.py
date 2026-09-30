"""Replace player T-Rex animation slots with the Giganotosaurus's own (E40) motions.

Used by pc_patch.py and psx_patch.py unless --trex-anims is given. Edit MAPPING to change
which Giga animation plays in which player slot; slots not listed keep the (root-scaled)
T-Rex motion.

Frame layout: u16 time, u16 duration, s16 root pose offset x, y, z, then 21 triplets.
Triplet 0 is NOT a rotation: it is the cumulative root motion the game moves the character by
(walk +215/frame, run +600/frame, deaths slide sideways). Triplets 1..20 rotate parts 0..19.

Roles were matched from root motion, hit spheres (bone 3 = head bite, bones 10/14 = toe stomp)
and sound cues (0x30/0x31 footsteps, 0x42-0x44 roars). The player slot keeps its own frame
count, timing, event data (hits, sounds) and root motion, so movement speed and distances stay
exactly as the game expects; only the pose comes from the Giga, resampled to fit. When both
animations have a hit window, the Giga motion is time-warped so its strike lands in the slot's.
"""
import struct

FRAME_SIZE = 0x88

# player slot -> E40 animation
MAPPING = {
    0: 0,     # walk (+215/frame)            <- Giga walk (+267/frame)
    1: 5,     # walk backwards (-175/frame)  <- Giga walk backwards (-214/frame)
    2: 2,     # run, toe stomps (+600/frame) <- Giga run (+650/frame)
    7: 27,    # death, falls to -x           <- Giga death (falls to -x)
    8: 7,     # walking bite                 <- Giga moving bite
    9: 8,     # walking bite                 <- Giga moving bite (variant)
    10: 7,    # walking bite                 <- Giga moving bite
    11: 20,   # standing bite                <- Giga standing bite
    12: 12,   # standing bite                <- Giga standing bite (jaw)
    21: 21,   # roar while backing off       <- Giga roar while backing off
    22: 22,   # roar while backing off       <- Giga roar (variant)
    24: 26,   # long roar                    <- Giga roar (cue 0x44)
    25: 26,   # long roar (variant)          <- Giga roar (cue 0x44)
}
# Not mapped (T-Rex motion, root-scaled): 3 charge, 4/5/23 turns, 6 death to +x (the Giga's
# only death falls the other way), 13/14 running bites, 15/18 hop back, 16/17/19/20 flinches.


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


def apply_giga_anims(blk, base, anim_ofs, limit, eblk, ebase, mapping=MAPPING):
    """Overwrite mapped slots' frame data in place. Returns (report, set of slot offsets)."""
    slots = _anims(blk, base, anim_ofs, limit)
    src = _anims(eblk, ebase, _anim_ofs_of(eblk, ebase), len(eblk))
    done, lines = set(), []
    for slot, gi in sorted(mapping.items()):
        a = slots[slot]
        dst = _frames(blk, a)
        g = _frames(eblk, src[gi])
        assert g, 'Giga animation %d is empty' % gi
        dwin = _hit_window(blk, a, base, dst)
        gwin = _hit_window(eblk, src[gi], ebase, g)
        for t in range(len(dst)):
            vals = _sample(g, _warp(t, len(dst), len(g), dwin, gwin))
            p = a + 0x14 + t * FRAME_SIZE
            struct.pack_into('<3h', blk, p + 4, *vals[:3])        # root pose offset
            struct.pack_into('<60h', blk, p + 16, *vals[6:])      # part rotations
            # p + 10: the slot's own root motion is kept
        done.add(a)
        lines.append('%d<-%d%s' % (slot, gi, ' (hit-aligned)' if dwin and gwin else ''))
    return 'Giga animations: ' + ', '.join(lines), done


def _anim_ofs_of(eblk, ebase):
    """E40 blocks keep the animation table right after the model (end of the quad table)."""
    end = struct.unpack_from('<I', eblk, 0x24 + 19 * 0x14 + 4)[0] - ebase
    return end
