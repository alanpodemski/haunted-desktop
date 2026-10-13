"""Extra procedural PBR textures for the v2 hallway (numpy only, no downloads).

Same conventions as room_tex.py (row 0 = bottom / V = 0, heights in millimetres):
    base (H, W, 3) sRGB, normal (H, W, 3) OpenGL, rough (H, W), optional metal / alpha / emit.
"""
import math

import numpy as np

from room_tex import (TAU, blob_field, blur, col, draw_strokes, grid, height_to_normal, lerp,
                      random_walk, spectral, ss, tint, wood_grain, wrapd)


def flat_normal(shape):
    return np.broadcast_to(col(0.5, 0.5, 1.0), (*shape, 3)).copy()


# =========================================================================== worn runner carpet
def carpet(NU=1024, NV=2048, W=0.9, L=1.8, seed=201):
    """Runner 0.9 m wide (U spans exactly the width, so the border sits at the edges), 1.8 m tile
    along its length.  Faded wool pile with a border, a lattice field, a threadbare walking path,
    stains and dust."""
    rng = np.random.default_rng(seed)
    shape = (NV, NU)
    size = (W, L)
    U, V = grid(shape, size)
    pxu, pxv = W / NU, L / NV
    S = lambda **k: spectral(shape, size, rng, **k)
    aa = 1.5 * pxu
    e = np.minimum(U, W - U)                          # distance from the long edges

    red = col(0.30, 0.065, 0.055)
    red2 = col(0.22, 0.05, 0.05)
    navy = col(0.07, 0.075, 0.11)
    beige = col(0.52, 0.42, 0.29)
    green = col(0.17, 0.21, 0.15)
    gold = col(0.50, 0.36, 0.17)

    # ---- field: diamond lattice (0.3 m cells) with a medallion in each cell
    cu = W / 2
    fu = (U - cu)
    fv = V
    p = 0.30
    a = wrapd(fu + fv, p) / p
    b = wrapd(fu - fv, p) / p
    lat = ss(0.045, 0.03, np.minimum(np.abs(a), np.abs(b)))       # lattice lines
    du = wrapd(fu, p)
    dv = wrapd(fv, p)
    r = np.sqrt(du ** 2 + dv ** 2)
    ang = np.arctan2(dv, du)
    petal = 0.045 + 0.02 * np.cos(ang * 8)
    med = ss(petal + aa, petal - aa, r)
    med_core = ss(0.018 + aa, 0.018 - aa, r)
    med_ring = ss(aa, -aa, np.abs(r - 0.075) - 0.006)
    du2 = wrapd(fu + p / 2, p)
    dv2 = wrapd(fv + p / 2, p)
    r2 = np.sqrt(du2 ** 2 + dv2 ** 2)
    star = ss(0.03 + 0.012 * np.cos(np.arctan2(dv2, du2) * 4) + aa, 0.03 + 0.012 * np.cos(np.arctan2(dv2, du2) * 4) - aa, r2)
    c = np.broadcast_to(red, (*shape, 3)).copy()
    abrash = S(beta=2.5, fmin=0.6, fmax=12, stretch=(1.0, 0.25))   # dye lots: bands across
    c = lerp(c, red2, ss(-0.8, 1.2, abrash) * 0.7)
    c = lerp(c, navy, lat * 0.9)
    c = lerp(c, beige, med_ring * 0.85)
    c = lerp(c, navy, med * 0.9)
    c = lerp(c, gold, med_core * 0.9)
    c = lerp(c, green, star * 0.85)

    # ---- border bands
    band = lambda e0, e1: ss(e0 - aa, e0 + aa, e) * ss(e1 + aa, e1 - aa, e)
    binding = band(-1, 0.012)
    guard_o = band(0.016, 0.03)
    border = band(0.03, 0.115)
    guard_i = band(0.12, 0.134)
    ros_p = 0.09
    rv = wrapd(V, ros_p)
    re_ = e - 0.0725
    rr = np.sqrt(re_ ** 2 + rv ** 2)
    ros = ss(0.028 + 0.01 * np.cos(np.arctan2(rv, re_) * 6) + aa, 0.028 + 0.01 * np.cos(np.arctan2(rv, re_) * 6) - aa, rr)
    vine = ss(aa, -aa, np.abs(re_ - 0.022 * np.sin(V / ros_p * TAU)) - 0.004)
    infield = ss(0.134 - aa, 0.134 + aa, e)
    c = lerp(c, red, (1 - infield)[..., None] * np.ones(3))
    c = lerp(c, navy, border)
    c = lerp(c, beige, border * np.clip(ros + vine * 0.8, 0, 1))
    c = lerp(c, red2 * 1.2, border * ss(aa, -aa, rr - 0.009))
    c = lerp(c, gold, guard_o + guard_i)
    c = lerp(c, col(0.09, 0.07, 0.06), binding)

    # ---- pile, fading, wear
    pile = S(beta=0.8, fmin=200, fmax=1100)
    tufts = S(beta=1.4, fmin=40, fmax=500)
    c *= (1 + 0.10 * pile + 0.06 * tufts)[..., None]
    low = S(beta=2.8, fmin=0.6, fmax=20)
    fade = ss(-1.0, 1.5, low) * 0.35 + 0.25
    grey = c.mean(axis=-1, keepdims=True)
    c = lerp(c, grey * col(1.15, 1.0, 0.85), fade)                  # sun-faded, dusty
    # threadbare walking path down the middle: pile gone, the beige warp/weft grid shows
    wn = S(beta=2.6, fmin=0.8, fmax=40)
    path = ss(0.36, 0.12, np.abs(U - cu + 0.03 * wn)) * ss(-0.4, 1.0, wn + 0.4 * S(beta=1.6, fmin=8, fmax=200))
    weave_u = 0.5 + 0.5 * np.cos(TAU * U / 0.0028)
    weave_v = 0.5 + 0.5 * np.cos(TAU * V / 0.0028)
    weave = np.maximum(weave_u, weave_v)
    warp_c = lerp(col(0.40, 0.34, 0.26), col(0.25, 0.20, 0.15), weave)
    bare = ss(0.55, 0.85, path)
    c = lerp(c, c * 0.85 + col(0.06, 0.05, 0.04), path * 0.6)
    c = lerp(c, warp_c, bare * 0.8)
    # stains: dark dried blotches + water tide marks + one large old dark stain
    st = np.zeros(shape)
    tide = np.zeros(shape)
    for _ in range(6):
        w1 = S(beta=2.5, fmin=2, fmax=60) * 0.04
        fld = blob_field(U, V, rng.uniform(0.1, 0.8), rng.uniform(0, L), rng.uniform(0.04, 0.16),
                         rng.uniform(0.05, 0.2), w1, w1, None, L)
        st = np.maximum(st, ss(-0.05, 0.4, fld) * rng.uniform(0.4, 0.9))
        tide = np.maximum(tide, np.exp(-(fld / 0.02) ** 2))
    c = tint(c, col(0.55, 0.45, 0.35), st * 0.8)
    c = tint(c, col(0.45, 0.35, 0.25), tide * 0.6)
    w1 = S(beta=2.5, fmin=2, fmax=80) * 0.05
    dk = blob_field(U, V, 0.58, 1.25, 0.13, 0.2, w1, w1, None, L)
    dk = np.maximum(dk, blob_field(U, V, 0.44, 1.05, 0.05, 0.06, w1, w1, None, L) - 0.1)
    c = tint(c, col(0.18, 0.08, 0.06), ss(-0.05, 0.35, dk) * 0.95)
    dust = ss(-0.6, 1.8, S(beta=2.2, fmin=1, fmax=80))
    c = lerp(c, col(0.36, 0.33, 0.30), dust * 0.35)
    edge_dirt = ss(0.2, 0.0, e) * 0.5
    c = tint(c, col(0.5, 0.45, 0.4), edge_dirt)

    hmm = (0.35 * pile + 0.25 * tufts) * (1 - bare) - 1.2 * path + 0.25 * weave * bare
    hmm += 0.8 * binding + 0.2 * (border * ros)
    hmm -= 0.3 * ss(0.1, 0.6, dk)
    rough = np.clip(0.93 + 0.03 * pile - 0.12 * ss(0.1, 0.6, dk) - 0.05 * st, 0.05, 1)
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, pxu, pxv, strength=1.6, pre_blur=0.8),
                rough=rough)


# =========================================================================== flaking paint over wood
def painted_wood(N=1024, T=1.0, seed=211, paint=(0.24, 0.27, 0.19), under=(0.62, 0.56, 0.42),
                 wood=((0.40, 0.30, 0.21), (0.22, 0.15, 0.10)), chip=1.75, grime=0.6, mildew=0.0,
                 gloss=0.45, rings=220):
    """Painted boards (grain along U) with an older paint layer and bare wood showing through chips."""
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    late, fibre = wood_grain(U, V, rng, shape, size, rings_per_m=rings, along="U")
    wd = lerp(col(*wood[0]), col(*wood[1]), late)
    wd *= (1 + 0.1 * fibre)[..., None]
    brush = S(beta=1.5, fmin=10, fmax=500, stretch=(18.0, 1.0))
    low = S(beta=2.8, fmin=1, fmax=30)
    p = col(*paint) * (1 + 0.03 * brush[..., None] + 0.05 * low[..., None])
    p = tint(p, col(1.05, 1.0, 0.85), ss(-1, 2, low) * 0.3)
    chip_n = S(beta=2.0, fmin=5, fmax=300) + 0.35 * S(beta=1.4, fmin=40, fmax=600)
    chip_n += 0.5 * fibre * 0.3
    chips = ss(chip, chip + 0.08, chip_n)
    old = ss(chip - 0.3, chip - 0.22, chip_n)
    c = lerp(p, col(*under), old)
    c = lerp(c, wd, chips)
    edge = np.clip(np.abs(blur(old, 1.0) - old) * 3, 0, 1)
    edge2 = np.clip(np.abs(blur(chips, 1.0) - chips) * 3, 0, 1)
    c = lerp(c, col(0.12, 0.10, 0.08), np.clip(edge * 0.45 + edge2 * 0.5, 0, 1))
    # paint crazing (alligatoring) on the top layer
    craze = ss(0.06, 0.0, np.abs(S(beta=1.6, fmin=25, fmax=500))) * (1 - old)
    c = lerp(c, c * 0.55, craze[..., None] * np.ones(3) * 0.6)
    g = ss(-0.5, 2.0, S(beta=2.2, fmin=2, fmax=100))
    c = tint(c, col(0.55, 0.50, 0.42), g * grime)
    if mildew > 0:
        md = ss(1.6, 2.5, S(beta=1.0, fmin=30, fmax=700)) * ss(-0.5, 1.5, S(beta=2.5, fmin=1, fmax=12))
        c = tint(c, col(0.22, 0.24, 0.18), md * mildew)
    specks = ss(2.2, 2.9, S(beta=0.8, fmin=60, fmax=900))
    c = lerp(c, col(0.1, 0.09, 0.08), specks * 0.6)
    hmm = 0.05 * brush + 0.14 * (1 - old) + 0.14 * (1 - chips) + 0.05 * late * chips + 0.03 * fibre
    hmm -= 0.08 * craze
    r = np.full(shape, gloss) + 0.04 * brush * 0.3
    r = lerp(r, 0.65, old * (1 - chips))
    r = lerp(r, 0.88, chips) + 0.15 * g * grime
    r = lerp(r, 0.8, craze * 0.6)
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, px, px, strength=1.6),
                rough=np.clip(r, 0.05, 1))


def wainscot():
    return painted_wood(N=1024, T=1.0, seed=221, paint=(0.20, 0.23, 0.16), under=(0.55, 0.50, 0.38),
                        chip=1.65, grime=0.7, mildew=0.6, gloss=0.42)


def door_paint():
    return painted_wood(N=1024, T=1.0, seed=231, paint=(0.40, 0.40, 0.35), under=(0.30, 0.36, 0.30),
                        wood=((0.33, 0.24, 0.16), (0.17, 0.11, 0.07)), chip=1.85, grime=0.75,
                        gloss=0.4)


def window_frame():
    return painted_wood(N=1024, T=0.5, seed=241, paint=(0.70, 0.68, 0.61), under=(0.52, 0.55, 0.47),
                        wood=((0.34, 0.30, 0.25), (0.20, 0.17, 0.14)), chip=1.6, grime=0.9,
                        mildew=1.0, gloss=0.55, rings=300)


# =========================================================================== window glass (RGBA)
def window_glass(N=1024, seed=251):
    """UV 0..1 covers one whole window (all panes).  Alpha = coverage: grime film, rain streaks,
    a crack star with a punched-out hole and a second hairline crack."""
    rng = np.random.default_rng(seed)
    shape = (N, N)
    U, V = grid(shape, (1.0, 1.0))
    S = lambda **k: spectral(shape, (1.0, 1.0), rng, **k)
    e = np.minimum(np.minimum(U, 1 - U), np.minimum(V, 1 - V))
    grime = 0.12 + 0.25 * ss(-0.5, 2.0, S(beta=2.2, fmin=1, fmax=60))
    grime += 0.35 * ss(0.12, 0.0, e) + 0.25 * ss(0.35, 0.0, V)
    streak = ss(0.4, 2.0, S(beta=1.4, fmin=4, fmax=300, stretch=(1.0, 30.0))) * ss(0.1, 0.9, 1 - V)
    grime += 0.25 * streak
    grime = np.clip(grime, 0, 0.85)
    # cracks: radial walks from an impact point + concentric arcs
    strokes = []
    ip = np.array([0.66 * N, 0.36 * N])           # (row = v, col = u)
    for k in range(13):
        a = k / 13 * TAU + rng.normal(0, 0.15)
        strokes.append((random_walk(rng, ip, a, rng.uniform(0.15, 0.55) * N, 3.0, 0.07), 1.0, rng.uniform(0.6, 1.3)))
    for rad in (0.06, 0.11, 0.17):
        for k in range(9):
            a0 = rng.uniform(0, TAU)
            pts = np.array([ip + rad * N * (1 + rng.normal(0, 0.06)) * np.array([math.sin(a0 + t), math.cos(a0 + t)])
                            for t in np.linspace(0, rng.uniform(0.25, 0.6), 8)])
            strokes.append((pts, 0.8, 0.6))
    p2 = np.array([0.2 * N, 0.75 * N])
    strokes.append((random_walk(rng, p2, 2.2, 0.6 * N, 3.0, 0.05), 0.8, 0.7))
    strokes.append((random_walk(rng, p2, -0.6, 0.35 * N, 3.0, 0.06), 0.7, 0.6))
    cr = draw_strokes(shape, strokes, sigma=0.6)
    # hole punched through around the impact
    w1 = S(beta=1.8, fmin=4, fmax=120) * 0.035
    hole_f = blob_field(U, V, ip[1] / N, ip[0] / N, 0.075, 0.09, w1, w1)
    hole_f += 0.05 * S(beta=1.2, fmin=20, fmax=300)
    hole = ss(-0.02, 0.02, hole_f)
    a = np.clip(grime + cr * 0.75, 0, 1) * (1 - hole)
    c = np.broadcast_to(col(0.17, 0.19, 0.18), (*shape, 3)).copy()
    c = lerp(c, col(0.30, 0.27, 0.21), np.clip((grime - 0.1) * 1.6, 0, 1))
    c = lerp(c, col(0.36, 0.38, 0.36), cr * 0.7)
    rough = np.clip(0.06 + 0.7 * np.clip(grime - 0.12, 0, 1) + 0.3 * cr, 0.03, 1)
    hmm = -0.2 * cr + 0.02 * grime
    return dict(base=np.clip(c, 0, 1), alpha=np.clip(a, 0, 1), rough=rough,
                normal=height_to_normal(hmm, 1.0 / N, 1.0 / N, strength=1.0))


# =========================================================================== tattered curtain (RGBA)
def curtain(NU=1024, NV=2048, W=0.8, H=2.4, seed=261):
    """One drape, flat size W x H (U across, V up).  Faded damask, moth holes, rips, a ragged hem.
    Alpha is (almost) binary so it works as an alpha-test cut-out (and in shadow maps)."""
    rng = np.random.default_rng(seed)
    shape = (NV, NU)
    size = (W, H)
    U, V = grid(shape, size)
    pxu, pxv = W / NU, H / NV
    S = lambda **k: spectral(shape, size, rng, **k)
    # damask: two-tone motif, period 0.2 x 0.32
    pu = wrapd(U - W / 2, 0.2)
    pv = wrapd(V, 0.32)
    x = np.abs(pu)
    lob = np.sqrt((x / 0.06) ** 2 + ((pv - 0.02) / 0.11) ** 2)
    lob2 = np.sqrt(((x - 0.05) / 0.03) ** 2 + ((pv + 0.08) / 0.05) ** 2)
    motif = np.clip(ss(1.0, 0.85, lob) - ss(0.55, 0.4, lob) + ss(1.0, 0.8, lob2), 0, 1)
    base = col(0.26, 0.12, 0.14)
    c = np.broadcast_to(base, (*shape, 3)).copy()
    c = lerp(c, col(0.36, 0.20, 0.20), motif * 0.7)
    weave = 0.5 + 0.25 * np.sin(TAU * U / 0.0012) + 0.25 * np.sin(TAU * V / 0.0012)
    c *= (0.92 + 0.12 * weave)[..., None]
    # sun fading in vertical bands (folds that faced the window), dust on top
    fold = S(beta=2.6, fmin=1.0, fmax=12, stretch=(1.0, 40.0))
    c = lerp(c, c.mean(axis=-1, keepdims=True) * col(1.3, 1.15, 1.0) + 0.05, ss(-0.5, 1.5, fold) * 0.5)
    c = lerp(c, col(0.40, 0.37, 0.33), ss(H - 0.6, H, V) * 0.35 + 0.15 * ss(0, 2, S(beta=2, fmin=2, fmax=80)))
    wst = ss(0.5, 0.0, V) * 0.6 + 0.3 * ss(-0.2, 1.5, S(beta=2.5, fmin=1, fmax=30))
    c = tint(c, col(0.55, 0.45, 0.35), np.clip(wst, 0, 1) * 0.8)              # damp rot from the sill
    mold = ss(1.6, 2.4, S(beta=1.0, fmin=30, fmax=700)) * np.clip(wst, 0, 1)
    c = tint(c, col(0.2, 0.22, 0.17), mold * 0.9)
    # alpha: ragged hem (tatters), rips, moth holes
    hem_n = S(beta=1.6, fmin=3, fmax=200, stretch=(1.0, 3.0))
    tatters = 0.08 + 0.55 * ss(0.0, 2.2, S(beta=1.3, fmin=4, fmax=200, stretch=(1.0, 40.0))) + 0.04 * hem_n
    a = ss(tatters - 0.004, tatters + 0.004, V)
    rip = S(beta=1.6, fmin=3, fmax=300, stretch=(1.0, 14.0))
    rips = ss(2.3, 2.45, rip) * ss(0.2, 0.9, V) * ss(H - 0.1, H - 0.5, V)
    holes = ss(2.35, 2.5, S(beta=1.3, fmin=20, fmax=500) + 0.6 * np.clip(wst, 0, 1))
    a = a * (1 - rips) * (1 - holes)
    frayed = np.clip(np.abs(blur(a, 1.5) - a) * 3, 0, 1)
    c = lerp(c, col(0.45, 0.38, 0.33), frayed * 0.7)
    hmm = 0.15 * weave + 0.25 * motif + 0.6 * fold
    rough = np.full(shape, 0.95)
    return dict(base=np.clip(c, 0, 1), alpha=np.clip(a, 0, 1), rough=rough,
                normal=height_to_normal(hmm, pxu, pxv, strength=1.0))


# =========================================================================== oil paintings atlas
def paintings(N=2048, seed=271):
    """2x2 atlas of dark, varnished, crazed oil paintings:
    [0,0] portrait of a man (eyes scratched out)   [1,0] house at night
    [0,1] woman, face scribbled out                [1,1] stormy sea"""
    rng = np.random.default_rng(seed)
    h = N // 2
    shape = (h, h)
    U, V = grid(shape, (1.0, 1.0))
    S = lambda **k: spectral(shape, (1.0, 1.0), rng, **k)
    out = np.zeros((N, N, 3))
    hm = np.zeros((N, N))

    def vign(c):
        r = np.sqrt((U - 0.5) ** 2 + (V - 0.5) ** 2)
        return c * (1 - 0.6 * ss(0.25, 0.75, r))[..., None]

    def ell(cx, cy, rx, ry):
        return np.sqrt(((U - cx) / rx) ** 2 + ((V - cy) / ry) ** 2)

    brush = S(beta=1.6, fmin=8, fmax=300)
    # --- portrait (man)
    c = lerp(col(0.10, 0.07, 0.04), col(0.20, 0.14, 0.07), ss(-1, 1.5, S(beta=2.5, fmin=1, fmax=20)))
    body = ss(1.0, 0.97, ell(0.5, 0.05, 0.38, 0.42))
    c = lerp(c, col(0.04, 0.035, 0.03), body)
    collar = ss(1.0, 0.95, ell(0.5, 0.38, 0.07, 0.07)) * body
    c = lerp(c, col(0.45, 0.42, 0.36), collar)
    face = ss(1.0, 0.96, ell(0.5, 0.6, 0.13, 0.18))
    shade = ss(0.35, 0.65, U)
    fc = lerp(col(0.52, 0.38, 0.27), col(0.25, 0.16, 0.10), shade)
    c = lerp(c, fc, face)
    hair = ss(1.0, 0.96, ell(0.5, 0.7, 0.14, 0.12)) * ss(0.66, 0.72, V)
    c = lerp(c, col(0.06, 0.05, 0.04), hair)
    strokes = []
    for ex in (0.45, 0.55):
        for _ in range(9):
            p0 = np.array([0.62 * h + rng.normal(0, 6), ex * h + rng.normal(0, 8)])
            strokes.append((random_walk(rng, p0, rng.uniform(0, TAU), rng.uniform(20, 55), 2.0, 0.3), 1.0, 1.2))
    sc = draw_strokes(shape, strokes, 0.7)
    c = lerp(c, col(0.62, 0.55, 0.45), sc)                         # gouged to the ground
    out[:h, :h] = vign(c)
    hm[:h, :h] = -0.6 * sc
    # --- house at night
    c = lerp(col(0.03, 0.04, 0.05), col(0.10, 0.11, 0.12), ss(0.3, 1.0, V) * ss(-1, 1.5, S(beta=2.4, fmin=1, fmax=15)))
    hill = V < 0.3 + 0.04 * np.sin(U * 5) + 0.02 * S(beta=2, fmin=2, fmax=40)
    c = np.where(hill[..., None], col(0.04, 0.035, 0.025), c)
    house = (np.abs(U - 0.55) < 0.14) & (V > 0.28) & (V < 0.5)
    roof = (V >= 0.5) & (V < 0.62 - np.abs(U - 0.55) * 0.8) & (np.abs(U - 0.55) < 0.17)
    c = np.where((house | roof)[..., None], col(0.02, 0.02, 0.02), c)
    win = (np.abs(U - 0.6) < 0.018) & (np.abs(V - 0.42) < 0.025)
    c = np.where(win[..., None], col(0.60, 0.45, 0.20), c)
    c = lerp(c, col(0.35, 0.27, 0.12), np.exp(-(((U - 0.6) / 0.05) ** 2 + ((V - 0.42) / 0.05) ** 2)) * 0.3)
    out[:h, h:] = vign(c)
    # --- woman, face scribbled out
    c = lerp(col(0.14, 0.13, 0.10), col(0.22, 0.20, 0.15), ss(-1, 1.5, S(beta=2.5, fmin=1, fmax=20)))
    dress = ss(1.0, 0.97, ell(0.5, 0.02, 0.33, 0.45))
    c = lerp(c, col(0.05, 0.06, 0.07), dress)
    face = ss(1.0, 0.96, ell(0.5, 0.6, 0.11, 0.16))
    c = lerp(c, col(0.55, 0.45, 0.36), face)
    hair = ss(1.0, 0.96, ell(0.5, 0.62, 0.16, 0.2)) * (1 - face * ss(0.55, 0.5, V))
    c = lerp(c, col(0.08, 0.06, 0.05), hair * (1 - face))
    strokes = []
    p0 = np.array([0.6 * h, 0.5 * h])
    for _ in range(26):
        strokes.append((random_walk(rng, p0 + rng.normal(0, 15, 2), rng.uniform(0, TAU), rng.uniform(60, 170), 3.0, 0.5), 1.0, 2.0))
    sc = draw_strokes(shape, strokes, 0.8)
    c = lerp(c, col(0.03, 0.02, 0.02), sc * face)
    out[h:, :h] = vign(c)
    hm[h:, :h] = 0.4 * sc * face
    # --- stormy sea
    sky = lerp(col(0.10, 0.11, 0.10), col(0.25, 0.26, 0.22), ss(-1, 2, S(beta=2.2, fmin=1, fmax=30, stretch=(3.0, 1.0))))
    sea = lerp(col(0.04, 0.06, 0.05), col(0.18, 0.22, 0.18), ss(0.5, 2.5, S(beta=1.8, fmin=3, fmax=150, stretch=(4.0, 1.0))))
    hz = 0.42 + 0.01 * np.sin(U * 9)
    c = np.where((V > hz)[..., None], sky, sea)
    mast = (np.abs(U - 0.32 - (V - 0.4) * 0.15) < 0.004) & (V > 0.4) & (V < 0.62)
    hull = (np.abs(U - 0.33) < 0.07 - (0.43 - V) * 0.6) & (V > 0.36) & (V < 0.43)
    c = np.where((mast | hull)[..., None], col(0.03, 0.03, 0.03), c)
    out[h:, h:] = vign(c)
    # --- shared: brushwork, yellowed varnish, craquelure, frame-rebate shadow
    U2, V2 = grid((N, N), (2.0, 2.0))
    rngb = np.random.default_rng(seed + 7)
    bw = spectral((N, N), (2.0, 2.0), rngb, beta=1.5, fmin=10, fmax=500, stretch=(1.0, 3.0))
    out *= (1 + 0.06 * bw)[..., None]
    out = tint(out, col(0.85, 0.65, 0.35), np.full((N, N), 0.55))
    cq = spectral((N, N), (2.0, 2.0), rngb, beta=1.4, fmin=25, fmax=500)
    craq = ss(0.07, 0.0, np.abs(cq))
    out = lerp(out, out * 0.4, craq[..., None] * np.ones(3) * 0.7)
    grime = ss(-0.5, 2.0, spectral((N, N), (2.0, 2.0), rngb, beta=2.2, fmin=1, fmax=60))
    out = tint(out, col(0.6, 0.55, 0.45), grime * 0.4)
    hm += 0.15 * bw - 0.25 * craq
    rough = np.clip(0.42 + 0.3 * grime + 0.2 * craq, 0.05, 1)
    return dict(base=np.clip(out, 0, 1), normal=height_to_normal(hm, 0.5 / N, 0.5 / N, strength=1.0), rough=rough)


# =========================================================================== cracked leather
def leather(N=512, T=0.5, seed=281):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    low = S(beta=2.6, fmin=2, fmax=40)
    grain = S(beta=1.0, fmin=80, fmax=700)
    crack = ss(0.06, 0.0, np.abs(S(beta=1.5, fmin=12, fmax=300)))
    c = col(0.10, 0.065, 0.045) * (1 + 0.15 * low[..., None] + 0.05 * grain[..., None])
    worn = ss(0.5, 2.0, low)
    c = lerp(c, col(0.25, 0.18, 0.12), worn * 0.6)
    c = lerp(c, col(0.35, 0.30, 0.25), crack * 0.6)
    dust = ss(-0.5, 2, S(beta=2, fmin=2, fmax=80))
    c = lerp(c, col(0.3, 0.28, 0.25), dust * 0.3)
    hmm = 0.06 * grain - 0.35 * crack + 0.1 * low
    r = np.clip(0.55 + 0.25 * crack + 0.15 * dust - 0.1 * worn, 0.05, 1)
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, px, px, strength=1.5), rough=r)


# =========================================================================== night backdrop
def night_sky(NU=2048, NV=1024, seed=291):
    """Night view for the window backdrops (U 0..1 across ~8 m, V 0..1 bottom..top ~4 m):
    overcast sky lit by a hidden moon, bare tree silhouettes, a low hill line."""
    rng = np.random.default_rng(seed)
    shape = (NV, NU)
    size = (2.0, 1.0)
    U, V = grid(shape, size)
    U = U / 2.0
    S = lambda **k: spectral(shape, size, rng, **k)
    c = lerp(col(0.030, 0.038, 0.055), col(0.010, 0.012, 0.022), ss(0.2, 1.0, V))
    cl = S(beta=2.4, fmin=0.8, fmax=60, stretch=(3.0, 1.0))
    cl2 = S(beta=2.0, fmin=3, fmax=150, stretch=(3.5, 1.0))
    clouds = ss(-0.3, 1.4, cl + 0.35 * cl2)
    moon = np.exp(-(((U - 0.66) / 0.14) ** 2 + ((V - 0.78) / 0.22) ** 2))
    glow = np.exp(-(((U - 0.66) / 0.05) ** 2 + ((V - 0.78) / 0.09) ** 2))
    lit = col(0.16, 0.18, 0.22) * (0.25 + 1.1 * moon)[..., None]
    c = lerp(c, lit, clouds[..., None] * (0.35 + 0.65 * moon)[..., None])
    c = c + col(0.25, 0.27, 0.30) * (glow * (1 - 0.7 * clouds))[..., None]
    # silhouettes: hill + bare trees (recursive branches)
    hill = 0.16 + 0.05 * np.sin(U * 7.0 + 1.0) + 0.03 * S(beta=2.2, fmin=1, fmax=40)
    mask = (V < hill).astype(np.float64)
    strokes = []

    def branch(p, a, L, w, depth):
        pts = random_walk(rng, p, a, L, step=3.0, wiggle=0.06 + 0.05 * (4 - depth))
        strokes.append((pts, 1.0, w))
        if depth == 0 or w < 0.6:
            return
        n = rng.integers(2, 4)
        for k in range(n):
            i = int(len(pts) * rng.uniform(0.45, 1.0)) - 1
            na = a + rng.choice([-1, 1]) * rng.uniform(0.25, 0.8)
            branch(pts[i], na, L * rng.uniform(0.45, 0.7), w * 0.6, depth - 1)

    for k in range(9):
        x = rng.uniform(0.02, 0.98) * NU
        base_v = float(hill[0, int(x) % NU]) * NV - 4
        Lt = rng.uniform(0.35, 0.8) * NV
        branch(np.array([base_v, x]), math.pi / 2 + rng.normal(0, 0.08), Lt * 0.55, rng.uniform(5, 11), 4)
    tr = draw_strokes(shape, strokes, 0.7)
    mask = np.maximum(mask, tr)
    c = lerp(c, col(0.004, 0.005, 0.007), np.clip(mask, 0, 1))
    return dict(base=np.clip(c, 0, 1), normal=flat_normal(shape), rough=np.full(shape, 1.0))
