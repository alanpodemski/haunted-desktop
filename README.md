# Haunted Desktop

Your wallpaper is a dark room now. You have a flashlight, a camera and your files. Something lives in the corridor.

It runs in the browser on a fake macOS desktop. The wallpaper is a live three.js scene: an abandoned room seen from
one fixed spot, with an open doorway onto a corridor. The only light is the flashlight, and it points wherever your
cursor is. Every so often something goes past the doorway. Sometimes it stops and waits in the dark until you find it.
And sometimes it comes in. It only moves while it is not in your light.

**Play it: https://deskhaunt.vercel.app**

![Caught in the light](docs/hero.jpg)

## Controls

| Input | What it does |
|---|---|
| Mouse | Aim the flashlight |
| Drag a folder onto the floor | It becomes a moving box in the room. Barricade the door. Drop onto a box to stack. |
| Drag a `.usdz` file into the room | Use it: candle, road flare, salt, fresh batteries, music box (see below) |
| Drag a box | Push or carry it (heavy ones only slide) |
| Double-click a box | The file goes back to the desktop |
| Space | Camera flash. The photo lands on your desktop; double-click it to look. |
| F | Flashlight on or off |
| Click anywhere | Turn the sound on |
| N | Sound on or off |
| P | Pause |
| R | Tidy the icons |
| H | Make it come for you now |
| 1 to 7 | Make it happen now: dash, crawl, walk, drag, watch, intrude, peek (for recording) |

URL options: `?nohud` hides the hint, `?hq` renders at full Retina resolution, `?low` renders below CSS resolution.

## How to survive

Every couple of minutes it comes through the doorway for you. In the beam it freezes mid-step. While the beam is
somewhere else it walks; in the dark, or while the old torch flickers, it runs. The catch: the flashlight follows your
cursor, so every file you drag to build a barricade takes the light off it.

- **Barricade.** Boxes are real rigid bodies. A file's size sets its box's size and mass, from a 1 kg box for a text
  file to an 80 kg one for a disk. It pushes with a limited force, so a heavy pile stops it, and then it beats at it.
- **Flash.** A flash in its face drives it back out. The flash needs four seconds to recharge.
- **Battery.** The menu bar battery is the torch's. Two old alkaline cells: they drain while it burns, sag with
  continuous use, creep back when it rests, and the bulb dims and yellows as they fail (light ∝ V^3.4). The switch has a
  loose contact; a hard shake of the mouse reseats it.
- **Your things.** Folders are moving boxes (their icons are cardboard). The `.usdz` files are what you defend yourself
  with, shown with 3D thumbnails like Finder shows them:
  - `candle`: a 1.5 cd flame. It will not move inside its small pool of light. Burns about two minutes; knock it
    over and it goes out.
  - `road_flare`: red magnesium light for 30 s, bright enough to cast shadows across the room. It freezes anywhere near.
  - `salt`: poured as a line across its way. It will not step over it until it has scuffed it away (about 12 s).
  - `batteries`: fresh cells for the torch.
  - `music_box`: it plays a waltz that runs down. It goes to listen, and then it breaks it.
- **Bait.** A box left out in the corridor draws it: it comes for it, carries it off into the dark, and leaves you
  alone for a while. The file comes back later, chewed. Candy works fastest.
- If it reaches you, you will know.

The camera has another use. Take a few photos of the empty room and look at them.

## What it does

- **Flashlight.** A shadow-casting spotlight held a little right of and below your eye, with a reflector beam
  profile (hot centre, ring, dim corona, faint spill). The hand is a damped spring with a little tremor, so the beam
  lags and settles. A second light at the beam's hit point re-emits the light the lit patch reflects, which is what
  dimly fills a real room around a torch beam.
- **Air.** Dust motes only show where the beam crosses them, brightest when they are between you and the light.
  A ray-marched haze pass adds the faint visible cone, with the shadow map so furniture casts shadows into it.
- **Physics.** Rapier 3D: the room's walls and big furniture are static colliders, the boxes dynamic bodies with
  cardboard-on-wood friction, and the creature a 75 kg capsule that walks with a capped force. Your hand is a spring
  with a 380 N limit. Impacts make a thump scaled by the contact force.
- **Photos.** The flash is a short, bright light at the lens. The frame is saved as a JPEG with a date stamp and shown
  in a Quick Look style viewer. What it sometimes shows is posed for that one render only, never the live view.
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

- `src/haunt/`: the three.js scene (`scene.js`), flashlight, dust, haze, post-processing, physics and boxes, the
  camera, the creature's events and hunt, and the sound. `layout.js` holds the room's dimensions, and `SPEC.md` the contract the assets follow.
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
