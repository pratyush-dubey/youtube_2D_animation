"""Skeleton motion, blending, head turn, blink, and fallback mouth animation."""
import math


def animate_character(rig, face, fps):
    rig.animation_data_create()
    rig.location = (0, -3.0, 0)
    rig.keyframe_insert("location", frame=1)
    rig.location = (0, -1.1, 0)
    rig.keyframe_insert("location", frame=21 * fps)
    rig.location = (0, -1.2, 0)
    rig.keyframe_insert("location", frame=30 * fps)
    for frame in range(5 * fps, 21 * fps + 1, max(1, fps // 2)):
        phase = (frame - 5 * fps) / fps * math.tau * 0.9
        for side, sign in (("L", 1), ("R", -1)):
            rig.pose.bones[f"upper_leg.{side}"].rotation_mode = "XYZ"
            rig.pose.bones[f"upper_leg.{side}"].rotation_euler.x = math.sin(phase) * 0.42 * sign
            rig.pose.bones[f"lower_leg.{side}"].rotation_mode = "XYZ"
            rig.pose.bones[f"lower_leg.{side}"].rotation_euler.x = max(0, -math.sin(phase) * sign) * 0.58
            rig.pose.bones[f"upper_arm.{side}"].rotation_mode = "XYZ"
            rig.pose.bones[f"upper_arm.{side}"].rotation_euler.y = -math.sin(phase) * 0.08 * sign
            for bone in (f"upper_leg.{side}", f"lower_leg.{side}", f"upper_arm.{side}"):
                rig.pose.bones[bone].keyframe_insert("rotation_euler", frame=frame)
    head = rig.pose.bones["head"]
    head.rotation_mode = "XYZ"
    for seconds, angle in ((0, 0), (21, 0), (23, -0.42), (25, -0.18), (30, 0)):
        head.rotation_euler.z = angle
        head.keyframe_insert("rotation_euler", frame=seconds * fps + 1)
    for eye_name in ("eye.L", "eye.R"):
        eye = face[eye_name]
        for seconds, scale_z in ((21.8, 1), (22.0, 0.08), (22.15, 1), (24.0, 1.2)):
            eye.scale.z = eye.scale.z * scale_z if scale_z != 1 else abs(eye.scale.z)
            eye.keyframe_insert("scale", frame=int(seconds * fps))
    mouth = face["mouth"]
    base_mouth_z = mouth.scale.z
    for frame in range(1, 30 * fps, max(2, fps // 3)):
        mouth.scale.z = base_mouth_z * (0.6 + 0.9 * abs(math.sin(frame * 0.31)))
        mouth.keyframe_insert("scale", frame=frame)
