"""Procedural PBR textures for the haunted room (numpy only, no downloads).

Every generator returns a dict of float arrays in 0..1, row 0 = bottom (Blender image order,
i.e. V = 0), column 0 = U = 0:
    base   (H, W, 3)  sRGB colour
    normal (H, W, 3)  tangent-space normal, OpenGL convention (+Y = +V)
    rough  (H, W)     roughness (later packed with metallic into G/B of one image)
    metal  (H, W)     optional
    alpha  (H, W)     optional
Heights are authored in millimetres and converted to normals with the real texel size so the
relief is physically scaled (then exaggerated a little, as games do).
"""
import math

import numpy as np

TAU = 2.0 * math.pi


# =========================================================================== noise toolkit
def _freqs(shape, size):
    """Physical frequency grids (cycles / metre) for an rfft2 of `shape` covering `size` metres."""
    h, w = shape
    W, H = size
    fy = np.fft.fftfreq(h, d=H / h)[:, None]
    fx = np.fft.rfftfreq(w, d=W / w)[None, :]
    return fy, fx


def spectral(shape, size, rng, beta=2.0, fmin=0.5, fmax=None, stretch=(1.0, 1.0)):
    """Tileable noise with a power-law spectrum (1/f^beta power), zero mean, unit std.
    fmin / fmax are in cycles per metre.  stretch=(sx, sy): features become sx times longer along U
    and sy times longer along V."""
    h, w = shape
    F = np.fft.rfft2(rng.standard_normal((h, w)))
    fy, fx = _freqs(shape, size)
    fx = fx * stretch[0]
    fy = fy * stretch[1]
    f = np.sqrt(fx * fx + fy * fy)
    f[0, 0] = 1e-9
    amp = f ** (-beta / 2.0)
    amp *= 1.0 - np.exp(-(f / fmin) ** 4)
    if fmax is not None:
        amp *= np.exp(-(f / fmax) ** 2)
    amp[0, 0] = 0.0
    out = np.fft.irfft2(F * amp, s=(h, w))
    out -= out.mean()
    out /= out.std() + 1e-12
    return out


def blur(a, sigma_px):
    """Tileable gaussian blur (sigma in pixels, may be a (sy, sx) tuple)."""
    if np.isscalar(sigma_px):
        sy = sx = sigma_px
    else:
        sy, sx = sigma_px
    if sy <= 0 and sx <= 0:
        return a
    h, w = a.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    g = np.exp(-2.0 * math.pi ** 2 * ((sy * fy) ** 2 + (sx * fx) ** 2))
    return np.fft.irfft2(np.fft.rfft2(a) * g, s=(h, w))


def ss(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    t = np.asarray(t)
    rgb = np.ndim(a) in (1, 3) or np.ndim(b) in (1, 3)
    if rgb and t.ndim == 2:
        t = t[..., None]
    return a + (b - a) * t


def sample(arr, yy, xx):
    """Bilinear wrap-around sampling of arr at fractional pixel coords."""
    h, w = arr.shape[:2]
    y0 = np.floor(yy).astype(np.int64)
    x0 = np.floor(xx).astype(np.int64)
    ty = yy - y0
    tx = xx - x0
    y0 %= h
    x0 %= w
    y1 = (y0 + 1) % h
    x1 = (x0 + 1) % w
    if arr.ndim == 3:
        ty = ty[..., None]
        tx = tx[..., None]
    a = arr[y0, x0]
    b = arr[y0, x1]
    c = arr[y1, x0]
    d = arr[y1, x1]
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty


def splat(shape, ys, xs, wts=None):
    """Accumulate points (fractional pixel coords) into a grid with bilinear weights (wrapping)."""
    h, w = shape
    acc = np.zeros(h * w)
    if wts is None:
        wts = np.ones_like(ys)
    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    ty = ys - y0
    tx = xs - x0
    for dy, dx, ww in ((0, 0, (1 - ty) * (1 - tx)), (0, 1, (1 - ty) * tx),
                       (1, 0, ty * (1 - tx)), (1, 1, ty * tx)):
        idx = ((y0 + dy) % h) * w + (x0 + dx) % w
        acc += np.bincount(idx, weights=ww * wts, minlength=h * w)
    return acc.reshape(h, w)


def polyline_points(pts, step=0.5):
    """Densify a polyline (array (n,2) in pixel coords y,x) to points `step` px apart."""
    pts = np.asarray(pts, dtype=np.float64)
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
        t = np.arange(n)[:, None] / n
        out.append(a + (b - a) * t)
    out.append(pts[-1:])
    return np.concatenate(out)


def draw_strokes(shape, strokes, sigma=0.6):
    """strokes: list of (points (n,2) y,x px, intensity, width_px).  Returns 0..~1 coverage."""
    acc = np.zeros(shape)
    groups = {}
    for pts, inten, width in strokes:
        groups.setdefault(round(max(width, 0.5) * 2) / 2, []).append((pts, inten))
    for width, items in groups.items():
        ys, xs, ws = [], [], []
        for pts, inten in items:
            p = polyline_points(pts, 0.5)
            ys.append(p[:, 0])
            xs.append(p[:, 1])
            ws.append(np.full(len(p), inten))
        g = splat(shape, np.concatenate(ys), np.concatenate(xs), np.concatenate(ws))
        # 0.5 px spacing -> ~2 samples per px of line; normalise and widen
        g = blur(g, max(sigma, width * 0.5)) * (math.sqrt(TAU) * max(sigma, width * 0.5)) * 0.5
        acc = np.maximum(acc, g)
    return np.clip(acc, 0, 1)


def random_walk(rng, start, angle, length, step=2.0, wiggle=0.12, bias=0.0):
    pts = [np.array(start, dtype=np.float64)]
    a = angle
    for _ in range(int(length / step)):
        a += rng.normal(0, wiggle) + bias
        pts.append(pts[-1] + step * np.array([math.sin(a), math.cos(a)]))
    return np.array(pts)


def height_to_normal(hmm, px_u_m, px_v_m, strength=1.0, pre_blur=0.6):
    """Height in millimetres -> tangent-space normal (OpenGL)."""
    h = blur(hmm, pre_blur) * 1e-3
    du = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) / (2 * px_u_m) * strength
    dv = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) / (2 * px_v_m) * strength
    n = np.stack([-du, -dv, np.ones_like(h)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5


def grid(shape, size):
    """Pixel-centre coordinates in metres: U (h,w), V (h,w)."""
    h, w = shape
    W, H = size
    u = (np.arange(w) + 0.5) * (W / w)
    v = (np.arange(h) + 0.5) * (H / h)
    return np.broadcast_to(u[None, :], shape), np.broadcast_to(v[:, None], shape)


def wrapd(d, period):
    return (d + period * 0.5) % period - period * 0.5


def col(*rgb):
    return np.array(rgb, dtype=np.float64)


def tint(img, color, amount):
    """Multiply-blend an RGB image towards `color` by amount (h,w)."""
    return img * (1.0 - amount[..., None] + amount[..., None] * color)


def downsample(a, f=2):
    h, w = a.shape[:2]
    return a.reshape(h // f, f, w // f, f, *a.shape[2:]).mean(axis=(1, 3))


def blob_field(U, V, cu, cv, ru, rv, warp_u, warp_v, period_u=None, period_v=None):
    """1 at the blob centre, 0 at its (warped) ellipse edge, negative outside."""
    du = U - cu + warp_u
    if period_u:
        du = wrapd(du, period_u)
    dv = V - cv + warp_v
    if period_v:
        dv = wrapd(dv, period_v)
    return 1.0 - np.sqrt((du / ru) ** 2 + (dv / rv) ** 2)


# =========================================================================== wood helpers
def wood_grain(U, V, rng, shape, size, rings_per_m=180.0, warp_amt=0.012, along="V",
               phase=0.0, fine=0.35):
    """Plain-sawn-ish grain: returns (latewood 0..1, fibre streaks ~N(0,1)).
    `along` is the grain direction in texture space."""
    if along == "V":
        stretch, across = (1.0, 14.0), U
    else:
        stretch, across = (14.0, 1.0), V
    w1 = spectral(shape, size, rng, beta=2.6, fmin=1.0, fmax=40, stretch=stretch)
    w2 = spectral(shape, size, rng, beta=2.0, fmin=4.0, fmax=120, stretch=stretch)
    x = across * rings_per_m + (w1 * warp_amt + w2 * warp_amt * 0.25) * rings_per_m + phase
    f = x - np.floor(x)
    late = ss(0.55, 0.8, f) * (1.0 - ss(0.85, 1.0, f))
    fibre = spectral(shape, size, rng, beta=1.2, fmin=20, fmax=900,
                     stretch=(1.0, 40.0) if along == "V" else (40.0, 1.0))
    return late, fibre * fine


# =========================================================================== wallpaper wall
def wallpaper(N=2048, W=2.5, H=2.75, seed=11):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (W, H)
    U, Z = grid(shape, size)
    pxu, pxv = W / N, H / N
    S = lambda **k: spectral(shape, size, rng, **k)
    T = H - Z                                   # distance from the ceiling

    # ---------------------------------------------------------------- plaster substrate
    pl_low = S(beta=3.0, fmin=0.3, fmax=8)
    pl_mid = S(beta=2.2, fmin=4, fmax=200)
    pl_fine = S(beta=1.0, fmin=80, fmax=700)
    plaster_h = 0.9 * pl_low + 0.5 * pl_mid + 0.08 * pl_fine
    plaster_c = col(0.70, 0.67, 0.60) * (1 + 0.05 * pl_mid[..., None] + 0.03 * pl_low[..., None])
    plaster_c = tint(plaster_c, col(0.85, 0.80, 0.70), ss(0.5, 2.0, pl_low) * 0.6)

    # ---------------------------------------------------------------- lath behind plaster
    lp = 0.047
    zl = (Z % lp) / lp
    lath_board = ss(0.02, 0.06, zl) * (1 - ss(0.76, 0.82, zl))
    lath_id = np.floor(Z / lp)
    lgr = S(beta=1.5, fmin=10, fmax=600, stretch=(30.0, 1.0))
    lath_tone = 0.85 + 0.25 * np.sin(lath_id * 12.9898) ** 2
    lath_c = col(0.36, 0.26, 0.17) * (lath_tone[..., None] + 0.12 * lgr[..., None])
    lath_c = lerp(col(0.02, 0.018, 0.016), lath_c, lath_board)
    lath_h = -14.0 + 1.2 * lath_board + 0.3 * lgr * lath_board - 18.0 * (1 - lath_board)

    # ---------------------------------------------------------------- tears (paper / plaster missing)
    wu = S(beta=2.6, fmin=0.6, fmax=30) * 0.05
    wv = S(beta=2.6, fmin=0.6, fmax=30) * 0.05
    jag = S(beta=1.6, fmin=8, fmax=400)
    # rolls are 0.5 m wide, seams at u = 0.03 + k * 0.5; every feature stays inside its roll so the
    # rolls can be hung in any order on the walls (the room script picks a roll per 0.5 m column)
    blobs = [  # cu, cz, ru, rz
        (0.78, 1.38, 0.19, 0.40),      # roll 1: big tear down to plaster and lath
        (1.80, 0.32, 0.09, 0.15),      # roll 3: low tear
        (0.20, 0.95, 0.07, 0.20),      # roll 0
        (2.36, 2.45, 0.09, 0.14),      # roll 4: near the ceiling
    ]
    F = np.full(shape, -1.0)
    for cu, cz, ru, rz in blobs:
        F = np.maximum(F, blob_field(U, Z, cu, cz, ru, rz, wu, wv, W))
    F = F + 0.06 * jag
    # top part of the roll between seams 1.53..2.03 peeled away (a hanging strip is modelled there)
    seam0 = 0.03
    roll = np.floor((U - seam0) / 0.5)
    pu_roll = (U - seam0) % 0.5
    in_roll = (roll == 3)
    peel_line = 1.98 + 0.05 * S(beta=2.0, fmin=2, fmax=60)
    edge_soft = np.minimum(pu_roll, 0.5 - pu_roll)
    F_peel = np.where(in_roll, (Z - peel_line) * 4.0, -1.0)
    F_peel = np.where(in_roll, np.minimum(F_peel, edge_soft * 60 + 0.1 * jag), F_peel)
    F = np.maximum(F, F_peel)
    # small chips & lifted edges along seams near the floor and ceiling
    ds = np.abs(wrapd(U - seam0, 0.5))
    chip_n = S(beta=1.8, fmin=3, fmax=200)
    chips = (chip_n - 1.9 + 1.5 * np.exp(-ds / 0.02) * (ss(0.6, 0.15, Z) + ss(0.4, 0.05, T)))
    F = np.maximum(F, chips * 0.5)
    t1 = ss(-0.01, 0.01, F)                       # top paper missing
    F2 = F - 0.18 - 0.08 * S(beta=2.0, fmin=3, fmax=100)
    t2 = ss(-0.01, 0.01, F2)                      # older paper layer missing too -> plaster
    big = blob_field(U, Z, 0.78, 1.42, 0.11, 0.25, wu * 1.5, wv * 1.5, W) + 0.08 * jag
    t3 = ss(-0.01, 0.01, big) * t2                # plaster broken -> lath
    # fibrous torn edge: thin bright band just outside t1
    edge_band = np.exp(-((F + 0.006) / 0.006) ** 2) * (1 - t1)

    # ---------------------------------------------------------------- paper design
    strip_off = rng.uniform(-0.008, 0.008, 6)[np.clip(roll.astype(int), 0, 5) % 6]
    strip_fade = rng.uniform(-0.05, 0.05, 6)[np.clip(roll.astype(int), 0, 5) % 6]
    rep = 0.5
    pu = (U - seam0) % rep
    pv = (T + strip_off) % rep
    aa = 1.6 * pxu

    def ell(x, y, cx, cy, rx, ry, ang=0.0):
        ca, sa = math.cos(ang), math.sin(ang)
        dx, dy = x - cx, y - cy
        xr = dx * ca + dy * sa
        yr = -dx * sa + dy * ca
        return (np.sqrt((xr / rx) ** 2 + (yr / ry) ** 2) - 1.0) * min(rx, ry)

    def fill(d):
        return ss(aa, -aa, d)

    def ring(d, t):
        return ss(aa, -aa, np.abs(d) - t)

    # medallion at (0.25, 0.25) of each repeat cell; mirrored in x
    x = np.abs(pu - 0.25)
    y = 0.25 - pv
    m = np.zeros(shape)
    m = np.maximum(m, ring(ell(x, y, 0, -0.03, 0.055, 0.092), 0.006))
    m = np.maximum(m, fill(ell(x, y, 0, -0.035, 0.024, 0.05)))
    m = np.maximum(m, fill(ell(x, y, 0.078, 0.045, 0.062, 0.017, math.radians(38))))
    m = np.maximum(m, fill(ell(x, y, 0.066, -0.112, 0.05, 0.014, math.radians(-33))))
    m = np.maximum(m, fill(ell(x, y, 0.0, 0.105, 0.022, 0.03)))
    m = np.maximum(m, fill(ell(x, y, 0.0, 0.158, 0.008, 0.02)))
    sc = ell(x, y, 0.108, -0.035, 0.036, 0.036)
    m = np.maximum(m, ring(sc, 0.0045) * ss(0.09, 0.11, x))
    m = np.maximum(m, fill(ell(x, y, 0.125, 0.11, 0.009, 0.009)))
    m = np.maximum(m, fill(ell(x, y, 0.0, -0.16, 0.012, 0.012)))
    m = np.maximum(m, fill(ell(x, y, 0.035, 0.19, 0.03, 0.008, math.radians(25))))
    # small sprig half-way between medallions
    ys = wrapd(pv - 0.0, rep)
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        m = np.maximum(m, fill(ell(pu - 0.25, ys, 0.018 * math.cos(a), 0.018 * math.sin(a),
                                   0.016, 0.006, a)))
    m = np.maximum(m, fill(ell(pu - 0.25, ys, 0, 0, 0.006, 0.006)))
    # satin stripe centred on the roll edges with two pinstripes
    xs = np.abs(wrapd(pu, rep))
    stripe = ss(0.034 + aa, 0.034 - aa, xs)
    pin = ring(xs - 0.042, 0.0016) + ring(xs - 0.05, 0.0009)
    ink_var = np.clip(0.75 + 0.25 * S(beta=2.0, fmin=2, fmax=300), 0.3, 1.0)
    ground = col(0.60, 0.55, 0.43)
    paper_c = np.broadcast_to(ground, (*shape, 3)).copy()
    paper_c = lerp(paper_c, col(0.64, 0.59, 0.47), stripe)
    paper_c = lerp(paper_c, col(0.41, 0.37, 0.28), m * ink_var * 0.85)
    paper_c = lerp(paper_c, col(0.42, 0.29, 0.23), np.clip(pin, 0, 1) * ink_var * 0.8)
    paper_c *= (1 + strip_fade)[..., None]
    pap_low = S(beta=2.8, fmin=0.4, fmax=20)
    paper_c *= (1 + 0.05 * pap_low)[..., None]
    paper_c = tint(paper_c, col(0.92, 0.85, 0.68), ss(-0.5, 1.5, pap_low) * 0.5)

    # older layer under the top paper: faded pink trellis
    q = 0.06
    tu = ((U + Z) % q) / q
    tv = ((U - Z) % q) / q
    trellis = ss(0.08, 0.0, np.minimum(tu, 1 - tu)) + ss(0.08, 0.0, np.minimum(tv, 1 - tv))
    old_c = lerp(col(0.62, 0.52, 0.46), col(0.50, 0.38, 0.36), np.clip(trellis, 0, 1) * 0.7)
    old_c *= (1 + 0.06 * pl_mid)[..., None]

    # ---------------------------------------------------------------- composite colour + height
    c = lerp(plaster_c, lath_c, t3)
    hmm = lerp(plaster_h, lath_h, t3)
    c = lerp(c, old_c, (1 - t2))
    hmm = hmm + 0.22 * (1 - t2)
    c = lerp(c, paper_c, (1 - t1))
    blisters = np.maximum(0, S(beta=3.0, fmin=2, fmax=40) - 0.6)
    wrinkles = S(beta=2.0, fmin=6, fmax=250, stretch=(1.0, 3.0))
    seam_ridge = np.exp(-(wrapd(U - seam0, 0.5) / 0.0015) ** 2)
    seam_lift = np.exp(-np.abs(wrapd(U - seam0, 0.5)) / 0.008) * ss(0.4, 1.5, chip_n)
    paper_h = 0.45 + 0.04 * m + 0.6 * blisters + 0.05 * wrinkles + 0.12 * seam_ridge + 0.5 * seam_lift
    hmm = lerp(hmm, hmm * 0.3 + paper_h, (1 - t1))
    c = lerp(c, col(0.86, 0.83, 0.74), edge_band * 0.8)
    hmm = hmm + 0.35 * edge_band
    # dirt line in seams
    c = tint(c, col(0.7, 0.65, 0.58), np.exp(-(wrapd(U - seam0, 0.5) / 0.0012) ** 2) * (1 - t1) * 0.6)

    # ---------------------------------------------------------------- water stains from the ceiling
    meander = S(beta=3.0, fmin=0.4, fmax=10, stretch=(1.0, 4.0)) * 0.03
    drip = S(beta=1.6, fmin=3, fmax=300, stretch=(1.0, 25.0))
    st = np.zeros(shape)
    for cu, wd, ln, strength in ((0.28, 0.11, 1.25, 1.0), (1.28, 0.13, 0.75, 0.55),
                                 (2.28, 0.09, 1.85, 1.0), (0.84, 0.05, 2.1, 0.45)):
        du = wrapd(U - cu + meander, W)
        prof = np.exp(-(du / wd) ** 2)
        lenf = ln * (0.75 + 0.35 * drip)
        st = np.maximum(st, strength * prof * ss(lenf, lenf * 0.55, T))
    st = np.maximum(st, ss(0.3, 0.0, T) * (0.3 + 0.25 * pap_low))
    st = np.clip(st + 0.08 * S(beta=2.0, fmin=4, fmax=200), 0, 1)
    tide = sum(np.exp(-((st - L) / 0.018) ** 2) for L in (0.18, 0.42, 0.7))
    c = tint(c, col(0.80, 0.68, 0.50), ss(0.1, 0.9, st) * 0.9)
    c = tint(c, col(0.62, 0.48, 0.32), np.clip(tide, 0, 1) * ss(0.05, 0.2, st) * 0.7)
    hmm = hmm + 0.4 * blisters * st

    # ---------------------------------------------------------------- grime, scuffs, mildew
    gn = S(beta=2.0, fmin=1, fmax=100)
    grime = ss(0.55, 0.12, Z) * (0.7 + 0.3 * gn)
    c = tint(c, col(0.42, 0.38, 0.33), np.clip(grime, 0, 1) * 0.75)
    strokes = []
    for _ in range(140):
        z0 = rng.uniform(0.18, 1.1) / pxv
        u0 = rng.uniform(0, W) / pxu
        L = rng.uniform(0.02, 0.18) / pxu
        a = rng.normal(0, 0.12)
        pts = random_walk(rng, (z0, u0), math.pi / 2 + a, L, step=3.0, wiggle=0.03)
        strokes.append((pts, rng.uniform(0.25, 0.9), rng.uniform(0.6, 3.0)))
    scuff = draw_strokes(shape, strokes)
    c = tint(c, col(0.35, 0.33, 0.31), scuff * 0.6)
    mild_n = S(beta=1.0, fmin=40, fmax=900)
    mild_mask = np.clip(st * 0.8 + ss(0.3, 0.0, Z) * 0.6 + 0.3 * S(beta=3.0, fmin=0.5, fmax=10), 0, 1)
    mildew = ss(1.7, 2.6, mild_n) * mild_mask
    c = tint(c, col(0.22, 0.24, 0.18), np.clip(mildew, 0, 1) * 0.85)
    dust = ss(0.0, 1.5, S(beta=2.2, fmin=1, fmax=60))
    c = lerp(c, col(0.55, 0.53, 0.50), dust * 0.12)

    # ---------------------------------------------------------------- roughness
    r = np.full(shape, 0.82)
    r = lerp(r, 0.70, m * (1 - t1))                # ink a touch glossier
    r = lerp(r, 0.74, stripe * (1 - t1))
    r = lerp(r, 0.92, t1 * (1 - t3))
    r = lerp(r, 0.86, t3)
    r = lerp(r, 0.68, ss(0.2, 0.9, st) * 0.6)      # damp, sized paper
    r = lerp(r, 0.9, grime * 0.5)
    r += 0.03 * pl_mid
    hmm += 0.06 * mild_n * mildew
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, pxu, pxv, strength=3.0),
                rough=np.clip(r, 0.05, 1))


# =========================================================================== floorboards
def floorboards(N=2048, T=2.08, seed=21):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    ncol = 16
    bw = T / ncol
    ci = np.minimum((U / bw).astype(int), ncol - 1)
    ul = U / bw - ci
    # butt joints per column (wrapping) -> board id + distance to joints
    bid = np.zeros(shape, dtype=np.int64)
    djoint = np.full(shape, 9.0)
    nb = 0
    rows_v = (np.arange(N) + 0.5) * px
    for c in range(ncol):
        k = rng.integers(1, 3)
        js = np.sort(rng.uniform(0, T, k))
        if k == 2 and (js[1] - js[0] < 0.5 or T - js[1] + js[0] < 0.5):
            js = np.array([js[0], (js[0] + T / 2) % T])
            js.sort()
        seg = np.searchsorted(js, rows_v) % k
        d = np.min(np.abs(wrapd(rows_v[:, None] - js[None, :], T)), axis=1)
        cols = ci[0] == c
        bid[:, cols] = (nb + seg)[:, None]
        djoint[:, cols] = d[:, None]
        nb += k
    tone = rng.uniform(0, 1, nb)
    grey = rng.uniform(0, 1, nb)
    rings = rng.uniform(150, 320, nb)
    phase = rng.uniform(0, 10, nb)
    offv = rng.integers(0, N, nb)
    cup = rng.uniform(0.15, 0.45, nb)
    gapw = rng.uniform(0.0018, 0.0055, ncol)

    warp = S(beta=2.6, fmin=0.8, fmax=40, stretch=(1.0, 14.0))
    warp2 = S(beta=2.0, fmin=4, fmax=160, stretch=(1.0, 10.0))
    rows = (np.arange(N)[:, None] + offv[bid]) % N
    cols = np.broadcast_to(np.arange(N)[None, :], shape)
    wv = warp[rows, cols] * 0.011 + warp2[rows, cols] * 0.002
    x = (ul * bw + wv) * rings[bid] + phase[bid]
    f = x - np.floor(x)
    late = ss(0.5, 0.78, f) * (1 - ss(0.82, 1.0, f))
    fibre = S(beta=1.1, fmin=20, fmax=900, stretch=(1.0, 40.0))
    # knots
    knot = np.zeros(shape)
    for _ in range(9):
        ku, kv = rng.uniform(0, T), rng.uniform(0, T)
        r = np.sqrt((wrapd(U - ku, T) / rng.uniform(0.006, 0.012)) ** 2 +
                    (wrapd(V - kv, T) / rng.uniform(0.012, 0.025)) ** 2)
        knot = np.maximum(knot, np.exp(-r ** 2) + 0.4 * np.exp(-(r / 2.2) ** 2) * (0.5 + 0.5 * np.sin(r * 9)))

    light = col(0.45, 0.35, 0.25)
    dark = col(0.24, 0.17, 0.115)
    base = lerp(light, dark, tone[bid] * 0.8 + 0.2 * late)
    base = lerp(base, base * col(0.62, 0.55, 0.50), late * 0.55)
    base *= (1 + 0.07 * fibre)[..., None]
    base = lerp(base, col(0.40, 0.37, 0.33), (0.15 + grey[bid] * 0.4)[..., None] * np.ones(3))
    base = lerp(base, col(0.12, 0.07, 0.04), np.clip(knot, 0, 1) * 0.8)

    # gaps and edges
    de = np.minimum(ul, 1 - ul) * bw
    gw = gapw[ci]
    gw_r = gapw[(ci + 1) % ncol]
    gap_side = np.where(ul < 0.5, gw, gw_r) * 0.5
    gap = ss(gap_side + 0.0004, gap_side - 0.0004, de)
    jgap = ss(0.0011, 0.0004, djoint)
    gapm = np.maximum(gap, jgap)
    edge = np.exp(-np.maximum(de - gap_side, 0) / 0.0035) + np.exp(-djoint / 0.003)
    base = tint(base, col(0.55, 0.48, 0.42), np.clip(edge, 0, 1) * 0.5)
    base = lerp(base, col(0.03, 0.025, 0.02), gapm)

    # nails at joists
    nails = np.zeros(shape)
    jp = T / 5
    for k in range(5):
        jv = k * jp + 0.07
        for side in (0.22, 0.78):
            r = np.sqrt(((ul - side) * bw) ** 2 + wrapd(V - jv - 0.004 * np.sin(bid * 3.1), T) ** 2)
            nails = np.maximum(nails, ss(0.0028, 0.0018, r))
            base = tint(base, col(0.55, 0.40, 0.30), ss(0.006, 0.0025, r) * 0.6)
    base = lerp(base, col(0.08, 0.07, 0.06), nails)

    # scratches
    strokes = []
    for _ in range(700):
        p0 = (rng.uniform(0, N), rng.uniform(0, N))
        if rng.random() < 0.75:
            a = rng.normal(0, 0.18)             # mostly along the boards (V)
        else:
            a = rng.uniform(0, math.pi)
        L = rng.uniform(0.01, 0.25) / px
        strokes.append((random_walk(rng, p0, a, L, step=4.0, wiggle=0.02),
                        rng.uniform(0.3, 1.0), rng.uniform(0.4, 1.4)))
    scr = draw_strokes(shape, strokes)
    base = lerp(base, base * 1.3 + 0.04, scr * 0.35)

    # wear, dust, stains
    wear = ss(0.2, 1.6, S(beta=3.0, fmin=0.5, fmax=12))
    dust = ss(-0.3, 1.8, S(beta=2.2, fmin=1, fmax=80))
    base = lerp(base, base * 1.18, wear[..., None] * np.ones(3) * 0.6)
    base = lerp(base, col(0.42, 0.40, 0.37), dust * 0.42)
    stain = np.zeros(shape)
    for _ in range(4):
        cu, cv = rng.uniform(0, T), rng.uniform(0, T)
        w1 = S(beta=2.5, fmin=2, fmax=60) * 0.03
        fld = blob_field(U, V, cu, cv, rng.uniform(0.08, 0.2), rng.uniform(0.08, 0.25), w1, w1, T, T)
        stain = np.maximum(stain, ss(0.0, 0.3, fld) * 0.7 + np.exp(-(fld / 0.02) ** 2) * 0.5)
    base = tint(base, col(0.55, 0.45, 0.38), np.clip(stain, 0, 1) * 0.7)

    hmm = (0.6 * cup[bid] * (2 * ul - 1) ** 2 - 0.8 * (1 - ss(0.0, 0.003, de - gap_side))
           - 4.0 * gapm - 0.6 * (1 - ss(0.0, 0.002, djoint)) + 0.12 * late + 0.08 * fibre
           - 0.12 * scr - 0.3 * nails + 0.1 * knot)
    r = 0.74 + 0.05 * fibre * 0.5 + 0.06 * dust - 0.18 * wear + 0.15 * scr
    r = lerp(r, 0.95, gapm)
    r = lerp(r, 0.6, np.clip(stain, 0, 1) * 0.5)
    return dict(base=np.clip(base, 0, 1), normal=height_to_normal(hmm, px, px, strength=2.6),
                rough=np.clip(r, 0.05, 1))


# =========================================================================== cracked plaster ceiling
def ceiling(N=2048, T=2.75, seed=31, dirt=1.0):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    low = S(beta=3.0, fmin=0.3, fmax=8)
    mid = S(beta=2.2, fmin=4, fmax=200)
    fine = S(beta=1.0, fmin=80, fmax=700)
    c = col(0.70, 0.68, 0.63) * (1 + 0.04 * mid[..., None] + 0.04 * low[..., None])
    hmm = 1.2 * low + 0.25 * mid + 0.05 * fine
    # lath ghosting (dust lines where the lath sits behind the plaster)
    lg = (V % 0.047) / 0.047
    c = tint(c, col(0.85, 0.83, 0.80), ss(0.75, 0.9, lg) * (1 - ss(0.9, 1.0, lg)) * 0.6
             * ss(-1.0, 1.0, low))
    # stains with tide rings
    st = np.zeros(shape)
    tide = np.zeros(shape)
    for _ in range(5):
        cu, cv = rng.uniform(0, T), rng.uniform(0, T)
        w1 = S(beta=2.6, fmin=1, fmax=30) * 0.07
        w2 = S(beta=2.6, fmin=1, fmax=30) * 0.07
        fld = blob_field(U, V, cu, cv, rng.uniform(0.2, 0.55), rng.uniform(0.2, 0.5), w1, w2, T, T)
        st = np.maximum(st, ss(-0.05, 0.6, fld))
        for L in (0.0, 0.25, 0.5):
            tide = np.maximum(tide, np.exp(-((fld - L) / 0.012) ** 2) * (1 - L * 0.6))
    c = tint(c, col(0.78, 0.66, 0.48), st * 0.85 * dirt)
    c = tint(c, col(0.58, 0.45, 0.30), tide * 0.75 * dirt)
    # cracks
    strokes = []
    for _ in range(7):
        p0 = (rng.uniform(0, N), rng.uniform(0, N))
        a = rng.uniform(0, TAU)
        main = random_walk(rng, p0, a, rng.uniform(600, 1600), step=3.0, wiggle=0.16)
        strokes.append((main, 1.0, rng.uniform(1.2, 2.2)))
        for _ in range(rng.integers(2, 6)):
            i = rng.integers(0, len(main))
            br = random_walk(rng, main[i], a + rng.choice([-1, 1]) * rng.uniform(0.5, 1.3),
                             rng.uniform(80, 500), step=2.5, wiggle=0.22)
            strokes.append((br, 0.8, rng.uniform(0.6, 1.2)))
    for _ in range(60):          # hairline craze
        p0 = (rng.uniform(0, N), rng.uniform(0, N))
        strokes.append((random_walk(rng, p0, rng.uniform(0, TAU), rng.uniform(30, 160), 2.0, 0.35),
                        0.5, 0.5))
    cr = draw_strokes(shape, strokes, sigma=0.55)
    crack_halo = blur(cr, 4) * 3
    c = tint(c, col(0.82, 0.78, 0.72), np.clip(crack_halo, 0, 1) * 0.5)
    c = lerp(c, col(0.12, 0.10, 0.08), cr)
    hmm -= 2.0 * cr + 0.25 * np.clip(crack_halo, 0, 1)
    # flaking paint
    fl_n = S(beta=1.8, fmin=6, fmax=250)
    flake = ss(1.1, 1.25, fl_n + 1.0 * st + 0.8 * np.clip(crack_halo, 0, 1) - 1.15)
    flake_edge = np.clip(np.abs(blur(flake, 1.2) - flake) * 4, 0, 1)
    c = lerp(c, col(0.60, 0.58, 0.54) * (1 + 0.05 * fine[..., None]), flake)
    c = lerp(c, col(0.35, 0.32, 0.28), flake_edge * 0.6)
    hmm -= 0.35 * flake
    hmm += 0.25 * flake_edge
    mold = ss(1.8, 2.7, S(beta=1.0, fmin=40, fmax=900)) * np.clip(st * 1.2 + 0.2, 0, 1)
    c = tint(c, col(0.25, 0.25, 0.2), mold * 0.85)
    c *= (1 - 0.08 * dirt * ss(-1, 2, low))[..., None]
    r = 0.88 + 0.04 * mid - 0.12 * st * 0.5 + 0.06 * flake
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, px, px, strength=1.5),
                rough=np.clip(r, 0.05, 1))


# =========================================================================== chipped painted trim
def painted_trim(N=1024, T=0.5, seed=41):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    late, fibre = wood_grain(U, V, rng, shape, size, rings_per_m=260, along="U")
    wood = lerp(col(0.47, 0.38, 0.28), col(0.32, 0.24, 0.17), late)
    wood = lerp(wood, col(0.42, 0.40, 0.37), 0.35)
    brush = S(beta=1.5, fmin=10, fmax=500, stretch=(18.0, 1.0))
    low = S(beta=2.8, fmin=1, fmax=30)
    paint = col(0.80, 0.77, 0.67) * (1 + 0.025 * brush[..., None])
    paint = tint(paint, col(0.93, 0.86, 0.70), ss(-1, 2, low) * 0.6)
    chip_n = S(beta=2.0, fmin=6, fmax=300)
    chips = ss(1.85, 1.95, chip_n + 0.4 * S(beta=1.4, fmin=40, fmax=600))
    under = ss(1.6, 1.7, chip_n)      # older green layer exposed around the chips
    c = lerp(paint, col(0.48, 0.52, 0.43), under * 0.9)
    c = lerp(c, wood, chips)
    edge = np.clip(np.abs(blur(under, 1.0) - under) * 3, 0, 1)
    c = lerp(c, col(0.25, 0.22, 0.18), edge * 0.5)
    grime = ss(-0.5, 2.0, S(beta=2.2, fmin=2, fmax=100))
    c = tint(c, col(0.55, 0.50, 0.42), grime * 0.55)
    specks = ss(2.2, 2.9, S(beta=0.8, fmin=60, fmax=900))
    c = lerp(c, col(0.15, 0.13, 0.11), specks * 0.7)
    hmm = 0.06 * brush + 0.15 * (1 - under) + 0.12 * (1 - chips) + 0.05 * late * chips + 0.03 * fibre
    r = lerp(np.full(shape, 0.5) + 0.05 * brush * 0.3, 0.86, chips) + 0.12 * grime
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, px, px, strength=1.6),
                rough=np.clip(r, 0.05, 1))


# =========================================================================== old dark wood (furniture)
def old_wood(N=1024, T=1.0, seed=51):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    late, fibre = wood_grain(U, V, rng, shape, size, rings_per_m=230, warp_amt=0.02, along="U")
    late2, _ = wood_grain(U, V, rng, shape, size, rings_per_m=60, warp_amt=0.05, along="U", fine=0)
    c = lerp(col(0.27, 0.19, 0.13), col(0.13, 0.09, 0.06), np.clip(late * 0.7 + 0.15 * late2, 0, 1))
    c *= (1 + 0.09 * fibre)[..., None]
    low = S(beta=3.0, fmin=0.7, fmax=20)
    c *= (1 + 0.08 * low)[..., None]
    worn = ss(0.8, 2.2, S(beta=2.4, fmin=2, fmax=80))
    c = lerp(c, c * 1.4 + col(0.05, 0.045, 0.04), worn * 0.35)
    strokes = []
    for _ in range(260):
        p0 = (rng.uniform(0, N), rng.uniform(0, N))
        a = rng.uniform(0, math.pi)
        strokes.append((random_walk(rng, p0, a, rng.uniform(10, 140), 3.0, 0.03),
                        rng.uniform(0.3, 1), rng.uniform(0.4, 1.2)))
    scr = draw_strokes(shape, strokes)
    c = lerp(c, c * 1.4 + 0.04, scr * 0.3)
    dust = ss(-0.6, 1.8, S(beta=2.0, fmin=2, fmax=150))
    c = lerp(c, col(0.36, 0.34, 0.31), dust * 0.45)
    rings = ss(0.0, 0.004, np.abs(np.sqrt(wrapd(U - 0.3, T) ** 2 + wrapd(V - 0.6, T) ** 2) - 0.035))
    c = tint(c, col(0.75, 0.7, 0.62), (1 - rings) * 0.6)      # an old cup ring
    hmm = 0.05 * late + 0.04 * fibre - 0.1 * scr + 0.15 * low * 0.2
    r = 0.55 + 0.2 * worn + 0.2 * dust + 0.1 * scr + 0.03 * fibre
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, px, px, strength=1.5),
                rough=np.clip(r, 0.05, 1))


# =========================================================================== rusty painted iron
def rusty_iron(N=1024, T=0.5, seed=61):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    low = S(beta=2.8, fmin=1, fmax=30)
    mid = S(beta=2.0, fmin=5, fmax=300)
    fine = S(beta=1.0, fmin=80, fmax=900)
    paint = col(0.72, 0.70, 0.62) * (1 + 0.03 * mid[..., None])
    paint = tint(paint, col(0.9, 0.84, 0.70), ss(-1, 2, low) * 0.6)
    rust_n = mid + 0.5 * S(beta=1.4, fmin=30, fmax=700)
    chip = ss(1.15, 1.3, rust_n)
    bare = np.clip(np.abs(blur(chip, 1.5) - chip) * 3, 0, 1) * 0.6
    rust_c = lerp(col(0.40, 0.19, 0.07), col(0.16, 0.08, 0.04), ss(-1.5, 1.5, fine + 0.6 * low))
    rust_c = lerp(rust_c, col(0.55, 0.30, 0.12), ss(1.2, 2.5, fine) * 0.6)
    bleed = np.clip(blur(chip, 8) * 1.3, 0, 1) * (1 - chip)     # rust bloom around chips
    c = tint(paint, col(0.78, 0.55, 0.38), bleed * 0.9)
    c = lerp(c, rust_c, chip)
    c = lerp(c, col(0.30, 0.29, 0.28), bare * (1 - chip))
    grime = ss(-0.5, 2.2, S(beta=2.0, fmin=2, fmax=100))
    c = tint(c, col(0.55, 0.5, 0.45), grime * 0.5)
    hmm = 0.1 * (1 - chip) - 0.1 * chip + 0.06 * fine * chip + 0.04 * mid
    pits = ss(2.0, 2.8, fine) * chip
    hmm -= 0.08 * pits
    r = lerp(np.full(shape, 0.42), 0.88, chip) + 0.1 * grime
    r = lerp(r, 0.45, bare * (1 - chip))
    metal = bare * (1 - chip) * 0.8
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, px, px, strength=2.0),
                rough=np.clip(r, 0.05, 1), metal=np.clip(metal, 0, 1))


# =========================================================================== stained mattress ticking
def mattress(NW=1024, NH=2048, W=1.0, H=2.0, seed=71):
    rng = np.random.default_rng(seed)
    shape = (NH, NW)
    size = (W, H)
    U, V = grid(shape, size)
    pxu, pxv = W / NW, H / NH
    S = lambda **k: spectral(shape, size, rng, **k)
    sp = 0.055
    x = (U % sp) / sp
    stripe = ss(0.04, 0.06, x) * (1 - ss(0.26, 0.28, x))
    thin = np.exp(-((x - 0.5) / 0.025) ** 2) + np.exp(-((x - 0.62) / 0.015) ** 2)
    weave = 0.5 + 0.5 * np.sin(TAU * (U + V) / 0.004)
    c = col(0.70, 0.67, 0.58) * (1 + 0.04 * weave[..., None])
    c = lerp(c, col(0.40, 0.43, 0.47), stripe * 0.55)
    c = lerp(c, col(0.45, 0.42, 0.40), np.clip(thin, 0, 1) * 0.6)
    low = S(beta=2.8, fmin=0.5, fmax=20)
    c = tint(c, col(0.92, 0.85, 0.68), ss(-1, 2, low) * 0.7)
    st = np.zeros(shape)
    tide = np.zeros(shape)
    for i in range(7):
        cu, cv = rng.uniform(0.05, 0.95), rng.uniform(0.1, 1.9)
        w1 = S(beta=2.5, fmin=2, fmax=60) * 0.05
        w2 = S(beta=2.5, fmin=2, fmax=60) * 0.05
        fld = blob_field(U, V, cu, cv, rng.uniform(0.07, 0.25), rng.uniform(0.07, 0.3), w1, w2, W)
        st = np.maximum(st, ss(-0.05, 0.5, fld) * rng.uniform(0.5, 1.0))
        tide = np.maximum(tide, np.exp(-(fld / 0.015) ** 2) + 0.25 * np.exp(-((fld - 0.3) / 0.012) ** 2))
    c = tint(c, col(0.75, 0.58, 0.36), st * 0.9)
    c = tint(c, col(0.50, 0.33, 0.20), tide * 0.8)
    # one old dark stain
    w1 = S(beta=2.5, fmin=2, fmax=80) * 0.04
    dk = blob_field(U, V, 0.58, 1.15, 0.16, 0.12, w1, w1, W)
    c = tint(c, col(0.34, 0.19, 0.12), ss(-0.05, 0.4, dk) * 0.95)
    c = tint(c, col(0.25, 0.12, 0.08), np.exp(-(dk / 0.02) ** 2) * 0.8)
    mold = ss(1.6, 2.6, S(beta=1.0, fmin=30, fmax=600)) * ss(0.2, 1.5, S(beta=3, fmin=1, fmax=10))
    c = tint(c, col(0.2, 0.22, 0.16), mold * 0.9)
    dirt = ss(-0.5, 2, S(beta=2.2, fmin=1, fmax=60))
    c = tint(c, col(0.7, 0.66, 0.6), dirt * 0.4)
    # tufting buttons + quilting
    tu, tv = 0.16, 0.18
    du = wrapd(U - tu / 2, tu)
    dv = wrapd(V - tv / 2, tv)
    rr = np.sqrt(du ** 2 + dv ** 2)
    tuft = np.exp(-(rr / 0.018) ** 2)
    pleat = np.exp(-(rr / 0.05) ** 2) * (0.5 + 0.5 * np.cos(np.arctan2(dv, du) * 6))
    hmm = -7.0 * tuft - 1.5 * pleat + 0.08 * weave + 1.5 * low
    c = lerp(c, c * 0.6, tuft[..., None] * np.ones(3) * 0.6)
    r = 0.93 - 0.08 * st
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, pxu, pxv, strength=1.0, pre_blur=1.0),
                rough=np.clip(r, 0.05, 1))


# =========================================================================== paper sheet + backing
def paper_sheet(N=1024, seed=81):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (0.21, 0.297)
    U, V = grid(shape, size)
    pxu, pxv = 0.21 / N, 0.297 / N
    S = lambda **k: spectral(shape, size, rng, **k)
    low = S(beta=2.6, fmin=4, fmax=100)
    c = col(0.66, 0.61, 0.50) * (1 + 0.06 * low[..., None])
    c = tint(c, col(0.75, 0.70, 0.62), ss(-0.5, 2.0, S(beta=2.0, fmin=8, fmax=200)) * 0.6)
    # handwriting-ish lines
    lh = 0.0075
    row = np.floor((0.297 - V) / lh)
    yv = ((0.297 - V) % lh) / lh
    inrow = np.exp(-((yv - 0.55) / 0.12) ** 2)
    seg = spectral(shape, size, rng, beta=1.0, fmin=40, fmax=900, stretch=(1.0, 50.0))
    wordmask = ss(-0.2, 0.2, S(beta=1.2, fmin=30, fmax=400, stretch=(1.0, 40.0)))
    margin = (U > 0.022) & (U < 0.19) & (V < 0.27) & (V > 0.03)
    endline = U < (0.19 - 0.06 * (np.sin(row * 7.3) * 0.5 + 0.5))
    ink = inrow * wordmask * margin * endline * ss(0.0, 0.8, 0.5 + 0.5 * np.sin(U / 0.0012 + seg * 3))
    c = lerp(c, col(0.22, 0.20, 0.24), np.clip(ink, 0, 1) * 0.75)
    st = np.zeros(shape)
    for _ in range(3):
        w1 = S(beta=2.5, fmin=10, fmax=200) * 0.01
        fld = blob_field(U, V, rng.uniform(0, 0.21), rng.uniform(0, 0.3), rng.uniform(0.02, 0.07),
                         rng.uniform(0.02, 0.07), w1, w1, 0.21)
        st = np.maximum(st, ss(-0.05, 0.4, fld) * 0.7 + np.exp(-(fld / 0.02) ** 2) * 0.5)
    c = tint(c, col(0.72, 0.58, 0.38), np.clip(st, 0, 1))
    edge = np.minimum(np.minimum(U, 0.21 - U), np.minimum(V, 0.297 - V))
    c = tint(c, col(0.75, 0.65, 0.48), ss(0.012, 0.0, edge))
    fold = np.exp(-((V - 0.099) / 0.0008) ** 2) + np.exp(-((V - 0.198) / 0.0008) ** 2)
    hmm = 0.03 * S(beta=1.5, fmin=50, fmax=900) - 0.15 * fold + 0.1 * low
    c = tint(c, col(0.8, 0.75, 0.68), fold * 0.6)
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, pxu, pxv, strength=1.0),
                rough=np.full(shape, 0.86))


def paper_backing(N=512, T=0.5, seed=91):
    rng = np.random.default_rng(seed)
    shape = (N, N)
    size = (T, T)
    U, V = grid(shape, size)
    px = T / N
    S = lambda **k: spectral(shape, size, rng, **k)
    low = S(beta=2.6, fmin=2, fmax=40)
    fib = S(beta=1.0, fmin=60, fmax=500)
    c = col(0.66, 0.62, 0.53) * (1 + 0.05 * low[..., None] + 0.03 * fib[..., None])
    paste = ss(0.5, 1.5, S(beta=2.2, fmin=6, fmax=150))
    c = tint(c, col(0.85, 0.80, 0.70), paste * 0.5)
    plaster = ss(1.5, 2.2, S(beta=1.6, fmin=20, fmax=300))
    c = lerp(c, col(0.78, 0.76, 0.72), plaster * 0.8)
    hmm = 0.04 * fib + 0.3 * low + 0.15 * plaster
    return dict(base=np.clip(c, 0, 1), normal=height_to_normal(hmm, px, px, strength=1.0),
                rough=np.clip(0.9 - 0.1 * paste, 0, 1))


# =========================================================================== cobweb (RGBA)
def cobweb(N=1024, seed=101):
    """Tangled, dusty corner web.  Threads anchor on the U=0, U=1 and V=1 borders (the two walls and
    the ceiling for a corner quad); the V=0 border hangs free.  Alpha carries the threads."""
    rng = np.random.default_rng(seed)
    shape = (N, N)

    def edge_pt():
        k = rng.choice(3, p=[0.33, 0.33, 0.34])
        t = rng.beta(1.3, 1.0)                 # biased toward the top corner region
        if k == 0:
            return np.array([N * (0.25 + 0.75 * t), 2.0])          # (y=row, x=col) on U=0
        if k == 1:
            return np.array([N * (0.25 + 0.75 * t), N - 3.0])      # on U=1
        return np.array([N - 3.0, N * rng.uniform(0.05, 0.95)])   # on V=1

    def sag_line(a, b, sag):
        ts = np.linspace(0, 1, 12)[:, None]
        pts = a + (b - a) * ts
        pts[:, 0] -= sag * np.sin(np.pi * ts[:, 0]) * np.linalg.norm(b - a)   # rows: sag downward (-V)
        return pts

    strokes = []
    # sheet hub region near the upper middle
    hubs = [np.array([N * rng.uniform(0.6, 0.85), N * rng.uniform(0.3, 0.7)]) for _ in range(5)]
    for _ in range(140):
        a = edge_pt()
        b = hubs[rng.integers(len(hubs))] + rng.normal(0, N * 0.08, 2) if rng.random() < 0.6 else edge_pt()
        strokes.append((sag_line(a, b, rng.uniform(0.0, 0.08)), rng.uniform(0.35, 0.9), rng.uniform(0.5, 0.9)))
    for _ in range(90):        # short tangles near the hubs
        h = hubs[rng.integers(len(hubs))]
        a = h + rng.normal(0, N * 0.12, 2)
        b = a + rng.normal(0, N * 0.08, 2)
        strokes.append((sag_line(a, b, 0.05), rng.uniform(0.3, 0.7), 0.5))
    for _ in range(12):        # strands hanging down from the sheet
        a = hubs[rng.integers(len(hubs))] + rng.normal(0, N * 0.1, 2)
        L = rng.uniform(0.15, 0.5) * N
        pts = np.array([a + np.array([-L * t, 8 * np.sin(t * 5 + rng.uniform(0, 6))]) for t in np.linspace(0, 1, 10)])
        strokes.append((pts, rng.uniform(0.4, 0.8), 0.6))
    a = draw_strokes(shape, strokes, sigma=0.6) * 1.3
    rng2 = np.random.default_rng(seed + 1)
    sheet = spectral(shape, (1, 1), rng2, beta=1.4, fmin=2, fmax=250)
    yy, xx = np.mgrid[0:N, 0:N] / N
    dens = np.zeros(shape)
    for h in hubs:
        dens = np.maximum(dens, np.exp(-(((yy - h[0] / N) / 0.18) ** 2 + ((xx - h[1] / N) / 0.25) ** 2)))
    dens = np.maximum(dens, ss(0.75, 1.0, yy) * 0.8)                   # dusty along the ceiling
    a = np.maximum(a, dens * np.clip(0.18 + 0.22 * sheet, 0, 1) * blur(np.clip(a, 0, 1), 6) * 10)
    a = np.maximum(a, dens * np.clip(0.06 + 0.1 * sheet, 0, 1))
    clumps = ss(2.0, 2.7, spectral(shape, (1, 1), rng2, beta=1.0, fmin=30, fmax=400)) * np.clip(a * 3, 0, 1)
    a = np.clip(a + clumps * 0.5, 0, 1) * ss(0.0, 0.12, yy) * ss(1.0, 0.985, yy) * ss(0.0, 0.012, np.minimum(xx, 1 - xx))           # free bottom edge fades out
    c = np.broadcast_to(col(0.62, 0.61, 0.58), (*shape, 3)).copy()
    c = lerp(c, col(0.42, 0.40, 0.37), np.clip(clumps + dens * 0.4, 0, 1))
    return dict(base=c, alpha=np.clip(a, 0, 1) * 0.85, rough=np.full(shape, 0.8),
                normal=np.broadcast_to(col(0.5, 0.5, 1.0), (*shape, 3)).copy())


# =========================================================================== grime decals (RGBA atlas)
def decals(N=1024, seed=111):
    """2x2 atlas: [0,0] picture-frame ghost, [1,0] handprint, [0,1] smeared handprints, [1,1] grime."""
    rng = np.random.default_rng(seed)
    h = N // 2
    shape = (h, h)
    out_a = np.zeros((N, N))
    U, V = grid(shape, (1.0, 1.0))
    S = lambda **k: spectral(shape, (1.0, 1.0), rng, **k)

    # ghost of a picture frame: darker surround, clean inside; fades at the quad border
    inside = ss(0.0, 0.015, np.minimum(np.minimum(U - 0.18, 0.82 - U), np.minimum(V - 0.15, 0.85 - V)))
    outer = ss(0.0, 0.18, np.minimum(np.minimum(U, 1 - U), np.minimum(V, 1 - V)))
    ghost = (1 - inside) * outer * (0.22 + 0.1 * S(beta=2, fmin=2, fmax=60))
    ghost += np.exp(-((V - 0.15) / 0.02) ** 2) * (np.abs(U - 0.5) < 0.32) * 0.35   # dust ledge under it
    out_a[:h, :h] = np.clip(ghost, 0, 1)

    def hand(cx, cy, s, ang, smear=0.0):
        a = np.zeros(shape)
        ca, sa = math.cos(ang), math.sin(ang)
        x = ((U - cx) * ca + (V - cy) * sa) / s
        y = (-(U - cx) * sa + (V - cy) * ca) / s
        y2 = y + smear * np.clip(-x * 0 + 1, 0, 1) * 0
        palm = np.sqrt((x / 0.42) ** 2 + ((y + 0.15) / 0.5) ** 2)
        a = np.maximum(a, ss(1.0, 0.75, palm))
        for fx, fy, L, fa in ((-0.33, 0.35, 0.45, 0.35), (-0.14, 0.45, 0.62, 0.08), (0.06, 0.47, 0.68, -0.02),
                              (0.24, 0.42, 0.6, -0.12), (0.42, 0.2, 0.45, -0.5)):
            dx, dy = x - fx, y2 - fy
            xr = dx * math.cos(fa) + dy * math.sin(fa)
            yr = -dx * math.sin(fa) + dy * math.cos(fa)
            t = np.clip(yr / L, 0, 1)
            d = np.sqrt(xr ** 2 + (yr - t * L) ** 2)
            a = np.maximum(a, ss(0.1, 0.06, d))
        return a

    n = S(beta=1.6, fmin=8, fmax=200)
    hp = hand(0.5, 0.45, 0.42, 0.15) * np.clip(0.7 + 0.35 * n, 0, 1)
    sm = blur(hp, (40, 3))          # smear downward
    hp = np.maximum(hp * 0.85, np.clip(sm * 1.4, 0, 1) * ss(0.6, 0.2, V) * 0.6)
    out_a[:h, h:] = np.clip(hp, 0, 1) * 0.6
    hp2 = np.maximum(hand(0.32, 0.6, 0.3, 0.3), hand(0.66, 0.42, 0.32, -0.2)) * np.clip(0.6 + 0.4 * n, 0, 1)
    hp2 = np.maximum(hp2, np.clip(blur(hp2, (60, 2)) * 1.5, 0, 1) * 0.5)
    out_a[h:, :h] = np.clip(hp2, 0, 1) * 0.55
    gr = ss(-0.2, 1.5, S(beta=2.2, fmin=2, fmax=100)) * ss(0.5, 0.15, np.sqrt((U - 0.5) ** 2 + (V - 0.5) ** 2))
    out_a[h:, h:] = np.clip(gr, 0, 1) * 0.8
    c = np.broadcast_to(col(0.16, 0.13, 0.10), (N, N, 3)).copy()
    c[:h, h:] = col(0.20, 0.11, 0.07)
    c[h:, :h] = col(0.18, 0.10, 0.07)
    return dict(base=c, alpha=out_a, rough=np.full((N, N), 0.7),
                normal=np.broadcast_to(col(0.5, 0.5, 1.0), (N, N, 3)).copy())
