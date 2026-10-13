"""Haunted room + corridor environment -> public/models/room.glb

    blender -b -P blender/room.py                 # build, bake AO, export, render previews
    blender -b -P blender/room.py -- --retex      # also regenerate the procedural textures
    blender -b -P blender/room.py -- --no-preview # skip the preview renders

Authoring is in Blender space (Z up).  The glTF exporter maps Blender (x, y, z) -> glTF (x, z, -y),
so the SPEC's glTF room z in [-4.2, 0.8] is Blender y in [-0.8, 4.2] (the back wall is at y = +4.2).
All textures are generated procedurally by room_tex.py (numpy) and cached as JPEG/PNG in
blender/_tex/.  Ambient occlusion is baked with Cycles into one shared lightmap atlas (UV map "AO",
glTF TEXCOORD_1) and exported as the glTF occlusionTexture of every material.
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
import room_tex as RT  # noqa: E402
from common import ROOT, MODELS, link, set_active, smooth, _enable_gpu  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RETEX = "--retex" in ARGS
PREVIEW = "--no-preview" not in ARGS
TEXDIR = os.path.join(HERE, "_tex")
OUT = os.path.join(MODELS, "room.glb")

# ----------------------------------------------------------------------------- layout (Blender space)
X0, X1 = -2.6, 2.6          # room interior
Y0, Y1 = -0.8, 4.2
H = 2.75
BT = 0.14                   # back wall thickness
YC0, YC1 = Y1 + BT, 5.75    # corridor
CX0, CX1 = -4.5, 3.5
CH = 2.6
DX0, DX1, DH = -1.0, -0.1, 2.05      # doorway (clear opening)
D2X0, D2X1 = -2.025, -1.175          # second doorway, corridor far wall
CLO_Y1, CLO_X0, CLO_X1, CLO_H = 6.9, -2.45, -0.75, 2.3   # closet behind it
ROLL = 0.5                  # wallpaper roll width (texture tile = 5 rolls = 2.5 m)
WALL_TILE = 2.5
FLOOR_TILE = 2.08
CEIL_TILE = 2.75
TRIM_TILE = 0.5
WOOD_TILE = 1.0
IRON_TILE = 0.5

RNG = np.random.default_rng(1234)


# =============================================================================== mesh builder
class MB:
    """Collects verts / faces / per-corner UVs / material indices, then builds one mesh object."""

    def __init__(self):
        self.V, self.F, self.UV, self.M = [], [], [], []

    def v(self, p):
        self.V.append(tuple(p))
        return len(self.V) - 1

    def f(self, vids, uvs, m=0):
        self.F.append(list(vids))
        self.UV.append([tuple(u) for u in uvs])
        self.M.append(m)

    def extend(self, other):
        off = len(self.V)
        self.V += other.V
        self.F += [[i + off for i in f] for f in other.F]
        self.UV += other.UV
        self.M += other.M

    def obj(self, name, mats, recalc=False, weld=0.0, smooth_deg=35.0):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.V, [], self.F)
        uv = me.uv_layers.new(name="UVMap")
        flat = np.array([c for f in self.UV for c in f], dtype=np.float32)
        uv.data.foreach_set("uv", flat.ravel())
        me.polygons.foreach_set("material_index", self.M)
        for m in mats:
            me.materials.append(m)
        ob = link(bpy.data.objects.new(name, me))
        if recalc or weld:
            bm = bmesh.new()
            bm.from_mesh(me)
            if weld:
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=weld)
            if recalc:
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(me)
            bm.free()
        me.validate()
        smooth(ob, smooth_deg)
        return ob


def V3(*a):
    return Vector(a)


def lines(a, b, step, extras=()):
    n = max(1, int(round((b - a) / step)))
    vals = set(np.round(np.linspace(a, b, n + 1), 6))
    for e in extras:
        if a < e < b:
            vals.add(round(e, 6))
    return sorted(vals)


def grid_surface(mb, P, s_lines, t_lines, uvf, normal, mat):
    idx = {}

    def vid(i, j):
        if (i, j) not in idx:
            idx[(i, j)] = mb.v(P(s_lines[i], t_lines[j]))
        return idx[(i, j)]

    normal = Vector(normal)
    for i in range(len(s_lines) - 1):
        for j in range(len(t_lines) - 1):
            q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            p = [Vector(P(s_lines[a], t_lines[b])) for a, b in q]
            if (p[1] - p[0]).cross(p[3] - p[0]).dot(normal) < 0:
                q = q[::-1]
            mb.f([vid(*k) for k in q], [uvf(s_lines[a], t_lines[b]) for a, b in q], mat)


def sweep(mb, path, profile, origin, ea, eb, k, closed=False, uvs=0.5, mat=0, u0=0.0):
    """Sweep a closed (p, q) profile along a 2D polyline in the plane (origin, ea, eb).
    p = offset to the LEFT of the path direction (in plane), q = along k (out of plane).
    Mitred corners.  Caps at open ends.  Normals are fixed afterwards with recalc."""
    origin, ea, eb, k = Vector(origin), Vector(ea), Vector(eb), Vector(k)
    path = [np.array(p, dtype=float) for p in path]
    n = len(path)
    plen = [0.0]
    prof = list(profile) + [profile[0]]
    for a, b in zip(prof[:-1], prof[1:]):
        plen.append(plen[-1] + math.dist(a, b))
    rings = []
    s_acc = 0.0
    svals = []
    for i in range(n):
        if closed:
            prv, nxt = path[i - 1], path[(i + 1) % n]
        else:
            prv = path[i - 1] if i > 0 else None
            nxt = path[i + 1] if i < n - 1 else None
        din = (path[i] - prv) / np.linalg.norm(path[i] - prv) if prv is not None else None
        dout = (nxt - path[i]) / np.linalg.norm(nxt - path[i]) if nxt is not None else None
        t = (din if din is not None else 0) + (dout if dout is not None else 0)
        t = t / np.linalg.norm(t)
        nl = np.array([-t[1], t[0]])
        dref = din if din is not None else dout
        nseg = np.array([-dref[1], dref[0]])
        m = 1.0 / max(0.3, float(nl @ nseg))
        if i > 0:
            s_acc += float(np.linalg.norm(path[i] - path[i - 1]))
        svals.append(s_acc)
        ring = []
        for p, q in profile:
            a2 = path[i] + nl * p * m
            ring.append(mb.v(origin + ea * a2[0] + eb * a2[1] + k * q))
        rings.append(ring)
    if closed:
        rings.append(rings[0])
        svals.append(s_acc + float(np.linalg.norm(path[0] - path[-1])))
    P = len(profile)
    for i in range(len(rings) - 1):
        for j in range(P):
            j2 = (j + 1) % P
            mb.f([rings[i][j], rings[i + 1][j], rings[i + 1][j2], rings[i][j2]],
                 [((u0 + svals[i]) / uvs, plen[j] / uvs), ((u0 + svals[i + 1]) / uvs, plen[j] / uvs),
                  ((u0 + svals[i + 1]) / uvs, plen[j + 1] / uvs), ((u0 + svals[i]) / uvs, plen[j + 1] / uvs)],
                 mat)
    if not closed:
        cu = [(p / uvs, q / uvs) for p, q in profile]
        mb.f(rings[0][::-1], cu[::-1], mat)
        mb.f(rings[-1], cu, mat)


def frame_from_tangent(t):
    t = Vector(t).normalized()
    up = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
    n = t.cross(up).normalized()
    b = t.cross(n).normalized()
    return n, b


def tube(mb, pts, r, sides=12, mat=0, uvs=0.5, caps=True):
    """Tube along a 3D polyline with parallel-transport frames; r scalar or per-point list."""
    pts = [Vector(p) for p in pts]
    rs = r if isinstance(r, (list, tuple, np.ndarray)) else [r] * len(pts)
    tans = []
    for i in range(len(pts)):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, len(pts) - 1)]
        tans.append((b - a).normalized())
    n, b = frame_from_tangent(tans[0])
    rings, svals = [], []
    s = 0.0
    for i, p in enumerate(pts):
        if i > 0:
            s += (pts[i] - pts[i - 1]).length
            t0, t1 = tans[i - 1], tans[i]
            ax = t0.cross(t1)
            if ax.length > 1e-8:
                ang = t0.angle(t1)
                R = Matrix.Rotation(ang, 3, ax.normalized())
                n = (R @ n).normalized()
                b = (R @ b).normalized()
        svals.append(s)
        ring = []
        for j in range(sides):
            a = TAU * j / sides
            ring.append(mb.v(p + (n * math.cos(a) + b * math.sin(a)) * rs[i]))
        rings.append(ring)
    circ = TAU * float(np.mean(rs))
    for i in range(len(rings) - 1):
        for j in range(sides):
            j2 = (j + 1) % sides
            v0, v1 = j / sides * circ / uvs, (j + 1) / sides * circ / uvs
            mb.f([rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j]],
                 [(svals[i] / uvs, v0), (svals[i] / uvs, v1), (svals[i + 1] / uvs, v1), (svals[i + 1] / uvs, v0)],
                 mat)
    if caps:
        for ring, rr, flip in ((rings[0], rs[0], True), (rings[-1], rs[-1], False)):
            cu = [(0.5 + rr * math.cos(TAU * j / sides) / uvs, 0.5 + rr * math.sin(TAU * j / sides) / uvs)
                  for j in range(sides)]
            if flip:
                mb.f(ring[::-1], cu[::-1], mat)
            else:
                mb.f(ring, cu, mat)


def lathe(mb, prof, center=(0, 0, 0), segs=24, mat=0, uvs=0.5, axis_m=None):
    """Revolve an (r, z) profile around +Z (then optional matrix).  r == 0 points collapse."""
    c = Vector(center)
    M = axis_m or Matrix.Identity(3)
    rings = []
    for r, z in prof:
        if r < 1e-6:
            rings.append([mb.v(c + M @ Vector((0, 0, z)))] * segs)
        else:
            rings.append([mb.v(c + M @ Vector((r * math.cos(TAU * j / segs), r * math.sin(TAU * j / segs), z)))
                          for j in range(segs)])
    plen = [0.0]
    for a, b in zip(prof[:-1], prof[1:]):
        plen.append(plen[-1] + math.dist(a, b))
    rmax = max(r for r, _ in prof)
    for i in range(len(rings) - 1):
        for j in range(segs):
            j2 = (j + 1) % segs
            q = [rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j]]
            uv = [(j / segs * TAU * rmax / uvs, plen[i] / uvs), ((j + 1) / segs * TAU * rmax / uvs, plen[i] / uvs),
                  ((j + 1) / segs * TAU * rmax / uvs, plen[i + 1] / uvs), (j / segs * TAU * rmax / uvs, plen[i + 1] / uvs)]
            keep = [kk for kk in range(4) if q[kk] not in q[:kk]]
            if len(keep) >= 3:
                mb.f([q[kk] for kk in keep], [uv[kk] for kk in keep], mat)


TAU = 2 * math.pi


def box(mb, size, M=Matrix.Identity(4), mat=0, bevel=0.004, segs=2, uvs=1.0, cuts=0, deform=None,
        grain=None, uvoff=None, uvscale=None):
    """Bevelled box (local centre at origin) with grain-aware box-projected UVs, transformed by M."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if cuts:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    if bevel > 0:
        edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0) > 1.0]
        bmesh.ops.bevel(bm, geom=edges, offset=bevel, offset_type="OFFSET", segments=segs,
                        profile=0.5, affect="EDGES", clamp_overlap=True)
    if deform:
        for v in bm.verts:
            v.co = Vector(deform(v.co.copy()))
    bm.normal_update()
    g = grain if grain is not None else int(np.argmax(size))
    ou, ov = uvoff if uvoff is not None else RNG.uniform(0, 1, 2)
    su, sv = uvscale if uvscale else (uvs, uvs)
    vmap = {}
    for v in bm.verts:
        vmap[v] = mb.v(M @ v.co)
    for f in bm.faces:
        ax = int(np.argmax([abs(f.normal[i]) for i in range(3)]))
        others = [i for i in range(3) if i != ax]
        if g in others:
            ua, va = g, [o for o in others if o != g][0]
        else:
            ua, va = others
        uvl = [(l.vert.co[ua] / su + ou, l.vert.co[va] / sv + ov) for l in f.loops]
        mb.f([vmap[l.vert] for l in f.loops], uvl, mat)
    bm.free()


def T(loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0):
    from mathutils import Euler
    return Matrix.Translation(Vector(loc)) @ Euler(rot, "XYZ").to_matrix().to_4x4() @ Matrix.Scale(scale, 4)


# =============================================================================== textures / materials
def save_img(arr, path, quality=90, alpha=None):
    h, w = arr.shape[:2]
    img = bpy.data.images.new("tmp_save", w, h, alpha=alpha is not None)
    px = np.ones((h, w, 4), dtype=np.float32)
    if arr.ndim == 2:
        px[..., :3] = arr[..., None]
    else:
        px[..., :3] = arr
    if alpha is not None:
        px[..., 3] = alpha
    img.pixels.foreach_set(np.clip(px, 0, 1).ravel())
    img.filepath_raw = path
    img.file_format = "PNG" if path.endswith(".png") else "JPEG"
    if alpha is not None:
        img.alpha_mode = "STRAIGHT"
    img.save(filepath=path, quality=quality)
    bpy.data.images.remove(img)


def load_img(path, name, noncolor):
    img = bpy.data.images.load(path, check_existing=False)
    img.name = name
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    return img


TEXSETS = {
    # name: (generator, base px divisor, normal divisor, rm divisor, alpha)
    "Wall": (RT.wallpaper, 1, 1, 2, False),
    "Floor": (RT.floorboards, 1, 1, 2, False),
    "Ceiling": (RT.ceiling, 1, 1, 2, False),
    "Trim": (RT.painted_trim, 1, 1, 1, False),
    "Wood": (RT.old_wood, 1, 1, 1, False),
    "Iron": (RT.rusty_iron, 1, 1, 1, False),
    "Mattress": (RT.mattress, 1, 1, 2, False),
    "Paper": (RT.paper_sheet, 1, 2, 2, False),
    "Backing": (RT.paper_backing, 1, 1, 1, False),
    "Cobweb": (RT.cobweb, 1, 0, 0, True),
    "Decals": (RT.decals, 1, 0, 0, True),
}


def texture_set(name):
    gen, db, dn, dr, alpha = TEXSETS[name]
    os.makedirs(TEXDIR, exist_ok=True)
    pb = os.path.join(TEXDIR, f"{name}_base." + ("png" if alpha else "jpg"))
    pn = os.path.join(TEXDIR, f"{name}_normal.jpg")
    pr = os.path.join(TEXDIR, f"{name}_rm.jpg")
    need = [pb] + ([pn] if dn else []) + ([pr] if dr else [])
    if RETEX or not all(os.path.exists(p) for p in need):
        t0 = time.time()
        d = gen()
        b = RT.downsample(d["base"], db) if db > 1 else d["base"]
        save_img(b, pb, 92, alpha=d.get("alpha"))
        if dn:
            save_img(RT.downsample(d["normal"], dn) if dn > 1 else d["normal"], pn, 94)
        if dr:
            rough = d["rough"]
            metal = d.get("metal", np.zeros_like(rough))
            rm = np.stack([np.ones_like(rough), rough, metal], axis=-1)
            save_img(RT.downsample(rm, dr) if dr > 1 else rm, pr, 90)
        print(f"[tex] {name}: {time.time() - t0:.1f}s")
    out = dict(base=load_img(pb, f"{name}_base", False), alpha=alpha,
               metal="metal" in ("Iron",) and name == "Iron")
    out["normal"] = load_img(pn, f"{name}_normal", True) if dn else None
    out["rm"] = load_img(pr, f"{name}_rm", True) if dr else None
    return out


_GLTF_GROUP = None


def gltf_output_group():
    global _GLTF_GROUP
    if _GLTF_GROUP is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
        g.interface.new_socket("Thickness", in_out="INPUT", socket_type="NodeSocketFloat")
        _GLTF_GROUP = g
    return _GLTF_GROUP


AO_IMAGE = None
MATS = {}


def make_mat(name, tex=None, color=(0.5, 0.5, 0.5), rough=0.6, metal=0.0, vcol=False, nstrength=1.0,
             ao=True, blend=False, alpha=1.0, factor=None, double=False, spec=0.5, emission=None):
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    bsdf = N["Principled BSDF"]
    bsdf.inputs["Specular IOR Level"].default_value = spec
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    if tex is not None:
        tb = N.new("ShaderNodeTexImage")
        tb.image = tex["base"]
        tb.location = (-700, 400)
        col_out = tb.outputs["Color"]
        if vcol:
            vc = N.new("ShaderNodeVertexColor")
            vc.layer_name = "Dirt"
            vc.location = (-700, 650)
            mx = N.new("ShaderNodeMix")
            mx.data_type = "RGBA"
            mx.blend_type = "MULTIPLY"
            mx.inputs[0].default_value = 1.0
            mx.location = (-400, 500)
            L.new(col_out, mx.inputs[6])
            L.new(vc.outputs["Color"], mx.inputs[7])
            col_out = mx.outputs[2]
        elif factor is not None:
            mx = N.new("ShaderNodeMix")
            mx.data_type = "RGBA"
            mx.blend_type = "MULTIPLY"
            mx.inputs[0].default_value = 1.0
            mx.inputs[7].default_value = (*factor, 1.0)
            L.new(col_out, mx.inputs[6])
            col_out = mx.outputs[2]
        L.new(col_out, bsdf.inputs["Base Color"])
        if tex["alpha"]:
            L.new(tb.outputs["Alpha"], bsdf.inputs["Alpha"])
        if tex.get("rm") is not None:
            tr = N.new("ShaderNodeTexImage")
            tr.image = tex["rm"]
            tr.location = (-700, 50)
            sp = N.new("ShaderNodeSeparateColor")
            sp.location = (-400, 50)
            L.new(tr.outputs["Color"], sp.inputs[0])
            L.new(sp.outputs["Green"], bsdf.inputs["Roughness"])
            # always wire B -> metallic (0 for non-metals) so the exporter embeds the JPEG as-is
            L.new(sp.outputs["Blue"], bsdf.inputs["Metallic"])
        if tex.get("normal") is not None:
            tn = N.new("ShaderNodeTexImage")
            tn.image = tex["normal"]
            tn.location = (-700, -300)
            nm = N.new("ShaderNodeNormalMap")
            nm.inputs["Strength"].default_value = nstrength
            nm.location = (-400, -300)
            L.new(tn.outputs["Color"], nm.inputs["Color"])
            L.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission[0], 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission[1]
    if blend or alpha < 1.0:
        mat.surface_render_method = "BLENDED"
        try:
            mat.blend_method = "BLEND"
        except Exception:
            pass
    mat.use_backface_culling = not double
    # AO lightmap node (also the bake target)
    ta = N.new("ShaderNodeTexImage")
    ta.name = "AO"
    ta.image = AO_IMAGE
    ta.location = (-700, -650)
    uvn = N.new("ShaderNodeUVMap")
    uvn.uv_map = "AO"
    uvn.location = (-950, -650)
    L.new(uvn.outputs["UV"], ta.inputs["Vector"])
    if ao:
        sa = N.new("ShaderNodeSeparateColor")
        sa.location = (-400, -650)
        L.new(ta.outputs["Color"], sa.inputs[0])
        g = N.new("ShaderNodeGroup")
        g.node_tree = gltf_output_group()
        g.location = (-150, -650)
        L.new(sa.outputs["Red"], g.inputs["Occlusion"])
    N.active = ta
    MATS[name] = mat
    return mat


def build_materials():
    global AO_IMAGE
    AO_IMAGE = bpy.data.images.new("Room_AO", 2048, 2048, alpha=False, float_buffer=False)
    AO_IMAGE.colorspace_settings.name = "Non-Color"
    AO_IMAGE.generated_color = (1, 1, 1, 1)
    tx = {k: texture_set(k) for k in TEXSETS}
    make_mat("Wall", tx["Wall"], vcol=True, nstrength=1.0)
    make_mat("Floor", tx["Floor"], vcol=True, nstrength=1.0)
    make_mat("Ceiling", tx["Ceiling"], vcol=True, nstrength=1.0)
    make_mat("Trim", tx["Trim"], vcol=True, nstrength=1.0)
    make_mat("Wallpaper_Strip", tx["Wall"], nstrength=1.0, factor=(0.85, 0.82, 0.78))
    make_mat("Plaster", tx["Ceiling"], nstrength=1.0, factor=(0.9, 0.88, 0.85))
    make_mat("Wood_Old", tx["Wood"], nstrength=1.0)
    make_mat("Iron_Painted", tx["Iron"], nstrength=1.0)
    make_mat("Mattress", tx["Mattress"], nstrength=1.0)
    make_mat("Paper", tx["Paper"], nstrength=1.0)
    make_mat("Paper_Backing", tx["Backing"], nstrength=1.0)
    make_mat("Cobweb", tx["Cobweb"], blend=True, double=True, ao=False)
    make_mat("Decal_Grime", tx["Decals"], blend=True, ao=False)
    make_mat("Bakelite", None, color=(0.09, 0.05, 0.03), rough=0.35, spec=0.5)
    make_mat("Brass", None, color=(0.42, 0.30, 0.14), rough=0.45, metal=0.9)
    make_mat("Cord_Fabric", None, color=(0.10, 0.075, 0.055), rough=0.9)
    make_mat("Glass_Bulb", None, color=(0.75, 0.74, 0.70), rough=0.12, alpha=0.28, double=True, ao=False)
    make_mat("Glass_Shard", None, color=(0.05, 0.055, 0.05), rough=0.04, alpha=0.6, double=True, ao=False)
    make_mat("Filament", None, color=(0.15, 0.14, 0.13), rough=0.4, metal=1.0)
    return tx


def mats(*names):
    return [MATS[n] for n in names]


# =============================================================================== walls with wallpaper rolls
def wall_panels(mb, P, s0, s1, z0, z1, holes, seam0, rolls, height, normal, mat, u_dir=1.0, zstep=0.1):
    """Paper a wall: columns ROLL wide starting at seam0, each mapped to a roll of the 2.5 m texture.
    P(s, z) -> 3D.  u_dir = +1 if texture U increases with s, -1 if with -s."""
    cols = []
    a = seam0
    k = 0
    while a < s1 - 1e-6:
        b = a + ROLL
        lo, hi = max(a, s0), min(b, s1)
        if hi - lo > 1e-4:
            cols.append((lo, hi, a, rolls[k % len(rolls)]))
        a = b
        k += 1
    if u_dir < 0:
        # walk from the s1 end so the texture runs left->right for the viewer
        cols = []
        b = seam0
        k = 0
        while b > s0 + 1e-6:
            a = b - ROLL
            lo, hi = max(a, s0), min(b, s1)
            if hi - lo > 1e-4:
                cols.append((lo, hi, b, rolls[k % len(rolls)]))
            b = a
            k += 1
    for lo, hi, start, roll in cols:
        brks = sorted(set([lo, hi] + [e for hs0, hs1, _, _ in holes for e in (hs0, hs1) if lo < e < hi]))
        for sa, sb in zip(brks[:-1], brks[1:]):
            mid = 0.5 * (sa + sb)
            zr = [(z0, z1)]
            for hs0, hs1, hz0, hz1 in holes:
                if hs0 < mid < hs1:
                    zr = [(zz0, zz1) for zz0, zz1 in ((z0, hz0), (hz1, z1)) if zz1 - zz0 > 1e-4]
            for za, zb in zr:
                sl = lines(sa, sb, 0.1)
                zl = lines(za, zb, zstep)

                def uvf(s, z, start=start, roll=roll):
                    du = (s - start) if u_dir > 0 else (start - s)
                    return ((0.03 + roll * ROLL + du) / WALL_TILE, z / height)
                grid_surface(mb, P, sl, zl, uvf, normal, mat)


def build_room():
    mb = MB()
    W, F, C, TR, WD = 0, 1, 2, 3, 4
    xl = lines(X0, X1, 0.1, (DX0, DX1))
    yl = lines(Y0, Y1, 0.1)
    grid_surface(mb, lambda s, t: (s, t, 0), xl, yl, lambda s, t: (s / FLOOR_TILE, t / FLOOR_TILE),
                 (0, 0, 1), F)
    grid_surface(mb, lambda s, t: (s, t, H), xl, yl, lambda s, t: (s / CEIL_TILE + 0.31, t / CEIL_TILE + 0.17),
                 (0, 0, -1), C)
    # back wall (room side), texture U along +x
    wall_panels(mb, lambda s, z: (s, Y1, z), X0, X1, 0, H, [(DX0, DX1, 0, DH)], X0,
                [4, 3, 1, 2, 0, 2, 0, 4, 3, 2, 0], H, (0, -1, 0), W)
    # left wall: viewer's right is +y
    wall_panels(mb, lambda s, z: (X0, s, z), Y0, Y1, 0, H, [], Y0,
                [1, 2, 0, 3, 1, 4, 2, 4, 0, 2], H, (1, 0, 0), W)
    # right wall: viewer's right is -y -> start at the back corner
    wall_panels(mb, lambda s, z: (X1, s, z), Y0, Y1, 0, H, [], Y1,
                [0, 2, 4, 1, 3, 0, 2, 4, 1, 3], H, (-1, 0, 0), W, u_dir=-1)
    # front wall: viewer's right is -x
    wall_panels(mb, lambda s, z: (s, Y0, z), X0, X1, 0, H, [], X1,
                [2, 0, 4, 1, 3, 2, 0, 4, 1, 3, 2], H, (0, 1, 0), W, u_dir=-1)
    # door jambs (reveal), painted wood
    zl = lines(0, DH, 0.25)
    yr = [Y1, YC0]
    grid_surface(mb, lambda y, z: (DX0, y, z), yr, zl, lambda y, z: (z / TRIM_TILE, y / TRIM_TILE), (1, 0, 0), TR)
    grid_surface(mb, lambda y, z: (DX1, y, z), yr, zl, lambda y, z: (z / TRIM_TILE, y / TRIM_TILE + 0.3), (-1, 0, 0), TR)
    grid_surface(mb, lambda x, y: (x, y, DH), lines(DX0, DX1, 0.3), yr,
                 lambda x, y: (x / TRIM_TILE, y / TRIM_TILE + 0.6), (0, 0, -1), TR)
    shell = mb.obj("Room_shell", mats("Wall", "Floor", "Ceiling", "Trim", "Wood_Old"), weld=1e-4)

    tm = MB()
    # baseboards (CCW from above so the left normal points into the room)
    base_prof = [(0, 0.19), (0.007, 0.19), (0.012, 0.186), (0.0135, 0.18), (0.0135, 0.172), (0.016, 0.166),
                 (0.02, 0.16), (0.02, 0.022), (0.024, 0.021), (0.029, 0.017), (0.033, 0.01), (0.034, 0.0), (0, 0)]
    PL = 0.105
    sweep(tm, [(DX0 - PL, Y1), (X0, Y1), (X0, Y0), (X1, Y0), (X1, Y1), (DX1 + PL, Y1)], base_prof,
          (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), uvs=TRIM_TILE, mat=0)
    # crown moulding
    cr = [(0, 0), (0, 0.11), (0.008, 0.11), (0.008, 0.098)]
    for i in range(9):
        th = math.radians(180 + 90 * i / 8)
        cr.append((0.1 + 0.088 * math.cos(th), 0.1 + 0.088 * math.sin(th)))
    cr += [(0.098, 0.008), (0.11, 0.008), (0.11, 0)]
    sweep(tm, [(X0, Y1), (X0, Y0), (X1, Y0), (X1, Y1)], cr, (0, 0, H), (1, 0, 0), (0, 1, 0), (0, 0, -1),
          closed=True, uvs=TRIM_TILE, mat=0, u0=0.37)
    # door casing (room side) + plinth blocks + stop bead + threshold
    door_trim(tm, Y1, -1, DX0, DX1)
    door_trim(tm, YC0, +1, DX0, DX1)
    stop_prof = [(0, -0.0175), (-0.012, -0.0175), (-0.012, 0.0175), (0, 0.0175)]
    sweep(tm, [(DX0, 0.0), (DX0, DH), (DX1, DH), (DX1, 0.0)], stop_prof, (0, Y1 + BT * 0.55, 0),
          (1, 0, 0), (0, 0, 1), (0, 1, 0), uvs=TRIM_TILE, mat=0)
    trims = tm.obj("Room_trim", mats("Trim"), recalc=True)
    th = MB()
    box(th, (DX1 - DX0 + 0.03, BT + 0.05, 0.02), T((0.5 * (DX0 + DX1), Y1 + BT / 2, 0.006)), 0,
        bevel=0.006, segs=3, uvs=WOOD_TILE)
    thr = th.obj("Room_threshold", mats("Wood_Old"))
    room = join_objs("Room", [shell, trims, thr])
    return room


def door_trim(mb, yface, side, x0, x1, ztop=DH):
    """Casing around an opening on the wall face at y = yface; side = -1 faces -y, +1 faces +y."""
    cas = [(0.003, 0), (0.003, 0.012), (0.006, 0.017), (0.011, 0.019), (0.016, 0.0175), (0.02, 0.016),
           (0.065, 0.017), (0.072, 0.019), (0.078, 0.024), (0.086, 0.025), (0.092, 0.022), (0.094, 0.015),
           (0.094, 0)]
    PZ = 0.24
    sweep(mb, [(x0, PZ), (x0, ztop), (x1, ztop), (x1, PZ)], cas, (0, yface, 0), (1, 0, 0), (0, 0, 1),
          (0, side, 0), uvs=TRIM_TILE, mat=0, u0=RNG.uniform(0, 1))
    for xc in (x0 - 0.054, x1 + 0.054):
        box(mb, (0.104, 0.034, PZ), T((xc, yface + side * 0.017, PZ / 2)), 0, bevel=0.004, segs=2,
            uvs=TRIM_TILE, grain=2)


def join_objs(name, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ob = bpy.context.active_object
    ob.name = ob.data.name = name
    return ob


def build_corridor():
    mb = MB()
    W, F, C, TR = 0, 1, 2, 3
    xl = lines(CX0, CX1, 0.1, (DX0, DX1, D2X0, D2X1))
    yl = lines(YC0, YC1, 0.1)
    grid_surface(mb, lambda s, t: (s, t, 0), xl, yl, lambda s, t: (s / FLOOR_TILE + 0.4, t / FLOOR_TILE),
                 (0, 0, 1), F)
    grid_surface(mb, lambda s, t: (s, t, CH), xl, yl, lambda s, t: (s / CEIL_TILE, t / CEIL_TILE), (0, 0, -1), C)
    # near wall (corridor side of the back wall): viewer's right = -x
    wall_panels(mb, lambda s, z: (s, YC0, z), CX0, CX1, 0, CH, [(DX0, DX1, 0, DH)], CX1,
                [3, 0, 2, 4, 1, 0, 3, 2, 4, 1, 0, 2, 3, 4, 0, 1], CH, (0, 1, 0), W, u_dir=-1)
    # far wall: viewer's right = +x
    wall_panels(mb, lambda s, z: (s, YC1, z), CX0, CX1, 0, CH, [(D2X0, D2X1, 0, DH)], CX0,
                [2, 4, 0, 1, 3, 4, 0, 2, 4, 3, 1, 0, 2, 4, 1, 3], CH, (0, -1, 0), W)
    wall_panels(mb, lambda s, z: (CX0, s, z), YC0, YC1, 0, CH, [], YC0, [1, 4, 2], CH, (1, 0, 0), W)
    wall_panels(mb, lambda s, z: (CX1, s, z), YC0, YC1, 0, CH, [], YC1, [0, 3, 2], CH, (-1, 0, 0), W, u_dir=-1)
    # second doorway: jambs + closet behind
    yr = [YC1, YC1 + BT]
    zl = lines(0, DH, 0.25)
    grid_surface(mb, lambda y, z: (D2X0, y, z), yr, zl, lambda y, z: (z / TRIM_TILE, y / TRIM_TILE), (1, 0, 0), TR)
    grid_surface(mb, lambda y, z: (D2X1, y, z), yr, zl, lambda y, z: (z / TRIM_TILE, y / TRIM_TILE), (-1, 0, 0), TR)
    grid_surface(mb, lambda x, y: (x, y, DH), lines(D2X0, D2X1, 0.3), yr,
                 lambda x, y: (x / TRIM_TILE, y / TRIM_TILE), (0, 0, -1), TR)
    cy0 = YC1 + BT
    cxl = lines(CLO_X0, CLO_X1, 0.1, (D2X0, D2X1))
    cyl = lines(cy0, CLO_Y1, 0.1)
    grid_surface(mb, lambda s, t: (s, t, 0), cxl, cyl, lambda s, t: (s / FLOOR_TILE, t / FLOOR_TILE + 0.2),
                 (0, 0, 1), F)
    grid_surface(mb, lambda s, t: (s, t, CLO_H), cxl, cyl, lambda s, t: (s / CEIL_TILE, t / CEIL_TILE), (0, 0, -1), C)
    wall_panels(mb, lambda s, z: (s, cy0, z), CLO_X0, CLO_X1, 0, CLO_H, [(D2X0, D2X1, 0, DH)], CLO_X1,
                [1, 3, 0, 4], CLO_H, (0, 1, 0), W, u_dir=-1)
    wall_panels(mb, lambda s, z: (s, CLO_Y1, z), CLO_X0, CLO_X1, 0, CLO_H, [], CLO_X0, [2, 0, 4, 1], CLO_H,
                (0, -1, 0), W)
    wall_panels(mb, lambda s, z: (CLO_X0, s, z), cy0, CLO_Y1, 0, CLO_H, [], cy0, [3, 1, 0], CLO_H, (1, 0, 0), W)
    wall_panels(mb, lambda s, z: (CLO_X1, s, z), cy0, CLO_Y1, 0, CLO_H, [], CLO_Y1, [4, 2, 0], CLO_H,
                (-1, 0, 0), W, u_dir=-1)
    shell = mb.obj("Corridor_shell", mats("Wall", "Floor", "Ceiling", "Trim"), weld=1e-4)

    tm = MB()
    base_prof = [(0, 0.19), (0.007, 0.19), (0.012, 0.186), (0.0135, 0.18), (0.0135, 0.172), (0.016, 0.166),
                 (0.02, 0.16), (0.02, 0.022), (0.024, 0.021), (0.029, 0.017), (0.033, 0.01), (0.034, 0.0), (0, 0)]
    PL = 0.105
    sweep(tm, [(DX1 + PL, YC0), (CX1, YC0), (CX1, YC1), (D2X1 + PL, YC1)], base_prof,
          (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), uvs=TRIM_TILE)
    sweep(tm, [(D2X0 - PL, YC1), (CX0, YC1), (CX0, YC0), (DX0 - PL, YC0)], base_prof,
          (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), uvs=TRIM_TILE)
    door_trim(tm, YC1, -1, D2X0, D2X1)
    trims = tm.obj("Corridor_trim", mats("Trim"), recalc=True)
    return join_objs("Corridor", [shell, trims])


# =============================================================================== dirt vertex colours
def hnoise(p, seed=0, scales=(0.9, 0.37, 0.17)):
    r = np.random.default_rng(seed)
    acc = 0.0
    for i, s in enumerate(scales):
        k = r.normal(size=(4, 3)) / s
        ph = r.uniform(0, TAU, 4)
        acc += sum(math.sin(k[j] @ p + ph[j]) for j in range(4)) / (4 * (i + 1))
    return acc


def paint_dirt(ob, box_min, box_max, height, corridor=False):
    """Location-dependent grime as a vertex colour (multiplies base colour): darker towards the floor,
    the corners and the edges of the floor; large blotches that break up texture tiling."""
    me = ob.data
    ca = me.color_attributes.new("Dirt", "BYTE_COLOR", "CORNER")
    mw = ob.matrix_world
    bmin, bmax = np.array(box_min), np.array(box_max)
    mi_floor = [i for i, m in enumerate(me.materials) if m.name == "Floor"]
    mi_ceil = [i for i, m in enumerate(me.materials) if m.name == "Ceiling"]
    cols = np.ones((len(me.loops), 4), dtype=np.float32)
    cache = {}
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            key = (vi, poly.material_index)
            if key in cache:
                cols[li] = cache[key]
                continue
            p = np.array(mw @ me.vertices[vi].co)
            x, y, z = p
            # inside which box? (corridor has a closet too: use the nearest box walls only roughly)
            dx = min(abs(x - bmin[0]), abs(bmax[0] - x))
            dy = min(abs(y - bmin[1]), abs(bmax[1] - y))
            blot = hnoise(p, 3)
            f = 0.9 + 0.1 * blot
            if poly.material_index in mi_floor:
                d = min(dx, dy)
                d2 = max(dx, dy)
                f *= 1 - 0.42 * math.exp(-d / 0.09) - 0.15 * math.exp(-d / 0.45) - 0.25 * math.exp(-d2 / 0.3) * math.exp(-d / 0.3)
                f *= 0.92 + 0.08 * hnoise(p, 5, (0.25, 0.11))
            elif poly.material_index in mi_ceil:
                d = min(dx, dy)
                f *= 1 - 0.3 * math.exp(-d / 0.18)
                f *= 1 - 0.25 * math.exp(-((x - 0.15) ** 2 + (y - 3.0) ** 2) / 0.12)   # soot over the bulb
            else:
                dc = min(math.hypot(dx, dy), 9) if (dx < 0.6 and dy < 0.6) else 9
                f *= 1 - 0.35 * math.exp(-max(z - 0.18, 0) / 0.22) - 0.22 * math.exp(-(height - z) / 0.3)
                f *= 1 - 0.28 * math.exp(-min(dx, dy) / 0.14) * (1.0 if dc < 9 else 0.0)
                f *= 0.93 + 0.07 * hnoise(p, 7, (0.5, 0.2))
            if corridor:
                f *= 0.62 + 0.12 * hnoise(p, 11, (1.3, 0.6))
            f = max(0.2, min(1.0, f))
            c = (f, f * 0.975, f * 0.93, 1.0)
            cache[key] = c
            cols[li] = c
    ca.data.foreach_set("color", cols.ravel())
    me.color_attributes.active_color = ca


# =============================================================================== props
def mobj(mb, name, matnames, recalc=False, smooth_deg=35):
    return mb.obj(name, mats(*matnames), recalc=recalc, smooth_deg=smooth_deg)


def place(ob, loc=(0, 0, 0), rot_z=0.0):
    ob.data.transform(Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot_z, 4, "Z"))
    return ob


def build_bed():
    mb = MB()
    I = 0
    xa, xb = -0.46, 0.46
    yh, yf = 0.98, -0.98       # head (+y) and foot, local
    def post(x, y, h):
        tube(mb, [(x, y, 0.05), (x, y, h)], 0.021, 14, I, IRON_TILE)
        lathe(mb, [(0, h + 0.062), (0.016, h + 0.058), (0.028, h + 0.04), (0.03, h + 0.03), (0.026, h + 0.015),
                   (0.014, h + 0.006), (0.024, h), (0.024, h - 0.012), (0, h - 0.012)], (x, y, 0), 16, I, IRON_TILE)
        lathe(mb, [(0, 0.05), (0.026, 0.05), (0.03, 0.035), (0.026, 0.018), (0.012, 0.004), (0, 0.0)], (x, y, 0), 14, I, IRON_TILE)
        for zc in (0.32, 0.48):
            lathe(mb, [(0, zc + 0.02), (0.024, zc + 0.02), (0.027, zc), (0.024, zc - 0.02), (0, zc - 0.02)], (x, y, 0), 14, I, IRON_TILE)
    # head board
    post(xa, yh, 1.18)
    post(xb, yh, 1.18)
    arch = [(xa + (xb - xa) * t, yh, 1.06 + 0.08 * math.sin(math.pi * t)) for t in np.linspace(0, 1, 17)]
    tube(mb, arch, 0.014, 10, I, IRON_TILE)
    tube(mb, [(xa, yh, 0.48), (xb, yh, 0.48)], 0.012, 10, I, IRON_TILE)
    for t in np.linspace(0, 1, 11)[1:-1]:
        x = xa + (xb - xa) * t
        tube(mb, [(x, yh, 0.48), (x, yh, 1.06 + 0.08 * math.sin(math.pi * t))], 0.0065, 8, I, IRON_TILE)
    lathe(mb, [(0, 0.82), (0.03, 0.82), (0.035, 0.8), (0.03, 0.78), (0, 0.78)], (0, yh, 0), 16, I, IRON_TILE,
          axis_m=Matrix.Rotation(math.pi / 2, 3, "X"))
    # foot board
    post(xa, yf, 0.9)
    post(xb, yf, 0.9)
    tube(mb, [(xa, yf, 0.82), (xb, yf, 0.82)], 0.013, 10, I, IRON_TILE)
    tube(mb, [(xa, yf, 0.48), (xb, yf, 0.48)], 0.012, 10, I, IRON_TILE)
    for t in np.linspace(0, 1, 9)[1:-1]:
        x = xa + (xb - xa) * t
        tube(mb, [(x, yf, 0.48), (x, yf, 0.82)], 0.0065, 8, I, IRON_TILE)
    # side rails (angle iron)
    L = [(0, 0), (0.038, 0), (0.038, 0.004), (0.004, 0.004), (0.004, 0.038), (0, 0.038)]
    for x, s in ((xa + 0.02, 1), (xb - 0.02, -1)):
        prof = [(p * s, q) for p, q in L]
        if s < 0:
            prof = prof[::-1]
        sweep(mb, [(yf + 0.02, x), (yh - 0.02, x)], prof, (0, 0, 0.36), (0, 1, 0), (1, 0, 0), (0, 0, 1),
              uvs=IRON_TILE)
    # spring wire mesh, sagging
    sag = lambda x, y: 0.385 - 0.045 * (1 - (x / 0.44) ** 2) * (1 - (y / 0.95) ** 2)
    for x in np.linspace(xa + 0.05, xb - 0.05, 9):
        tube(mb, [(x, y, sag(x, y)) for y in np.linspace(yf + 0.03, yh - 0.03, 14)], 0.0018, 5, I, IRON_TILE, caps=False)
    for y in np.linspace(yf + 0.05, yh - 0.05, 26):
        tube(mb, [(x, y, sag(x, y) - 0.002) for x in np.linspace(xa + 0.03, xb - 0.03, 8)], 0.0016, 5, I, IRON_TILE, caps=False)
    ob = mobj(mb, "Bed_IronFrame", ["Iron_Painted"], recalc=True, smooth_deg=50)
    place(ob, (-2.07, 3.15, 0), 0)

    # mattress: sagging, pulled askew
    mm = MB()
    def mdef(co):
        x, y, z = co
        z -= 0.05 * (1 - (x / 0.45) ** 2) * (1 - (y / 0.97) ** 2) * (1 if z > -0.07 else 0.7)
        z += 0.012 * math.sin(x * 9 + y * 4) * math.cos(y * 6)
        x *= 1 + 0.02 * (z / 0.075)
        return (x, y, z)
    box(mm, (0.86, 1.88, 0.15), T((0, 0, 0)), 0, bevel=0.045, segs=4, cuts=10, deform=mdef,
        uvscale=(1.0, 2.0), uvoff=(0.07, 0.04), grain=1)
    m = mobj(mm, "Bed_Mattress", ["Mattress"], smooth_deg=60)
    m.data.transform(Matrix.Rotation(math.radians(5), 4, "Y"))
    place(m, (-2.0, 3.12, 0.44), math.radians(4))

    pm = MB()
    def pdef(co):
        x, y, z = co
        nx, ny = x / 0.28, y / 0.19
        k = max(0.0, 1 - nx ** 4) * max(0.0, 1 - ny ** 4)
        return (x, y, z * (0.15 + 0.85 * k) + 0.01 * math.sin(x * 20))
    box(pm, (0.56, 0.38, 0.12), T(), 0, bevel=0.0, cuts=8, deform=pdef, uvscale=(1.0, 2.0), grain=0)
    p = mobj(pm, "Bed_Pillow", ["Mattress"], smooth_deg=80)
    p.data.transform(Matrix.Rotation(math.radians(-12), 4, "X"))
    place(p, (-2.12, 3.82, 0.56), math.radians(-14))
    return [ob, m, p]


def build_chair():
    mb = MB()
    Wd = 0
    # local: front -y, back +y
    box(mb, (0.42, 0.40, 0.028), T((0, 0, 0.445)), Wd, bevel=0.007, segs=3, uvs=WOOD_TILE)
    legs = [(-0.18, -0.165), (0.18, -0.165)]
    for x, y in legs:
        tube(mb, [(x * 1.06, y * 1.08, 0.0), (x, y, 0.432)], [0.0125, 0.0165], 10, Wd, WOOD_TILE)
    for x in (-0.175, 0.175):
        pts = [(x * 1.04, 0.175, 0.0), (x, 0.165, 0.44), (x * 0.97, 0.2, 0.7), (x * 0.95, 0.235, 0.94)]
        tube(mb, pts, [0.0135, 0.017, 0.016, 0.014], 10, Wd, WOOD_TILE)
        lathe(mb, [(0, 0.965), (0.012, 0.962), (0.017, 0.95), (0.014, 0.937), (0, 0.935)],
              (x * 0.95, 0.235, 0), 12, Wd, WOOD_TILE)
    # stretchers (one side broken)
    tube(mb, [(-0.185, -0.17, 0.16), (0.185, -0.17, 0.16)], 0.009, 8, Wd, WOOD_TILE)
    tube(mb, [(-0.18, 0.172, 0.18), (0.18, 0.172, 0.18)], 0.009, 8, Wd, WOOD_TILE)
    tube(mb, [(-0.186, -0.17, 0.21), (-0.183, 0.172, 0.21)], 0.009, 8, Wd, WOOD_TILE)
    tube(mb, [(0.186, -0.17, 0.21), (0.186, -0.03, 0.212)], 0.009, 8, Wd, WOOD_TILE)
    tube(mb, [(0.183, 0.172, 0.21), (0.184, 0.06, 0.205), (0.19, 0.035, 0.17)], 0.009, 8, Wd, WOOD_TILE)
    # back slats, bent
    for zc, hgt in ((0.62, 0.045), (0.75, 0.045), (0.885, 0.075)):
        y = 0.2 + (zc - 0.62) * 0.13
        def bend(co, y=y):
            x, yy, z = co
            return (x, yy + y + 0.03 * (1 - (x / 0.17) ** 2), z)
        box(mb, (0.34, 0.016, hgt), T((0, 0, zc)), Wd, bevel=0.004, segs=2, cuts=4, deform=bend, uvs=WOOD_TILE, grain=0)
    ob = mobj(mb, "Chair_FacingWall", ["Wood_Old"], smooth_deg=40)
    place(ob, (1.18, 3.42, 0), math.radians(180 + 13))
    return [ob]


def build_dresser():
    mb = MB()
    Wd, Br = 0, 1
    w, d = 0.86, 0.45
    def b(size, loc, **k):
        box(mb, size, T(loc), Wd, uvs=WOOD_TILE, **k)
    b((0.02, d, 0.77), (-w / 2 + 0.01, 0, 0.08 + 0.385), bevel=0.003)
    b((0.02, d, 0.77), (w / 2 - 0.01, 0, 0.08 + 0.385), bevel=0.003)
    b((w - 0.04, 0.008, 0.77), (0, d / 2 - 0.004, 0.465), bevel=0.0)
    b((w + 0.03, d + 0.025, 0.026), (0, -0.0125, 0.863), bevel=0.009, segs=3)
    b((w - 0.02, d - 0.04, 0.07), (0, -0.0, 0.035), bevel=0.003)                    # plinth (recessed)
    b((w + 0.01, 0.025, 0.02), (0, -d / 2 + 0.005, 0.085), bevel=0.005, segs=3)     # base moulding
    for z in (0.335, 0.555, 0.775):                                                 # rails between drawers
        b((w - 0.04, 0.02, 0.02), (0, -d / 2 + 0.01, z), bevel=0.002)
    b((w - 0.04, 0.02, 0.05), (0, -d / 2 + 0.01, 0.825), bevel=0.002)
    drawers = [(0.095, 0.33, 0.0), (0.345, 0.55, 0.23), (0.565, 0.77, 0.0)]
    for i, (z0, z1, pull) in enumerate(drawers):
        hz = z1 - z0 - 0.006
        zc = 0.5 * (z0 + z1)
        yfront = -d / 2 - 0.012 - pull
        b((w - 0.05, 0.022, hz), (0, yfront, zc), bevel=0.004, segs=2)
        b((w - 0.12, 0.006, hz - 0.06), (0, yfront - 0.011, zc), bevel=0.006, segs=2)  # raised panel
        if pull > 0:
            dz = hz - 0.04
            b((0.012, d - 0.06, dz), (-w / 2 + 0.05, yfront + (d - 0.06) / 2, z0 + 0.01 + dz / 2), bevel=0.002)
            b((0.012, d - 0.06, dz), (w / 2 - 0.05, yfront + (d - 0.06) / 2, z0 + 0.01 + dz / 2), bevel=0.002)
            b((w - 0.11, 0.012, dz), (0, yfront + d - 0.06, z0 + 0.01 + dz / 2), bevel=0.002)
            b((w - 0.11, d - 0.06, 0.008), (0, yfront + (d - 0.06) / 2, z0 + 0.012), bevel=0.0)
        for xk in (-0.22, 0.22):
            if i == 2 and xk > 0:
                tube(mb, [(xk, yfront - 0.011, zc), (xk, yfront - 0.016, zc)], 0.003, 6, Br, 0.2)
                continue
            lathe(mb, [(0, -0.034), (0.017, -0.032), (0.019, -0.026), (0.016, -0.02), (0.008, -0.014),
                       (0.009, -0.0), (0, 0.0)], (xk, yfront - 0.011, zc), 14, Br, 0.2,
                  axis_m=Matrix.Rotation(-math.pi / 2, 3, "X"))
    ob = mobj(mb, "Dresser", ["Wood_Old", "Brass"])
    place(ob, (0.58, Y1 - d / 2 - 0.015, 0), 0)
    return [ob]


def build_radiator():
    mb = MB()
    I = 0
    n = 11
    sp = 0.07
    L = (n - 1) * sp
    for i in range(n):
        x = -L / 2 + i * sp
        foot = i in (0, n - 1)
        for yc in (-0.05, 0.0, 0.05):
            z0 = 0.0 if foot and yc != 0.0 else 0.13
            tube(mb, [(x, yc, z0), (x, yc, 0.69)], 0.0165, 10, I, IRON_TILE)
            lathe(mb, [(0, 0.712), (0.012, 0.708), (0.0165, 0.69), (0, 0.69)], (x, yc, 0), 10, I, IRON_TILE)
        for zc in (0.155, 0.655):
            box(mb, (0.052, 0.14, 0.05), T((x, 0, zc)), I, bevel=0.012, segs=2, uvs=IRON_TILE, grain=1)
        box(mb, (0.006, 0.1, 0.44), T((x, 0, 0.405)), I, bevel=0.002, uvs=IRON_TILE, grain=2)
    for zc in (0.155, 0.655):
        tube(mb, [(-L / 2, 0, zc), (L / 2, 0, zc)], 0.019, 10, I, IRON_TILE)
    # supply pipe + valve from the floor
    xp = -L / 2 - 0.09
    tube(mb, [(xp, 0.02, 0.0), (xp, 0.02, 0.12), (xp + 0.02, 0.02, 0.15), (-L / 2 - 0.02, 0.0, 0.155)],
         0.0135, 10, I, IRON_TILE)
    lathe(mb, [(0, 0.12), (0.022, 0.12), (0.026, 0.1), (0.022, 0.07), (0, 0.07)], (xp, 0.02, 0), 14, I, IRON_TILE)
    tube(mb, [(xp, 0.02, 0.12), (xp, 0.02, 0.2)], 0.005, 8, I, IRON_TILE)
    ring = [(xp + 0.035 * math.cos(a), 0.02 + 0.035 * math.sin(a), 0.2) for a in np.linspace(0, TAU, 20)]
    tube(mb, ring, 0.0045, 6, I, IRON_TILE)
    for a in (0, TAU / 3, 2 * TAU / 3):
        tube(mb, [(xp, 0.02, 0.2), (xp + 0.035 * math.cos(a), 0.02 + 0.035 * math.sin(a), 0.2)], 0.003, 6, I, IRON_TILE)
    ob = mobj(mb, "Radiator", ["Iron_Painted"], recalc=True, smooth_deg=45)
    place(ob, (1.96, Y1 - 0.115, 0), 0)
    return [ob]


def build_bulb():
    mb = MB()
    Pl, Co, Bk, Br, Gl, Fi = range(6)
    cx, cy = 0.15, 3.0
    prof = [(0, H), (0.15, H), (0.15, H - 0.008), (0.142, H - 0.012), (0.135, H - 0.01), (0.12, H - 0.016),
            (0.1, H - 0.02), (0.085, H - 0.018), (0.07, H - 0.024), (0.05, H - 0.03), (0.03, H - 0.034),
            (0.012, H - 0.042), (0, H - 0.042)]
    lathe(mb, prof, (cx, cy, 0), 40, Pl, 0.5)
    ztop = H - 0.04
    zh = 2.06
    cord = [(cx + 0.006 * math.sin(t * 5) * t, cy + 0.004 * math.sin(t * 3.0), ztop - (ztop - zh) * t)
            for t in np.linspace(0, 1, 18)]
    tube(mb, cord, 0.0036, 8, Co, 0.1)
    lathe(mb, [(0, zh + 0.002), (0.008, zh + 0.002), (0.012, zh - 0.006), (0.016, zh - 0.012), (0.018, zh - 0.02),
               (0.0185, zh - 0.05), (0.017, zh - 0.052), (0.0175, zh - 0.06), (0, zh - 0.06)],
          (cx, cy, 0), 20, Bk, 0.2)
    zb = zh - 0.06
    lathe(mb, [(0, zb), (0.0135, zb), (0.0135, zb - 0.02), (0, zb - 0.02)], (cx, cy, 0), 20, Br, 0.2)
    zg = zb - 0.02
    gp = [(0.0125, zg), (0.014, zg - 0.008), (0.022, zg - 0.03), (0.03, zg - 0.055), (0.0315, zg - 0.07),
          (0.029, zg - 0.088), (0.021, zg - 0.102), (0.01, zg - 0.109), (0, zg - 0.11)]
    lathe(mb, gp, (cx, cy, 0), 28, Gl, 0.2)
    lathe(mb, [(0.004, zg), (0.004, zg - 0.04), (0, zg - 0.045)], (cx, cy, 0), 8, Gl, 0.2)
    for s in (-1, 1):
        tube(mb, [(cx + s * 0.002, cy, zg - 0.04), (cx + s * 0.009, cy, zg - 0.068)], 0.0005, 4, Fi, 0.1)
    zig = [(cx - 0.009 + 0.018 * t, cy + 0.002 * math.sin(t * 40), zg - 0.068 - 0.003 * math.sin(t * math.pi))
           for t in np.linspace(0, 1, 30)]
    tube(mb, zig, 0.0007, 4, Fi, 0.1)
    ob = mobj(mb, "Bulb_Hanging", ["Plaster", "Cord_Fabric", "Bakelite", "Brass", "Glass_Bulb", "Filament"],
              recalc=True, smooth_deg=50)
    return [ob]


def paper_sheets(name, specs, seed):
    """specs: list of (x, y, z, rot, curl, tilt)"""
    rng = np.random.default_rng(seed)
    mb = MB()
    for x, y, z, rot, curl, tilt in specs:
        sc = rng.uniform(0.7, 1.0)
        w, h = 0.21 * sc, 0.297 * rng.uniform(0.6, 1.0) * sc
        nu, nv = 6, 8
        flip = rng.random() < 0.5
        idx = {}
        lift = rng.uniform(0, 0.012)
        corner = rng.integers(0, 4)
        def P(i, j):
            u, v = i / nu, j / nv
            lx, ly = (u - 0.5) * w, (v - 0.5) * h
            lz = curl * (2 * u - 1) ** 2 + 0.002 * (1 + math.sin(v * 7 + u * 3)) * rng.uniform(0.5, 1)
            cu, cv = (u, v) if corner == 0 else (1 - u, v) if corner == 1 else (u, 1 - v) if corner == 2 else (1 - u, 1 - v)
            lz += lift * max(0, cu + cv - 1.2) ** 2 * 8
            pt = Matrix.Rotation(tilt, 3, "X") @ Vector((lx, ly, lz))
            return Matrix.Rotation(rot, 3, "Z") @ pt + Vector((x, y, z + 0.0015))
        verts = {}
        for i in range(nu + 1):
            for j in range(nv + 1):
                verts[(i, j)] = P(i, j)
        for side in (0, 1):
            ids = {}
            for k, p in verts.items():
                ids[k] = mb.v(p - Vector((0, 0, 0.0004)) * side)
            for i in range(nu):
                for j in range(nv):
                    q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                    uv = [((a / nu) if not flip else 1 - a / nu, b / nv) for a, b in q]
                    if side:
                        q, uv = q[::-1], uv[::-1]
                    mb.f([ids[k] for k in q], uv, 0)
    return mobj(mb, name, ["Paper"], smooth_deg=60)


def build_papers():
    s = []
    rng = np.random.default_rng(5)
    for x, y in ((0.45, 3.42), (0.75, 3.55), (0.2, 3.25), (0.95, 3.2), (-0.35, 3.75), (-0.6, 3.55),
                 (-1.25, 3.3), (-1.45, 3.05), (0.5, 3.0), (1.5, 3.05), (-0.1, 3.05)):
        s.append((x + rng.normal(0, 0.03), y + rng.normal(0, 0.03), 0.0, rng.uniform(0, TAU),
                  rng.uniform(0.0, 0.012), 0.0))
    s.append((-1.95, 2.85, 0.56, 0.4, 0.01, 0.06))           # on the mattress
    s.append((0.62, Y1 - 0.24 - 0.23, 0.36, 0.2, 0.004, 0))    # in the open drawer
    s.append((0.45, Y1 - 0.24 - 0.18, 0.37, -0.5, 0.006, 0))
    s.append((0.75, 3.95, 0.878, 1.2, 0.006, 0))               # on top of the dresser
    papers = paper_sheets("Papers_Scattered", s, 9)
    c = []
    for x, y in ((-0.5, 4.6), (-0.8, 4.85), (-0.25, 5.2), (0.6, 4.9), (-1.6, 5.3), (1.4, 5.0)):
        c.append((x + rng.normal(0, 0.04), y, 0.0, rng.uniform(0, TAU), rng.uniform(0, 0.015), 0.0))
    cpapers = paper_sheets("Corridor_Papers", c, 13)
    return [papers, cpapers]


def build_frame():
    mb = MB()
    Wd, Bk, Gl, Ir = 0, 1, 2, 3
    w, h = 0.40, 0.50
    prof = [(0, 0), (0, 0.016), (0.008, 0.022), (0.02, 0.024), (0.03, 0.02), (0.04, 0.012), (0.045, 0.012),
            (0.045, 0.0), (0.012, 0.0), (0.012, 0.006), (0.006, 0.006), (0.006, 0)][::-1]
    path = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    sweep(mb, path, prof, (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, -1), closed=True, uvs=WOOD_TILE)
    box(mb, (w - 0.07, h - 0.07, 0.004), T((0, 0, 0.002)), Bk, bevel=0.0, uvs=0.5)
    box(mb, (w - 0.075, h - 0.075, 0.002), T((0, 0, -0.002)), Gl, bevel=0.0, uvs=0.5)
    tube(mb, [(-0.14, 0.12, 0.006), (-0.05, 0.16, 0.008), (0.05, 0.16, 0.008), (0.14, 0.12, 0.006)], 0.0008, 4, Ir, 0.1)
    ob = mobj(mb, "Picture_Frame_Fallen", ["Wood_Old", "Paper_Backing", "Glass_Bulb", "Iron_Painted"], recalc=True)
    # lying face down: local -z is the front -> rotate so the back faces up, then a slight tilt on a shard
    ob.data.transform(Matrix.Translation((0, 0, 0.0245)) @ Matrix.Rotation(math.radians(2.5), 4, "X"))
    place(ob, (0.36, 3.44, 0), math.radians(24))
    # glass shards on the floor
    sm = MB()
    rng = np.random.default_rng(3)
    for _ in range(9):
        cx, cy = 0.36 + rng.normal(0, 0.18), 3.44 + rng.normal(0, 0.14)
        a0 = rng.uniform(0, TAU)
        r = rng.uniform(0.012, 0.05)
        pts = [(cx + r * math.cos(a0 + k * 2.1 + rng.normal(0, 0.3)), cy + r * math.sin(a0 + k * 2.1 + rng.normal(0, 0.3)))
               for k in range(3)]
        top = [sm.v((x, y, 0.0022)) for x, y in pts]
        bot = [sm.v((x, y, 0.0002)) for x, y in pts]
        uv = [(0, 0), (1, 0), (0, 1)]
        sm.f(top, uv)
        sm.f(bot[::-1], uv[::-1])
        for k in range(3):
            k2 = (k + 1) % 3
            sm.f([bot[k], bot[k2], top[k2], top[k]], [(0, 0), (1, 0), (1, 1), (0, 1)])
    shards = mobj(sm, "Glass_Shards", ["Glass_Shard"], recalc=True, smooth_deg=10)
    # the nail it hung from
    nm = MB()
    tube(nm, [(0.58, Y1 + 0.005, 1.62), (0.58, Y1 - 0.022, 1.625)], 0.0016, 6, 0, 0.1)
    lathe(nm, [(0, 0.0), (0.004, 0.0), (0.004, -0.0015), (0, -0.0015)], (0.58, Y1 - 0.022, 1.625), 10, 0, 0.1,
          axis_m=Matrix.Rotation(math.pi / 2, 3, "X"))
    nail = mobj(nm, "Wall_Nail", ["Iron_Painted"], recalc=True)
    return [ob, shards, nail]


def build_switch_outlet():
    out = []
    mb = MB()
    Bk, Br = 0, 1
    x, z = 0.2, 1.24
    box(mb, (0.072, 0.008, 0.115), T((x, Y1 - 0.004, z)), Bk, bevel=0.003, segs=3, uvs=0.2)
    box(mb, (0.022, 0.012, 0.032), T((x, Y1 - 0.012, z)), Bk, bevel=0.004, segs=2, uvs=0.2)
    tube(mb, [(x, Y1 - 0.016, z), (x, Y1 - 0.032, z + 0.008)], [0.0045, 0.0035], 10, Bk, 0.2)
    for dz in (-0.042, 0.042):
        lathe(mb, [(0, 0.0015), (0.003, 0.001), (0.0035, 0), (0, 0)], (x, Y1 - 0.0085, z + dz), 10, Br, 0.1,
              axis_m=Matrix.Rotation(math.pi / 2, 3, "X"))
    out.append(mobj(mb, "Wall_Switch", ["Bakelite", "Brass"], recalc=True))
    mb = MB()
    for (x, z, nm) in ((1.3, 0.33, "Wall_Outlet"),):
        lathe(mb, [(0, 0.016), (0.03, 0.016), (0.036, 0.012), (0.038, 0.004), (0.038, 0), (0, 0)], (x, Y1, z), 28,
              Bk, 0.2, axis_m=Matrix.Rotation(math.pi / 2, 3, "X"))
        for dx in (-0.0095, 0.0095):
            lathe(mb, [(0, 0.0165), (0.0032, 0.0165), (0.0032, 0.010), (0, 0.010)], (x + dx, Y1, z), 10, Br, 0.1,
                  axis_m=Matrix.Rotation(math.pi / 2, 3, "X"))
    out.append(mobj(mb, "Wall_Outlet", ["Bakelite", "Brass"], recalc=True))
    return out


def build_hinges():
    mb = MB()
    for zc in (0.26, 1.78):
        box(mb, (0.0025, 0.032, 0.089), T((DX0 + 0.00125, Y1 + 0.018, zc)), 0, bevel=0.0008, segs=1, uvs=IRON_TILE)
        for dz in (-0.0297, 0.0297):
            tube(mb, [(DX0 + 0.004, Y1 - 0.001, zc + dz - 0.0145), (DX0 + 0.004, Y1 - 0.001, zc + dz + 0.0145)],
                 0.0055, 10, 0, IRON_TILE)
        for dz in (-0.03, 0.0, 0.03):
            lathe(mb, [(0, 0.0012), (0.0035, 0.0008), (0.004, 0), (0, 0)], (DX0 + 0.0025, Y1 + 0.019, zc + dz), 8,
                  0, 0.1, axis_m=Matrix.Rotation(math.pi / 2, 3, "Y"))
    return [mobj(mb, "Door_Hinges", ["Iron_Painted"], recalc=True)]


def build_cobwebs():
    out = []

    def web(name, corners, sag_dir, sag=0.03, uvrot=0):
        mb = MB()
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
                mb.f([idx[k] for k in q], [((a / n), (b / n)) for a, b in q])
        out.append(mobj(mb, name, ["Cobweb"], smooth_deg=89))

    e = 0.004
    web("Cobweb_CornerBackLeft", [(X0 + e, Y1 - 0.62, H - 0.6), (X0 + 0.62, Y1 - e, H - 0.6),
                                  (X0 + 0.7, Y1 - e, H - e), (X0 + e, Y1 - 0.7, H - e)], (0.5, -0.5, -0.3), 0.06)
    web("Cobweb_CornerBackRight", [(X1 - 0.5, Y1 - e, H - 0.45), (X1 - e, Y1 - 0.5, H - 0.45),
                                   (X1 - e, Y1 - 0.55, H - e), (X1 - 0.55, Y1 - e, H - e)], (-0.5, -0.5, -0.3), 0.05)
    yw = Y1 + 0.09
    web("Cobweb_Doorway", [(DX0 + e, yw, DH - 0.42), (DX0 + 0.45, yw, DH - 0.42), (DX0 + 0.45, yw, DH - e),
                           (DX0 + e, yw, DH - e)], (0, 1, 0), 0.03)
    return out


def build_peel_strips():
    """Peeled wallpaper strips hanging from the attach line of roll 3 (texture tears match)."""
    mb = MB()
    Fr, Bk = 0, 1
    rng = np.random.default_rng(17)

    def strip(x0, x1, za, length, origin_u, P, nrm_out, side_sign):
        """Paper peeled from the top: it leaves the wall at za, folds outward and hangs down,
        showing its backing.  Per-column lengths give a torn, tapered free end."""
        nu, ns = 10, 30
        lens = np.convolve(rng.uniform(0.55, 1.0, nu + 5), np.ones(3) / 3, mode="valid")[:nu + 1] * length
        lens *= 1 - 0.35 * np.abs(np.linspace(-1, 1, nu + 1)) ** 3
        curl_end = rng.uniform(0.8, 1.5)

        def theta(s, L):
            if s < 0.09:
                return math.pi * s / 0.09
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
        for side in (0, 1):
            ids = {}
            for i in range(nu + 1):
                t = i / nu
                ss_, pts = cols[i]
                for j in range(ns + 1):
                    n_off, dz = pts[j]
                    f = j / ns
                    taper = 0.06 * f ** 2 * (2 * t - 1)
                    s_world = x0 + (x1 - x0) * (0.02 + 0.92 * t) - taper * (x1 - x0)
                    sway = 0.025 * f ** 2 * math.sin(t * 3.0 + 1.0)
                    p = P(s_world, za + dz, n_off + 0.002 + sway + side * 0.0006)
                    ids[(i, j)] = mb.v(p)
            for i in range(nu):
                for j in range(ns):
                    q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                    if side == 0:
                        uv = [((origin_u + (x1 - x0) * (0.02 + 0.92 * a / nu)) / WALL_TILE,
                               (za + cols[a][0][b]) / H) for a, b in q]
                        mat = Fr
                    else:
                        q = q[::-1]
                        uv = [((a / nu) * (x1 - x0) / 0.5, cols[a][0][b] / 0.5) for a, b in q]
                        mat = Bk
                    mb.f([ids[k] for k in q], uv, mat)

    # back wall: columns start at X0 every 0.5 m; roll 3 sits in columns 1 and 8 (see build_room)
    Pb = lambda s, z, n: (s, Y1 - n, z)
    strip(X0 + 0.5, X0 + 1.0, 2.0, 0.74, 0.03 + 3 * ROLL, Pb, (0, -1, 0), 1)
    strip(X0 + 4.0, X0 + 4.32, 2.0, 0.6, 0.03 + 3 * ROLL, Pb, (0, -1, 0), 1)
    ob = mobj(mb, "Wallpaper_Peel", ["Wallpaper_Strip", "Paper_Backing"], recalc=False, smooth_deg=70)
    return [ob]


def chunk(mb, center, size, rng, mat=0, uvs=0.5):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    sx, sy, sz = size
    for v in bm.verts:
        d = 1 + rng.normal(0, 0.18)
        v.co = Vector((v.co.x * sx * d, v.co.y * sy * d, max(v.co.z, -0.35) * sz * d))
    bm.normal_update()
    rot = Matrix.Rotation(rng.uniform(0, TAU), 3, "Z")
    vm = {v: mb.v(rot @ v.co + Vector(center)) for v in bm.verts}
    for f in bm.faces:
        mb.f([vm[l.vert] for l in f.loops], [(l.vert.co.x / uvs + 0.3, l.vert.co.y / uvs + l.vert.co.z / uvs)
                                              for l in f.loops], mat)
    bm.free()


def build_debris():
    out = []
    rng = np.random.default_rng(23)
    mb = MB()
    # under the big lath tear left of the doorway (column x in [-2.1+0.5.. ] -> roll 1 at x -1.6..-1.1)
    for _ in range(22):
        x = rng.uniform(-1.55, -1.12)
        y = Y1 - abs(rng.normal(0, 0.12)) - 0.04
        s = rng.uniform(0.006, 0.035)
        chunk(mb, (x, y, s * 0.3), (s, s * rng.uniform(0.6, 1), s * rng.uniform(0.3, 0.6)), rng)
    for _ in range(40):
        x = rng.uniform(-1.6, -1.05)
        y = Y1 - abs(rng.normal(0, 0.2)) - 0.03
        s = rng.uniform(0.002, 0.008)
        chunk(mb, (x, y, s * 0.3), (s, s, s * 0.5), rng)
    for x, y, a in ((-1.4, 3.98, 0.4), (-1.22, 4.06, -0.2)):
        box(mb, (0.24, 0.036, 0.008), T((x, y, 0.004 + 0.004), (0, 0, a)), 1, bevel=0.0015, segs=1, uvs=WOOD_TILE)
    out.append(mobj(mb, "Debris_Plaster", ["Plaster", "Wood_Old"], smooth_deg=40))
    mb = MB()
    for _ in range(30):
        x = rng.uniform(-1.6, 0.8)
        y = YC1 - abs(rng.normal(0, 0.18)) - 0.05
        s = rng.uniform(0.008, 0.05)
        chunk(mb, (x, y, s * 0.3), (s, s * rng.uniform(0.6, 1), s * rng.uniform(0.3, 0.6)), rng)
    for _ in range(4):
        box(mb, (rng.uniform(0.3, 0.9), 0.036, 0.008),
            T((rng.uniform(-1.4, 0.6), rng.uniform(4.6, 5.5), 0.008), (0, 0, rng.uniform(-0.5, 0.5))), 1,
            bevel=0.0015, segs=1, uvs=WOOD_TILE)
    out.append(mobj(mb, "Corridor_Debris", ["Plaster", "Wood_Old"], smooth_deg=40))
    # plank leaning against the corridor far wall (visible through the doorway)
    mb = MB()
    ang = math.atan2(1.48, 0.42)
    box(mb, (0.19, 0.024, 1.56), T((0, 0, 0)), 0, bevel=0.004, segs=2, uvs=WOOD_TILE, grain=2)
    pl = mobj(mb, "Corridor_Plank", ["Wood_Old"])
    pl.data.transform(Matrix.Translation((-0.82, YC1 - 0.21 - 0.014, 0.74)) @ Matrix.Rotation(-(math.pi / 2 - ang), 4, "X")
                      @ Matrix.Rotation(math.radians(4), 4, "Y"))
    out.append(pl)
    # enamel bucket
    mb = MB()
    lathe(mb, [(0, 0.005), (0.10, 0.005), (0.104, 0.0), (0.11, 0.008), (0.135, 0.27), (0.142, 0.272),
               (0.142, 0.28), (0.13, 0.28), (0.124, 0.272), (0.1, 0.012), (0, 0.012)], (0, 0, 0), 32, 0, IRON_TILE)
    hp = [(0.14 * math.cos(a), 0.0, 0.27 + 0.14 * math.sin(a) * 0.9) for a in np.linspace(0, math.pi, 16)]
    tube(mb, [(x, y, z) for x, y, z in hp], 0.0025, 6, 0, IRON_TILE)
    bk = mobj(mb, "Corridor_Bucket", ["Iron_Painted"], recalc=True)
    bk.data.transform(Matrix.Rotation(math.radians(70), 4, "Z") @ Matrix.Rotation(math.radians(-9), 4, "X"))
    place(bk, (-0.38, 5.42, 0.012), 0)
    out.append(bk)
    return out


def build_decals():
    mb = MB()
    def quad(c, ux, uy, w, h, uv0, uv1):
        c, ux, uy = Vector(c), Vector(ux), Vector(uy)
        ps = [c - ux * w / 2 - uy * h / 2, c + ux * w / 2 - uy * h / 2, c + ux * w / 2 + uy * h / 2,
              c - ux * w / 2 + uy * h / 2]
        ids = [mb.v(p) for p in ps]
        mb.f(ids, [(uv0[0], uv0[1]), (uv1[0], uv0[1]), (uv1[0], uv1[1]), (uv0[0], uv1[1])])
    e = 0.0015
    quad((0.58, Y1 - e, 1.42), (1, 0, 0), (0, 0, 1), 0.62, 0.74, (0, 0), (0.5, 0.5))          # frame ghost
    quad((0.08, Y1 - e, 1.12), (1, 0, 0), (0, 0, 1), 0.22, 0.28, (0.5, 0), (1, 0.5))          # handprint
    quad((-0.42, YC1 - e, 1.2), (1, 0, 0), (0, 0, 1), 0.4, 0.42, (0, 0.5), (0.5, 1))          # corridor
    quad((-1.25, 3.25, e), (1, 0, 0), (0, 1, 0), 0.9, 0.7, (0.5, 0.5), (1, 1))                 # floor grime
    quad((1.6, 3.7, e), (0.8, 0.6, 0), (-0.6, 0.8, 0), 0.7, 0.6, (0.5, 0.5), (1, 1))
    return [mobj(mb, "Decals", ["Decal_Grime"], smooth_deg=10)]


# =============================================================================== AO bake
def bake_ao(objs, hide):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if _enable_gpu() else "CPU"
    scene.cycles.samples = 192
    scene.cycles.use_denoising = False
    world = bpy.data.worlds.new("BakeWorld")
    scene.world = world
    world.light_settings.distance = 0.55
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
    bpy.ops.uv.pack_islands(rotate=True, margin_method="FRACTION", margin=0.0025, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[ao] lightmap uv {time.time() - t0:.1f}s")
    t0 = time.time()
    bpy.ops.object.bake(type="AO", margin=6, margin_type="EXTEND", use_clear=True, target="IMAGE_TEXTURES")
    print(f"[ao] bake {time.time() - t0:.1f}s")
    for o in hide:
        o.hide_render = False
    for o in objs:
        o.data.uv_layers.active = o.data.uv_layers["UVMap"]
    a = np.array(AO_IMAGE.pixels[:], dtype=np.float32).reshape(2048, 2048, 4)[..., 0]
    a = RT.blur(a.astype(np.float64), 0.7)
    a = np.clip(a, 0, 1) ** 1.15
    path = os.path.join(TEXDIR, "Room_AO.jpg")
    save_img(a, path, 92)
    img = load_img(path, "Room_AO_baked", True)
    for m in bpy.data.materials:
        if m.node_tree and "AO" in m.node_tree.nodes:
            m.node_tree.nodes["AO"].image = img


# =============================================================================== preview renders
def blender_from_gltf(p):
    x, y, z = p
    return Vector((x, -z, y))


CAM = blender_from_gltf((0.25, 1.58, 0.35))
LOOK = blender_from_gltf((-0.2, 1.25, -4.2))


def setup_camera(aspect=(1600, 1000)):
    scene = bpy.context.scene
    cd = bpy.data.cameras.new("PreviewCam")
    cd.sensor_fit = "VERTICAL"
    cd.angle_y = math.radians(50)
    cd.clip_start = 0.05
    cam = link(bpy.data.objects.new("PreviewCam", cd))
    cam.location = CAM
    cam.rotation_euler = (LOOK - CAM).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = aspect
    return cam


def render(path, aim=None, world_strength=0.0, power=60.0, samples=96, offset=(0.12, 0, -0.1)):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if _enable_gpu() else "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    w = bpy.data.worlds.get("PrevWorld") or bpy.data.worlds.new("PrevWorld")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.6, 0.62, 0.66, 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = world_strength
    scene.world = w
    old = bpy.data.objects.get("Flashlight")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    if aim is not None:
        ld = bpy.data.lights.new("Flashlight", "SPOT")
        ld.energy = power
        ld.spot_size = math.radians(35)
        ld.spot_blend = 0.55
        ld.color = (1.0, 0.9, 0.76)
        ld.shadow_soft_size = 0.015
        lo = link(bpy.data.objects.new("Flashlight", ld))
        cam = scene.camera
        r = cam.matrix_world.to_3x3()
        lo.location = CAM + r @ Vector(offset)
        lo.rotation_euler = (Vector(aim) - lo.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("[preview]", path)


# =============================================================================== main
def main():
    t_start = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_materials()
    room = build_room()
    paint_dirt(room, (X0, Y0, 0), (X1, Y1, H), H)
    corr = build_corridor()
    paint_dirt(corr, (CX0, YC0, 0), (CX1, YC1, CH), CH, corridor=True)
    props = []
    props += build_bed()
    props += build_chair()
    props += build_dresser()
    props += build_radiator()
    props += build_bulb()
    props += build_papers()
    props += build_frame()
    props += build_switch_outlet()
    props += build_hinges()
    props += build_peel_strips()
    props += build_debris()
    alpha_objs = build_cobwebs() + build_decals()
    bake_objs = [room, corr] + props
    bake_ao(bake_objs, alpha_objs)
    for o in alpha_objs:   # keep a consistent 2-UV layout (unused) so every primitive looks alike
        o.data.uv_layers.new(name="AO")
        o.data.uv_layers.active = o.data.uv_layers["UVMap"]

    emp = bpy.data.objects.new("Empty_FlashlightTarget_Default", None)
    emp.empty_display_type = "SPHERE"
    emp.empty_display_size = 0.1
    emp.location = (-1.25, Y1, 1.38)
    link(emp)

    allobjs = [room, corr] + props + alpha_objs + [emp]
    os.makedirs(MODELS, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in allobjs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=OUT, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
        export_texcoords=True, export_normals=True, export_materials="EXPORT", export_image_format="AUTO",
        export_cameras=False, export_lights=False, export_animations=False, export_skins=False,
        export_morph=False, export_vertex_color="MATERIAL",
        export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
        export_draco_position_quantization=14, export_draco_normal_quantization=10,
        export_draco_texcoord_quantization=12, export_draco_color_quantization=8)
    print(f"[export] {OUT}: {os.path.getsize(OUT) / 1e6:.2f} MB  ({time.time() - t_start:.0f}s)")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(TEXDIR, "room_build.blend"))

    if PREVIEW:
        previews()


def previews(only=None):
    setup_camera()
    target = bpy.data.objects["Empty_FlashlightTarget_Default"].location.copy()
    pv = lambda n: os.path.join(HERE, f"room_preview_{n}.png")
    shots = [
        ("overview", None),
        ("flash_default", target),
        ("flash_doorway", blender_from_gltf((-0.55, 1.1, -5.4))),
        ("flash_leftwall", Vector((-2.2, 3.4, 0.9))),
        ("flash_floor", Vector((0.3, 3.2, 0.0))),
        ("flash_right", Vector((1.6, 3.9, 0.9))),
    ]
    for name, aim in shots:
        if only and name not in only:
            continue
        if aim is None:
            # low, even fill to judge the layout: a dim ceiling softbox + a fill from the camera
            for nm, loc, size, pw in (("FillTop", (0, 1.8, H - 0.05), 4.0, 120.0), ("FillCorr", (-0.5, 5.0, CH - 0.05), 3.0, 40.0)):
                ld = bpy.data.lights.new(nm, "AREA")
                ld.size = size
                ld.energy = pw
                lo = link(bpy.data.objects.new(nm, ld))
                lo.location = loc
            render(pv(name), None, samples=64)
            for nm in ("FillTop", "FillCorr"):
                bpy.data.objects.remove(bpy.data.objects[nm], do_unlink=True)
        else:
            render(pv(name), aim, power=FLASH_W)


FLASH_W = 450.0

if "--preview-only" in ARGS:
    bpy.ops.wm.open_mainfile(filepath=os.path.join(TEXDIR, "room_build.blend"))
    only = [a for a in ARGS if not a.startswith("--")]
    previews(only or None)
else:
    main()
