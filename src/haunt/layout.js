// Room layout shared by the renderer, the flashlight ray caster and the creature (see SPEC.md).
// glTF / three.js space: metres, +Y up, the camera looks down -Z.

export const ROOM = { x0: -2.6, x1: 2.6, y0: 0, y1: 2.75, z0: -4.2, z1: 0.8 };
export const WALL_T = 0.14;
export const DOOR = { cx: -0.55, w: 0.9, h: 2.05 };
export const CORRIDOR = { x0: -4.5, x1: 3.5, y0: 0, y1: 2.6, z0: -5.75, z1: ROOM.z0 - WALL_T };
export const CORRIDOR_LANE_Z = -5.0;

export const CAMERA = { pos: [0.25, 1.58, 0.35], look: [-0.2, 1.25, -4.2], fov: 50 };

const doorX0 = DOOR.cx - DOOR.w / 2, doorX1 = DOOR.cx + DOOR.w / 2;

/** Distance along a ray (o inside box b) to where it leaves the box, and the face it leaves through. */
function exitBox(o, d, b) {
  let t = Infinity, axis = -1, sign = 0;
  const lo = [b.x0, b.y0, b.z0], hi = [b.x1, b.y1, b.z1];
  for (let i = 0; i < 3; i++) {
    if (Math.abs(d[i]) < 1e-9) continue;
    const ti = ((d[i] > 0 ? hi[i] : lo[i]) - o[i]) / d[i];
    if (ti < t) { t = ti; axis = i; sign = d[i] > 0 ? 1 : -1; }
  }
  return { t, axis, sign };
}

/**
 * Where a ray from inside the room first hits a wall, floor or ceiling, looking through the doorway into the
 * corridor when it passes the opening. Props are ignored: the light sits near the eye, so aiming at the wall
 * behind a chair puts the beam on the chair as well.
 * Returns { point: [x,y,z], normal: [x,y,z], dist, inCorridor }.
 */
export function castRoom(o, d) {
  const r = exitBox(o, d, ROOM);
  const p = [o[0] + d[0] * r.t, o[1] + d[1] * r.t, o[2] + d[2] * r.t];
  const throughDoor = r.axis === 2 && r.sign < 0 && p[0] > doorX0 && p[0] < doorX1 && p[1] < DOOR.h;
  if (!throughDoor) {
    const n = [0, 0, 0]; n[r.axis] = -r.sign;
    return { point: p, normal: n, dist: r.t, inCorridor: false };
  }
  // through the wall thickness: the jambs and the head of the opening
  const tWall = (CORRIDOR.z1 - o[2]) / d[2];
  const q = [o[0] + d[0] * tWall, o[1] + d[1] * tWall, CORRIDOR.z1];
  if (q[0] < doorX0 || q[0] > doorX1 || q[1] > DOOR.h) {
    // hits a jamb or the head inside the reveal
    let t = tWall, n = [0, 0, 1];
    if (q[0] < doorX0) { t = (doorX0 - o[0]) / d[0]; n = [1, 0, 0]; }
    else if (q[0] > doorX1) { t = (doorX1 - o[0]) / d[0]; n = [-1, 0, 0]; }
    if (q[1] > DOOR.h) { const th = (DOOR.h - o[1]) / d[1]; if (th < t) { t = th; n = [0, -1, 0]; } }
    return { point: [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t], normal: n, dist: t, inCorridor: false };
  }
  const c = exitBox(q, d, CORRIDOR);
  const t = tWall + c.t;
  const n = [0, 0, 0]; n[c.axis] = -c.sign;
  return { point: [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t], normal: n, dist: t, inCorridor: true };
}
