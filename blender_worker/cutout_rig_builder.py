"""Build a bone-rigged 2D cutout puppet from a rig.json + part PNGs produced by
app.images.production_assets.extract_character_rig() (see
app/images/character_illustration.py for how that manifest is generated).

Each part becomes a flat image plane; a bone is created per joint (the pivot
each part rotates around); planes are rigidly parented to their bone (no
armature-deform/weight-paint - this is a puppet, not a soft-body character);
IK constraints with a pole target are added on the lower-arm and lower-leg
bones so a single hand/foot target drives natural bend.

Run headless:
    blender --background --python cutout_rig_builder.py -- --rig <rig.json> --out <out.blend> [--report <report.json>]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def winlong(path: Path) -> Path:
    """Bypass Windows' 260-char MAX_PATH limit for absolute paths.

    Blender's bundled Python does not carry the same longPathAware app
    manifest the python.org installer sets, so Path.is_file()/bpy image
    loading can silently fail to find files the rest of this project's
    tooling reads fine (project output/temp paths can exceed 260 chars once
    nested under output/<project_id>/characters/<slug>/rig/<part>.png). The
    documented \\\\?\\ extended-length prefix is a plain WinAPI mechanism, not
    a Python feature, so it works regardless of that manifest flag.
    """
    if sys.platform != "win32":
        return path
    resolved = str(path.resolve())
    if resolved.startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\" + resolved)

# Bones with an IK chain (parent -> this bone -> this bone's own child are the
# 3-bone chain IK solves across); the *_l/_r naming matches rig.json's joints.
IK_CHAIN_TIP_JOINTS = ("wrist_l", "wrist_r", "ankle_l", "ankle_r")
# World-unit character height after pixel->world scaling (see load_rig()).
TARGET_HEIGHT = 1.8


def parse_args():
    if "--" not in sys.argv:
        raise SystemExit("Usage: blender --background --python cutout_rig_builder.py -- --rig <rig.json> --out <out.blend>")
    parser = argparse.ArgumentParser()
    parser.add_argument("--rig", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", default=None)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.armatures):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def load_rig(rig_path: Path) -> dict:
    manifest = json.loads(rig_path.read_text(encoding="utf-8"))
    canvas_w = float(manifest["canvas_size"][0])
    canvas_h = float(manifest["canvas_size"][1])
    scale = TARGET_HEIGHT / canvas_h

    def to_world(px: float, py: float) -> tuple[float, float]:
        # Image space is Y-down from top-left; Blender's character-facing
        # plane here is XZ (Y is the shared depth axis for all parts, offset
        # slightly per part below to avoid z-fighting) with Z-up, so Y (image)
        # flips sign relative to Z (world). World X centres on the canvas
        # midpoint (not its left edge) so the puppet ends up centred at
        # world X=0, matching the camera's aim point in main().
        return (px - canvas_w / 2) * scale, (canvas_h - py) * scale

    manifest["_scale"] = scale
    manifest["_to_world"] = to_world
    return manifest


def material_for_image(path: str, name: str):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    nodes = material.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeEmission")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(path, check_existing=True)
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Color"])
    shader.inputs["Strength"].default_value = 1.0
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    material.node_tree.links.new(texture.outputs["Alpha"], mix.inputs[0])
    material.node_tree.links.new(transparent.outputs[0], mix.inputs[1])
    material.node_tree.links.new(shader.outputs[0], mix.inputs[2])
    material.node_tree.links.new(mix.outputs[0], out.inputs[0])
    return material


def part_plane(name: str, path: str, width: float, height: float, pivot_local: tuple[float, float],
                world_location: tuple[float, float, float], collection):
    """A quad whose local origin sits at pivot_local (fraction within the
    part's own bbox, e.g. (0.5, 0.9) for a leg), so parenting it to a bone
    positioned at that same world point rotates it around the correct joint
    instead of its own visual centre."""
    px, py = pivot_local
    x0, x1 = -width * px, width * (1 - px)
    # Image-space pivot_y is measured top-down; the local Z axis here is
    # up, so invert.
    z0, z1 = -height * (1 - py), height * py
    vertices = [(x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1)]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
    mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(mesh.uv_layers[0].data, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop.uv = uv
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = world_location
    obj.data.materials.append(material_for_image(path, f"mat_{name}"))
    return obj


def derive_bone_parents(manifest: dict) -> dict[str, str | None]:
    """One bone per joint actually used as a part's pivot. A joint's bone-parent
    is the joint of that part's parent part (skipping parts with no joint of
    their own, e.g. any part sharing a joint with its parent)."""
    parts = manifest["parts"]
    joint_of_part = {name: data["joint"] for name, data in parts.items()}
    bone_parent: dict[str, str | None] = {}
    for name, data in parts.items():
        joint = data["joint"]
        parent_part = data.get("parent")
        parent_joint = joint_of_part.get(parent_part) if parent_part else None
        if joint not in bone_parent:
            bone_parent[joint] = parent_joint if parent_joint != joint else None
        elif parent_joint and parent_joint != joint and bone_parent[joint] is None:
            bone_parent[joint] = parent_joint
    return bone_parent


def build_armature(manifest: dict, collection) -> "bpy.types.Object":
    to_world = manifest["_to_world"]
    joints = manifest["joints"]
    bone_parent = derive_bone_parents(manifest)
    # Only build bones for joints actually referenced by a visible part's pivot.
    used_joints = {data["joint"] for data in manifest["parts"].values() if data.get("visible", True)}
    used_joints |= {j for j in bone_parent if bone_parent[j] in used_joints or j in used_joints}

    armature_data = bpy.data.armatures.new("PuppetArmature")
    armature_obj = bpy.data.objects.new("Puppet_Armature", armature_data)
    collection.objects.link(armature_obj)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = armature_data.edit_bones
    default_length = manifest["_scale"] * manifest["canvas_size"][1] * 0.04

    # Children-of map, so a bone's tail can point toward its single child
    # (gives IK chains a sensible default bend direction) with a safe default
    # for leaves/branch points.
    children_of: dict[str, list[str]] = {}
    for joint, parent in bone_parent.items():
        if parent:
            children_of.setdefault(parent, []).append(joint)

    for joint in used_joints:
        if joint not in joints:
            continue
        head_world = to_world(*joints[joint])
        bone = edit_bones.new(joint)
        bone.head = Vector((head_world[0], 0.0, head_world[1]))
        kids = children_of.get(joint, [])
        if len(kids) == 1 and kids[0] in joints:
            tail_world = to_world(*joints[kids[0]])
            bone.tail = Vector((tail_world[0], 0.0, tail_world[1]))
        else:
            bone.tail = bone.head + Vector((0, 0, default_length))
        # Every bone lies in the Y=0 (camera-facing) plane, so its direction
        # vector never has a Y component - align_roll(world -Y) is therefore
        # always well-defined here. This pins local Z to world -Y (toward the
        # camera) for every bone, regardless of whether it happens to run
        # mostly vertically or diagonally, so "rotate around local Z" always
        # means "rotate within the character's own flat XZ plane" - the only
        # rotation that bends a limb without tipping its flat plane out of
        # camera-facing orientation. Without this, Blender's default per-bone
        # roll heuristic gives each bone an arbitrary, direction-dependent
        # local frame, making a single fixed axis-lock choice inconsistent
        # across bones (this is what caused the earlier scissoring/edge-on
        # vanishing - the "bend" axis silently meant something different for
        # each bone).
        bone.align_roll(Vector((0, -1, 0)))

    for joint, parent in bone_parent.items():
        if joint in edit_bones and parent and parent in edit_bones:
            edit_bones[joint].parent = edit_bones[parent]
            # Keep bone-local coordinates but do not force-connect heads to
            # parent tails - a puppet's pivots are exact anatomical points,
            # not necessarily chained end-to-end like a deforming mesh rig.
            edit_bones[joint].use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    return armature_obj


def add_ik(armature_obj, manifest: dict) -> None:
    """IK on each *_l/_r chain tip (wrist/ankle): a separate, independently
    posable target bone drives the tip+its parent (e.g. wrist+lower-arm) to
    reach it, plus a pole target so the elbow/knee bends toward the camera
    instead of an ambiguous direction. The constraint must target a DIFFERENT
    bone than the one it's attached to - targeting the tip bone from its own
    IK constraint is a circular dependency Blender's depsgraph rejects."""
    bone_parent = derive_bone_parents(manifest)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature_obj.data.edit_bones
    ik_setup = {}
    for tip in IK_CHAIN_TIP_JOINTS:
        if tip not in edit_bones:
            continue
        mid = bone_parent.get(tip)
        if not mid or mid not in edit_bones:
            continue
        tip_bone = edit_bones[tip]

        target_name = f"ik_target_{tip}"
        target = edit_bones.new(target_name)
        target.head = tip_bone.tail.copy()
        target.tail = target.head + Vector((0, 0, 0.05))
        target.parent = None
        target.use_deform = False

        pole_name = f"ik_pole_{tip}"
        pole = edit_bones.new(pole_name)
        mid_head = edit_bones[mid].head.copy()
        pole.head = mid_head + Vector((0, -0.8, 0))
        pole.tail = pole.head + Vector((0, 0, 0.05))
        pole.parent = None
        pole.use_deform = False

        ik_setup[tip] = (target_name, pole_name)
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.mode_set(mode="POSE")
    for tip, (target_name, pole_name) in ik_setup.items():
        pose_bone = armature_obj.pose.bones[tip]
        constraint = pose_bone.constraints.new("IK")
        constraint.target = armature_obj
        constraint.subtarget = target_name
        # No pole target: with X and Y locked below, every bone in the chain
        # has exactly one rotational DOF (Z), which fully determines the bend
        # - there is no plane ambiguity left for a pole to resolve, and its
        # world-Y offset is meaningless once the chain is confined to the XZ
        # plane (it was fighting the axis locks, producing crossed/twisted
        # poses even after the alignment fix).
        # 3 bones: tip (e.g. ankle) + lower segment (shin/forearm) + upper
        # segment (thigh/upper-arm), so the hip/shoulder shares the bend
        # instead of the whole target displacement forcing an oversized knee/
        # elbow rotation (a small sideways step is a large fraction of the
        # shin's own length, so a 2-bone chain scissored wildly to reach it).
        constraint.chain_count = 3
        # `lock_rotation` (Transform Locks) has no effect on IK-solved rotation -
        # only these dedicated IK-axis locks do. build_armature() aligned every
        # bone's local Z to world -Y (camera-facing), so rotation around local
        # Z is the only rotation that bends a limb without tipping its flat
        # plane out of camera-facing orientation (X/Y rotation would rotate
        # the plane's own normal away from the camera - the edge-on/vanishing
        # artifact seen before this fix). Lock X and Y (twist), leave Z free.
        chain_bone_name = tip
        for _ in range(constraint.chain_count):
            chain_pose_bone = armature_obj.pose.bones.get(chain_bone_name)
            if chain_pose_bone is None:
                break
            chain_pose_bone.lock_ik_x = True
            chain_pose_bone.lock_ik_y = True
            # Hard angle cap on the one free axis, independent of target
            # amplitude - guarantees no single joint can ever swing far
            # enough to cross the body's midline or fold back on itself,
            # regardless of how the target/chain-length math works out.
            chain_pose_bone.use_ik_limit_z = True
            chain_pose_bone.ik_min_z = math.radians(-40)
            chain_pose_bone.ik_max_z = math.radians(40)
            chain_bone_name = bone_parent.get(chain_bone_name)
    bpy.ops.object.mode_set(mode="OBJECT")


def lock_to_2d_plane(armature_obj) -> None:
    """Constrain every bone to rotate only around Y and translate only in the
    XZ plane - motion stays in the camera-facing plane, as the spec requires,
    instead of an animator/automation accidentally rotating a part out of it."""
    for bone in armature_obj.pose.bones:
        bone.lock_rotation = (True, False, True)
        bone.lock_rotation_w = False
        bone.rotation_mode = "YXZ"
        bone.lock_location = (False, True, False)


def build_puppet(manifest: dict) -> tuple["bpy.types.Object", "bpy.types.Object", dict]:
    to_world = manifest["_to_world"]
    scale = manifest["_scale"]
    collection = bpy.context.scene.collection

    part_names_by_depth = sorted(
        manifest["parts"].items(),
        key=lambda item: len(_ancestor_chain(item[0], manifest["parts"])),
    )
    skipped = []
    part_objects = {}
    for index, (name, data) in enumerate(part_names_by_depth):
        if not data.get("visible", True):
            skipped.append(name)
            print(f"SKIP {name}: not visible", file=sys.stderr)
            continue
        path = winlong(Path(data["path"]))
        if not path.is_file():
            skipped.append(name)
            print(f"SKIP {name}: file missing at {path}", file=sys.stderr)
            continue
        w_px, h_px = data["size"]
        cx = data["position"][0] + w_px / 2
        cy = data["position"][1] + h_px / 2
        pivot_frac = data.get("pivot", [0.5, 0.5])
        # Reconstruct the pivot's absolute canvas position from the part's own
        # bbox instead of assuming it exactly equals the joint - the two are
        # designed to coincide in extract_character_rig() but this keeps the
        # plane's own geometry self-consistent even if they drift slightly.
        pivot_abs = (
            data["position"][0] + pivot_frac[0] * w_px,
            data["position"][1] + pivot_frac[1] * h_px,
        )
        world_x, world_z = to_world(*pivot_abs)
        # Depth-order children in front of parents (root furthest back) so
        # overlapping parts never z-fight; index scales with hierarchy depth
        # and sibling order, matching blender_worker/cinematic_2d25d_proof.py's
        # build_character() approach for the same problem.
        depth = -0.01 * (len(manifest["parts"]) - index)
        obj = part_plane(
            name, str(path), w_px * scale, h_px * scale,
            pivot_frac, (world_x, depth, world_z), collection,
        )
        part_objects[name] = (obj, data["joint"])

    armature_obj = build_armature(manifest, collection)
    add_ik(armature_obj, manifest)
    lock_to_2d_plane(armature_obj)

    for name, (obj, joint) in part_objects.items():
        if joint not in armature_obj.data.bones:
            continue
        # A CHILD_OF constraint (rather than parent_type='BONE') avoids that
        # mode's bone-length/tail-offset matrix convention entirely - it is
        # deterministic to compute headlessly: freeze the object's CURRENT
        # world position (already set to its intended pivot point above) as
        # the rest state by inverting the bone's current world matrix, then
        # the object rigidly follows that bone's pose from here on. This is
        # the rigid, non-deforming parenting the spec calls for.
        constraint = obj.constraints.new("CHILD_OF")
        constraint.target = armature_obj
        constraint.subtarget = joint
        pose_bone = armature_obj.pose.bones[joint]
        constraint.inverse_matrix = (armature_obj.matrix_world @ pose_bone.matrix).inverted()

    return armature_obj, collection, {"parts": len(part_objects), "skipped": skipped}


def _ancestor_chain(name: str, parts: dict) -> list[str]:
    chain = []
    current = name
    seen = set()
    while current and current in parts and current not in seen:
        seen.add(current)
        parent = parts[current].get("parent")
        if not parent:
            break
        chain.append(parent)
        current = parent
    return chain


def main():
    args = parse_args()
    rig_path = Path(args.rig)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    clear_scene()
    manifest = load_rig(rig_path)
    armature_obj, collection, stats = build_puppet(manifest)

    camera_data = bpy.data.cameras.new("PuppetCamera")
    camera_obj = bpy.data.objects.new("PuppetCamera", camera_data)
    collection.objects.link(camera_obj)
    camera_obj.location = (0, -3.2, TARGET_HEIGHT / 2)
    camera_obj.rotation_euler = (1.5708, 0, 0)
    bpy.context.scene.camera = camera_obj

    light_data = bpy.data.lights.new("PuppetLight", type="SUN")
    light_data.energy = 3.0
    light_obj = bpy.data.objects.new("PuppetLight", light_data)
    collection.objects.link(light_obj)
    light_obj.location = (0, -2, TARGET_HEIGHT)

    bpy.ops.wm.save_as_mainfile(filepath=str(out_path))

    report = {
        "rig_source": str(rig_path),
        "output": str(out_path),
        "parts_built": stats["parts"],
        "parts_skipped": stats["skipped"],
        "bones": len(armature_obj.data.bones),
        "bone_names": sorted(b.name for b in armature_obj.data.bones),
    }
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
