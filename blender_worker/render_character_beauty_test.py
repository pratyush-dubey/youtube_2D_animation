"""Render the character-only beauty sheet and bounded motion tests."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def studio_material(name, color, roughness=0.7):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = roughness
    return material


def setup_studio():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BeautyStudioWorld")
    scene.world.color = (0.018, 0.024, 0.045)
    world_nodes = scene.world.node_tree if scene.world.use_nodes else None
    if not scene.world.use_nodes:
        scene.world.use_nodes = True
        world_nodes = scene.world.node_tree
    if world_nodes:
        world_nodes.nodes["Background"].inputs["Color"].default_value = (0.015, 0.025, 0.055, 1)
        world_nodes.nodes["Background"].inputs["Strength"].default_value = 0.22

    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, -0.022))
    floor = bpy.context.object
    floor.name = "BeautyStudioFloor"
    floor.data.materials.append(studio_material("Studio charcoal", (0.055, 0.065, 0.09), 0.48))

    lights = [
        ("Key", "AREA", (-2.2, -3.2, 3.4), (1.0, 0.73, 0.53), 980, 2.5),
        ("Fill", "AREA", (2.7, -2.1, 2.1), (0.36, 0.60, 1.0), 680, 2.2),
        ("Rim", "AREA", (0.5, 2.2, 2.9), (0.55, 0.72, 1.0), 1100, 1.8),
    ]
    for name, light_type, location, color, energy, size in lights:
        data = bpy.data.lights.new(name, light_type)
        data.color = color
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        light = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(light)
        light.location = location
        look_at(light, (0, 0, 1.0))

    camera_data = bpy.data.cameras.new("BeautyCamera")
    camera = bpy.data.objects.new("BeautyCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    return camera


def render_still(camera, output, location, target, lens, resolution=(720, 900)):
    scene = bpy.context.scene
    camera.location = location
    camera.data.lens = lens
    look_at(camera, target)
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.filepath = str(output)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


def rig_and_body():
    rig = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    body = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.endswith(".body"))
    return rig, body


def clear_animation(rig, body):
    if rig.animation_data:
        rig.animation_data_clear()
    rig.location = (0, 0, 0)
    rig.rotation_euler = (0, 0, 0)
    for bone in rig.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
        bone.location = (0, 0, 0)
    if body.data.shape_keys:
        body.data.shape_keys.animation_data_clear()
        for key in body.data.shape_keys.key_blocks:
            if key.name.startswith("!ex-"):
                key.value = 0.0


def key_bone(rig, bone_name, frame, rotation=None, location=None):
    bone = rig.pose.bones.get(bone_name)
    if not bone:
        return
    if rotation is not None:
        bone.rotation_euler = rotation
        bone.keyframe_insert("rotation_euler", frame=frame)
    if location is not None:
        bone.location = location
        bone.keyframe_insert("location", frame=frame)


def prepare_idle(rig, body):
    clear_animation(rig, body)
    for frame, breath, sway in ((1, 0.0, -0.012), (25, 0.018, 0.012), (49, 0.0, -0.012), (73, 0.018, 0.012)):
        key_bone(rig, "spine03", frame, (breath, 0.0, sway))
        key_bone(rig, "head", frame, (-breath * 0.35, 0.0, -sway * 0.45))
        key_bone(rig, "upperarm01.L", frame, (sway * 0.45, 0.0, 0.0))
        key_bone(rig, "upperarm01.R", frame, (-sway * 0.45, 0.0, 0.0))


def prepare_walk(rig, body):
    clear_animation(rig, body)
    poses = ((1, 0.42), (13, 0.0), (25, -0.42), (37, 0.0), (49, 0.42), (61, 0.0), (73, -0.42))
    for frame, swing in poses:
        key_bone(rig, "upperleg01.L", frame, (swing, 0.0, 0.0))
        key_bone(rig, "upperleg01.R", frame, (-swing, 0.0, 0.0))
        key_bone(rig, "lowerleg01.L", frame, (max(0.0, -swing) * 0.65, 0.0, 0.0))
        key_bone(rig, "lowerleg01.R", frame, (max(0.0, swing) * 0.65, 0.0, 0.0))
        key_bone(rig, "upperarm01.L", frame, (-swing * 0.72, 0.0, 0.0))
        key_bone(rig, "upperarm01.R", frame, (swing * 0.72, 0.0, 0.0))
        key_bone(rig, "spine03", frame, (0.0, 0.0, swing * 0.035))
        rig.location.z = 0.018 if frame % 24 == 13 else 0.0
        rig.keyframe_insert("location", frame=frame)


def prepare_expression(rig, body):
    clear_animation(rig, body)
    keys = body.data.shape_keys.key_blocks
    names = [
        "!ex-mouthSmileLeft", "!ex-mouthSmileRight", "!ex-cheekSquintLeft",
        "!ex-cheekSquintRight", "!ex-browInnerUp", "!ex-eyeBlinkLeft", "!ex-eyeBlinkRight",
    ]
    for name in names:
        key = keys.get(name)
        if not key:
            continue
        for frame, value in ((1, 0.0), (25, 0.0), (43, 0.8), (61, 0.8), (73, 0.0)):
            if "Blink" in name:
                value = 1.0 if frame == 25 else 0.0
            key.value = value
            key.keyframe_insert("value", frame=frame)
    key_bone(rig, "head", 1, (0.0, 0.0, -0.05))
    key_bone(rig, "head", 43, (0.03, 0.0, 0.07))
    key_bone(rig, "head", 73, (0.0, 0.0, -0.05))


def render_video(camera, output, camera_location, target, lens):
    scene = bpy.context.scene
    camera.location = camera_location
    camera.data.lens = lens
    look_at(camera, target)
    scene.render.resolution_x = 640
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.fps = 24
    scene.frame_start = 1
    scene.frame_end = 73
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.filepath = str(output)
    bpy.ops.render.render(animation=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--stills-only", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    camera = setup_studio()
    rig, body = rig_and_body()
    clear_animation(rig, body)

    views = {
        "character_front.png": ((0.0, -4.15, 1.02), (0, 0, 0.91), 60),
        "character_3quarter.png": ((2.65, -3.25, 1.13), (0, 0, 0.92), 62),
        "character_side.png": ((4.2, -0.02, 1.04), (0, 0, 0.92), 62),
        "character_full_body.png": ((0.0, -4.35, 0.91), (0, 0, 0.86), 58),
        "character_closeup.png": ((0.0, -2.05, 1.49), (0, -0.02, 1.48), 72),
    }
    for filename, (location, target, lens) in views.items():
        render_still(camera, output / filename, location, target, lens)

    videos = []
    if not args.stills_only:
        prepare_idle(rig, body)
        render_video(camera, output / "character_idle.mp4", (0, -4.25, 1.0), (0, 0, 0.9), 60)
        prepare_walk(rig, body)
        render_video(camera, output / "character_walk.mp4", (0, -4.25, 1.0), (0, 0, 0.9), 60)
        prepare_expression(rig, body)
        render_video(camera, output / "character_expression.mp4", (0, -2.1, 1.48), (0, -0.02, 1.47), 72)
        videos = ["character_idle.mp4", "character_walk.mp4", "character_expression.mp4"]
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "character_animation_test.blend"))

    report = {
        "render_engine": "BLENDER_EEVEE",
        "views": list(views),
        "videos": videos,
        "fps": 24,
        "frames_per_test": 73,
        "cost_inr": 0,
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
