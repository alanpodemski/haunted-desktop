// Walkable-floor navigation for the creature. At start the floor of the hallway and its rooms is sampled on a
// 0.15 m grid: a cell is walkable if a body of the creature's radius standing there touches no static collider
// (walls, jambs, furniture; door leaves and boxes are left out, it pushes those). Routes are A* over that grid,
// then pulled taut (a point is skipped whenever the straight line past it stays on walkable cells).

import { BOUNDS } from './layout.js';

export function createNav(physics, { radius = 0.27, cell = 0.15 } = {}) {
  const { RAPIER, world } = physics;
  const x0 = BOUNDS.x0 - 0.2, z0 = BOUNDS.z0 - 0.2;
  const nx = Math.ceil((BOUNDS.x1 + 0.2 - x0) / cell), nz = Math.ceil((BOUNDS.z1 + 0.2 - z0) / cell);
  const free = new Uint8Array(nx * nz);
  const shape = new RAPIER.Cylinder(0.55, radius);
  const rot = { x: 0, y: 0, z: 0, w: 1 };
  const flags = RAPIER.QueryFilterFlags.EXCLUDE_DYNAMIC | RAPIER.QueryFilterFlags.EXCLUDE_KINEMATIC;
  world.step();                                           // make sure the query structures are built
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const p = { x: x0 + (i + 0.5) * cell, y: 0.62, z: z0 + (j + 0.5) * cell };
      // standing room (not inside a wall) and a floor under it
      const hitFloor = world.castRay(new RAPIER.Ray({ x: p.x, y: 0.5, z: p.z }, { x: 0, y: -1, z: 0 }), 0.8, true, flags);
      free[j * nx + i] = hitFloor && !world.intersectionWithShape(p, rot, shape, flags) ? 1 : 0;
    }
  }
  const ci = (x) => Math.floor((x - x0) / cell), cj = (z) => Math.floor((z - z0) / cell);
  const ok = (i, j) => i >= 0 && j >= 0 && i < nx && j < nz && free[j * nx + i] === 1;
  const centre = (i, j) => [x0 + (i + 0.5) * cell, z0 + (j + 0.5) * cell];

  /** the walkable cell nearest to a point (spiral search) */
  function nearest(x, z) {
    let i = ci(x), j = cj(z);
    if (ok(i, j)) return [i, j];
    for (let r = 1; r < 25; r++) {
      let best = null, bd = Infinity;
      for (let dj = -r; dj <= r; dj++) for (let di = -r; di <= r; di++) {
        if (Math.max(Math.abs(di), Math.abs(dj)) !== r || !ok(i + di, j + dj)) continue;
        const [cx, cz] = centre(i + di, j + dj), d = (cx - x) ** 2 + (cz - z) ** 2;
        if (d < bd) { bd = d; best = [i + di, j + dj]; }
      }
      if (best) return best;
    }
    return [i, j];
  }
  /** straight line from a to b over walkable cells only */
  function clear(ax, az, bx, bz) {
    const d = Math.hypot(bx - ax, bz - az), n = Math.ceil(d / (cell * 0.5));
    for (let k = 0; k <= n; k++) {
      const t = k / Math.max(1, n);
      if (!ok(ci(ax + (bx - ax) * t), cj(az + (bz - az) * t))) return false;
    }
    return true;
  }

  // A* (8-connected, no corner cutting) with a binary heap
  const g = new Float32Array(nx * nz), from = new Int32Array(nx * nz), closed = new Uint8Array(nx * nz);
  const heapK = new Int32Array(nx * nz * 8), heapF = new Float32Array(nx * nz * 8);
  function astar(a, b) {
    g.fill(Infinity); closed.fill(0); from.fill(-1);
    const start = a[1] * nx + a[0], goal = b[1] * nx + b[0];
    let n = 0;
    const push = (k, f) => {
      let i = n++;
      while (i > 0) { const p = (i - 1) >> 1; if (heapF[p] <= f) break; heapK[i] = heapK[p]; heapF[i] = heapF[p]; i = p; }
      heapK[i] = k; heapF[i] = f;
    };
    const pop = () => {
      const top = heapK[0], lk = heapK[--n], lf = heapF[n];
      let i = 0;
      while (true) {
        let c = 2 * i + 1; if (c >= n) break;
        if (c + 1 < n && heapF[c + 1] < heapF[c]) c++;
        if (heapF[c] >= lf) break;
        heapK[i] = heapK[c]; heapF[i] = heapF[c]; i = c;
      }
      heapK[i] = lk; heapF[i] = lf;
      return top;
    };
    const h = (k) => Math.hypot((k % nx) - b[0], Math.floor(k / nx) - b[1]);
    g[start] = 0; push(start, h(start));
    while (n > 0 && n < heapK.length - 8) {
      const cur = pop();
      if (cur === goal) break;
      if (closed[cur]) continue;
      closed[cur] = 1;
      const ci0 = cur % nx, cj0 = Math.floor(cur / nx);
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        if (!di && !dj) continue;
        const ni = ci0 + di, nj = cj0 + dj;
        if (!ok(ni, nj) || (di && dj && (!ok(ci0 + di, cj0) || !ok(ci0, cj0 + dj)))) continue;
        const nk = nj * nx + ni, cost = g[cur] + (di && dj ? 1.4142 : 1);
        if (cost < g[nk]) { g[nk] = cost; from[nk] = cur; push(nk, cost + h(nk)); }
      }
    }
    if (from[goal] === -1 && goal !== start) return null;
    const out = [];
    for (let k = goal; k !== -1; k = from[k]) { out.push(centre(k % nx, Math.floor(k / nx))); if (k === start) break; }
    return out.reverse();
  }

  return {
    walkable: (x, z) => ok(ci(x), cj(z)),
    /** the nearest place it can stand */
    snap(x, z) { const [i, j] = nearest(x, z); return centre(i, j); },
    /** waypoints from a to b around walls and furniture, pulled taut; [b] if the way is straight */
    route(ax, az, bx, bz) {
      if (clear(ax, az, bx, bz)) return [[bx, bz]];
      const a = nearest(ax, az), b = nearest(bx, bz);
      const cells = astar(a, b);
      if (!cells) return [[bx, bz]];
      cells.push([bx, bz]);
      // string pulling
      const out = [];
      let px = ax, pz = az, k = 0;
      while (k < cells.length - 1) {
        let far = k + 1;
        while (far + 1 < cells.length && clear(px, pz, cells[far + 1][0], cells[far + 1][1])) far++;
        out.push(cells[far]);
        [px, pz] = cells[far];
        k = far;
      }
      if (!out.length || out[out.length - 1][0] !== bx || out[out.length - 1][1] !== bz) out.push([bx, bz]);
      return out;
    },
    stats() { let n = 0; for (const v of free) n += v; return { cells: nx * nz, walkable: n }; },
  };
}
