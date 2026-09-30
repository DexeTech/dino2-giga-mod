"""Forward kinematics for Dino Crisis 2 20-part models.

Frame layout (0x88 bytes): u16 time, u16 duration, s16 root x, y, z, then 21 rotation
triplets (4096 = 360 degrees); triplet 0 is the root's own and is not needed here, triplets
1..20 belong to parts 0..19. Part records at 0x1C + k*0x14 hold the offset from the parent
and the parent index. Convention (verified by the T-Rex walk keeping its feet planted):
R = Rz * Ry * Rx with the z angle negated; y is down.
"""
import math, struct

ORDER = 'zyx'
SIGNS = (1, 1, -1)


def _rot(axis, a):
    t = a * 2 * math.pi / 4096
    c, s = math.cos(t), math.sin(t)
    if axis == 'x':
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if axis == 'y':
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mv(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def mtv(a, v):
    """transpose(a) * v, i.e. the inverse rotation."""
    return [sum(a[k][i] * v[k] for k in range(3)) for i in range(3)]


def skeleton(blk):
    """(offset, parent) per part for the model at offset 0 of `blk`."""
    parts = []
    for k in range(20):
        r = 0x1C + k * 0x14
        parts.append((struct.unpack_from('<3h', blk, r), blk[r + 6]))
    return parts


def frames(blk, anim):
    n = struct.unpack_from('<I', blk, anim)[0]
    return [struct.unpack_from('<2H66h', blk, anim + 0x14 + f * 0x88) for f in range(n)]


def pose(parts, frame):
    """World (rotation, position) of every part for one frame."""
    world = [None] * 20
    for k in range(20):
        r = frame[5 + 3 * (k + 1):8 + 3 * (k + 1)]
        R = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        for ax in ORDER:
            i = 'xyz'.index(ax)
            R = mm(R, _rot(ax, SIGNS[i] * r[i]))
        off, parent = parts[k]
        if k == 0:
            world[k] = (R, list(frame[2:5]))
        else:
            PR, Pt = world[parent]
            world[k] = (mm(PR, R), [Pt[i] + v for i, v in enumerate(mv(PR, off))])
    return world
