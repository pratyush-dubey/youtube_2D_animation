"""Hand-authored (procedurally keyframed) test walk cycle on a puppet built by
cutout_rig_builder.py, rendered to a PNG sequence - Stage 2 acceptance test
from the rebuild-v2 spec: confirm parts stay connected at every joint through
motion, no gaps during arm/leg swing, no z-fighting/flicker.

Run: blender --background <puppet.blend> --python walk_cycle_test.py -- --out <frames_dir> [--seconds 4] [--fps 30]
"""
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]


def arg(name, default=None, cast=str):
    if name in args:
        return cast(args[args.index(name) + 1])
    return default


out_dir_arg = arg("--out")
if not out_dir_arg:
    raise SystemExit("Usage: blender --background <puppet.blend> --python walk_cycle_test.py -- --out <frames_dir>")
out_dir = Path(out_dir_arg)
seconds = arg("--seconds", 4.0, float)
fps = arg("--fps", 30, int)
out_dir.mkdir(parents=True, exist_ok=True)

armature = bpy.data.objects["Puppet_Armature"]
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 1280
if not scene.world:
    scene.world = bpy.data.worlds.new("World")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.07, 1.0)
scene.render.fps = fps
frame_count = max(1, round(seconds * fps))
scene.frame_start = 1
scene.frame_end = frame_count

# Measured from this rig's actual rest pose (blender_worker bone-position
# dump): ankles sit only ~0.026-0.047 world units from the body's own
# midline (a "feet together" reference photo), so anything near the earlier
# 0.10 unit swing was geometrically guaranteed to cross to the opposite
# side - it's not a tuning nicety, the numbers don't fit otherwise. Wrists
# have more margin (~0.08-0.10) but share the same constraint.
STEP_LEN = 0.015   # how far forward/back a foot swings, world units
LIFT = 0.025       # how high the swinging foot lifts
ARM_SWING = 0.03
HIP_BOB = 0.015


bpy.context.preferences.edit.keyframe_new_interpolation_type = "SINE"


def kf(bone_name, frame, location=None):
    pb = armature.pose.bones.get(bone_name)
    if pb is None:
        return
    if location is not None:
        pb.location = location
    pb.keyframe_insert(data_path="location", frame=frame)


def phase(frame, cycle_frames, offset=0.0):
    import math
    t = ((frame - 1) / max(cycle_frames, 1) + offset) % 1.0
    return math.sin(t * 2 * math.pi), math.sin(t * 2 * math.pi + math.pi / 2)


bpy.ops.object.select_all(action="DESELECT")
armature.select_set(True)
bpy.context.view_layer.objects.active = armature
bpy.ops.object.mode_set(mode="POSE")

cycle_frames = fps  # one stride cycle per second, matching the spec's guidance
step = max(1, cycle_frames // 8)  # ~8 keyframes per gait cycle, regardless of total duration
for frame in range(1, frame_count + 1, step):
    swing_l, lift_l = phase(frame, cycle_frames, offset=0.0)
    swing_r, lift_r = phase(frame, cycle_frames, offset=0.5)

    # Motion is along X (screen-lateral) and Z (lift), staying in the Y=0
    # camera-facing plane every bone's IK is now restricted to (see
    # cutout_rig_builder.add_ik's align_roll comment) - a Y/depth offset
    # would ask the solver to reach a point its single free rotation axis
    # can never produce. Amplitude is kept well under the hip-to-hip spacing
    # so the two legs' swings never cross the body's own midline.
    kf("ik_target_ankle_l", frame, (swing_l * STEP_LEN, 0, max(0.0, lift_l) * LIFT))
    kf("ik_target_ankle_r", frame, (swing_r * STEP_LEN, 0, max(0.0, lift_r) * LIFT))
    # Arms counter-swing the opposite-side leg.
    kf("ik_target_wrist_l", frame, (-swing_r * ARM_SWING, 0, 0))
    kf("ik_target_wrist_r", frame, (-swing_l * ARM_SWING, 0, 0))
    # Subtle hip bob, double frequency of the stride (a bob on every step).
    import math
    hip_t = ((frame - 1) / cycle_frames) % 1.0
    hip_z = abs(math.sin(hip_t * 2 * math.pi * 2)) * HIP_BOB
    kf("hips", frame, (0, 0, hip_z))

bpy.ops.object.mode_set(mode="OBJECT")

scene.render.filepath = str(out_dir) + "/frame_"
scene.render.image_settings.file_format = "PNG"
scene.frame_set(1)
for frame in range(1, frame_count + 1):
    scene.frame_set(frame)
    scene.render.filepath = str(out_dir / f"frame_{frame:05d}.png")
    bpy.ops.render.render(write_still=True)

print(f"rendered {frame_count} frames to {out_dir}")
