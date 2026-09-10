# hullcheck

Catches the ways 3D assets break on the way into Roblox. Point it at a `.blend`, `.fbx`, `.glb`, or `.obj`; it names what is wrong, exits non-zero, and can fix the safe parts and export an engine-ready GLB.

Roblox rejects or renders-wrong an asset for a short list of mechanical reasons: no UVs, inverted normals, non-manifold geometry, wrong scale, too many triangles. Every one of those is a script that can check them. This is that script.

```
$ hullcheck lamp.blend

FAIL uv.missing           Shade                    mesh has no UV layer; textures and surface appearance need UVs
WARN scene.units          -                        scene unit system is 'METRIC'; Roblox expects studs (see create.roblox.com/docs/art/blender)
WARN geometry.ngons       Base                     2 n-gons (faces with more than 4 vertices); quads and tris are safest
WARN geometry.ngons       Shade                    1 n-gons (faces with more than 4 vertices); quads and tris are safest
WARN geometry.doubles     Bulb                     482 duplicate vertices; merge by distance only if intended (watch UV seams)

hullcheck 0.1.0 | lamp.blend | profile roblox | Blender 4.4.3
3 mesh objects, 1,994 triangles | 1 fail, 4 warn, 0 info -> FAILED
```

Exit codes: `0` passed, `1` failed checks, `2` could not run. That is the point: it drops into a CI step or a build script and refuses to pass a broken asset.

[![Ko-fi](https://img.shields.io/badge/Ko--fi-buy_me_a_coffee-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white)](https://ko-fi.com/jju1s)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

## What it checks

| Check | Severity | Why it matters |
|---|---|---|
| `uv.missing` | fail | No UV layer. Textures and SurfaceAppearance cannot map. |
| `normals.inverted` | fail | Closed mesh wound inside out. Renders as holes or black faces. |
| `geometry.nonmanifold` | fail | Edges shared by 3+ faces. Breaks collision and export. |
| `budget.exceeded` | fail | Over 20,000 triangles in one mesh. Roblox rejects the import. |
| `size.too_large` / `size.tiny` | fail | Over 2,048 studs across, or too small to see. |
| `texture.missing` | fail | A material points at an image file that is not there. |
| `geometry.holes` | warn | Open edges after welding. Roblox asks for watertight geometry. |
| `geometry.ngons` | warn | Faces with more than 4 vertices. Quads and tris are safest. |
| `geometry.doubles` | warn | Duplicate vertices. |
| `geometry.loose` | warn | Wire edges and stray vertices. |
| `geometry.zero_area` | warn | Degenerate faces. |
| `transform.unapplied` | warn | Object scale or rotation not applied. |
| `naming.duplicate` | warn | A name ending in `.001`, usually an accidental copy. |
| `material.untextured` | info | Solid-color or vertex-color materials. Fine, just noted. |
| `scene.units` | warn | Scene is not in studs. |

The triangle and size limits come from Roblox's [general modeling specifications](https://create.roblox.com/docs/art/modeling/specifications). The `generic` profile trades those for looser engine-agnostic numbers.

## Install

Needs Python 3 and Blender. Blender ships its own Python, so there is nothing to `pip install`.

```
git clone https://github.com/cig13zs/hullcheck.git
cd hullcheck
```

If Blender is not in the default location, set `HULLCHECK_BLENDER`:

```
set HULLCHECK_BLENDER=C:\path\to\blender.exe     Windows
export HULLCHECK_BLENDER=/path/to/blender        bash
```

## Use

```
hullcheck model.blend                          check it
hullcheck model.fbx --strict                   warnings count as failures
hullcheck model.blend --fix                    apply safe repairs
hullcheck model.blend --fix --export out.glb   repair and export engine-ready
hullcheck model.blend --json report.json       full machine-readable report
hullcheck model.blend --profile generic        loosen the limits for another engine
```

`--fix` only touches things with exactly one safe answer: it applies object scale and rotation into the mesh data, deletes loose vertices and wire edges, and recals normals on closed shells. It never merges doubles, since that can silently join UV seams, and it leaves shared or linked mesh data alone.

## Use it in a build or CI

```
blender --background --python hullcheck.py -- model.blend --strict || exit 1
```

Because the exit code is meaningful, this is a one-liner in any pipeline. The `--json` report carries every finding with its check id, object name, and severity, so a wrapper script can filter or gate on specific checks.

## Tests

```
python tests/run_tests.py
```

Builds nine fixture assets (one clean, seven broken in exactly one way, one empty), then asserts each check fires on the right fixture and stays silent on the clean one. Also covers `--fix` clearing the fixable findings and `--export` writing a real GLB. Blender must be installed; the path is auto-detected, or set `HULLCHECK_BLENDER` in the environment.

## Limits

- It checks geometry and materials, not taste.
- Manifold checking runs on a welded copy of the mesh, so UV-seam vertex splits from an FBX or glTF export do not read as holes.
- It does not verify rigs, bones, weights, or animation tracks. Roblox has its own rules there and they need a different pass.
- No automatic decimation. Over-budget meshes are reported, not silently shrunk, because that is a modeling decision.
- The Roblox limits are current as of Blender 4.4 and the 2026 specification docs; check the docs if a limit changes.

---

Hullcheck is an independent tool. Not affiliated with or endorsed by Roblox Corporation.
