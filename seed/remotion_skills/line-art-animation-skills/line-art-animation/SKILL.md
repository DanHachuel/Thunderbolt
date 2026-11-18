---
name: line-art-animation
description: Build animated line-art components in SVG and TypeScript — thin ink lines on paper, people and animals that walk, run, cycle and react, scenes with wind, lit windows and a day/night cycle, exported to video if needed. Use this whenever someone asks for a line art (or ink, pen, doodle, hand-drawn) animation, an animated illustration or scene component, little characters doing everyday things, a living street/village/shop/park, a day-night cycle illustration, "make it like this clip" for a drawn animation, or a video of such a component — even if they never say "SVG" or "line art".
version: 0.1.0
---

# Line-art animation

Animated illustration components: everything is drawn with one thin pen on paper,
built live in SVG from TypeScript, so it stays crisp at any size, responds to the
pointer, and can be stepped frame by frame for checking or video export.

This skill ships a small library (`lib/`, four dependency-free `.ts` files) and reference
notes (`references/`). In this Thunderbolt copy the library is already vendored at
`packages/remotion/src/compositions/lineart/lib/` and the composition `LineArtAnimation`
is registered in `packages/remotion/src/Root.tsx`. The upstream `examples/` and `scripts/`
folders are NOT part of this copy. Read `references/style.md` first, then build ONE figure
or one corner and show it before building the rest.

- walks that bob on a sine wave, feet that slide, gaits sped up to fit a time-lapse
- limbs drawn as closed tubes; ruler-straight lines; rigid clothes that ignore the legs
- a whole set of components built in one go that all look alike ("AI slop")
- interactions that feel like UI instead of the world reacting
- a page whose background changes with the scene ("looks like a video, not a component")
- reusing characters from a reference clip when asked for something new
- leftover props nobody asked for (they asked to remove hanging laundry)

## Workflow

1. **Pin the look** before anything moves. Read `references/style.md`. Decide the pen
   weight, paper colour, figure proportions and the one or two flat accent colours.
2. **Set up the project.** In the Thunderbolt `lib/` is already vendored at
   `packages/remotion/src/compositions/lineart/lib/` (still four dependency-free `.ts`
   files). No Vite needed: the Remotion `tsconfig.json` compiles them as they are.
   full set built at once comes back as generic; one good piece shows the bar.
4. **Make it move** with `references/motion.md`: `gait()` for walking and running,
   `spring()` / `pendulum()` for anything attached or hanging, keyed poses with
   `curve()` or `sequence()` for gestures. Never animate a figure with free sines.
5. **Compose the scene** with `references/scenes.md`: a self-contained card on a fixed
   page background, layers, a time-of-day palette from `lib/daynight.ts`, lights,
   wind, people arriving on schedules, interactions that are reactions.
6. **Verify** with `references/verify.md` before showing anything: typecheck,
   `?debug` stepping, zoomed frame strips of every moving thing, interactions
   triggered and stepped through, 60 fps in a real tab.
7. **If there's a reference clip to match**, follow `references/matching.md` — measure
   timing and poses from the clip instead of guessing, and check with an overlay.
8. **If they want a video**, render the `LineArtAnimation` composition with Remotion

## Rules that make it work

- **Limbs are two open strokes.** `limb()` draws a paper-filled band between two pen
  lines that stop short of each other at the far end. This is the style's signature.
- **Lines curve.** Joints are rounded, edges bow slightly, nothing is ruler-straight.
- **Draw each figure in its own space** — ~95 units tall, feet on y = 120, facing +x,
  standing at x = 40 — and place it with `place(g, x, y, dir, scale)`. Proportions,
  pen weight and the gait presets all assume this space.
- **Clothes are drawn around the skeleton.** Solve the legs (even if hidden), then
  draw the coat or kimono hem from the forward knee and the ankles so the cloth opens
  and closes with the stride. Sleeves, scarves and bags swing on springs.
- **Feet are planted.** Move a walker by exactly `gait.speed × scale` per second and
  the stance foot stays still on the ground. Don't speed a gait up to match a
  compressed clock; compress arrivals instead.
- **Ink is `currentColor`, paper is `.pp`.** Retint the whole drawing with
  `applyPalette()` (day: dark ink on warm paper; night: pale ink on indigo, warm
  windows). Solid-colour limb fills must use `solid()`, or the paper CSS wins.
- **The component is a card.** The page around it never changes colour.
- **Interactions are the world reacting**: a person bows or tips a hat, a cat wakes and
  stretches, a lantern swings, birds scatter, a fish jumps. Pointer movement is wind.
  No buttons inside the scene; a single faint hint line is enough.
- **New means new.** If the brief is "like this but new", keep the medium, pen,
  proportions and timing feel; invent the characters, activities and props.

## Library at a glance

| module | what it gives you |
|---|---|
| `lib/ink.ts` | `pen` `shape` `blot` `paint` `limb` `solid` `joint` `hang` `curve` `shoe` `place` `toScene` `inkDefs` `run` |
| `lib/gait.ts` | `gait({ kind: 'walk' \| 'shuffle' \| 'run', …overrides })` → `{ speed, period, pose(phase, go) }` |
| `lib/motion.ts` | `spring` `pendulum` `pointerWind` `sequence` `seeded` `wobble` `ease` `minJerk` … |
| `lib/daynight.ts` | `palette(τ)` → sky, paper, ink, `lamp`, `night`, `sunset`; `applyPalette` `nightTint` |

`run(draw)` drives everything with `draw(t, dt)`. Two URL flags matter for checking:
`?t=1.25` freezes time; `?debug` disables rAF and exposes `window.__step(seconds)`
for exact stepping (background and headless tabs throttle rAF, so always verify in debug mode).

## Scripts

- video export: `npx remotion render` (composition `LineArtAnimation`).
