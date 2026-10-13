# Haunted Desktop

Your wallpaper is a dark room now. You have a flashlight. Something lives in the corridor.

It runs in the browser on a fake macOS desktop. The wallpaper is a live three.js scene: an abandoned room seen from
one fixed spot, with an open doorway onto a corridor. The only light is the flashlight, and it points wherever your
cursor is. Every so often something goes past the doorway. Sometimes it stops and waits in the dark until you find it.

**Play it: https://deskhaunt.vercel.app**

![Caught in the light](docs/hero.jpg)

## Controls

| Input | What it does |
|---|---|
| Mouse | Aim the flashlight |
| F | Flashlight on or off |
| Click anywhere | Turn the sound on |
| N | Sound on or off |
| Space | Pause |
| 1 to 7 | Make it happen now: dash, crawl, walk, drag, watch, intrude, peek (for recording) |

URL options: `?nohud` hides the hint, `?hq` renders at full Retina resolution, `?low` renders below CSS resolution.

## What it does

- **Flashlight.** A shadow-casting spotlight held a little right of and below your eye, with a reflector beam
  profile (hot centre, ring, dim corona, faint spill). The hand is a damped spring with a little tremor, so the beam
  lags and settles. A second light at the beam's hit point re-emits the light the lit patch reflects, which is what
  dimly fills a real room around a torch beam.
- **Air.** Dust motes only show where the beam crosses them, brightest when they are between you and the light.
  A ray-marched haze pass adds the faint visible cone, with the shadow map so furniture casts shadows into it.
- **The thing in the corridor.** Seven events: it sprints past, scuttles past on all fours, shuffles past slowly,
  drags itself along the floor, stands in the doorway in the dark, or (rarely) comes into the room. If the beam lands
  on it, it turns to you, screams and runs. Its ground speed comes from each animation's own root motion, so its
  feet do not slide.
- **Sound.** Synthesised with WebAudio, no samples: room tone, settling floorboards, footsteps panned in 3D and
  muffled when they come through the wall, a sting when you catch it.
- **Camera.** Grain, vignette and a little chromatic aberration at the edges.
- **Laptop friendly.** Renders at CSS-pixel resolution, 60 fps while something moves and 30 fps when it is quiet,
  and lowers its own render scale if the GPU takes longer than 7 ms a frame.

## Run it locally

```bash
npm install
npm run dev
```

Then open http://localhost:5175.

## How it's built

- `src/haunt/`: the three.js scene (`scene.js`), flashlight, dust, haze, post-processing, the creature's events and
  the sound. `layout.js` holds the room's dimensions, and `SPEC.md` the contract the assets follow.
- `src/desktop/`: the fake macOS desktop in plain DOM and CSS, shared with Desktop Roomba.
- `blender/room.py` and `room_tex.py`: build the room, corridor and props procedurally, generate every texture with
  numpy (nothing downloaded), bake ambient occlusion and export `public/models/room.glb`.
- `blender/mixamo.py`: turns Mixamo FBX downloads into `public/models/creature.glb` and `creature.json`.
- `scripts/fake-desktop.py`: makes the made-up desktop files and renders their real Finder icons.

## Credits and disclaimer

Made by Alan Podemski, built with Claude Code. The creature is the Prisoner B Styperek character with zombie
animations from [Mixamo](https://www.mixamo.com) (Adobe), used under the Mixamo terms. The character and
animations are not covered by this repository's license.

This is a fan project for fun. It is not affiliated with or endorsed by Apple or Adobe. macOS and Apple app icons
are trademarks and property of Apple Inc.

The code is MIT licensed. See [LICENSE](LICENSE).
