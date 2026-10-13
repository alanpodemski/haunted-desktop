"""Haunted hallway environment (SPEC "v2: the hallway") -> public/models/hallway.glb

    blender -b -P blender/hallway.py                    # build, bake AO, export, render previews
    blender -b -P blender/hallway.py -- --retex         # also regenerate the procedural textures
    blender -b -P blender/hallway.py -- --no-preview    # skip the preview renders
    blender -b -P blender/hallway.py -- --quick         # no AO bake (white AO), fast look-dev
    blender -b -P blender/hallway.py -- --preview-only [hall door door2 fill moon]

Authoring is in Blender space (Z up).  The glTF exporter maps Blender (x, y, z) -> glTF (x, z, -y), so the
SPEC's hallway z in [-14, 0.8] is Blender y in [-0.8, 14] (the far end wall is at y = +14).
Builds on room.py (mesh builder, sweeps, wallpaper layout, materials, dirt, the v1 props) and room_tex.py /
hall_tex.py (numpy textures, cached in blender/_tex/).  AO is baked with Cycles into one 4096 lightmap atlas
(UV map "AO" = glTF TEXCOORD_1) and exported as every opaque material's occlusionTexture.
"""
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import room as R  # noqa: E402   (helpers only; room.py's main() is guarded)
import room_tex as RT  # noqa: E402
import hall_tex as HT  # noqa: E402
from common import MODELS, link, _enable_gpu  # noqa: E402
from room import MB, T, TAU, lines, grid_surface, sweep, tube, lathe, join_objs, mats  # noqa: E402

ARGS = R.ARGS
PREVIEW = "--no-preview" not in ARGS
QUICK = "--quick" in ARGS
TEXDIR = R.TEXDIR
OUT = os.path.join(MODELS, "hallway.glb")
BLEND = os.path.join(TEXDIR, "hallway_build.blend")
AO_RES = 4096

# ----------------------------------------------------------------------------- layout (Blender space)
HX0, HX1 = -1.25, 1.25          # hallway interior
HY0, HY1 = -0.8, 14.0
HH = 2.9
WT = 0.14                       # interior wall thickness
EWT = 0.25                      # exterior wall thickness (hallway end wall)
RWT = 0.22                      # exterior wall thickness (side room far walls)
DW, DHT = 0.9, 2.1              # doorway clear opening
RD, RWID = 2.6, 3.0             # side room depth (x) and width (y)
ZW = 1.0                        # wainscot height
EW_W, EW_H, EW_Z = 1.1, 1.7, 0.85     # end window
SW_W, SW_H, SW_Z = 0.9, 1.45, 0.85    # side room windows
FT, CT = R.FLOOR_TILE, R.CEIL_TILE
TRIM_TILE, WOOD_TILE, IRON_TILE = R.TRIM_TILE, R.WOOD_TILE, R.IRON_TILE
WALL_TILE, ROLL = R.WALL_TILE, R.ROLL

# id, side, y centre, hinge ("near" = smaller y jamb, "far", "torn", None = empty opening), open angle (deg)
DOORS = [
    ("L1", "L", 2.6, "near", 7.0),
    ("L2", "L", 6.6, None, None),
    ("L3", "L", 10.6, "far", 42.0),
    ("R1", "R", 4.6, "far", 108.0),
    ("R2", "R", 8.6, "torn", None),
    ("R3", "R", 12.2, "near", 68.0),
]
MOON_ELEV = math.radians(30.0)
CEIL_HOLE = (0.32, 9.55, 0.42, 0.30)          # cx, cy, rx, ry

RNG = np.random.default_rng(4242)
COLLIDERS = []          # (name, centre, size, yaw)


def bl(p):
    """glTF (x, y, z) -> Blender (x, -z, y)"""
    return Vector((p[0], -p[2], p[1]))


def gl(p):
    """Blender -> glTF"""
    return (p[0], p[2], -p[1])


def side_x(side):
    """(hallway wall face x, room-side face x, unit normal into the room) for a doorway side"""
    if side == "L":
        return HX0, HX0 - WT, Vector((-1, 0, 0))
    return HX1, HX1 + WT, Vector((1, 0, 0))


def room_box(side, yc):
    if side == "L":
        return (HX0 - WT - RD, HX0 - WT, yc - RWID / 2, yc + RWID / 2)
    return (HX1 + WT, HX1 + WT + RD, yc - RWID / 2, yc + RWID / 2)


def xform_mb(mb, M):
    mb.V = [tuple(M @ Vector(v)) for v in mb.V]
    return mb


def basis(a_dir, b_dir, origin=(0, 0, 0)):
    """4x4 with columns a_dir, b_dir, +Z (may be left-handed -> rebuild normals with recalc)"""
    a, b = Vector(a_dir), Vector(b_dir)
    M = Matrix(((a.x, b.x, 0, origin[0]), (a.y, b.y, 0, origin[1]), (a.z, b.z, 1, origin[2]), (0, 0, 0, 1)))
    return M


def obj_from(mb, name, matnames, recalc=False, smooth_deg=35):
    return mb.obj(name, mats(*matnames), recalc=recalc, smooth_deg=smooth_deg)


def transform_obj(ob, M):
    ob.data.transform(M)
    ob.data.update()
    return ob


def rest_on_floor(ob, z=0.0):
    zmin = min(v.co.z for v in ob.data.vertices)
    transform_obj(ob, Matrix.Translation((0, 0, z - zmin)))


# =============================================================================== textures / materials
R.TEXSETS.update({
    "Carpet": (HT.carpet, 1, 1, 2, False),
    "Wainscot": (HT.wainscot, 1, 1, 1, False),
    "DoorPaint": (HT.door_paint, 1, 1, 1, False),
    "WinFrame": (HT.window_frame, 1, 1, 1, False),
    "GlassWin": (HT.window_glass, 1, 1, 1, True),
    "Curtain": (lambda: HT.curtain(NU=512, NV=1024), 1, 1, 1, True),
    "Paintings": (HT.paintings, 1, 2, 2, False),
    "Leather": (HT.leather, 1, 1, 1, False),
    "NightSky": (HT.night_sky, 1, 0, 0, False),
})


def alpha_clip(mat):
    """Route texture alpha through Math:Round so the glTF exporter writes alphaMode MASK (cutoff 0.5)."""
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    sock = bsdf.inputs["Alpha"]
    if not sock.links:
        return
    src = sock.links[0].from_socket
    nt.links.remove(sock.links[0])
    rnd = nt.nodes.new("ShaderNodeMath")
    rnd.operation = "ROUND"
    rnd.location = (-250, 200)
    nt.links.new(src, rnd.inputs[0])
    nt.links.new(rnd.outputs[0], sock)
    mat.surface_render_method = "DITHERED"


def emissive_from_base(mat, strength=1.0):
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = [n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image and n.image.name.endswith("_base")][0]
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = strength


def build_materials():
    R.AO_IMAGE = bpy.data.images.new("Hallway_AO", AO_RES, AO_RES, alpha=False, float_buffer=False)
    R.AO_IMAGE.colorspace_settings.name = "Non-Color"
    R.AO_IMAGE.generated_color = (1, 1, 1, 1)
    names = ["Wall", "Floor", "Ceiling", "Trim", "Wood", "Iron", "Mattress", "Paper", "Backing", "Cobweb",
             "Decals", "Carpet", "Wainscot", "DoorPaint", "WinFrame", "GlassWin", "Curtain", "Paintings",
             "Leather", "NightSky"]
    tx = {k: R.texture_set(k) for k in names}
    mk = R.make_mat
    mk("Wall", tx["Wall"], vcol=True)
    mk("Floor", tx["Floor"], vcol=True)
    mk("Ceiling", tx["Ceiling"], vcol=True)
    mk("Trim", tx["Trim"], vcol=True)
    mk("Wainscot", tx["Wainscot"], vcol=True)
    mk("Carpet", tx["Carpet"])
    mk("Carpet_Back", tx["Backing"], factor=(0.42, 0.36, 0.30))
    mk("DoorPaint", tx["DoorPaint"])
    mk("WindowFrame", tx["WinFrame"])
    mk("Glass_Window", tx["GlassWin"], blend=True, double=True, ao=False)
    alpha_clip(mk("Curtain", tx["Curtain"], double=True, ao=False))
    mk("Painting", tx["Paintings"])
    mk("Leather", tx["Leather"])
    emissive_from_base(mk("Outside_Night", tx["NightSky"], ao=False, factor=(0.25, 0.25, 0.25), rough=1.0), 1.0)
    mk("Wood_Old", tx["Wood"])
    mk("Iron_Painted", tx["Iron"])
    mk("Iron_Dark", tx["Iron"], factor=(0.30, 0.30, 0.32))
    mk("Rubber", tx["Leather"], factor=(0.45, 0.5, 0.55))
    mk("Gilt", tx["Iron"], factor=(0.62, 0.45, 0.20))
    mk("Mattress", tx["Mattress"])
    mk("Paper", tx["Paper"])
    mk("Paper_Backing", tx["Backing"])
    mk("Paper_Backing_Dirty", tx["Backing"], factor=(0.62, 0.57, 0.50))
    mk("Wallpaper_Strip", tx["Wall"], factor=(0.85, 0.82, 0.78))
    mk("Plaster", tx["Ceiling"], factor=(0.9, 0.88, 0.85))
    mk("Terracotta", tx["Ceiling"], factor=(0.62, 0.36, 0.25))
    mk("DeadPlant", tx["Wood"], factor=(1.1, 0.95, 0.7))
    mk("Soil", tx["Ceiling"], factor=(0.16, 0.12, 0.09))
    mk("Cobweb", tx["Cobweb"], blend=True, double=True, ao=False)
    mk("Decal_Grime", tx["Decals"], blend=True, ao=False)
    mk("Brass", None, color=(0.42, 0.30, 0.14), rough=0.45, metal=0.9)
    mk("Bakelite", None, color=(0.09, 0.05, 0.03), rough=0.35)
    mk("Cord_Fabric", None, color=(0.10, 0.075, 0.055), rough=0.9)
    mk("Glass_Milk", None, color=(0.26, 0.25, 0.22), rough=0.45, alpha=0.8, double=True, ao=False)
    mk("Glass_Shard", None, color=(0.05, 0.055, 0.05), rough=0.04, alpha=0.6, double=True, ao=False)
    return tx


# =============================================================================== walls
CAS = [(p, q * 1.5) for p, q in [(0.003, 0), (0.003, 0.012), (0.006, 0.017), (0.011, 0.019), (0.016, 0.0175),
                                 (0.02, 0.016), (0.065, 0.017), (0.072, 0.019), (0.078, 0.024), (0.086, 0.025),
                                 (0.092, 0.022), (0.094, 0.015), (0.094, 0)]]
BASE_PROF = [(0, 0.19), (0.007, 0.19), (0.012, 0.186), (0.0135, 0.18), (0.0135, 0.172), (0.016, 0.166),
             (0.02, 0.16), (0.02, 0.022), (0.024, 0.021), (0.029, 0.017), (0.033, 0.01), (0.034, 0.0), (0, 0)]
CROWN = [(0, 0), (0, 0.11), (0.008, 0.11), (0.008, 0.098)]
for _i in range(9):
    _th = math.radians(180 + 90 * _i / 8)
    CROWN.append((0.1 + 0.088 * math.cos(_th), 0.1 + 0.088 * math.sin(_th)))
CROWN += [(0.098, 0.008), (0.11, 0.008), (0.11, 0)]
STOP = [(0, -0.0175), (-0.012, -0.0175), (-0.012, 0.0175), (0, 0.0175)]
PLINTH_W = 0.106


def paper_wall(mb, axis, c, s0, s1, nsign, holes, rolls, z0=0.0, mat=0):
    """Wallpaper a wall plane (x = c for axis 'x', y = c for axis 'y'), normal sign into the room.
    Returns (u_dir, seam0) so peel strips can find their roll."""
    if axis == "x":
        P = lambda s, z: (c, s, z)
        n = (nsign, 0, 0)
        u_dir = nsign
    else:
        P = lambda s, z: (s, c, z)
        n = (0, nsign, 0)
        u_dir = -nsign
    seam0 = s0 if u_dir > 0 else s1
    R.wall_panels(mb, P, s0, s1, z0, HH, holes, seam0, rolls, HH, n, mat, u_dir=u_dir)
    return u_dir, seam0


def column_of(seam0, u_dir, k):
    if u_dir > 0:
        return seam0 + k * ROLL, seam0 + (k + 1) * ROLL
    return seam0 - (k + 1) * ROLL, seam0 - k * ROLL


def casing(mb, face, kvec, s0, s1, ztop, axis="x", mat=0, plinth=True, zbot=None):
    """Door / window casing on a wall plane.  axis 'x': wall plane x = face, opening along y;
    axis 'y': wall plane y = face, opening along x.  kvec: +1/-1 = which way the wall face looks."""
    PZ = 0.24
    if axis == "x":
        origin, ea, k = (face, 0, 0), (0, 1, 0), (kvec, 0, 0)
    else:
        origin, ea, k = (0, face, 0), (1, 0, 0), (0, kvec, 0)
    zb = PZ if (plinth and zbot is None) else (zbot if zbot is not None else 0.0)
    sweep(mb, [(s0, zb), (s0, ztop), (s1, ztop), (s1, zb)], CAS, origin, ea, (0, 0, 1), k,
          uvs=TRIM_TILE, mat=mat, u0=float(RNG.uniform(0, 1)))
    if plinth:
        for sc in (s0 - 0.054, s1 + 0.054):
            if axis == "x":
                M = T((face + kvec * 0.021, sc, PZ / 2))
                R.box(mb, (0.042, 0.104, PZ), M, mat, bevel=0.004, segs=2, uvs=TRIM_TILE, grain=2)
            else:
                M = T((sc, face + kvec * 0.021, PZ / 2))
                R.box(mb, (0.104, 0.042, PZ), M, mat, bevel=0.004, segs=2, uvs=TRIM_TILE, grain=2)


def jambs(mb, side, yc, mat):
    xh, xr, _ = side_x(side)
    xa, xb = sorted((xh, xr))
    y0, y1 = yc - DW / 2, yc + DW / 2
    zl = lines(0, DHT, 0.25)
    xr_ = [xa, xb]
    grid_surface(mb, lambda x, z: (x, y0, z), xr_, zl, lambda x, z: (z / TRIM_TILE, x / TRIM_TILE), (0, 1, 0), mat)
    grid_surface(mb, lambda x, z: (x, y1, z), xr_, zl, lambda x, z: (z / TRIM_TILE, x / TRIM_TILE + 0.3), (0, -1, 0), mat)
    grid_surface(mb, lambda x, y: (x, y, DHT), xr_, lines(y0, y1, 0.3),
                 lambda x, y: (y / TRIM_TILE, x / TRIM_TILE + 0.6), (0, 0, -1), mat)


def reveal(mb, O, a_dir, out_dir, w, z0, z1, depth, mat):
    """Plaster reveal of a window opening: O = inner face centre at z = 0."""
    O, a, o = Vector(O), Vector(a_dir), Vector(out_dir)
    bl_ = [0.0, depth]
    zl = lines(z0, z1, 0.25)
    for sgn in (-1, 1):
        grid_surface(mb, lambda b, z, sgn=sgn: O + a * (sgn * w / 2) + o * b + Vector((0, 0, z)), bl_, zl,
                     lambda b, z: (b / CT, z / CT), -a * sgn, mat)
    al = lines(-w / 2, w / 2, 0.3)
    grid_surface(mb, lambda s, b: O + a * s + o * b + Vector((0, 0, z1)), al, bl_,
                 lambda s, b: (s / CT, b / CT), (0, 0, -1), mat)
    grid_surface(mb, lambda s, b: O + a * s + o * b + Vector((0, 0, z0)), al, bl_,
                 lambda s, b: (s / CT, b / CT), (0, 0, 1), mat)


def peel_strip(mb, P3, x0, x1, u_dir, origin_u, za, length, n_in, rng, mats_=(0, 1)):
    """Wallpaper peeled from the top (after room.build_peel_strips), on any wall.
    P3(s, z, n) -> world point, n = offset from the wall into the room."""
    Fr, Bk = mats_
    nu, ns = 10, 30
    lens = np.convolve(rng.uniform(0.55, 1.0, nu + 5), np.ones(3) / 3, mode="valid")[:nu + 1] * length
    lens *= 1 - 0.35 * np.abs(np.linspace(-1, 1, nu + 1)) ** 3
    curl_end = -rng.uniform(0.5, 1.0)

    def theta(s, L):
        if s < 0.06:
            return math.pi * s / 0.06
        if s < 0.6 * L:
            return math.pi + 0.06 * (s - 0.09) / max(0.6 * L - 0.09, 1e-3)
        return math.pi + 0.06 + curl_end * ((s - 0.6 * L) / (0.4 * L)) ** 1.8

    cols = []
    for i in range(nu + 1):
        L = lens[i]
        ss_ = np.linspace(0, L, ns + 1)
        pts = [(0.0, 0.0)]
        for a, b in zip(ss_[:-1], ss_[1:]):
            th = theta(0.5 * (a + b), L)
            pts.append((pts[-1][0] + (b - a) * math.sin(th), pts[-1][1] + (b - a) * math.cos(th)))
        cols.append((ss_, pts))
    W = x1 - x0
    faces = []
    for side in (0, 1):
        ids = {}
        for i in range(nu + 1):
            t = i / nu
            ss_, pts = cols[i]
            for j in range(ns + 1):
                n_off, dz = pts[j]
                f = j / ns
                taper = 0.06 * f ** 2 * (2 * t - 1)
                d = W * (0.02 + 0.92 * t) - taper * W
                s_world = x0 + d if u_dir > 0 else x1 - d
                sway = 0.012 * f ** 2 * math.sin(t * 3.0 + 1.0)
                ids[(i, j)] = mb.v(P3(s_world, za + dz, max(0.003, n_off * 0.6) + sway + side * 0.0006))
        for i in range(nu):
            for j in range(ns):
                q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                if side == 0:
                    uv = [((origin_u + W * (0.02 + 0.92 * a / nu)) / WALL_TILE, (za + cols[a][0][b]) / HH) for a, b in q]
                    m = Fr
                else:
                    q = q[::-1]
                    uv = [((a / nu) * W / 0.5, cols[a][0][b] / 0.5) for a, b in q]
                    m = Bk
                faces.append(([ids[k] for k in q], uv, m))
    # orientation: the first quad of the paper side must face the room
    v = [Vector(mb.V[k]) for k in faces[0][0]]
    flip = (v[1] - v[0]).cross(v[3] - v[0]).dot(Vector(n_in)) < 0
    for vids, uv, m in faces:
        if flip:
            vids, uv = vids[::-1], uv[::-1]
        mb.f(vids, uv, m)


def wainscot_segment(mb, P0, s_dir, n_dir, s0, s1, top=ZW, rng=None, skip_panel=None):
    """Panelled wainscot from s0 to s1 along a wall: backing, rails, stiles, raised panels, baseboard, cap.
    P0 = point on the wall plane at s = 0, z = 0.  Pieces are closed boxes / sweeps (rebuild normals)."""
    Mb = basis(s_dir, n_dir, P0)
    L = s1 - s0
    BK = 0.012                                  # backing thickness
    box = lambda size, c, grain, bev=0.003: R.box(mb, size, Mb @ T(c), 0, bevel=bev, segs=2, uvs=WOOD_TILE, grain=grain)
    box((L, BK, top), (s0 + L / 2, BK / 2, top / 2), 0, 0.0)
    z_br0, z_br1 = 0.17, 0.27
    z_tr0, z_tr1 = top - 0.13, top - 0.035
    box((L, 0.022, z_br1 - z_br0), (s0 + L / 2, BK + 0.011, (z_br0 + z_br1) / 2), 0)
    box((L, 0.022, z_tr1 - z_tr0), (s0 + L / 2, BK + 0.011, (z_tr0 + z_tr1) / 2), 0)
    npan = max(1, int(round((L - 0.09) / 0.6)))
    pw = (L - 0.09) / npan
    for k in range(npan + 1):
        sc = s0 + 0.045 + k * pw
        box((0.09, 0.022, z_tr0 - z_br1), (sc, BK + 0.011, (z_br1 + z_tr0) / 2), 2)
    for k in range(npan):
        if skip_panel is not None and k == skip_panel:
            continue
        sc = s0 + 0.045 + (k + 0.5) * pw
        ph = z_tr0 - z_br1
        box((pw - 0.09 + 0.02, 0.016, ph + 0.02), (sc, BK + 0.008, (z_br1 + z_tr0) / 2), 2, 0.0)
        tilt = 0.0 if rng is None else float(rng.normal(0, 0.004))
        R.box(mb, (pw - 0.09 - 0.05, 0.012, ph - 0.05),
              Mb @ T((sc, BK + 0.016 + 0.006, (z_br1 + z_tr0) / 2), (tilt, 0, 0)), 0, bevel=0.011, segs=2,
              uvs=WOOD_TILE, grain=2)
    P0v, sd, nd = Vector(P0), Vector(s_dir), Vector(n_dir)
    # baseboard + cap rail as sweeps in the (s, n) plane
    cap = [(0, top - 0.04), (0.026, top - 0.04), (0.03, top - 0.032), (0.03, top - 0.02), (0.042, top - 0.012),
           (0.045, top - 0.002), (0.042, top + 0.008), (0.03, top + 0.014), (0, top + 0.014)]
    for prof, u0 in ((BASE_PROF, 0.1), (cap, 0.6)):
        sweep(mb, [(s0, BK), (s1, BK)], prof, P0v, sd, nd, (0, 0, 1), uvs=TRIM_TILE, mat=0, u0=u0)


def build_hallway():
    mb = MB()
    W, F, C, TR, WD = 0, 1, 2, 3, 4
    Ldoors = [(d[0], d[2]) for d in DOORS if d[1] == "L"]
    Rdoors = [(d[0], d[2]) for d in DOORS if d[1] == "R"]
    edges = [y + s * DW / 2 for _, y in Ldoors + Rdoors for s in (-1, 1)]
    xl = lines(HX0, HX1, 0.1)
    yl = lines(HY0, HY1, 0.1, edges)
    grid_surface(mb, lambda s, t: (s, t, 0), xl, yl, lambda s, t: (t / FT + 0.37, -s / FT + 0.11), (0, 0, 1), F)
    # ceiling with a broken hole (plaster fallen, lath and joists above)
    cx, cy, rx, ry = CEIL_HOLE

    def in_hole(x, y):
        th = math.atan2((y - cy) / ry, (x - cx) / rx)
        rr = math.hypot((x - cx) / rx, (y - cy) / ry)
        return rr < 1 + 0.22 * math.sin(5 * th + 1) + 0.12 * math.sin(11 * th + 2)
    hole_cells = set()
    for i in range(len(xl) - 1):
        for j in range(len(yl) - 1):
            xa, xb, ya, yb = xl[i], xl[i + 1], yl[j], yl[j + 1]
            if in_hole(0.5 * (xa + xb), 0.5 * (ya + yb)):
                hole_cells.add((i, j))
                continue
            q = [(xa, ya), (xa, yb), (xb, yb), (xb, ya)]       # faces down
            ids = [mb.v((x, y, HH)) for x, y in q]
            mb.f(ids, [(x / CT + 0.31, y / CT + 0.17) for x, y in q], C)
    # plaster thickness at the hole rim
    PT = 0.022
    for (i, j) in hole_cells:
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (i + di, j + dj) in hole_cells:
                continue
            if di == 1:
                e = ((xl[i + 1], yl[j]), (xl[i + 1], yl[j + 1]))
            elif di == -1:
                e = ((xl[i], yl[j]), (xl[i], yl[j + 1]))
            elif dj == 1:
                e = ((xl[i], yl[j + 1]), (xl[i + 1], yl[j + 1]))
            else:
                e = ((xl[i], yl[j]), (xl[i + 1], yl[j]))
            p = [Vector((e[0][0], e[0][1], HH)), Vector((e[1][0], e[1][1], HH)),
                 Vector((e[1][0], e[1][1], HH + PT)), Vector((e[0][0], e[0][1], HH + PT))]
            ctr = Vector((0.5 * (xl[i] + xl[i + 1]), 0.5 * (yl[j] + yl[j + 1]), HH))
            mid = (p[0] + p[1]) / 2
            nrm = (ctr - mid)
            ids = [mb.v(v) for v in p]
            uv = [(0, 0), (0.1 / CT, 0), (0.1 / CT, PT / CT), (0, PT / CT)]
            if (p[1] - p[0]).cross(p[3] - p[0]).dot(nrm) < 0:
                ids, uv = ids[::-1], uv[::-1]
            mb.f(ids, uv, C)
    # cavity above the hole (closed box, seen from inside)
    ca0, ca1, cb0, cb1 = cx - rx - 0.35, cx + rx + 0.35, cy - ry - 0.3, cy + ry + 0.3
    zt = HH + 0.32
    cav_x, cav_y, cav_z = lines(ca0, ca1, 0.3), lines(cb0, cb1, 0.3), [HH + PT, zt]
    grid_surface(mb, lambda x, y: (x, y, zt), cav_x, cav_y, lambda x, y: (y / WOOD_TILE, x / WOOD_TILE), (0, 0, -1), WD)
    grid_surface(mb, lambda x, y: (x, y, HH + PT), cav_x, cav_y, lambda x, y: (x / CT, y / CT), (0, 0, 1), C)
    for xx, nx in ((ca0, 1), (ca1, -1)):
        grid_surface(mb, lambda y, z, xx=xx: (xx, y, z), cav_y, cav_z, lambda y, z: (y / CT, z / CT), (nx, 0, 0), C)
    for yy, ny in ((cb0, 1), (cb1, -1)):
        grid_surface(mb, lambda x, z, yy=yy: (x, yy, z), cav_x, cav_z, lambda x, z: (x / CT, z / CT), (0, ny, 0), C)

    # walls: wallpaper full height (wainscot is built in front of the lower metre)
    L_rolls = list(RNG.integers(0, 5, 32))
    R_rolls = list(RNG.integers(0, 5, 32))
    for k in (11, 24):
        L_rolls[k] = 3
    for k in (17, 27):
        L_rolls[k] = 1
    for k in (8, 9, 10, 12, 16, 18, 19, 20, 23, 25, 26, 28):
        if L_rolls[k] in (1, 3):
            L_rolls[k] = 2
    for k in (16,):
        R_rolls[k] = 3
    for k in (21, 7):
        R_rolls[k] = 1
    for k in (14, 15, 8, 9, 20, 22):
        if R_rolls[k] in (1, 3):
            R_rolls[k] = 4
    E_rolls = [1, 2, 0, 4, 3]
    N_rolls = [2, 0, 4, 1, 2]
    holesL = [(y - DW / 2, y + DW / 2, 0, DHT) for _, y in Ldoors]
    holesR = [(y - DW / 2, y + DW / 2, 0, DHT) for _, y in Rdoors]
    walls = {}
    walls["L"] = paper_wall(mb, "x", HX0, HY0, HY1, +1, holesL, L_rolls) + (L_rolls,)
    walls["R"] = paper_wall(mb, "x", HX1, HY0, HY1, -1, holesR, R_rolls) + (R_rolls,)
    walls["E"] = paper_wall(mb, "y", HY1, HX0, HX1, -1, [(-EW_W / 2, EW_W / 2, EW_Z, EW_Z + EW_H)], E_rolls) + (E_rolls,)
    walls["N"] = paper_wall(mb, "y", HY0, HX0, HX1, +1, [], N_rolls) + (N_rolls,)
    for d in DOORS:
        jambs(mb, d[1], d[2], TR)
    reveal(mb, (0, HY1, 0), (1, 0, 0), (0, 1, 0), EW_W, EW_Z, EW_Z + EW_H, EWT, C)
    shell = obj_from(mb, "Hallway_shell", ["Wall", "Floor", "Ceiling", "Trim", "Wood_Old"])
    shell.data.validate()

    # trims: crown, casings, stops
    tm = MB()
    sweep(tm, [(HX0, HY1), (HX0, HY0), (HX1, HY0), (HX1, HY1)], CROWN, (0, 0, HH), (1, 0, 0), (0, 1, 0), (0, 0, -1),
          closed=True, uvs=TRIM_TILE, mat=0, u0=0.37)
    for did, side, yc, hinge, ang in DOORS:
        xh, xr, nr = side_x(side)
        kin = -nr.x                       # hallway face looks into the hallway
        casing(tm, xh, kin, yc - DW / 2, yc + DW / 2, DHT, "x", 0)
        xs = xr - nr.x * (0.047 + 0.0175)
        sweep(tm, [(yc - DW / 2, 0.0), (yc - DW / 2, DHT), (yc + DW / 2, DHT), (yc + DW / 2, 0.0)], STOP,
              (xs, 0, 0), (0, 1, 0), (0, 0, 1), (kin, 0, 0), uvs=TRIM_TILE, mat=0)
    trims = obj_from(tm, "Hallway_trim", ["Trim"], recalc=True)

    # wainscot along all four walls, interrupted by the door casings and the end window
    wm = MB()
    wrng = np.random.default_rng(77)

    def segs_along(ys, a, b):
        cuts = sorted((y - DW / 2 - PLINTH_W, y + DW / 2 + PLINTH_W) for y in ys)
        out, cur = [], a
        for c0, c1 in cuts:
            if c0 > cur + 0.05:
                out.append((cur, c0))
            cur = max(cur, c1)
        if b > cur + 0.05:
            out.append((cur, b))
        return out
    for s0, s1 in segs_along([y for _, y in Ldoors], HY0, HY1):
        skip = 0 if (s0 < 8.0 < s1) else None
        wainscot_segment(wm, (HX0, 0, 0), (0, 1, 0), (1, 0, 0), s0, s1, rng=wrng,
                         skip_panel=(int((8.35 - s0 - 0.045) // ((s1 - s0 - 0.09) / max(1, round((s1 - s0 - 0.09) / 0.6)))) if skip is not None else None))
    for s0, s1 in segs_along([y for _, y in Rdoors], HY0, HY1):
        wainscot_segment(wm, (HX1, 0, 0), (0, 1, 0), (-1, 0, 0), s0, s1, rng=wrng)
    wx0, wx1 = -EW_W / 2 - 0.12, EW_W / 2 + 0.12
    wainscot_segment(wm, (0, HY1, 0), (1, 0, 0), (0, -1, 0), HX0, wx0, rng=wrng)
    wainscot_segment(wm, (0, HY1, 0), (1, 0, 0), (0, -1, 0), wx1, HX1, rng=wrng)
    wainscot_segment(wm, (0, HY1, 0), (1, 0, 0), (0, -1, 0), wx0, wx1, top=EW_Z - 0.105, rng=wrng)
    wainscot_segment(wm, (0, HY0, 0), (1, 0, 0), (0, 1, 0), HX0, HX1, rng=wrng)
    wains = obj_from(wm, "Hallway_wainscot", ["Wainscot"], recalc=True)

    # thresholds + leftover hinges on empty openings
    th = MB()
    for did, side, yc, hinge, ang in DOORS:
        xh, xr, nr = side_x(side)
        R.box(th, (WT + 0.03, DW + 0.03, 0.02), T(((xh + xr) / 2, yc, 0.006)), 0, bevel=0.006, segs=3, uvs=WOOD_TILE, grain=1)
    thr = obj_from(th, "Hallway_thresholds", ["Wood_Old"])

    # peeling wallpaper strips at the roll-3 columns (the texture shows the peeled area there)
    pm = MB()
    prng = np.random.default_rng(17)
    za = 1.98 * HH / 2.75
    P3s = {
        "L": (lambda s, z, n: (HX0 + n, s, z), (1, 0, 0)),
        "R": (lambda s, z, n: (HX1 - n, s, z), (-1, 0, 0)),
        "E": (lambda s, z, n: (s, HY1 - n, z), (0, -1, 0)),
    }
    for key, (P3, n_in) in P3s.items():
        u_dir, seam0, rolls = walls[key]
        for k, r in enumerate(rolls):
            if r != 3:
                continue
            x0, x1 = column_of(seam0, u_dir, k)
            lo, hi = (HY0, HY1) if key in "LR" else (HX0, HX1)
            if x0 < lo - 1e-6 or x1 > hi + 1e-6:
                continue
            blocked = False
            for d in DOORS:
                if (key == d[1]) and (x0 < d[2] + DW / 2 + PLINTH_W and x1 > d[2] - DW / 2 - PLINTH_W):
                    blocked = True
            if key == "E" and x0 < EW_W / 2 + 0.1 and x1 > -EW_W / 2 - 0.1:
                blocked = True
            if blocked:
                continue
            if u_dir > 0:
                x1 = x0 + ROLL * float(prng.uniform(0.55, 0.8))
            else:
                x0 = x1 - ROLL * float(prng.uniform(0.55, 0.8))
            peel_strip(pm, P3, x0, x1, u_dir, 0.03 + 3 * ROLL, za, float(prng.uniform(0.4, 0.6)), n_in, prng)
    peel = obj_from(pm, "Hallway_peel", ["Wallpaper_Strip", "Paper_Backing_Dirty"], smooth_deg=70)

    # lath + joists in the ceiling hole
    lm = MB()
    for yj in (cb0 + 0.12, cy, cb1 - 0.12):
        R.box(lm, (ca1 - ca0, 0.05, 0.2), T((cx, yj, HH + PT + 0.1)), 0, bevel=0.004, uvs=WOOD_TILE, grain=0)
    lr = np.random.default_rng(31)
    x = ca0 + 0.03
    while x < ca1 - 0.03:
        if lr.random() < 0.8:
            ya, yb = cb0 + 0.02, cb1 - 0.02
            # broken lath: cut at a random point inside the hole, the free end hangs down
            if in_hole(x, cy) and lr.random() < 0.45:
                yb2 = cy + lr.uniform(-0.15, 0.15)
                R.box(lm, (0.035, yb2 - ya, 0.007), T((x, (ya + yb2) / 2, HH + PT + 0.004)), 0, bevel=0.001, segs=1, uvs=WOOD_TILE, grain=1)
                Lh = lr.uniform(0.1, 0.35)
                ang = lr.uniform(0.5, 1.2)
                R.box(lm, (0.035, Lh, 0.007), T((x, yb2 + 0.02, HH + PT + 0.004)) @ T(rot=(-ang, 0, 0)) @ T((0, Lh / 2, 0)),
                      0, bevel=0.001, segs=1, uvs=WOOD_TILE, grain=1)
            else:
                R.box(lm, (0.035, yb - ya, 0.007), T((x, (ya + yb) / 2, HH + PT + 0.004)), 0, bevel=0.001, segs=1, uvs=WOOD_TILE, grain=1)
        x += 0.047
    lath = obj_from(lm, "Hallway_lath", ["Wood_Old"])
    hall = join_objs("Hallway", [shell, trims, wains, thr, peel, lath])
    return hall, walls


# =============================================================================== windows + curtains
def build_window(wid, O, n_in, a_dir, w, h, z0, depth, trim_mb, flip_glass=False):
    """Sash window (2 over 2) in an opening whose inner-face centre is O (at z = 0).
    Returns (frame object, glass object); the inner casing is added to trim_mb."""
    O, n_in, a = Vector(O), Vector(n_in), Vector(a_dir)
    out = -n_in
    Mb = basis(a, out, O)
    fm = MB()
    Fr, Br = 0, 1
    fb0 = depth * 0.35
    fd = 0.1

    def bx(size, c, grain, m=Fr, bev=0.003):
        R.box(fm, size, Mb @ T(c), m, bevel=bev, segs=2, uvs=0.5, grain=grain)
    # frame
    for s in (-1, 1):
        bx((0.045, fd, h), (s * (w / 2 - 0.0225), fb0 + fd / 2, z0 + h / 2), 2)
    bx((w, fd, 0.045), (0, fb0 + fd / 2, z0 + h - 0.0225), 0)
    bx((w + 0.04, 0.16, 0.04), (0, fb0 + 0.08, z0 + 0.02), 0)
    # sashes
    wi = w - 0.09
    zs0, zs1 = z0 + 0.04, z0 + h - 0.045
    hi = zs1 - zs0
    gm = MB()
    sash_planes = []
    for k, (za_, zb_, b0) in enumerate(((zs0, zs0 + hi / 2 + 0.018, fb0 + 0.012), (zs0 + hi / 2 - 0.018, zs1, fb0 + 0.052))):
        bt = 0.036
        bc = b0 + bt / 2
        sh = zb_ - za_
        for s in (-1, 1):
            bx((0.042, bt, sh), (s * (wi / 2 - 0.021), bc, (za_ + zb_) / 2), 2)
        rb = 0.065 if k == 0 else 0.03
        rt = 0.03 if k == 0 else 0.045
        bx((wi - 0.084, bt, rb), (0, bc, za_ + rb / 2), 0)
        bx((wi - 0.084, bt, rt), (0, bc, zb_ - rt / 2), 0)
        bx((0.022, bt * 0.8, sh - rb - rt), (0, bc, za_ + rb + (sh - rb - rt) / 2), 2)
        # glass quad in the sash plane (double-sided material, UV over the whole window)
        ga0, ga1 = -wi / 2 + 0.03, wi / 2 - 0.03
        gz0, gz1 = za_ + rb - 0.01, zb_ - rt + 0.01
        corners = [(ga0, gz0), (ga1, gz0), (ga1, gz1), (ga0, gz1)]
        ids = [gm.v(O + a * s_ + out * bc + Vector((0, 0, z))) for s_, z in corners]
        uv = [(((s_ + w / 2) / w) if not flip_glass else 1 - (s_ + w / 2) / w, (z - z0) / h) for s_, z in corners]
        v = [Vector(gm.V[i]) for i in ids]
        if (v[1] - v[0]).cross(v[3] - v[0]).dot(n_in) < 0:
            ids, uv = ids[::-1], uv[::-1]
        gm.f(ids, uv, 0)
    # sash lock on the meeting rail
    bx((0.05, 0.012, 0.02), (0.0, fb0 + 0.006, zs0 + hi / 2 + 0.01), 0, Br, 0.002)
    # stool + apron (room side)
    bx((w + 0.16, fb0 + 0.05, 0.03), (0, (fb0 - 0.05) / 2, z0 - 0.015), 0)
    bx((w + 0.08, 0.02, 0.075), (0, -0.01, z0 - 0.03 - 0.0375), 0)
    frame = obj_from(fm, f"WindowFrame_{wid}", ["WindowFrame", "Brass"], recalc=True)
    glass = obj_from(gm, f"WindowGlass_{wid}", ["Glass_Window"], smooth_deg=10)
    # inner casing on the wall face
    sweep(trim_mb, [(-w / 2, z0), (-w / 2, z0 + h), (w / 2, z0 + h), (w / 2, z0)], CAS, O, a, (0, 0, 1), n_in,
          uvs=TRIM_TILE, mat=0, u0=float(RNG.uniform(0, 1)))
    return frame, glass


def drape(mb, O, a_dir, n_in, w_win, rod_z, side, rng, torn=0.0, flat_w=0.8, uoff=0.0):
    """One tattered drape hanging from the rod, pleated, gathered to one side of the window.
    torn > 0 drops the inner top corner off the rod by that many metres."""
    O, a, n = Vector(O), Vector(a_dir), Vector(n_in)
    nu, nv = 34, 44
    L = rod_z - 0.03
    a_out = side * (w_win / 2 + 0.24)
    a_in = side * (w_win / 2 - 0.14 + rng.uniform(-0.04, 0.04))
    ph = rng.uniform(0, TAU)
    ids = {}
    for i in range(nu + 1):
        t = i / nu
        drop = torn * RT.ss(0.35, 1.0, t) if torn else 0.0
        for j in range(nv + 1):
            f = j / nv
            s = f * L                            # arclength down the fabric
            z = rod_z - 0.03 - drop - s
            aa = a_out + (a_in - a_out) * t * (1 - 0.15 * f) + side * 0.06 * f * math.sin(ph + t * 3)
            if torn:
                aa += (a_out - aa) * 0.25 * RT.ss(0.35, 1.0, t) * (1 - f)
            pleat = 0.032 * math.sin(t * flat_w / 0.12 * TAU + ph) * (1 - 0.35 * f)
            nn = 0.075 + pleat + 0.05 * f ** 1.5 + 0.01 * math.sin(f * 9 + t * 5)
            if z < 0.006:                        # pools on the floor
                nn += (0.006 - z) * 0.8
                z = 0.006 + 0.002 * math.sin(t * 20)
            ids[(i, j)] = mb.v(O + a * aa + n * nn + Vector((0, 0, z)))
    for i in range(nu):
        for j in range(nv):
            q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            uv = [(uoff + (ii / nu) * flat_w / 0.8, 1.0 - (jj / nv) * L / 2.4) for ii, jj in q]
            mb.f([ids[k] for k in q], uv, 0)


def curtain_rod(mb, O, a_dir, n_in, w_win, rod_z, mat=0):
    O, a, n = Vector(O), Vector(a_dir), Vector(n_in)
    e = w_win / 2 + 0.32
    tube(mb, [O + a * -e + n * 0.08 + Vector((0, 0, rod_z)), O + a * e + n * 0.08 + Vector((0, 0, rod_z))], 0.011, 10, mat, IRON_TILE)
    for s in (-1, 1):
        c = O + a * (s * (e + 0.02)) + n * 0.08 + Vector((0, 0, rod_z))
        M = Matrix.Rotation(math.pi / 2, 3, Vector(a).cross(Vector((0, 0, 1))).normalized()) if abs(a.z) < 0.9 else None
        lathe(mb, [(0, -0.03), (0.016, -0.025), (0.022, -0.01), (0.02, 0.01), (0.012, 0.025), (0, 0.03)],
              c, 12, mat, IRON_TILE, axis_m=M)
        b = O + a * (s * (e - 0.08)) + Vector((0, 0, rod_z))
        tube(mb, [b + n * 0.005, b + n * 0.08], 0.006, 8, mat, IRON_TILE)
    for k in range(10):
        t = (k + 0.5) / 10
        c = O + a * (-e + 2 * e * t) + n * 0.08 + Vector((0, 0, rod_z - 0.002))
        ring = [c + (a * 0.0 + n * math.cos(th) * 0.018 + Vector((0, 0, math.sin(th) * 0.018))) for th in np.linspace(0, TAU, 13)]
        tube(mb, ring, 0.0025, 5, mat, IRON_TILE, caps=False)


# =============================================================================== side rooms
def build_side_room(did, side, yc, rng):
    rx0, rx1, ry0, ry1 = room_box(side, yc)
    mb = MB()
    W, F, C, TR = 0, 1, 2, 3
    xl = lines(rx0, rx1, 0.1)
    yl = lines(ry0, ry1, 0.1, (yc - DW / 2, yc + DW / 2, yc - SW_W / 2, yc + SW_W / 2))
    fo = rng.uniform(0, 1, 2)
    grid_surface(mb, lambda s, t: (s, t, 0), xl, yl, lambda s, t: (t / FT + fo[0], s / FT + fo[1]), (0, 0, 1), F)
    grid_surface(mb, lambda s, t: (s, t, HH), xl, yl, lambda s, t: (s / CT + fo[1], t / CT + fo[0]), (0, 0, -1), C)
    rolls = lambda: list(rng.integers(0, 5, 12))
    door_hole = [(yc - DW / 2, yc + DW / 2, 0, DHT)]
    win_hole = [(yc - SW_W / 2, yc + SW_W / 2, SW_Z, SW_Z + SW_H)]
    if side == "L":
        door_x, far_x, n_door, n_far = rx1, rx0, -1, +1
    else:
        door_x, far_x, n_door, n_far = rx0, rx1, +1, -1
    paper_wall(mb, "x", door_x, ry0, ry1, n_door, door_hole, rolls())
    paper_wall(mb, "x", far_x, ry0, ry1, n_far, win_hole, rolls())
    paper_wall(mb, "y", ry0, rx0, rx1, +1, [], rolls())
    paper_wall(mb, "y", ry1, rx0, rx1, -1, [], rolls())
    O_win = Vector((far_x, yc, 0))
    n_in = Vector((n_far, 0, 0))
    reveal(mb, O_win, (0, 1, 0), -n_in, SW_W, SW_Z, SW_Z + SW_H, RWT, C)
    shell = obj_from(mb, f"SideRoom_{did}_shell", ["Wall", "Floor", "Ceiling", "Trim"])

    tm = MB()
    PL = 0.105
    if side == "L":
        path = [(rx1, yc + DW / 2 + PL), (rx1, ry1), (rx0, ry1), (rx0, ry0), (rx1, ry0), (rx1, yc - DW / 2 - PL)]
    else:
        path = [(rx0, yc - DW / 2 - PL), (rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1), (rx0, yc + DW / 2 + PL)]
    sweep(tm, path, BASE_PROF, (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), uvs=TRIM_TILE, mat=0)
    sweep(tm, [(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)], CROWN, (0, 0, HH), (1, 0, 0), (0, 1, 0), (0, 0, -1),
          closed=True, uvs=TRIM_TILE, mat=0, u0=float(rng.uniform(0, 1)))
    casing(tm, door_x, n_door, yc - DW / 2, yc + DW / 2, DHT, "x", 0)
    frame, glass = build_window(did, O_win, n_in, (0, 1, 0), SW_W, SW_H, SW_Z, RWT, tm, flip_glass=bool(rng.random() < 0.5))
    trims = obj_from(tm, f"SideRoom_{did}_trim", ["Trim"], recalc=True)
    room = join_objs(f"SideRoom_{did}", [shell, trims])
    R.paint_dirt(room, (rx0, ry0, 0), (rx1, ry1, HH), HH, corridor=True)

    # curtains
    cm = MB()
    rod_z = SW_Z + SW_H + 0.14
    torn = {"L1": 0.0, "R1": 0.55, "L2": 0.0, "R2": 0.0, "L3": 0.9, "R3": 0.0}[did]
    drape(cm, O_win, (0, 1, 0), n_in, SW_W, rod_z, -1, rng, torn=0.0, uoff=float(rng.uniform(0, 1)))
    if did != "R2":
        drape(cm, O_win, (0, 1, 0), n_in, SW_W, rod_z, +1, rng, torn=torn, uoff=float(rng.uniform(0, 1)))
    curtains = obj_from(cm, f"Curtains_{did}", ["Curtain"], smooth_deg=80)
    rm = MB()
    curtain_rod(rm, O_win, (0, 1, 0), n_in, SW_W, rod_z)
    rod = obj_from(rm, f"CurtainRod_{did}", ["Iron_Dark"], recalc=True, smooth_deg=50)
    COLLIDERS.append((f"COL_SideRoom_{did}_FarWall", ((far_x - n_far * RWT / 2), yc, HH / 2), (RWT, RWID + 2 * WT, HH), 0.0))
    for yy, sg in ((ry0, -1), (ry1, 1)):
        COLLIDERS.append((f"COL_SideRoom_{did}_SideWall{'AB'[(sg + 1) // 2]}",
                          ((rx0 + rx1) / 2 - n_far * RWT / 2 * 0, yy + sg * WT / 2, HH / 2), (RD, WT, HH), 0.0))
    return room, frame, glass, curtains, rod, (rx0, rx1, ry0, ry1)


# =============================================================================== doors
def door_leaf_mesh(width=0.87, height=2.075, t=0.042, rng=None):
    """Four-panel door in local space: hinge edge on the local Z axis, leaf along +X, thickness +-Y/2."""
    mb = MB()
    Pn, Br, Ir = 0, 1, 2
    sw, rt, rl, rb = 0.115, 0.115, 0.17, 0.22
    zl = 0.93
    b = lambda size, c, grain, m=Pn, bev=0.003: R.box(mb, size, T(c), m, bevel=bev, segs=2, uvs=WOOD_TILE, grain=grain)
    b((sw, t, height), (sw / 2, 0, height / 2), 2)
    b((sw, t, height), (width - sw / 2, 0, height / 2), 2)
    iw = width - 2 * sw
    b((iw, t * 0.98, rt), (width / 2, 0, height - rt / 2), 0)
    b((iw, t * 0.98, rl), (width / 2, 0, zl), 0)
    b((iw, t * 0.98, rb), (width / 2, 0, rb / 2), 0)
    mw = 0.1
    b((mw, t * 0.96, height - rt - rl - rb), (width / 2, 0, (rb + (height - rt)) / 2), 2)
    # panels: thin board + raised field on both faces
    for z0, z1 in ((rb, zl - rl / 2), (zl + rl / 2, height - rt)):
        for xc in (sw + (iw - mw) / 4, width - sw - (iw - mw) / 4):
            pw = (iw - mw) / 2
            ph = z1 - z0
            b((pw + 0.02, 0.014, ph + 0.02), (xc, 0, (z0 + z1) / 2), 2, bev=0.0)
            for sgn in (-1, 1):
                b((pw - 0.06, 0.008, ph - 0.06), (xc, sgn * 0.009, (z0 + z1) / 2), 2, bev=0.012)
    # knobs + escutcheons both sides, hinges on the hinge edge
    xk = width - 0.065
    for sgn in (-1, 1):
        M = Matrix.Rotation(-sgn * math.pi / 2, 3, "X")
        lathe(mb, [(0, 0.072), (0.02, 0.07), (0.028, 0.06), (0.029, 0.05), (0.022, 0.04), (0.009, 0.033),
                   (0.008, 0.012), (0.016, 0.006), (0.016, 0.0), (0, 0)], (xk, sgn * t / 2, zl), 18, Br, 0.2, axis_m=M)
        b((0.045, 0.004, 0.15), (xk, sgn * (t / 2 + 0.002), zl - 0.03), 2, Br, 0.0015)
    for zc in (0.25, height - 0.3):
        b((0.004, 0.035, 0.1), (0.0, -t / 2 + 0.0175, zc), 2, Ir, 0.001)
        tube(mb, [(-0.004, -t / 2 - 0.004, zc - 0.05), (-0.004, -t / 2 - 0.004, zc + 0.05)], 0.0065, 10, Ir, IRON_TILE)
    return mb


def build_doors():
    out, extras = [], []
    for did, side, yc, hinge, ang in DOORS:
        xh, xr, nr = side_x(side)
        if hinge in ("near", "far"):
            yj = yc - DW / 2 if hinge == "near" else yc + DW / 2
            c = Vector((0, 1, 0)) if hinge == "near" else Vector((0, -1, 0))
            axis = Vector((xr - nr.x * 0.026, yj + c.y * 0.025, 0.004))
            th = math.radians(ang)
            w = (c * math.cos(th) + nr * math.sin(th)).normalized()
            yv = Vector((0, 0, 1)).cross(w)
            # local -Y side should face the hinge stop side -> mirror the leaf when needed
            mbd = door_leaf_mesh()
            ob = obj_from(mbd, f"DoorLeaf_{did}", ["DoorPaint", "Brass", "Iron_Dark"], recalc=True)
            ob.matrix_world = Matrix(((w.x, yv.x, 0, axis.x), (w.y, yv.y, 0, axis.y), (0, 0, 1, axis.z), (0, 0, 0, 1)))
            sign = 1 if c.cross(nr).z > 0 else -1
            ob["open_deg"] = ang
            ob["open_sign"] = sign
            out.append(ob)
            yaw = math.atan2(w.y, w.x)
            cx_ = axis + w * 0.435
            COLLIDERS.append((f"COL_DoorLeaf_{did}", (cx_.x, cx_.y, 2.075 / 2 + 0.004), (0.87, 0.045, 2.075), yaw))
            extras.append((did, ang, sign, axis, yaw))
        elif hinge == "torn":
            mbd = door_leaf_mesh()
            ob = obj_from(mbd, f"FallenDoor_{did}", ["DoorPaint", "Brass", "Iron_Dark"], recalc=True)
            # lay it face up on the hallway floor, propped on debris at one end
            M = (T((0.22, yc + 0.75, 0.0)) @ T(rot=(0, 0, math.radians(-30))) @ T(rot=(math.radians(-90), 0, 0))
                 @ T(rot=(0, math.radians(1.2), 0)) @ T((-0.435, 0, -2.075 / 2)))
            transform_obj(ob, M)
            rest_on_floor(ob, 0.004)
            out.append(ob)
            yaw = math.radians(-30)
            bb = [ob.matrix_world @ Vector(v.co) for v in ob.data.vertices]
            ctr = sum(bb, Vector()) / len(bb)
            COLLIDERS.append((f"COL_FallenDoor_{did}", (ctr.x, ctr.y, 0.03), (2.075, 0.87, 0.06), yaw - math.pi / 2))
    # torn / leftover hinge plates on empty openings
    hm = MB()
    for did, side, yc, hinge, ang in DOORS:
        if hinge not in ("torn", None):
            continue
        xh, xr, nr = side_x(side)
        yj = yc - DW / 2 + 0.002
        for zc, bend in ((0.25, 0.0), (DHT - 0.32, 0.5 if hinge == "torn" else 0.0)):
            x = xr - nr.x * 0.02
            R.box(hm, (0.035, 0.004, 0.1), T((x, yj, zc)), 0, bevel=0.001, segs=1, uvs=IRON_TILE)
            tube(hm, [(xr - nr.x * 0.002, yj + 0.004, zc - 0.05), (xr - nr.x * 0.002, yj + 0.004, zc + 0.05)], 0.0065, 10, 0, IRON_TILE)
            if bend:
                R.box(hm, (0.035, 0.004, 0.1), T((xr + nr.x * 0.012, yj + 0.02, zc - 0.02), (0.0, 0.0, -nr.x * bend)), 0,
                      bevel=0.001, segs=1, uvs=IRON_TILE)
    out.append(obj_from(hm, "Door_Hinges_Remnant", ["Iron_Dark"], recalc=True))
    return out, extras


# =============================================================================== props
def place_v1(objs, old_loc, old_rot, new_loc, new_rot, extra=None):
    """Move props built by room.py (placed by place(ob, old_loc, old_rot)) to a new pose."""
    M_old = Matrix.Translation(Vector(old_loc)) @ Matrix.Rotation(old_rot, 4, "Z")
    M_new = Matrix.Translation(Vector(new_loc)) @ Matrix.Rotation(new_rot, 4, "Z")
    D = M_new @ (extra if extra is not None else Matrix.Identity(4)) @ M_old.inverted()
    for o in objs:
        transform_obj(o, D)
    return objs


def rename(objs, names):
    for o, n in zip(objs, names):
        o.name = o.data.name = n
    return objs


def col_from_objs(name, objs, yaw=0.0, pad=0.0, zmax=None):
    Rinv = Matrix.Rotation(-yaw, 4, "Z")
    pts = [Rinv @ (o.matrix_world @ v.co) for o in objs for v in o.data.vertices]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    if zmax is not None:
        mx.z = min(mx.z, zmax)
    c = Matrix.Rotation(yaw, 4, "Z") @ ((mn + mx) / 2)
    COLLIDERS.append((name, tuple(c), tuple(mx - mn + Vector((pad, pad, 0))), yaw))


def build_bed(did, loc, rot):
    objs = R.build_bed()
    place_v1(objs, (-2.07, 3.15, 0), 0.0, loc, rot)
    rename(objs, [f"Bed_{did}_IronFrame", f"Bed_{did}_Mattress", f"Bed_{did}_Pillow"])
    col_from_objs(f"COL_Bed_{did}", objs, rot, zmax=0.62)
    return objs


def build_chair_at(name, loc, rot, topple=None):
    ob = R.build_chair()[0]
    ob.name = ob.data.name = name
    place_v1([ob], (1.18, 3.42, 0), math.radians(193), (0, 0, 0), 0.0)
    if topple is not None:
        transform_obj(ob, Matrix.Rotation(topple[0], 4, "X") @ Matrix.Rotation(topple[1], 4, "Y"))
        rest_on_floor(ob)
    transform_obj(ob, Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot, 4, "Z"))
    col_from_objs(f"COL_{name}", [ob], rot)
    return ob


def build_wardrobe(name, loc, rot, door_open=1.2):
    mb = MB()
    Wd, Br = 0, 1
    w, d, h = 1.0, 0.56, 1.95
    b = lambda size, c, grain, bev=0.003, M=None: R.box(mb, size, (M or Matrix.Identity(4)) @ T(c), Wd, bevel=bev,
                                                        segs=2, uvs=WOOD_TILE, grain=grain)
    for s in (-1, 1):
        b((0.022, d, h - 0.12), (s * (w / 2 - 0.011), 0, 0.12 + (h - 0.12) / 2), 2)
    b((w - 0.04, 0.01, h - 0.12), (0, d / 2 - 0.005, 0.12 + (h - 0.12) / 2), 2, 0.0)
    b((w - 0.04, d - 0.02, 0.02), (0, 0, 0.13), 0)
    b((w - 0.04, d - 0.02, 0.02), (0, 0, h - 0.01), 0)
    b((w + 0.06, d + 0.05, 0.05), (0, -0.015, h + 0.025), 0, 0.008)
    b((w + 0.1, d + 0.07, 0.03), (0, -0.02, h + 0.065), 0, 0.01)
    b((w + 0.02, d + 0.02, 0.1), (0, 0, 0.07), 0, 0.006)
    b((w - 0.04, d - 0.04, 0.018), (0, 0, 1.6), 0)
    tube(mb, [(-w / 2 + 0.03, 0.0, 1.5), (w / 2 - 0.03, 0.0, 1.5)], 0.012, 10, Br, 0.2)
    dw = (w - 0.03) / 2
    dh = h - 0.2
    for s, ang in ((-1, door_open), (1, 0.03)):
        hinge = Vector((s * (w / 2 - 0.005), -d / 2 - 0.012, 0.15))
        Md = T(tuple(hinge)) @ T(rot=(0, 0, s * ang))
        cx = -s * dw / 2
        R.box(mb, (dw, 0.022, dh), Md @ T((cx, 0, dh / 2)), Wd, bevel=0.003, segs=2, uvs=WOOD_TILE, grain=2)
        R.box(mb, (dw - 0.1, 0.008, dh - 0.25), Md @ T((cx, -0.014, dh / 2 + 0.05)), Wd, bevel=0.012, segs=2, uvs=WOOD_TILE, grain=2)
        lathe(mb, [(0, 0.035), (0.012, 0.033), (0.016, 0.022), (0.006, 0.012), (0.007, 0), (0, 0)],
              tuple(Md @ Vector((-s * (dw - 0.05), -0.011, dh * 0.5))), 12, Br, 0.2, axis_m=Matrix.Rotation(math.pi / 2, 3, "X") @ Matrix.Rotation(math.pi, 3, "X"))
    ob = obj_from(mb, name, ["Wood_Old", "Brass"], recalc=True)
    transform_obj(ob, Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot, 4, "Z"))
    col_from_objs(f"COL_{name}", [ob], rot)
    return ob


def build_radiator_hall():
    ob = R.build_radiator()[0]
    ob.name = ob.data.name = "Radiator"
    place_v1([ob], (1.96, R.Y1 - 0.115, 0), 0.0, (HX0 + 0.05 + 0.085, 4.5, 0), math.radians(90))
    col_from_objs("COL_Radiator", [ob], math.radians(90))
    return ob


def build_side_table():
    mb = MB()
    Wd, Br, Tc, So, Pl = range(5)
    b = lambda size, c, grain, m=Wd, bev=0.004: R.box(mb, size, T(c), m, bevel=bev, segs=2, uvs=WOOD_TILE, grain=grain)
    b((0.56, 0.38, 0.025), (0, 0, 0.7325), 0, bev=0.007)
    b((0.46, 0.018, 0.09), (0, -0.155, 0.675), 0)
    b((0.46, 0.018, 0.09), (0, 0.155, 0.675), 0)
    b((0.018, 0.29, 0.09), (-0.225, 0, 0.675), 1)
    b((0.018, 0.29, 0.09), (0.225, 0, 0.675), 1)
    b((0.47, 0.30, 0.015), (0, 0, 0.17), 0)
    b((0.3, 0.012, 0.062), (0, -0.168, 0.675), 0)
    lathe(mb, [(0, 0.022), (0.009, 0.02), (0.012, 0.012), (0.005, 0.006), (0.005, 0), (0, 0)], (0, -0.174, 0.675), 12, Br, 0.2,
          axis_m=Matrix.Rotation(math.pi / 2, 3, "X"))
    leg = [(0, 0), (0.016, 0), (0.019, 0.02), (0.013, 0.08), (0.015, 0.25), (0.021, 0.3), (0.017, 0.33), (0.019, 0.6),
           (0.019, 0.72), (0, 0.72)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            lathe(mb, leg, (sx * 0.235, sy * 0.155, 0), 12, Wd, WOOD_TILE)
    # cracked terracotta pot, dry soil, dead plant
    pc = Vector((0.06, 0.02, 0.745))
    lathe(mb, [(0, 0), (0.058, 0), (0.062, 0.008), (0.082, 0.14), (0.093, 0.15), (0.094, 0.175), (0.084, 0.177),
               (0.08, 0.16), (0.073, 0.145), (0.054, 0.012), (0, 0.012)], tuple(pc), 28, Tc, 0.3)
    lathe(mb, [(0, 0.128), (0.074, 0.128), (0.074, 0.12), (0, 0.12)], tuple(pc), 20, So, 0.3)
    rng = np.random.default_rng(8)
    tips = []
    for k in range(9):
        a = rng.uniform(0, TAU)
        r0 = rng.uniform(0, 0.03)
        p0 = pc + Vector((r0 * math.cos(a), r0 * math.sin(a), 0.128))
        up = rng.uniform(0.15, 0.32)
        out_ = rng.uniform(0.08, 0.2)
        dirv = Vector((math.cos(a), math.sin(a), 0))
        pts = []
        for t in np.linspace(0, 1, 9):
            hgt = up * math.sin(t * math.pi * 0.62) - rng.uniform(0, 0.01) - (0.12 * t ** 2 if k % 3 == 0 else 0)
            pts.append(p0 + dirv * out_ * t ** 1.4 + Vector((0, 0, hgt)))
        tube(mb, pts, list(np.linspace(0.0035, 0.0012, len(pts))), 6, Pl, 0.2)
        tips.append((pts[-1], pts[-2]))
    # curled dead leaves (thin bent boxes), at stem tips and fallen on the table / floor
    def leaf(p, ang, tilt, s=1.0):
        def curl(co):
            x, y, z = co
            return (x, y, z + 18 * (x ** 2) * 0.5 + 6 * y * y)
        R.box(mb, (0.035 * s, 0.06 * s, 0.0012), T(tuple(p), (tilt, 0, ang)), Pl, bevel=0.0, cuts=3, deform=curl,
              uvs=0.2, grain=1)
    for p, q in tips[:6]:
        leaf(p, rng.uniform(0, TAU), rng.uniform(-1.2, 1.2))
    for _ in range(6):
        leaf((rng.uniform(-0.22, 0.22), rng.uniform(-0.15, 0.15), 0.747), rng.uniform(0, TAU), rng.uniform(-0.2, 0.2))
    for _ in range(7):
        leaf((rng.uniform(-0.45, 0.3), rng.uniform(-0.35, 0.3), 0.004), rng.uniform(0, TAU), rng.uniform(-0.2, 0.2))
    ob = obj_from(mb, "SideTable_DeadPlant", ["Wood_Old", "Brass", "Terracotta", "Soil", "DeadPlant"], recalc=True)
    rot = math.radians(-90)
    transform_obj(ob, Matrix.Translation((HX1 - 0.035 - 0.2, 6.5, 0)) @ Matrix.Rotation(rot, 4, "Z"))
    COLLIDERS.append(("COL_SideTable", (HX1 - 0.035 - 0.2, 6.5, 0.375), (0.56, 0.38, 0.75), rot))
    return ob


def ring_pts(c, ax_u, ax_v, r, n=48):
    c, u, v = Vector(c), Vector(ax_u), Vector(ax_v)
    return [c + (u * math.cos(t) + v * math.sin(t)) * r for t in np.linspace(0, TAU, n + 1)]


def build_wheelchair():
    mb = MB()
    Fr, Lt, Rb = 0, 1, 2
    sw = 0.235
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    for sx in (-1, 1):
        x = sx * sw
        tube(mb, [(x, -0.25, 0.50), (x, 0.20, 0.50)], 0.011, 10, Fr, 0.5)
        tube(mb, [(x, 0.19, 0.26), (x, 0.20, 0.5), (x, 0.235, 0.86), (x, 0.26, 0.92), (x, 0.33, 0.95), (x, 0.40, 0.955)],
             0.011, 10, Fr, 0.5)
        tube(mb, [(x, 0.33, 0.951), (x, 0.43, 0.957)], 0.0165, 10, Rb, 0.3)
        tube(mb, [(x, -0.25, 0.52), (x, -0.25, 0.19)], 0.011, 10, Fr, 0.5)
        tube(mb, [(x, -0.25, 0.25), (x, 0.19, 0.28)], 0.0095, 10, Fr, 0.5)
        for yy in (-0.12, 0.14):
            tube(mb, [(x, yy, 0.5), (x, yy, 0.7)], 0.009, 8, Fr, 0.5)
        tube(mb, [(x, -0.14, 0.70), (x, 0.17, 0.70)], 0.009, 8, Fr, 0.5)
        R.box(mb, (0.05, 0.26, 0.03), T((x, 0.02, 0.725)), Lt, bevel=0.008, segs=2, uvs=0.3, grain=1)
        tube(mb, [(x, -0.25, 0.4), (x * 0.95, -0.33, 0.28), (x * 0.9, -0.40, 0.14)], 0.009, 8, Fr, 0.5)
        R.box(mb, (0.15, 0.12, 0.008), T((x * 0.62, -0.43, 0.13), (0.25, 0, 0)), Fr, bevel=0.002, segs=1, uvs=0.3)
        # rear wheel
        wc = Vector((x + sx * 0.045, 0.13, 0.3))
        tube(mb, ring_pts(wc, Y, Z, 0.3), 0.017, 10, Rb, 0.4, caps=False)
        tube(mb, ring_pts(wc, Y, Z, 0.281), 0.008, 8, Fr, 0.4, caps=False)
        tube(mb, ring_pts(wc + X * sx * 0.035, Y, Z, 0.262), 0.0065, 8, Fr, 0.4, caps=False)
        for k in range(6):
            t = k / 6 * TAU
            p = wc + (Y * math.cos(t) + Z * math.sin(t)) * 0.262
            q = wc + (Y * math.cos(t) + Z * math.sin(t)) * 0.281
            tube(mb, [p + X * sx * 0.035, q + X * sx * 0.01], 0.003, 5, Fr, 0.3)
        lathe(mb, [(0, -0.035), (0.02, -0.035), (0.03, -0.015), (0.03, 0.015), (0.02, 0.035), (0, 0.035)], tuple(wc), 14, Fr, 0.3,
              axis_m=Matrix.Rotation(math.pi / 2, 3, "Y"))
        for k in range(24):
            t = k / 24 * TAU
            off = X * (0.02 if k % 2 else -0.02)
            tube(mb, [wc + off, wc + (Y * math.cos(t + 0.15) + Z * math.sin(t + 0.15)) * 0.278], 0.0016, 4, Fr, 0.2)
        # caster
        cc = Vector((x, -0.27, 0.085))
        tube(mb, [(x, -0.25, 0.2), (x, -0.25, 0.17), (x - 0.02, -0.27, 0.12), (x - 0.02, -0.27, 0.085)], 0.006, 8, Fr, 0.3)
        tube(mb, [(x, -0.25, 0.17), (x + 0.02, -0.27, 0.12), (x + 0.02, -0.27, 0.085)], 0.006, 8, Fr, 0.3)
        tube(mb, ring_pts(cc, Y, Z, 0.075), 0.012, 8, Rb, 0.3, caps=False)
        lathe(mb, [(0, -0.015), (0.03, -0.015), (0.04, 0), (0.03, 0.015), (0, 0.015)], tuple(cc), 12, Fr, 0.3,
              axis_m=Matrix.Rotation(math.pi / 2, 3, "Y"))
    tube(mb, [(-sw, -0.03, 0.26), (0, 0.04, 0.37), (sw, 0.12, 0.49)], 0.0085, 8, Fr, 0.5)
    tube(mb, [(sw, -0.03, 0.26), (0, 0.04, 0.37), (-sw, 0.12, 0.49)], 0.0085, 8, Fr, 0.5)
    # seat + back slings (sagging, torn corner), two faces
    nu, nv = 10, 10
    for kind in ("seat", "back"):
        for side in (0, 1):
            ids = {}
            for i in range(nu + 1):
                for j in range(nv + 1):
                    u, v = i / nu, j / nv
                    xx = -sw + 2 * sw * u
                    if kind == "seat":
                        p = Vector((xx, -0.24 + 0.43 * v, 0.505 - 0.05 * math.sin(math.pi * u) * (0.6 + 0.4 * math.sin(math.pi * v))))
                    else:
                        zz = 0.56 + 0.32 * v
                        p = Vector((xx, 0.2 + (zz - 0.5) * 0.098 + 0.045 * math.sin(math.pi * u) * (0.5 + 0.5 * math.sin(math.pi * v)), zz))
                        if u > 0.75 and v > 0.7:      # torn corner flops down
                            p.z -= 0.12 * (u - 0.75) * 4 * (v - 0.7) / 0.3
                            p.y += 0.04 * (u - 0.75) * 4
                    p.z -= side * 0.004
                    ids[(i, j)] = mb.v(p)
            for i in range(nu):
                for j in range(nv):
                    q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                    if (kind == "seat") == (side == 1):
                        q = q[::-1]
                    mb.f([ids[k] for k in q], [(a / nu * 0.47 / 0.3, b / nv * 0.43 / 0.3) for a, b in q], Lt)
    ob = obj_from(mb, "Wheelchair", ["Iron_Dark", "Leather", "Rubber"], smooth_deg=50)
    rot = math.radians(-24)
    transform_obj(ob, Matrix.Translation((-0.52, 12.75, 0.0)) @ Matrix.Rotation(rot, 4, "Z"))
    rest_on_floor(ob)
    col_from_objs("COL_Wheelchair", [ob], rot, zmax=0.75)
    return ob


def lathe_mask(mb, prof, center, segs, mat, uvs, keep, axis_m=None):
    """room.lathe with a face filter keep(theta, z) -> bool (for broken glass)."""
    c = Vector(center)
    M = axis_m or Matrix.Identity(3)
    rings = []
    for r, z in prof:
        rings.append([mb.v(c + M @ Vector((r * math.cos(TAU * j / segs), r * math.sin(TAU * j / segs), z)))
                      for j in range(segs)])
    plen = [0.0]
    for a, b in zip(prof[:-1], prof[1:]):
        plen.append(plen[-1] + math.dist(a, b))
    rmax = max(r for r, _ in prof)
    for i in range(len(rings) - 1):
        zm = 0.5 * (prof[i][1] + prof[i + 1][1])
        for j in range(segs):
            if not keep((j + 0.5) / segs * TAU, zm):
                continue
            j2 = (j + 1) % segs
            q = [rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j]]
            uv = [(j / segs * TAU * rmax / uvs, plen[i] / uvs), ((j + 1) / segs * TAU * rmax / uvs, plen[i] / uvs),
                  ((j + 1) / segs * TAU * rmax / uvs, plen[i + 1] / uvs), (j / segs * TAU * rmax / uvs, plen[i + 1] / uvs)]
            mb.f(q, uv, mat)


GLOBE = [(0.05, 0.0), (0.058, -0.02), (0.085, -0.06), (0.118, -0.11), (0.138, -0.16), (0.143, -0.2),
         (0.134, -0.24), (0.108, -0.268), (0.084, -0.278)]


def shards(mb, cx, cy, z, n, spread, rng):
    for _ in range(n):
        px, py = cx + rng.normal(0, spread), cy + rng.normal(0, spread * 0.8)
        a0 = rng.uniform(0, TAU)
        r = rng.uniform(0.01, 0.045)
        pts = [(px + r * math.cos(a0 + k * 2.1 + rng.normal(0, 0.3)), py + r * math.sin(a0 + k * 2.1 + rng.normal(0, 0.3)))
               for k in range(3)]
        top = [mb.v((x, y, z + 0.003)) for x, y in pts]
        bot = [mb.v((x, y, z + 0.0005)) for x, y in pts]
        uv = [(0, 0), (1, 0), (0, 1)]
        mb.f(top, uv)
        mb.f(bot[::-1], uv[::-1])
        for k in range(3):
            k2 = (k + 1) % 3
            mb.f([bot[k], bot[k2], top[k2], top[k]], [(0, 0), (1, 0), (1, 1), (0, 1)])


def build_fixtures():
    """Ceiling lights every ~3 m, all broken in a different way."""
    opaque, glass = MB(), MB()
    Pl, Br, Co, Bk = 0, 1, 2, 3
    sh = MB()
    rng = np.random.default_rng(12)
    spots = [(1.3, "broken"), (4.3, "dangling"), (7.3, "tilted"), (10.6, "bare"), (13.0, "dusty")]
    for y, kind in spots:
        cx, cy = 0.02, y
        rose = [(0, HH), (0.16, HH), (0.16, HH - 0.01), (0.13, HH - 0.018), (0.09, HH - 0.024), (0.05, HH - 0.03), (0, HH - 0.032)]
        if kind == "bare":
            lathe_mask(opaque, rose, (cx, cy, 0), 32, Pl, 0.5, lambda th, z: not (1.0 < th < 2.9))
        else:
            lathe(opaque, rose, (cx, cy, 0), 32, Pl, 0.5)
        lathe(opaque, [(0, HH - 0.03), (0.06, HH - 0.03), (0.06, HH - 0.04), (0.05, HH - 0.07), (0.015, HH - 0.085), (0, HH - 0.085)],
              (cx, cy, 0), 24, Br, 0.2)
        top = Vector((cx, cy, HH - 0.085))
        if kind in ("broken", "dusty", "tilted"):
            tilt = math.radians(31) if kind == "tilted" else math.radians(rng.uniform(-2, 2))
            M3 = Matrix.Rotation(tilt, 3, "X")
            Lr = 0.42
            if kind == "tilted":
                # hanging from one of its two chains, the other one snapped
                bot = top + M3 @ Vector((0, 0, -Lr))
                tube(opaque, [top + Vector((-0.03, 0, 0)), bot + Vector((-0.03, 0, 0))], 0.0025, 6, Br, 0.1)
                tube(opaque, [top + Vector((0.03, 0, 0)), top + Vector((0.03, 0.01, -0.16))], 0.0025, 6, Br, 0.1)
                tube(opaque, [bot + Vector((0.03, 0, 0)), bot + Vector((0.035, 0.02, 0.12))], 0.0025, 6, Br, 0.1)
            else:
                tube(opaque, [top, top + M3 @ Vector((0, 0, -Lr))], 0.0065, 10, Br, 0.2)
                bot = top + M3 @ Vector((0, 0, -Lr))
            lathe(opaque, [(0, 0), (0.03, 0), (0.05, -0.012), (0.056, -0.03), (0.052, -0.04), (0, -0.04)], tuple(bot), 20, Br, 0.2, axis_m=M3)
            lathe(opaque, [(0, -0.03), (0.017, -0.03), (0.017, -0.075), (0, -0.075)], tuple(bot), 12, Bk, 0.2, axis_m=M3)
            gc = bot + M3 @ Vector((0, 0, -0.035))
            if kind == "broken":
                keep = lambda th, z: z > -0.06 or not (0.6 < th < 3.3) and z > -0.17 - 0.05 * math.sin(th * 7)
                shards(sh, cx + 0.05, cy + 0.15, 0.008, 16, 0.18, rng)
            elif kind == "tilted":
                keep = lambda th, z: z > -0.22 + 0.06 * math.sin(th * 5) or (th > 4.0)
                shards(sh, cx - 0.1, cy + 0.05, 0.008, 8, 0.14, rng)
            else:
                keep = lambda th, z: True
            lathe_mask(glass, GLOBE, tuple(gc), 36, 0, 0.3, keep, axis_m=M3)
        elif kind == "dangling":
            pts = [top + Vector((0.012 * math.sin(t * 4) * t, 0.03 * t * t, -0.75 * t)) for t in np.linspace(0, 1, 16)]
            tube(opaque, pts, 0.0035, 8, Co, 0.1)
            end = pts[-1]
            M3 = Matrix.Rotation(math.radians(9), 3, "X")
            lathe(opaque, [(0, 0.0), (0.012, 0.0), (0.017, -0.012), (0.018, -0.06), (0, -0.06)], tuple(end), 16, Bk, 0.2, axis_m=M3)
            # the globe lies smashed on the carpet below
            Mf = Matrix.Rotation(math.radians(96), 3, "Y") @ Matrix.Rotation(math.radians(30), 3, "Z")
            lathe_mask(glass, GLOBE, (cx + 0.22, cy + 0.3, 0.155), 36, 0, 0.3,
                       lambda th, z: not (2.0 < th < 4.6) or z > -0.05, axis_m=Mf)
            shards(sh, cx + 0.15, cy + 0.25, 0.008, 22, 0.25, rng)
        elif kind == "bare":
            for k in range(3):
                a = k * 2.1
                tube(opaque, [top, top + Vector((0.03 * math.cos(a), 0.03 * math.sin(a), -0.08 - 0.05 * k)),
                              top + Vector((0.05 * math.cos(a), 0.06 * math.sin(a), -0.14 - 0.06 * k))], 0.0016, 5, Co, 0.1)
    ob1 = obj_from(opaque, "CeilingFixtures", ["Plaster", "Brass", "Cord_Fabric", "Bakelite"], recalc=False, smooth_deg=50)
    ob2 = obj_from(glass, "CeilingFixtures_Glass", ["Glass_Milk"], smooth_deg=60)
    ob3 = obj_from(sh, "Glass_Shards", ["Glass_Shard"], smooth_deg=10)
    return [ob1], [ob2, ob3]


def build_frames():
    """Picture frames: some crooked, one fallen (leaning against the wainscot)."""
    opaque = []
    rng = np.random.default_rng(5)
    prof = [(-0.008, 0.0), (-0.008, 0.02), (0.0, 0.03), (0.012, 0.044), (0.028, 0.05), (0.045, 0.043), (0.056, 0.031),
            (0.066, 0.035), (0.075, 0.022), (0.075, 0.0)]
    cells = {"man": (0.0, 0.0), "house": (0.5, 0.0), "woman": (0.0, 0.5), "sea": (0.5, 0.5)}
    specs = [  # name, wall, s, z, w, h, tilt_deg, cell
        ("Frame_Portrait", "L", 3.65, 1.62, 0.42, 0.54, 3.5, "man"),
        ("Frame_House", "L", 9.45, 1.66, 0.62, 0.46, -1.5, "house"),
        ("Frame_Woman", "L", 12.2, 1.6, 0.4, 0.52, 11.0, "woman"),
        ("Frame_Sea", "R", 6.5, 1.55, 0.56, 0.42, 0.8, "sea"),
        ("Frame_Woman2", "R", 9.62, 1.68, 0.38, 0.5, -7.0, "woman"),
        ("Frame_Fallen", "F", 8.55, 0.0, 0.5, 0.62, 0.0, "man"),
    ]
    for name, wall, s, z, w, h, tilt, cell in specs:
        fm, cm = MB(), MB()
        path = [(-w / 2, -h / 2), (-w / 2, h / 2), (w / 2, h / 2), (w / 2, -h / 2)]
        sweep(fm, path, prof, (0, 0, 0), (1, 0, 0), (0, 0, 1), (0, 1, 0), closed=True, uvs=WOOD_TILE, mat=0)
        tube(fm, [(-w * 0.3, 0.004, h * 0.32), (0, 0.004, h / 2 + 0.06), (w * 0.3, 0.004, h * 0.32)], 0.0009, 4, 1, 0.1)
        u0, v0 = cells[cell]
        nu, nv = 4, 4
        ids = {}
        for i in range(nu + 1):
            for j in range(nv + 1):
                x = -w / 2 - 0.004 + (w + 0.008) * i / nu
                zz = -h / 2 - 0.004 + (h + 0.008) * j / nv
                bulge = 0.003 * math.sin(math.pi * i / nu) * math.sin(math.pi * j / nv)
                ids[(i, j)] = cm.v((x, 0.014 + bulge, zz))
        for i in range(nu):
            for j in range(nv):
                q = [(i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)]       # faces +y (out of the wall)
                cm.f([ids[k] for k in q], [(u0 + 0.02 + 0.46 * (1 - a / nu), v0 + 0.02 + 0.46 * b / nv) for a, b in q], 0)
        fo = obj_from(fm, name + "_f", ["Gilt", "Iron_Dark"], recalc=True, smooth_deg=40)
        co = obj_from(cm, name + "_c", ["Painting"], smooth_deg=40)
        ob = join_objs(name, [fo, co])
        if wall == "F":
            # fallen: standing on its bottom edge, leaning back against the wainscot, face out
            M = (Matrix.Translation((HX0 + 0.05 + 0.2, s, 0)) @ Matrix.Rotation(-math.pi / 2, 4, "Z")
                 @ Matrix.Rotation(math.radians(16), 4, "X") @ Matrix.Translation((0, 0, h / 2 + 0.075)))
            transform_obj(ob, M)
            rest_on_floor(ob)
        else:
            if wall == "L":
                Bm = basis((0, -1, 0), (1, 0, 0), (HX0, s, z))
            else:
                Bm = basis((0, 1, 0), (-1, 0, 0), (HX1, s, z))
            pivot = Vector((0, 0, h / 2 + 0.06))
            Mloc = (Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(tilt), 4, "Y") @
                    Matrix.Rotation(math.radians(-2.5), 4, "X") @ Matrix.Translation(-pivot))
            transform_obj(ob, Bm @ Matrix.Translation((0, 0.004, 0)) @ Mloc)
        opaque.append(ob)
    # nail left behind where the fallen one hung
    nm = MB()
    tube(nm, [(HX0 - 0.005, 8.55, 1.98), (HX0 + 0.022, 8.55, 1.985)], 0.0016, 6, 0, 0.1)
    opaque.append(obj_from(nm, "Wall_Nail", ["Iron_Dark"], recalc=True))
    return opaque


def build_carpet():
    """Runner: two surfaces (wool top / jute back) with skirt edges, curled long edges, a ruck, a folded corner."""
    mb = MB()
    TOP, BACK = 0, 1
    Wc, x_c = 0.9, -0.06
    y0, y1 = -0.5, 11.95
    th = 0.0065
    us = sorted(set(list(np.linspace(-0.45, 0.45, 19)) + list(np.linspace(-0.45, -0.33, 7)) + list(np.linspace(0.33, 0.45, 7))))
    vs = list(np.arange(y0, y1, 0.05)) + [y1]
    nI, nJ = len(us), len(vs)
    rng = np.random.default_rng(3)
    ph = rng.uniform(0, TAU, 6)

    def curl_amt(y, sgn):
        a = 0.5 + 0.5 * math.sin(y * 0.9 + ph[0 if sgn < 0 else 1]) * math.sin(y * 0.37 + ph[2])
        return max(0.0, a) ** 1.5 * (0.9 if sgn > 0 else 0.6)
    wz = 0.11
    fold_a = Vector((x_c + 0.45, y1 - 0.42))
    fold_b = Vector((x_c + 0.02, y1))
    fd = (fold_b - fold_a).normalized()
    fn = Vector((fd.y, -fd.x))                         # points to the corner side
    if fn.dot(Vector((x_c + 0.45, y1)) - fold_a) < 0:
        fn = -fn

    def P(u, y, under):
        """material coords (u across, y along) -> 3D point on the top or underside surface."""
        sgn = 1 if u >= 0 else -1
        e0 = 0.45 - wz
        zmid0 = th * 0.55
        zmid = zmid0
        nrm = Vector((0, 0, 1))
        lat = u
        k = curl_amt(y, sgn) * float(RT.ss(y1 - 0.5, y1 - 1.2, y)) * float(RT.ss(y0 + 0.2, y0 + 0.8, y) * 0.7 + 0.3)
        if abs(u) > e0 and k > 0.02:
            s_ = abs(u) - e0
            r = wz / (k * math.pi * 0.85)
            ang = s_ / r
            lat = sgn * (e0 + r * math.sin(ang))
            zmid = zmid0 + r * (1 - math.cos(ang))
            nrm = Vector((-sgn * math.sin(ang), 0, math.cos(ang)))
        zmid += 0.05 * math.exp(-((y - 5.6) / 0.13) ** 2) * (1 - 0.4 * abs(u) / 0.45) + 0.018 * math.exp(-((y - 2.2) / 0.1) ** 2)
        pm = Vector((x_c + lat + 0.015 * math.exp(-((y - 5.6) / 0.25) ** 2), y, zmid))
        dist = (Vector((pm.x, pm.y)) - fold_a).dot(fn)
        if dist > 0:                                   # folded-over corner at the far end
            along = (Vector((pm.x, pm.y)) - fold_a).dot(fd)
            rad = 0.006
            fn3 = Vector((fn.x, fn.y, 0))
            if dist < math.pi * rad:
                phi = dist / rad
                lateral = rad * math.sin(phi)
                zz = zmid0 + rad * (1 - math.cos(phi))
                nrm = -fn3 * math.sin(phi) + Vector((0, 0, math.cos(phi)))
            else:
                lateral = -(dist - math.pi * rad)
                zz = zmid0 + 2 * rad
                nrm = Vector((0, 0, -1))
            base2 = fold_a + fd * along + fn * lateral
            pm = Vector((base2.x, base2.y, zz))
        return pm + nrm * (th * 0.45 * (-1 if under else 1))
    for surf in (TOP, BACK):
        ids = {}
        for i, u in enumerate(us):
            for j, y in enumerate(vs):
                ids[(i, j)] = mb.v(P(u, y, surf == BACK))
        for i in range(nI - 1):
            for j in range(nJ - 1):
                q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                uv = [((us[a] + 0.45) / Wc, (vs[b] - y0) / 1.8) for a, b in q]
                if surf == BACK:
                    q, uv = q[::-1], uv[::-1]
                mb.f([ids[k] for k in q], uv, surf)
        if surf == TOP:
            top_ids = ids
        else:
            bot_ids = ids
    # skirts along the boundary
    border = [(i, 0) for i in range(nI)] + [(nI - 1, j) for j in range(1, nJ)] + \
             [(i, nJ - 1) for i in range(nI - 2, -1, -1)] + [(0, j) for j in range(nJ - 2, 0, -1)]
    for k in range(len(border)):
        a, b = border[k], border[(k + 1) % len(border)]
        mb.f([top_ids[b], top_ids[a], bot_ids[a], bot_ids[b]], [(0, 0), (0.01, 0), (0.01, 0.007), (0, 0.007)], TOP)
        mb.f([bot_ids[b], bot_ids[a], top_ids[a], top_ids[b]], [(0, 0.007), (0.01, 0.007), (0.01, 0), (0, 0)], TOP)
    ob = obj_from(mb, "Carpet_Runner", ["Carpet", "Carpet_Back"], smooth_deg=60)
    return ob


def build_debris():
    rng = np.random.default_rng(23)
    mb = MB()
    Pl, Wd = 0, 1
    cx, cy, rx, ry = CEIL_HOLE
    # fallen ceiling plaster under the hole (on carpet and floor)
    for _ in range(70):
        x = cx + rng.normal(0, rx * 0.7)
        y = cy + rng.normal(0, ry * 0.8)
        s = rng.uniform(0.008, 0.07) if rng.random() < 0.7 else rng.uniform(0.002, 0.008)
        z0 = 0.009 if abs(x + 0.06) < 0.44 else 0.0
        R.chunk(mb, (x, y, z0 + s * 0.25), (s, s * rng.uniform(0.5, 1), s * rng.uniform(0.15, 0.35)), rng, Pl)
    for _ in range(8):     # plaster slabs with lath imprint
        x, y = cx + rng.normal(0, rx * 0.6), cy + rng.normal(0, ry * 0.6)
        R.box(mb, (rng.uniform(0.08, 0.2), rng.uniform(0.06, 0.15), 0.02),
              T((x, y, 0.02), (rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2), rng.uniform(0, TAU))), Pl,
              bevel=0.004, segs=1, uvs=0.5, deform=lambda co: (co[0] + 0.01 * math.sin(co[1] * 40), co[1], co[2]))
    for _ in range(6):
        L = rng.uniform(0.2, 0.7)
        R.box(mb, (L, 0.035, 0.007), T((cx + rng.normal(0, 0.3), cy + rng.normal(0, 0.25), 0.02),
                                         (0, rng.uniform(-0.15, 0.15), rng.uniform(0, TAU))), Wd, bevel=0.001, segs=1, uvs=WOOD_TILE)
    # crumbs along the wall bases + under wallpaper tears
    for _ in range(160):
        side = rng.choice([-1, 1])
        y = rng.uniform(0.5, 13.8)
        x = side * (HX1 - 0.06 - abs(rng.normal(0, 0.06)))
        s = rng.uniform(0.003, 0.025)
        R.chunk(mb, (x, y, s * 0.3), (s, s * rng.uniform(0.6, 1), s * rng.uniform(0.3, 0.6)), rng, Pl)
    for y0 in (7.95, 12.95, 4.45):
        for _ in range(20):
            x = HX0 + 0.07 + abs(rng.normal(0, 0.12))
            s = rng.uniform(0.006, 0.03)
            R.chunk(mb, (x, y0 + rng.normal(0, 0.15), s * 0.3), (s, s, s * 0.5), rng, Pl)
    # the panel that came off the wainscot
    R.box(mb, (0.45, 0.012, 0.5), T((HX0 + 0.33, 8.25, 0.008), (math.radians(90), 0, math.radians(80))), Wd,
          bevel=0.01, segs=2, uvs=WOOD_TILE, grain=2)
    # rooms: a few chunks each
    for did, side, yc, _, _ in DOORS:
        rx0, rx1, ry0, ry1 = room_box(side, yc)
        for _ in range(25):
            x, y = rng.uniform(rx0 + 0.1, rx1 - 0.1), rng.uniform(ry0 + 0.1, ry1 - 0.1)
            if rng.random() < 0.7:
                x = rx0 + 0.08 if rng.random() < 0.5 else rx1 - 0.08
            s = rng.uniform(0.005, 0.04)
            R.chunk(mb, (x, y, s * 0.3), (s, s * rng.uniform(0.6, 1), s * rng.uniform(0.3, 0.6)), rng, Pl)
    deb = obj_from(mb, "Debris", ["Plaster", "Wood_Old"], smooth_deg=40)
    return deb


def build_papers():
    rng = np.random.default_rng(55)
    s = []
    for _ in range(26):
        y = rng.uniform(1.0, 13.5)
        x = rng.choice([rng.uniform(-1.15, -0.55), rng.uniform(0.45, 1.1), rng.uniform(-0.5, 0.35)], p=[0.4, 0.3, 0.3])
        z = 0.0085 if -0.5 < x < 0.37 else 0.0
        s.append((x, y, z, rng.uniform(0, TAU), rng.uniform(0.0, 0.012), 0.0))
    for did, side, yc, _, _ in DOORS:      # spilling out of the doorways
        xh, xr, nr = side_x(side)
        for _ in range(3):
            s.append((xh - nr.x * rng.uniform(0.1, 0.5), yc + rng.normal(0, 0.3), 0.0, rng.uniform(0, TAU), rng.uniform(0, 0.01), 0.0))
        rx0, rx1, ry0, ry1 = room_box(side, yc)
        for _ in range(5):
            s.append((rng.uniform(rx0 + 0.2, rx1 - 0.2), rng.uniform(ry0 + 0.2, ry1 - 0.2), 0.0, rng.uniform(0, TAU),
                      rng.uniform(0, 0.012), 0.0))
    s.append((HX1 - 0.235 - 0.05, 6.45, 0.7475, 0.3, 0.004, 0.0))         # on the side table
    s.append((-0.52, 12.72, 0.53, 1.2, 0.01, 0.12))                         # on the wheelchair seat
    return R.paper_sheets("Papers_Scattered", s, 9)


def build_cobwebs():
    mb = MB()

    def web(corners, sag_dir, sag=0.03):
        c = [Vector(p) for p in corners]
        n = 10
        idx = {}
        for i in range(n + 1):
            for j in range(n + 1):
                u, v = i / n, j / n
                p = (c[0] * (1 - u) * (1 - v) + c[1] * u * (1 - v) + c[2] * u * v + c[3] * (1 - u) * v)
                p += Vector(sag_dir) * sag * math.sin(math.pi * u) * math.sin(math.pi * v)
                idx[(i, j)] = mb.v(p)
        for i in range(n):
            for j in range(n):
                q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                mb.f([idx[k] for k in q], [(a / n, b / n) for a, b in q])
    e = 0.004
    H = HH
    # far hallway ceiling corners
    web([(HX0 + e, HY1 - 0.75, H - 0.7), (HX0 + 0.7, HY1 - e, H - 0.7), (HX0 + 0.8, HY1 - e, H - e), (HX0 + e, HY1 - 0.8, H - e)],
        (0.5, -0.5, -0.3), 0.07)
    web([(HX1 - 0.6, HY1 - e, H - 0.55), (HX1 - e, HY1 - 0.6, H - 0.55), (HX1 - e, HY1 - 0.65, H - e), (HX1 - 0.65, HY1 - e, H - e)],
        (-0.5, -0.5, -0.3), 0.06)
    # end window upper corners
    zt = EW_Z + EW_H
    web([(-EW_W / 2 + e, HY1 + 0.02, zt - 0.35), (-EW_W / 2 + 0.35, HY1 + 0.02, zt - 0.35), (-EW_W / 2 + 0.38, HY1 + 0.02, zt - e),
         (-EW_W / 2 + e, HY1 + 0.02, zt - e)], (0, -1, 0), 0.03)
    # along the hallway: wall/ceiling edges at random spots
    for y, side in ((3.9, "L"), (7.6, "R"), (8.0, "L"), (11.3, "R"), (12.9, "L"), (5.4, "R")):
        x = HX0 if side == "L" else HX1
        s = 1 if side == "L" else -1
        L = 0.5
        web([(x + s * e, y - L / 2, H - 0.35), (x + s * 0.32, y + L / 2, H - 0.25), (x + s * 0.4, y + L / 2, H - e),
             (x + s * e, y - L / 2, H - e)], (s * 0.6, 0, -0.4), 0.05)
    # doorway heads (hallway side), top corner on the latch side
    for did, side, yc, hinge, ang in DOORS:
        if did in ("L2", "R2", "L3"):
            xh, xr, nr = side_x(side)
            x = (xh + xr) / 2
            y0 = yc + DW / 2 - e
            web([(x, y0, DHT - 0.45), (x, y0 - 0.42, DHT - 0.45), (x, y0 - 0.45, DHT - e), (x, y0, DHT - e)], (nr.x, 0, 0), 0.03)
    # side room corners + window corners
    for did, side, yc, _, _ in DOORS:
        rx0, rx1, ry0, ry1 = room_box(side, yc)
        fx = rx0 if side == "L" else rx1
        s = 1 if side == "L" else -1
        web([(fx + s * e, ry1 - 0.6, H - 0.55), (fx + s * 0.6, ry1 - e, H - 0.55), (fx + s * 0.65, ry1 - e, H - e), (fx + s * e, ry1 - 0.65, H - e)],
            (s * 0.5, -0.5, -0.3), 0.06)
        zt = SW_Z + SW_H
        web([(fx + s * 0.03, yc - SW_W / 2 + e, zt - 0.3), (fx + s * 0.03, yc - SW_W / 2 + 0.3, zt - 0.3),
             (fx + s * 0.03, yc - SW_W / 2 + 0.32, zt - e), (fx + s * 0.03, yc - SW_W / 2 + e, zt - e)], (s, 0, 0), 0.02)
    # between the wheelchair's push handle and the wall
    web([(-0.62, 13.05, 0.95), (HX0 + 0.04, 13.05, 1.05), (HX0 + 0.04, 13.3, 1.5), (-0.62, 13.12, 1.0)], (0, 0.2, -0.3), 0.04)
    return obj_from(mb, "Cobwebs", ["Cobweb"], smooth_deg=89)


def build_decals():
    mb = MB()

    def quad(c, ux, uy, w, h, uv0, uv1):
        c, ux, uy = Vector(c), Vector(ux), Vector(uy)
        ps = [c - ux * w / 2 - uy * h / 2, c + ux * w / 2 - uy * h / 2, c + ux * w / 2 + uy * h / 2, c - ux * w / 2 + uy * h / 2]
        mb.f([mb.v(p) for p in ps], [(uv0[0], uv0[1]), (uv1[0], uv0[1]), (uv1[0], uv1[1]), (uv0[0], uv1[1])])
    e = 0.0015
    GH, HP, SM, GR = ((0, 0), (0.5, 0.5)), ((0.5, 0), (1, 0.5)), ((0, 0.5), (0.5, 1)), ((0.5, 0.5), (1, 1))
    L, Rw = ((0, 1, 0), (0, 0, 1)), ((0, -1, 0), (0, 0, 1))
    quad((HX0 + e, 8.55, 1.68), *L, 0.66, 0.8, *GH)                    # ghost of the fallen frame
    quad((HX1 - e, 8.0, 1.22), *Rw, 0.24, 0.3, *HP)                     # handprint near R2
    quad((HX0 + e, 10.03, 1.3), *L, 0.22, 0.28, *HP)                    # handprint by L3
    quad((0.92, HY1 - e, 1.22), (1, 0, 0), (0, 0, 1), 0.36, 0.36, *SM)  # smeared hands by the end window
    for x, y, a, w, h in ((0.95, 3.1, 0.3, 0.7, 0.6), (-1.0, 11.4, 1.2, 0.8, 0.7), (0.9, 9.0, 2.0, 0.6, 0.5),
                          (-1.05, 5.4, 0.7, 0.5, 0.6), (0.4, 13.4, 0.2, 0.9, 0.7), (CEIL_HOLE[0], CEIL_HOLE[1], 0.4, 1.4, 1.1)):
        quad((x, y, e if abs(x - CEIL_HOLE[0]) > 0.01 else 0.0092), (math.cos(a), math.sin(a), 0), (-math.sin(a), math.cos(a), 0), w, h, *GR)
    quad((CEIL_HOLE[0] + 0.3, CEIL_HOLE[1] - 0.6, HH - e), (1, 0, 0), (0, -1, 0), 1.0, 0.9, *GR)        # water stain
    quad((-0.2, 3.0, HH - e), (1, 0, 0), (0, -1, 0), 1.2, 1.0, *GR)
    for did, side, yc, _, _ in DOORS:
        rx0, rx1, ry0, ry1 = room_box(side, yc)
        quad(((rx0 + rx1) / 2, yc + 0.2, e), (1, 0, 0), (0, 1, 0), 1.4, 1.2, *GR)
    return obj_from(mb, "Decals", ["Decal_Grime"], smooth_deg=10)


def build_outside():
    """Night backdrop quads 3 m outside every window (emissive, very dark)."""
    mb = MB()
    rng = np.random.default_rng(91)

    def backdrop(c, a_dir, n_in, wdt=8.0, hgt=5.0, z0=-1.2, u0=0.0):
        c, a, n = Vector(c), Vector(a_dir), Vector(n_in)
        ps = [c + a * (-wdt / 2) + Vector((0, 0, z0)), c + a * (wdt / 2) + Vector((0, 0, z0)),
              c + a * (wdt / 2) + Vector((0, 0, z0 + hgt)), c + a * (-wdt / 2) + Vector((0, 0, z0 + hgt))]
        ids = [mb.v(p) for p in ps]
        uv = [(u0, 0), (u0 + wdt / 8.0, 0), (u0 + wdt / 8.0, hgt / 4.0), (u0, hgt / 4.0)]
        v = [Vector(mb.V[i]) for i in ids]
        if (v[1] - v[0]).cross(v[3] - v[0]).dot(n) < 0:
            ids, uv = ids[::-1], uv[::-1]
        mb.f(ids, uv, 0)
    for did, side, yc, _, _ in DOORS:
        s = -1 if side == "L" else 1
        fx = (HX0 - WT - RD - RWT - 3.0) if side == "L" else (HX1 + WT + RD + RWT + 3.0)
        a = (0, -1, 0) if side == "L" else (0, 1, 0)
        backdrop((fx, yc, 0), a, (-s, 0, 0), u0=float(rng.uniform(0, 1)))
    backdrop((0, HY1 + EWT + 3.5, 0), (1, 0, 0), (0, -1, 0), wdt=9.0, hgt=5.5, z0=-1.3, u0=0.18)
    return obj_from(mb, "Outside", ["Outside_Night"], smooth_deg=10)


# =============================================================================== empties + colliders
def add_empty(name, loc, quat=None, size=0.15, shape="ARROWS"):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = shape
    e.empty_display_size = size
    e.location = Vector(loc)
    if quat is not None:
        e.rotation_mode = "QUATERNION"
        e.rotation_quaternion = quat
    link(e)
    return e


def build_empties():
    out = []
    for did, side, yc, _, _ in DOORS:
        xh, xr, nr = side_x(side)
        into_hall = -nr
        # glTF +Z (local) = Blender local -Y  -> track -Y to the direction
        q = into_hall.to_track_quat("-Y", "Z")
        out.append(add_empty(f"Door_{did}", ((xh + xr) / 2, yc, 0.0), q))
        out.append(add_empty(f"Inside_{did}", (xr + nr.x * 1.2, yc, 0.0), q))
        rx0, rx1, ry0, ry1 = room_box(side, yc)
        fx = rx0 if side == "L" else rx1
        moon = (nr * math.cos(MOON_ELEV) + Vector((0, 0, math.sin(MOON_ELEV)))).normalized()
        # glTF -Z (local) = Blender local +Y -> track +Y towards the moon
        e = add_empty(f"Window_{did}", (fx, yc, SW_Z + SW_H / 2), moon.to_track_quat("Y", "Z"))
        e["moon_elevation_deg"] = math.degrees(MOON_ELEV)
        out.append(e)
    moon = (Vector((0, 1, 0)) * math.cos(math.radians(22)) + Vector((0, 0, math.sin(math.radians(22))))).normalized()
    e = add_empty("Window_End", (0.0, HY1, EW_Z + EW_H / 2), moon.to_track_quat("Y", "Z"))
    e["moon_elevation_deg"] = 22.0
    out.append(e)
    out.append(add_empty("Empty_FlashlightTarget_Default", (HX0, 5.7, 1.35), None, 0.1, "SPHERE"))
    return out


def build_colliders():
    par = bpy.data.objects.new("Colliders", None)
    link(par)
    # shell: floor, ceiling, end walls, the two long walls split around the doorways (+ lintels)
    big = [
        ("COL_Floor", (0, (HY0 + HY1) / 2, -0.1), (2 * (HX1 + WT + RD + RWT), HY1 - HY0 + 2 * EWT, 0.2)),
        ("COL_Ceiling", (0, (HY0 + HY1) / 2, HH + 0.1), (2 * (HX1 + WT + RD + RWT), HY1 - HY0 + 2 * EWT, 0.2)),
        ("COL_Hall_EndWall", (0, HY1 + EWT / 2, HH / 2), (HX1 - HX0 + 2 * WT, EWT, HH)),
        ("COL_Hall_NearWall", (0, HY0 - EWT / 2, HH / 2), (HX1 - HX0 + 2 * WT, EWT, HH)),
    ]
    for side in "LR":
        xh, xr, nr = side_x(side)
        xc = (xh + xr) / 2
        ys = sorted(d[2] for d in DOORS if d[1] == side)
        cur = HY0
        k = 0
        for y in ys:
            big.append((f"COL_Hall_Wall{side}_{k}", (xc, (cur + y - DW / 2) / 2, HH / 2), (WT, (y - DW / 2) - cur, HH)))
            did = [d[0] for d in DOORS if d[1] == side and d[2] == y][0]
            big.append((f"COL_Hall_Lintel_{did}", (xc, y, (DHT + HH) / 2), (WT, DW, HH - DHT)))
            cur = y + DW / 2
            k += 1
        big.append((f"COL_Hall_Wall{side}_{k}", (xc, (cur + HY1) / 2, HH / 2), (WT, HY1 - cur, HH)))
    out = []
    for name, c, s in big:
        out.append((name, c, s, 0.0))
    out += COLLIDERS
    objs = [par]
    for name, c, s, yaw in out:
        me = bpy.data.meshes.new(name)
        hx, hy, hz = s[0] / 2, s[1] / 2, s[2] / 2
        vs = [(x, y, z) for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)]
        fs = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        me.from_pydata(vs, [], fs)
        me.update()
        ob = bpy.data.objects.new(name, me)
        link(ob)
        ob.location = Vector(c)
        ob.rotation_euler = (0, 0, yaw)
        ob.parent = par
        ob.hide_render = True
        ob.display_type = "WIRE"
        objs.append(ob)
    return objs, out


# =============================================================================== AO bake
def bake_ao(objs, hide):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if _enable_gpu() else "CPU"
    scene.cycles.samples = 128
    scene.cycles.use_denoising = False
    world = bpy.data.worlds.new("BakeWorld")
    scene.world = world
    world.light_settings.distance = 0.6
    for o in hide:
        o.hide_render = True
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        uv = o.data.uv_layers.get("AO") or o.data.uv_layers.new(name="AO")
        o.data.uv_layers.active = uv
        o.data.uv_layers["UVMap"].active_render = True
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    t0 = time.time()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, margin_method="FRACTION", margin=0.0015, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[ao] lightmap uv {time.time() - t0:.1f}s")
    t0 = time.time()
    if not QUICK:
        bpy.ops.object.bake(type="AO", margin=6, margin_type="EXTEND", use_clear=True, target="IMAGE_TEXTURES")
        print(f"[ao] bake {time.time() - t0:.1f}s")
    for o in hide:
        o.hide_render = False
    for o in objs:
        o.data.uv_layers.active = o.data.uv_layers["UVMap"]
    if QUICK:
        return
    a = np.array(R.AO_IMAGE.pixels[:], dtype=np.float32).reshape(AO_RES, AO_RES, 4)[..., 0]
    a = RT.blur(a.astype(np.float64), 0.8)
    a = np.clip(a, 0, 1) ** 1.15
    path = os.path.join(TEXDIR, "Hallway_AO.jpg")
    R.save_img(a, path, 90)
    img = R.load_img(path, "Hallway_AO_baked", True)
    for m in bpy.data.materials:
        if m.node_tree and "AO" in m.node_tree.nodes:
            m.node_tree.nodes["AO"].image = img


# =============================================================================== previews
CAM = bl((0.3, 1.6, 0.2))
LOOK = bl((-0.1, 1.2, -14.0))
FLASH_W = 900.0


def clear_lights(prefix="PV_"):
    for o in list(bpy.data.objects):
        if o.name.startswith(prefix):
            bpy.data.objects.remove(o, do_unlink=True)


def add_light(name, kind, loc, power, color=(1, 1, 1), size=1.0, aim=None, spot=None, blend=0.3, size_y=None):
    ld = bpy.data.lights.new("PV_" + name, kind)
    ld.energy = power
    ld.color = color
    if kind == "AREA":
        ld.size = size
        if size_y:
            ld.shape = "RECTANGLE"
            ld.size_y = size_y
    if kind == "SPOT":
        ld.spot_size = spot
        ld.spot_blend = blend
        ld.shadow_soft_size = size
    lo = link(bpy.data.objects.new("PV_" + name, ld))
    lo.location = Vector(loc)
    if aim is not None:
        lo.rotation_euler = (Vector(aim) - lo.location).to_track_quat("-Z", "Y").to_euler()
    return lo


def previews(only=None):
    R.CAM, R.LOOK = CAM, LOOK
    for o in bpy.data.objects:
        if o.name.startswith("COL_"):
            o.hide_render = True
    if not bpy.data.objects.get("PreviewCam"):
        R.setup_camera((1600, 1000))
    else:
        bpy.context.scene.camera = bpy.data.objects["PreviewCam"]
    pv = lambda n: os.path.join(HERE, f"hallway_preview_{n}.png")
    shots = only or ["hall", "door", "fill", "moon"]
    for name in shots:
        clear_lights()
        if name == "hall":
            R.render(pv("flash_hall"), LOOK, power=FLASH_W, samples=128)
        elif name == "door":
            R.render(pv("flash_door"), Vector((HX0 - 0.1, 8.6, 0.9)), power=FLASH_W, samples=128)
        elif name == "door2":
            R.render(pv("flash_door2"), Vector((HX1 + 0.1, 4.6, 1.0)), power=FLASH_W, samples=128)
        elif name == "end":
            R.render(pv("flash_end"), Vector((-0.3, 12.8, 0.6)), power=FLASH_W, samples=128)
        elif name.startswith("room"):
            # debug view from just inside a side room doorway (fill light), e.g. roomL2
            did = name[4:] or "L2"
            d = [x for x in DOORS if x[0] == did][0]
            xh, xr, nr = side_x(d[1])
            cam = bpy.data.objects["PreviewCam"]
            keep = (cam.location.copy(), cam.rotation_euler.copy())
            cam.location = Vector((xr + nr.x * 0.3, d[2] - 0.9, 1.5))
            tgt = Vector((xr + nr.x * RD, d[2] + 0.3, 1.0))
            cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
            rx0, rx1, ry0, ry1 = room_box(d[1], d[2])
            add_light("FillRoom", "AREA", ((rx0 + rx1) / 2, d[2], HH - 0.05), 60.0, (1.0, 0.95, 0.88), 2.0, aim=((rx0 + rx1) / 2, d[2], 0))
            R.render(pv(name), None, samples=64)
            cam.location, cam.rotation_euler = keep
        elif name == "fill":
            for k, y in enumerate(np.arange(0.5, 14.0, 2.0)):
                add_light(f"Fill{k}", "AREA", (0, y, HH - 0.05), 25.0, (1.0, 0.95, 0.88), 1.2, aim=(0, y, 0), size_y=1.6)
            for did, side, yc, _, _ in DOORS:
                rx0, rx1, ry0, ry1 = room_box(side, yc)
                add_light(f"FillR{did}", "AREA", ((rx0 + rx1) / 2, yc, HH - 0.05), 30.0, (1.0, 0.95, 0.88), 1.5, aim=((rx0 + rx1) / 2, yc, 0))
            R.render(pv("fill"), None, samples=96)
        elif name == "moon":
            moon_lights()
            R.render(pv("moon"), None, samples=160)
        clear_lights()
    old = bpy.data.objects.get("Flashlight")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)


def moon_lights(power=3500.0):
    col = (0.55, 0.66, 1.0)
    for e in bpy.data.objects:
        if not e.name.startswith("Window_") or e.type != "EMPTY":
            continue
        d = e.matrix_world.to_3x3() @ Vector((0, 1, 0))           # local +Y = towards the moon
        horiz = Vector((d.x, d.y, 0)).normalized()
        wall_t = EWT if e.name == "Window_End" else RWT
        p = e.location + horiz * (wall_t + 0.6) + d * 0.9
        pw = power * (0.35 if e.name == "Window_End" else 1.0)
        add_light("Moon_" + e.name, "SPOT", p, pw, col, 0.08, aim=p - d, spot=math.radians(55), blend=0.25)


# =============================================================================== main
def main():
    t_start = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_materials()
    hall, walls = build_hallway()
    etm = MB()
    efr, egl = build_window("End", (0, HY1, 0), (0, -1, 0), (1, 0, 0), EW_W, EW_H, EW_Z, EWT, etm)
    etrim = obj_from(etm, "EndWindow_casing", ["Trim"], recalc=True)
    hall = join_objs("Hallway", [hall, etrim])
    R.paint_dirt(hall, (HX0, HY0, 0), (HX1, HY1, HH), HH)
    print(f"[build] hallway {time.time() - t_start:.0f}s")
    rng = np.random.default_rng(99)
    rooms, frames, glasses, curtains, rods = [], [], [], [], []
    for did, side, yc, _, _ in DOORS:
        room, fr, gl_, cu, rod, box = build_side_room(did, side, yc, rng)
        rooms.append(room)
        frames.append(fr)
        glasses.append(gl_)
        curtains.append(cu)
        rods.append(rod)
    frames.append(efr)
    glasses.append(egl)
    print(f"[build] rooms {time.time() - t_start:.0f}s")

    props = []
    doors, door_info = build_doors()
    props += doors
    # side room furniture
    L = {d[0]: room_box(d[1], d[2]) for d in DOORS}
    props += build_bed("L1", (L["L1"][0] + 0.05 + 0.98, L["L1"][3] - 0.52, 0), math.radians(90))
    props += build_bed("R2", (L["R2"][1] - 0.05 - 0.98, L["R2"][2] + 0.52, 0), math.radians(-90))
    props += build_bed("R3", (L["R3"][1] - 0.05 - 0.98, L["R3"][3] - 0.52, 0), math.radians(-90))
    props.append(build_wardrobe("Wardrobe_R1", (L["R1"][0] + 1.55, L["R1"][3] - 0.31, 0), 0.0, 1.25))
    props.append(build_wardrobe("Wardrobe_L2", (L["L2"][0] + 0.95, L["L2"][2] + 0.31, 0), math.pi, 0.5))
    props.append(build_wardrobe("Wardrobe_R3", (L["R3"][0] + 1.6, L["R3"][2] + 0.31, 0), math.pi, 0.02))
    props.append(build_chair_at("Chair_FacingWindow_R1", (L["R1"][1] - 0.75, 4.6 - 0.35, 0), math.radians(90 + 8)))
    props.append(build_chair_at("Chair_FacingWindow_L3", (L["L3"][0] + 0.8, 10.6 + 0.2, 0), math.radians(-90 - 6)))
    # hallway props
    props.append(build_chair_at("Chair_Toppled", (0.62, 7.25, 0), math.radians(35), topple=(math.radians(-90), math.radians(8))))
    props.append(build_radiator_hall())
    props.append(build_side_table())
    props.append(build_wheelchair())
    fx_op, fx_alpha = build_fixtures()
    props += fx_op
    props += build_frames()
    props.append(build_carpet())
    props.append(build_debris())
    props.append(build_papers())
    print(f"[build] props {time.time() - t_start:.0f}s")

    alpha_objs = glasses + curtains + fx_alpha + [build_cobwebs(), build_decals()]
    outside = build_outside()
    empties = build_empties()
    col_objs, col_list = build_colliders()
    bake_objs = [hall] + rooms + frames + rods + props
    bake_ao(bake_objs, alpha_objs + [outside])
    for o in alpha_objs + [outside]:
        o.data.uv_layers.new(name="AO")
        o.data.uv_layers.active = o.data.uv_layers["UVMap"]
    print(f"[build] ao {time.time() - t_start:.0f}s")

    allobjs = [hall] + rooms + frames + rods + props + alpha_objs + [outside] + empties + col_objs
    os.makedirs(MODELS, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in allobjs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=OUT, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
        export_texcoords=True, export_normals=True, export_materials="EXPORT", export_image_format="AUTO",
        export_cameras=False, export_lights=False, export_animations=False, export_skins=False,
        export_morph=False, export_vertex_color="MATERIAL", export_extras=True,
        export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
        export_draco_position_quantization=14, export_draco_normal_quantization=10,
        export_draco_texcoord_quantization=12, export_draco_color_quantization=8)
    print(f"[export] {OUT}: {os.path.getsize(OUT) / 1e6:.2f} MB  ({time.time() - t_start:.0f}s)")
    for did, ang, sign, axis, yaw in door_info:
        print(f"[door] DoorLeaf_{did}: open {ang} deg, sign {sign}, hinge glTF {tuple(round(v, 3) for v in gl(axis))}")
    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    if PREVIEW:
        previews()


if __name__ == "__main__":
    if "--preview-only" in ARGS:
        bpy.ops.wm.open_mainfile(filepath=BLEND)
        only = [a for a in ARGS if not a.startswith("--")]
        previews(only or None)
    else:
        main()
