"""Standard humanoid skeleton creation and validation."""
import bpy
from mathutils import Vector

BONES = {
    "root": ((0, 0, 0), (0, 0, 0.35), None),
    "pelvis": ((0, 0, 0.85), (0, 0, 1.10), "root"),
    "spine": ((0, 0, 1.10), (0, 0, 1.42), "pelvis"),
    "chest": ((0, 0, 1.42), (0, 0, 1.68), "spine"),
    "neck": ((0, 0, 1.68), (0, 0, 1.82), "chest"),
    "head": ((0, 0, 1.82), (0, 0, 2.05), "neck"),
    "upper_arm.L": ((0.18, 0, 1.62), (0.48, 0, 1.38), "chest"),
    "lower_arm.L": ((0.48, 0, 1.38), (0.62, 0, 1.10), "upper_arm.L"),
    "hand.L": ((0.62, 0, 1.10), (0.66, 0, 0.96), "lower_arm.L"),
    "upper_arm.R": ((-0.18, 0, 1.62), (-0.48, 0, 1.38), "chest"),
    "lower_arm.R": ((-0.48, 0, 1.38), (-0.62, 0, 1.10), "upper_arm.R"),
    "hand.R": ((-0.62, 0, 1.10), (-0.66, 0, 0.96), "lower_arm.R"),
    "upper_leg.L": ((0.13, 0, 0.92), (0.15, 0, 0.49), "pelvis"),
    "lower_leg.L": ((0.15, 0, 0.49), (0.14, 0, 0.09), "upper_leg.L"),
    "foot.L": ((0.14, 0, 0.09), (0.14, -0.20, 0.04), "lower_leg.L"),
    "upper_leg.R": ((-0.13, 0, 0.92), (-0.15, 0, 0.49), "pelvis"),
    "lower_leg.R": ((-0.15, 0, 0.49), (-0.14, 0, 0.09), "upper_leg.R"),
    "foot.R": ((-0.14, 0, 0.09), (-0.14, -0.20, 0.04), "lower_leg.R"),
}


def create_humanoid_rig(name="CharacterRig"):
    armature = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, armature)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, (head, tail, parent) in BONES.items():
        bone = armature.edit_bones.new(bone_name)
        bone.head, bone.tail = Vector(head), Vector(tail)
        if parent:
            bone.parent = armature.edit_bones[parent]
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def validate_rig(rig):
    present = {bone.name for bone in rig.data.bones}
    missing = sorted(set(BONES) - present)
    return {"passed": not missing, "missing_bones": missing, "bone_count": len(present)}
