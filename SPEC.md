# Haunted Desktop — spec

A fake macOS desktop (menu bar, Dock, Halloween-flavoured desktop icons) whose wallpaper is a live three.js scene:
a pitch-black, abandoned room seen from one fixed camera. The only light is a flashlight that points where the
cursor is. In the back wall is an open doorway (a frame, no door) onto a dark corridor. From time to time something
runs past the doorway, crawls across it, or stands in it and bolts when the beam finds it.

Quality bar: it should read like a still from a modern horror game (Amnesia, Outlast, P.T.), not a three.js demo.
Real PBR textures with detail at 1–2 m viewing distance, contact shadows/AO in corners, believable materials
(dusty matte plaster, worn varnished wood, damp stains). Everything is lit by one spotlight, so normal and roughness
maps carry most of the realism.

## Units and axes (three.js / glTF space)

Metres. +Y up. The camera looks down -Z. Blender scripts author in Blender space (Z up) and let the glTF exporter
convert: Blender (x, y, z) → glTF (x, z, -y). So Blender -Y is glTF +Z (towards the camera).

## Room layout (glTF space)

| Thing | Where |
|---|---|
| Room interior | x ∈ [-2.6, 2.6], y ∈ [0, 2.75], z ∈ [-4.2, 0.8] |
| Camera | (0.25, 1.58, 0.35), looking at about (−0.2, 1.25, −4.2), vertical FOV ≈ 50° |
| Back wall | inner face at z = −4.2, thickness 0.14 m (outer face z = −4.34) |
| Doorway | in the back wall, centred x = −0.55, clear opening 0.90 m wide × 2.05 m tall, floor to top. No door leaf, but keep the hinge side's paint shadow / two old hinge plates on the casing. Wooden casing (trim) about 9 cm wide on the room side. |
| Corridor | behind the doorway, runs along X: x ∈ [−4.5, 3.5], z ∈ [−5.75, −4.34], y ∈ [0, 2.6]. Floor, ceiling, far wall (z = −5.75), closed ends. Same materials, dirtier. |
| Creature path | along the corridor centre line z ≈ −5.0 (runs ±X), and the doorway itself (x = −0.55, z from −5.0 to −4.25) |

Keep x ∈ [0.9, 2.6] at the back fairly clear of tall props near the camera's right: the desktop icons sit over the
right edge of the screen. The doorway sits left of centre on purpose.

## Assets

### public/models/room.glb  (blender/room.py)
Static room + corridor + props, one glb, Draco compressed, textures embedded as JPEG (PNG only where alpha is needed).
Node names the runtime looks for:
- `Room` (walls, floor, ceiling, trim) and `Corridor`: receive shadows.
- Props: any names, cast + receive shadows. Suggested: old wooden chair facing the wall, iron bed frame with a
  stained mattress, a dresser, a hanging bare bulb on a cord (off), a fallen picture frame, scattered papers,
  a radiator, outlets/switch, cobwebs in a corner (alpha), peeling wallpaper strips.
- `Empty_FlashlightTarget_Default`: an empty where the beam rests before the cursor moves (on the back wall near
  the doorway).
Materials: PBR (base color, normal, roughness/metallic, occlusion if baked). Texture budget ≈ 25 MB total in the glb.

### public/models/creature.glb  (blender/creature.py)
One skinned humanoid, ~2.0 m tall when upright, gaunt, too-long limbs, hunched, pale grey wet-looking skin.
Feet at y = 0, root at the origin, faces +Z in glTF (Blender -Y). Eyes are a separate material named `Eyes`
so the runtime can make them catch the flashlight. Animations (in place, no root motion, loopable unless noted):
- `run` — fast, a bit wrong (too long strides, head steady), loop
- `crawl` — on all fours, scuttling, loop
- `idle` — standing, slight sway, head tilt, loop
- `peek` — leans out sideways from behind a wall edge (toward the model's own +X), holds, pulls back; one shot
- `flee` — sudden turn and first steps of a sprint; one shot, ends in a pose that blends into `run`
Also write public/models/creature.json with `{ "run": { "speed": m/s }, "crawl": { "speed": m/s }, ... }`, the
ground speed that matches each in-place cycle (so the feet do not skate).

---

# v2: the hallway (replaces the room)

The scene becomes a long, abandoned hallway seen from one end. Doors on both sides open onto small dark rooms; the
rooms have windows, so moonlight falls out of the open doorways onto the hallway floor in pale patches. At the far
end is a tall window (lightning outside now and then). The creature moves from room to room across the hallway.

## Layout (glTF space, metres, +Y up, camera looks down -Z)

| Thing | Where |
|---|---|
| Hallway interior | x ∈ [-1.25, 1.25], y ∈ [0, 2.9], z ∈ [-14.0, 0.8] |
| Camera | (0.3, 1.6, 0.2), looking at about (-0.1, 1.2, -14), vertical FOV ≈ 50° |
| Side doorways | 0.9 m wide × 2.1 m clear opening, wooden casing both sides, wall thickness 0.14 m. Left wall (x = -1.25) at z = -2.6, -6.6, -10.6; right wall (x = +1.25) at z = -4.6, -8.6, -12.2 (z is the opening's centre). |
| Side rooms | behind each doorway, about 2.6 m deep × 3 m wide, closed except for the doorway and one window on the far wall. Sparse furniture, dark. |
| Door leaves | at least three doorways have an old panel door hanging open at different angles (one barely ajar, one wide open); the others are empty openings, one with the door torn off and lying in the hallway. Each leaf is its own node `DoorLeaf_<id>` with its pivot at the hinge axis so it can be swung at runtime. |
| End window | far wall z = -14.0: a tall sash window, sill at 0.85 m, 1.1 m wide × 1.7 m tall, cracked glass panes, old frame. |
| Outside | a simple night backdrop behind every window: dark sky with clouds, bare tree silhouettes; a separate mesh `Outside` (unlit/emissive-ish material, very dark) so it reads as night, not as a wall. |

Keep the right edge of the frame (x > 0.9 near the camera) free of tall props: desktop icons sit there.

## Props
A worn runner carpet down the middle (stained, curling at the edges), wainscoting to ~1 m with peeling wallpaper above,
crown moulding, picture frames (some crooked, one fallen), a side table with a dead plant, a radiator, a toppled chair, an
old wheelchair or a gurney-like trolley near the far end, broken ceiling light fixtures every ~3 m, cobwebs, debris and
papers. Side rooms: an iron bed, a wardrobe, a chair facing the window, curtains (tattered, alpha) at the windows.

## Required node names (empties unless noted)
- `Hallway` (shell, receive shadows), `SideRoom_L1`, `SideRoom_L2`, `SideRoom_L3`, `SideRoom_R1`, `SideRoom_R2`, `SideRoom_R3`.
- `Door_L1` … `Door_R3`: an empty at each doorway's threshold centre, on the floor (y = 0), its local +Z pointing into
  the hallway. `Inside_L1` … `Inside_R3`: an empty on the floor about 1.2 m inside each side room, centred on the
  doorway (where something can stand unseen).
- `Window_L1` … `Window_R3` and `Window_End`: an empty at the centre of each window opening (inside face), local -Z
  pointing outwards (towards the moon). The runtime puts moonlight there.
- `Empty_FlashlightTarget_Default`: on a wall about 6 m down the hallway.
- `Colliders`: a parent node holding simple boxes (meshes named `COL_*`, invisible in the runtime) for walls, floor,
  ceiling and big furniture, so the physics does not need the render mesh. Openings must stay open.

## Materials
Reuse the wallpaper, plaster, floorboard and trim textures from blender/room_tex.py (same quality bar), plus the new
ones (carpet, door panels, window frames, glass with cracks and grime, curtains). Base colour, normal, roughness and
baked AO (glTF occlusion, UV1) on everything. Output: public/models/hallway.glb (Draco, JPEG textures, ≤ 30 MB).
