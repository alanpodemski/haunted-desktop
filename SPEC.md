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
