"""Builds the fixture assets used by run_tests.py.

Each fixture is deliberately broken in exactly one way (except good.blend).
Run via the wrapper or directly:

    blender --background --factory-startup --python tests/make_fixtures.py -- OUT_DIR
"""

import os
import sys

import bpy


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def uv_cube(name="cube"):
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob


def save(out_dir, name):
    path = os.path.join(out_dir, name)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print("wrote", path)


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)

    # good: a clean UV-mapped cube, unit scale, tiny budget
    fresh()
    uv_cube()
    save(out_dir, "good.blend")

    # missing UVs (primitive_cube_add generates a UV map by default; strip it)
    fresh()
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    ob = bpy.context.active_object
    while ob.data.uv_layers:
        ob.data.uv_layers.remove(ob.data.uv_layers[0])
    save(out_dir, "bad_uvs.blend")

    # inverted normals: flip a closed cube's faces
    fresh()
    ob = uv_cube()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode="OBJECT")
    save(out_dir, "bad_normals.blend")

    # n-gons: cylinder with fill_type NGON, capped only on one end
    fresh()
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, end_fill_type="NGON")
    ob = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    save(out_dir, "bad_ngons.blend")

    # loose vertices and wire edges
    fresh()
    ob = uv_cube()
    me = ob.data
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.new((3.0, 3.0, 3.0))
    bm.verts.new((4.0, 4.0, 4.0))
    v1 = bm.verts.new((5.0, 5.0, 5.0))
    v2 = bm.verts.new((6.0, 6.0, 6.0))
    bm.edges.new((v1, v2))
    bm.to_mesh(me)
    bm.free()
    save(out_dir, "bad_loose.blend")

    # unapplied scale + giant size (3000 studs across)
    fresh()
    ob = uv_cube()
    ob.scale = (3000.0, 1.0, 1.0)
    save(out_dir, "bad_scale.blend")

    # over budget: subdivide well past 20k triangles
    fresh()
    ob = uv_cube()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    for _ in range(6):
        bpy.ops.mesh.subdivide()
    bpy.ops.object.mode_set(mode="OBJECT")
    save(out_dir, "bad_tris.blend")

    # duplicate vertices (doubles)
    fresh()
    ob = uv_cube()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.duplicate()
    bpy.ops.object.mode_set(mode="OBJECT")
    save(out_dir, "bad_doubles.blend")

    # empty scene
    fresh()
    save(out_dir, "empty.blend")

    # demo asset for the README: a lamp with three problems at once
    fresh()
    bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=0.8, radius2=0.0, depth=0.6, location=(0, 0, 0.3))
    shade = bpy.context.active_object
    shade.name = "Shade"
    while shade.data.uv_layers:
        shade.data.uv_layers.remove(shade.data.uv_layers[0])
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, end_fill_type="NGON", location=(0, 0, -0.2))
    base = bpy.context.active_object
    base.name = "Base"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(0, 0, 0.35))
    bulb = bpy.context.active_object
    bulb.name = "Bulb"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.duplicate()
    bpy.ops.object.mode_set(mode="OBJECT")
    save(out_dir, "demo.blend")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not args:
        print("usage: -- OUT_DIR")
        sys.exit(2)
    main(args[0])
