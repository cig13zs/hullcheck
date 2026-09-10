#!/usr/bin/env python3
"""hullcheck: catches the ways 3D assets break on the way into Roblox.

Loads a .blend / .fbx / .glb / .obj in Blender, runs mechanical checks, and
reports pass or fail with the exact problems. --fix applies safe repairs and
can export an engine-ready GLB.

    blender --background --factory-startup --python hullcheck.py -- model.blend

Exit codes: 0 pass, 1 failed checks (or warnings under --strict), 2 could not run.
"""

import argparse
import json
import mathutils
import os
import re
import sys

import bmesh
import bpy

VERSION = "0.1.0"
DUP_DIST = 1e-4
NAMING_RE = re.compile(r"\.\d{3}$")

# Roblox general mesh specs: 20,000 triangles per mesh, 2048 studs per part.
# https://create.roblox.com/docs/art/modeling/specifications
PROFILES = {
    "roblox": {"tri_fail": 20000, "tri_warn": 10000, "size_max": 2048.0, "size_min": 0.05, "units": "warn"},
    "generic": {"tri_fail": 500000, "tri_warn": 150000, "size_max": 1000000.0, "size_min": 0.001, "units": "info"},
}


class Report:
    def __init__(self):
        self.findings = []
        self.fixed = []

    def add(self, check, severity, message, obj=None, detail=None):
        self.findings.append({
            "id": check,
            "severity": severity,
            "object": obj,
            "message": message,
            "detail": detail or {},
        })

    def count(self, severity):
        return sum(1 for f in self.findings if f["severity"] == severity)


def load_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        elif ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=path)
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=path)
        else:
            raise ValueError("unsupported file type: %s" % ext)
    bpy.context.view_layer.update()


def transform_off(o):
    scale_off = max(abs(s - 1.0) for s in o.scale) > 1e-4
    if o.rotation_mode == "QUATERNION":
        rot_off = max(abs(a) for a in o.rotation_quaternion[1:]) > 1e-4
    else:
        rot_off = max(abs(a) for a in o.rotation_euler) > 1e-4
    return scale_off, rot_off


def mesh_stats(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    try:
        loose_verts = sum(1 for v in bm.verts if not v.link_edges)
        loose_edges = sum(1 for e in bm.edges if not e.link_faces)
        zero_area = sum(1 for f in bm.faces if f.calc_area() < 1e-9)
        seen = set()
        doubles = 0
        for v in bm.verts:
            key = (round(v.co.x, 4), round(v.co.y, 4), round(v.co.z, 4))
            if key in seen:
                doubles += 1
            else:
                seen.add(key)
        # Topology is measured on a welded copy: exporters (glTF, FBX) split
        # vertices at UV and normal seams, which is expected and still renders
        # watertight. Counting boundary edges on the raw mesh would flag every
        # imported file.
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=DUP_DIST)
        boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        junction = sum(1 for e in bm.edges if len(e.link_faces) > 2)
        closed = boundary == 0 and junction == 0 and len(bm.faces) > 0
        volume = bm.calc_volume(signed=True) if closed else None
    finally:
        bm.free()
    return {
        "boundary": boundary,
        "junction": junction,
        "loose_verts": loose_verts,
        "loose_edges": loose_edges,
        "zero_area": zero_area,
        "doubles": doubles,
        "closed": closed,
        "volume": volume,
    }


def check_materials(rep):
    untextured = 0
    for mat in bpy.data.materials:
        if not mat.use_nodes or not mat.node_tree:
            continue
        found = False
        for node in mat.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue
            found = True
            img = node.image
            if img.packed_file or not img.filepath:
                continue
            if not os.path.exists(bpy.path.abspath(img.filepath)):
                rep.add("texture.missing", "fail",
                        "material '%s' points at a missing file: %s" % (mat.name, img.filepath))
        if not found:
            untextured += 1
    if untextured:
        rep.add("material.untextured", "info",
                "%d material(s) use no image texture; solid color or vertex color is fine in Roblox" % untextured)


def run_checks(profile, tri_limit=None, rep=None, imported=False):
    rep = rep if rep is not None else Report()
    limits = dict(PROFILES[profile])
    if tri_limit:
        limits["tri_fail"] = tri_limit
        limits["tri_warn"] = max(tri_limit // 2, 1)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        rep.add("scene.no_meshes", "info", "no mesh objects in this file")

    us = bpy.context.scene.unit_settings
    if not imported and us.system != "NONE":
        rep.add("scene.units", limits["units"],
                "scene unit system is '%s'; Roblox expects studs (see create.roblox.com/docs/art/blender)" % us.system)

    for o in meshes:
        me = o.data
        if len(me.uv_layers) == 0:
            rep.add("uv.missing", "fail",
                    "mesh has no UV layer; textures and surface appearance need UVs", obj=o.name)

        st = mesh_stats(me)
        if st["junction"]:
            rep.add("geometry.nonmanifold", "fail",
                    "%d edges are shared by 3 or more faces" % st["junction"], obj=o.name)
        if st["closed"] and st["volume"] is not None and st["volume"] < 0:
            rep.add("normals.inverted", "fail",
                    "closed mesh has inverted normals (signed volume %.3f); faces render inside out" % st["volume"],
                    obj=o.name)
        if st["boundary"]:
            sev = "info" if imported and st["boundary"] <= 64 else "warn"
            rep.add("geometry.holes", sev,
                    "%d open edges after welding; Roblox specs ask for watertight geometry" % st["boundary"], obj=o.name)
        if st["doubles"]:
            sev = "info" if imported else "warn"
            rep.add("geometry.doubles", sev,
                    "%d duplicate vertices%s"
                    % (st["doubles"],
                       "; exporters split vertices at UV/normal seams, which is expected" if imported
                       else "; merge by distance only if intended (watch UV seams)"),
                    obj=o.name)
        if st["loose_verts"] or st["loose_edges"]:
            rep.add("geometry.loose", "warn",
                    "%d loose vertices, %d wire edges" % (st["loose_verts"], st["loose_edges"]), obj=o.name)
        if st["zero_area"]:
            rep.add("geometry.zero_area", "warn", "%d zero-area faces" % st["zero_area"], obj=o.name)

        ngons = sum(1 for p in me.polygons if len(p.vertices) > 4)
        if ngons:
            rep.add("geometry.ngons", "warn",
                    "%d n-gons (faces with more than 4 vertices); quads and tris are safest" % ngons, obj=o.name)

        tris = sum(len(p.vertices) - 2 for p in me.polygons)
        if tris > limits["tri_fail"]:
            rep.add("budget.exceeded", "fail",
                    "%s triangles; over the %s limit for one mesh" % (format(tris, ","), format(limits["tri_fail"], ",")),
                    obj=o.name)
        elif tris > limits["tri_warn"]:
            rep.add("budget.heavy", "warn",
                    "%s triangles; heavy for mobile, budget is %s" % (format(tris, ","), format(limits["tri_warn"], ",")),
                    obj=o.name)

        dims = o.dimensions
        longest = max(dims) if len(dims) else 0.0
        if longest > limits["size_max"]:
            rep.add("size.too_large", "fail",
                    "%.1f studs across on the longest axis; single parts cap at %.0f" % (longest, limits["size_max"]),
                    obj=o.name)
        elif longest and longest < limits["size_min"]:
            rep.add("size.tiny", "fail",
                    "%.4f studs across; too small to be visible" % longest, obj=o.name)

        scale_off, rot_off = transform_off(o)
        if scale_off or rot_off:
            rep.add("transform.unapplied", "warn", "scale or rotation is not applied", obj=o.name)

        if NAMING_RE.search(o.name):
            rep.add("naming.duplicate", "warn",
                    "name ends in a .001-style suffix; looks like an accidental duplicate", obj=o.name)

    check_materials(rep)
    return rep, limits


def apply_fixes(rep):
    for o in [x for x in bpy.data.objects if x.type == "MESH"]:
        notes = []
        scale_off, rot_off = transform_off(o)
        if scale_off or rot_off:
            if o.parent is None:
                loc = o.matrix_world.to_translation()
                rot = o.matrix_world.to_quaternion()
                scl = o.matrix_world.to_scale()
                o.data.transform(mathutils.Matrix.LocRotScale(None, rot, scl))
                o.matrix_world = mathutils.Matrix.Translation(loc)
                notes.append("applied rotation and scale into mesh data")
            else:
                notes.append("has a parent; transforms left alone")

        me = o.data
        if me.users > 1:
            notes.append("skipped: mesh data shared by other objects")
        elif me.library:
            notes.append("skipped: linked library mesh")
        else:
            bm = bmesh.new()
            bm.from_mesh(me)
            loose = [v for v in bm.verts if not v.link_edges]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context="VERTS")
                notes.append("deleted %d loose vertices" % len(loose))
            wire = [e for e in bm.edges if e.is_valid and not e.link_faces]
            if wire:
                bmesh.ops.delete(bm, geom=wire, context="EDGES")
                notes.append("deleted %d wire edges" % len(wire))
            bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces])
            bm.to_mesh(me)
            bm.free()
            me.update()

        rep.fixed.extend("%s: %s" % (o.name, n) for n in notes)


def print_report(path, rep, limits, mesh_count, total_tris):
    order = {"fail": 0, "warn": 1, "info": 2}
    findings = sorted(rep.findings, key=lambda f: order[f["severity"]])
    groups = {}
    for f in findings:
        groups.setdefault(f["id"], []).append(f)
    for cid, items in groups.items():
        sev = items[0]["severity"]
        for it in items[:5]:
            print("%-4s %-20s %-24s %s" % (sev.upper(), cid, it["object"] or "-", it["message"]))
        if len(items) > 5:
            print("%-4s %-20s %-24s ... and %d more (%s)" % ("", cid, "", len(items) - 5, cid))
    fails, warns, infos = rep.count("fail"), rep.count("warn"), rep.count("info")
    status = "PASSED" if not fails else "FAILED"
    print("")
    print("%s | %s | profile %s | Blender %s" % ("hullcheck " + VERSION, os.path.basename(path), profile_name(limits), bpy.app.version_string))
    print("%d mesh objects, %s triangles | %d fail, %d warn, %d info -> %s"
          % (mesh_count, format(total_tris, ","), fails, warns, infos, status))


def profile_name(limits):
    for name, p in PROFILES.items():
        if p == limits:
            return name
    return "custom"


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="hullcheck",
        description="Check a 3D asset for problems that break Roblox imports.",
        epilog="Usually run through the wrapper: hullcheck.cmd model.blend (see README).")
    p.add_argument("file", help=".blend, .fbx, .glb or .obj to check")
    p.add_argument("--profile", choices=sorted(PROFILES), default="roblox")
    p.add_argument("--fix", action="store_true", help="apply safe repairs (transforms, loose geometry, normals)")
    p.add_argument("--save", metavar="OUT.blend", help="save the fixed file to OUT.blend")
    p.add_argument("--export", metavar="OUT.glb", help="export the asset as GLB after checks and fixes")
    p.add_argument("--json", metavar="REPORT.json", help="write the full report as JSON")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures")
    p.add_argument("--tri-limit", type=int, metavar="N", help="override the per-mesh triangle limit")
    p.add_argument("--version", action="version", version="hullcheck " + VERSION)
    return p.parse_args(argv)


def main(argv):
    if not argv:
        print(__doc__)
        print("Run: hullcheck model.blend")
        return 2

    args = parse_args(argv)
    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        print("hullcheck: file not found: %s" % path)
        return 2

    try:
        load_file(path)
    except Exception as exc:
        print("hullcheck: could not load %s: %s" % (path, exc))
        return 2

    imported = not path.lower().endswith(".blend")
    rep = Report()
    if args.fix:
        apply_fixes(rep)

    rep, limits = run_checks(args.profile, args.tri_limit, rep, imported)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    total_tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
    print_report(path, rep, limits, len(meshes), total_tris)

    if rep.fixed:
        print("")
        print("fixed:")
        for n in rep.fixed:
            print("  - %s" % n)

    if args.json:
        data = {
            "hullcheck": VERSION,
            "blender": bpy.app.version_string,
            "file": path,
            "profile": args.profile,
            "limits": limits,
            "summary": {
                "fail": rep.count("fail"),
                "warn": rep.count("warn"),
                "info": rep.count("info"),
                "mesh_objects": len(meshes),
                "triangles": total_tris,
            },
            "findings": rep.findings,
            "fixed": rep.fixed,
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        print("report written to %s" % args.json)

    code = 0
    if rep.count("fail") or (args.strict and rep.count("warn")):
        code = 1

    if args.fix and args.save:
        try:
            bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save))
            print("saved %s" % args.save)
        except Exception as exc:
            print("hullcheck: could not save: %s" % exc)
            return 2
    elif args.save:
        print("hullcheck: --save needs --fix (nothing was changed)")

    if args.export:
        try:
            bpy.ops.export_scene.gltf(filepath=os.path.abspath(args.export), export_format="GLB")
            print("exported %s" % args.export)
        except Exception as exc:
            print("hullcheck: could not export: %s" % exc)
            return 2

    return code


def _script_args():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


if __name__ == "__main__":
    sys.exit(main(_script_args()))
