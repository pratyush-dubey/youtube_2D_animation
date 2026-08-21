"""Blender 2.5D renderer for the strict 10-second bank acceptance proof.

Run with Blender: blender --background --python this_file.py -- --manifest ...
All visible movement is evaluated by Blender before FFmpeg encodes the frames.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


FPS = 15
END_FRAME = 150
PART_ORDER = (
    "torso", "neck", "head", "eyes", "eyebrows", "mouth",
    "upper_arm_left", "lower_arm_left", "hand_left",
    "upper_arm_right", "lower_arm_right", "hand_right",
    "upper_leg_left", "lower_leg_left", "foot_left",
    "upper_leg_right", "lower_leg_right", "foot_right",
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            datablocks.remove(block)


def material_for_image(path: str, name: str):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.surface_render_method = "DITHERED"
    nodes = material.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeEmission")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(path, check_existing=True)
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Color"])
    shader.inputs["Strength"].default_value = 1.0
    # Transparent alpha is handled by mixing emission with a transparent shader.
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    material.node_tree.links.new(texture.outputs["Alpha"], mix.inputs[0])
    material.node_tree.links.new(transparent.outputs[0], mix.inputs[1])
    material.node_tree.links.new(shader.outputs[0], mix.inputs[2])
    material.node_tree.links.new(mix.outputs[0], out.inputs[0])
    return material


def textured_plane(name, path, width, height, location, collection, pivot="center"):
    if pivot == "top":
        z0, z1 = -height, 0
    elif pivot == "bottom":
        z0, z1 = 0, height
    else:
        z0, z1 = -height / 2, height / 2
    x0, x1 = -width / 2, width / 2
    vertices = [(x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1)]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
    mesh.uv_layers.new(name="UVMap")
    uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
    for loop, uv in zip(mesh.uv_layers[0].data, uvs): loop.uv = uv
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(material_for_image(path, f"mat_{name}"))
    return obj


def flat_material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
    return mat


def colored_part(name, width, height, location, collection, pivot="center"):
    kind = name.removeprefix("CHAR_")
    if pivot == "top": z0, z1 = -height, 0
    elif pivot == "bottom": z0, z1 = 0, height
    else: z0, z1 = -height/2, height/2
    faces = None
    if kind == "head":
        vertices = [(-width*.38, 0, z0), (width*.38, 0, z0), (width*.5, 0, z0+height*.22),
                    (width*.46, 0, z1-height*.14), (width*.28, 0, z1), (-width*.28, 0, z1),
                    (-width*.46, 0, z1-height*.14), (-width*.5, 0, z0+height*.22)]
        faces = [tuple(range(8))]
    elif kind in {"eyes", "eyebrows"}:
        gap = width*.12; half = width*.18
        vertices = [(-gap-half, 0, z0), (-gap+half, 0, z0), (-gap+half, 0, z1), (-gap-half, 0, z1),
                    (gap-half, 0, z0), (gap+half, 0, z0), (gap+half, 0, z1), (gap-half, 0, z1)]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7)]
    elif kind == "torso":
        vertices = [(-width*.38, 0, z0), (width*.38, 0, z0), (width*.5, 0, z1), (-width*.5, 0, z1)]
    else:
        vertices = [(-width/2, 0, z0), (width/2, 0, z0), (width/2, 0, z1), (-width/2, 0, z1)]
    mesh = bpy.data.meshes.new(f"{name}_mesh"); mesh.from_pydata(vertices, [], faces or [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh); collection.objects.link(obj); obj.location = location
    if "leg" in kind: color = (.08, .25, .26, 1)
    elif "foot" in kind: color = (.07, .045, .035, 1)
    elif kind in {"head", "neck", "hand_left", "hand_right"} or "lower_arm" in kind: color = (.48, .25, .13, 1)
    elif kind in {"eyes", "eyebrows", "mouth"}: color = (.035, .025, .02, 1)
    else: color = (.72, .64, .43, 1)
    obj.data.materials.append(flat_material(f"mat_{name}", color))
    return obj


def ellipse(name, scale, location, collection, color=(0.04, 0.03, 0.025, 0.42)):
    bpy.ops.mesh.primitive_circle_add(vertices=48, radius=1, fill_type="NGON", location=location, rotation=(math.pi/2, 0, 0))
    obj = bpy.context.object; obj.name = name
    for target in list(obj.users_collection): target.objects.unlink(obj)
    collection.objects.link(obj)
    obj.scale = scale
    obj.data.materials.append(flat_material(f"mat_{name}", color))
    return obj


def set_visible(collection, frame_start, frame_end):
    for obj in collection.objects:
        obj.hide_render = True; obj.keyframe_insert("hide_render", frame=max(1, frame_start-1))
        obj.hide_render = False; obj.keyframe_insert("hide_render", frame=frame_start)
        obj.hide_render = False; obj.keyframe_insert("hide_render", frame=frame_end)
        if frame_end < END_FRAME:
            obj.hide_render = True; obj.keyframe_insert("hide_render", frame=frame_end+1)


def aim(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def key_location(obj, frame, location):
    obj.location = location; obj.keyframe_insert("location", frame=frame)


def key_rotation(obj, frame, degrees, axis=1):
    values = list(obj.rotation_euler); values[axis] = math.radians(degrees)
    obj.rotation_euler = values; obj.keyframe_insert("rotation_euler", frame=frame)


def build_layers(assets):
    exterior = bpy.data.collections.new("SHOT_01_02_EXTERIOR")
    interior = bpy.data.collections.new("SHOT_03_INTERIOR")
    bpy.context.scene.collection.children.link(exterior); bpy.context.scene.collection.children.link(interior)
    # Farther planes are physically deeper in Y. Their apparent displacement under
    # camera dolly is therefore smaller than the foreground displacement.
    textured_plane("EXT_BG_depth_-10", assets["exterior_background"], 18.0, 10.125, (0, 5.5, 3.2), exterior)
    textured_plane("EXT_FAR_depth_-7", assets["exterior_far"], 17.0, 9.56, (0, 3.2, 3.1), exterior)
    textured_plane("EXT_BANK_depth_-4", assets["exterior_bank"], 15.5, 8.72, (0, 1.0, 2.9), exterior)
    textured_plane("EXT_FORE_depth_+8", assets["exterior_foreground"], 14.2, 8.0, (0, -4.0, 2.8), exterior)
    textured_plane("INT_BG_depth_-10", assets["interior_background"], 18.0, 10.125, (0, 5.2, 3.2), interior)
    textured_plane("INT_MID_depth_-4", assets["interior_midground"], 15.2, 8.55, (0, 0.6, 2.9), interior)
    textured_plane("INT_FORE_depth_+8", assets["interior_foreground"], 13.9, 7.82, (0, -4.2, 2.8), interior)
    set_visible(exterior, 1, 105); set_visible(interior, 106, 150)
    return exterior, interior


def build_character(assets):
    collection = bpy.data.collections.new("CHARACTER_RIG_18_PARTS")
    bpy.context.scene.collection.children.link(collection)
    root = bpy.data.objects.new("CHAR_ROOT", None); collection.objects.link(root)
    root.location = (0, 0, 0)
    specs = {
        "torso": (.92, 1.22, (0, 0, 1.46), "center", None),
        "neck": (.26, .26, (0, -.01, 2.15), "center", "torso"),
        "head": (.67, .76, (0, -.03, 2.53), "center", "neck"),
        "eyes": (.41, .14, (0, -.05, 2.61), "center", "head"),
        "eyebrows": (.44, .12, (0, -.06, 2.75), "center", "head"),
        "mouth": (.28, .15, (0, -.06, 2.35), "center", "head"),
        "upper_arm_left": (.28, .72, (-.50, .02, 1.95), "top", "torso"),
        "lower_arm_left": (.23, .64, (-.50, .01, 1.26), "top", "upper_arm_left"),
        "hand_left": (.21, .27, (-.50, 0, .66), "top", "lower_arm_left"),
        "upper_arm_right": (.28, .72, (.50, .02, 1.95), "top", "torso"),
        "lower_arm_right": (.23, .64, (.50, .01, 1.26), "top", "upper_arm_right"),
        "hand_right": (.21, .27, (.50, 0, .66), "top", "lower_arm_right"),
        "upper_leg_left": (.34, .84, (-.24, .03, .95), "top", "torso"),
        "lower_leg_left": (.30, .81, (-.24, .02, .16), "top", "upper_leg_left"),
        "foot_left": (.46, .24, (-.10, -.01, -.59), "center", "lower_leg_left"),
        "upper_leg_right": (.34, .84, (.24, .04, .95), "top", "torso"),
        "lower_leg_right": (.30, .81, (.24, .03, .16), "top", "upper_leg_right"),
        "foot_right": (.46, .24, (.38, 0, -.59), "center", "lower_leg_right"),
    }
    objects = {}
    for index, name in enumerate(PART_ORDER):
        width, height, pos, pivot, _parent = specs[name]
        obj = colored_part(f"CHAR_{name}", width, height,
                           (pos[0], -1.1-index*.002, pos[2]), collection, pivot)
        objects[name] = obj
    parents = {
        "neck": "torso", "head": "neck", "eyes": "head", "eyebrows": "head", "mouth": "head",
        "upper_arm_left": "torso", "lower_arm_left": "upper_arm_left", "hand_left": "lower_arm_left",
        "upper_arm_right": "torso", "lower_arm_right": "upper_arm_right", "hand_right": "lower_arm_right",
        "upper_leg_left": "torso", "lower_leg_left": "upper_leg_left", "foot_left": "lower_leg_left",
        "upper_leg_right": "torso", "lower_leg_right": "upper_leg_right", "foot_right": "lower_leg_right",
    }
    for name, obj in objects.items():
        world = obj.matrix_world.copy()
        parent = objects.get(parents.get(name), root)
        obj.parent = parent
        bpy.context.view_layer.update()
        obj.matrix_world = world
        bpy.context.view_layer.update()
    hair = colored_part("CHAR_hair", .64, .18, (0, -1.158, 2.87), collection)
    hair.data.materials.clear(); hair.data.materials.append(flat_material("mat_hair", (.035, .022, .016, 1)))
    world = hair.matrix_world.copy(); hair.parent = objects["head"]; bpy.context.view_layer.update(); hair.matrix_world = world
    shadow = ellipse("CHAR_ground_shadow", (.62, .17, 1), (-3.9, -1.0, .05), collection)
    set_visible(collection, 38, 150)
    return root, objects, shadow


def animate_walk(root, parts, shadow):
    key_location(root, 38, (-3.9, 0, 0)); key_location(root, 46, (-3.6, 0, 0))
    key_location(root, 105, (2.0, 0, 0))
    key_location(shadow, 38, (-3.9, -1.0, .05)); key_location(shadow, 46, (-3.6, -1.0, .05)); key_location(shadow, 105, (2.0, -1.0, .05))
    step = 7
    for frame in range(39, 106, step):
        phase = 1 if ((frame-39)//step) % 2 == 0 else -1
        key_rotation(parts["upper_leg_left"], frame, 25*phase)
        key_rotation(parts["upper_leg_right"], frame, -25*phase)
        key_rotation(parts["lower_leg_left"], frame, 30 if phase < 0 else 2)
        key_rotation(parts["lower_leg_right"], frame, 30 if phase > 0 else 2)
        key_rotation(parts["upper_arm_left"], frame, -19*phase)
        key_rotation(parts["upper_arm_right"], frame, 19*phase)
        key_rotation(parts["lower_arm_left"], frame, 7 if phase > 0 else 0)
        key_rotation(parts["lower_arm_right"], frame, 7 if phase < 0 else 0)
        key_rotation(parts["torso"], frame, 1.6*phase)
        key_rotation(parts["head"], frame, -.8*phase)
        travel = -3.9 + ((frame-38) / (105-38)) * 5.9
        root.location = (travel, 0, 0 if phase > 0 else -.06); root.keyframe_insert("location", frame=frame)
        shadow.scale = (.62 if phase > 0 else .57, .17, 1); shadow.keyframe_insert("scale", frame=frame)


def animate_look_and_sit(root, parts, shadow):
    # Hard shot cut: character and camera are repositioned inside the bank.
    key_location(root, 105, (2.0, 0, 0)); key_location(root, 106, (-.45, 0, 0))
    root.scale = (1, 1, 1); root.keyframe_insert("scale", frame=105)
    root.scale = (1.45, 1.45, 1.45); root.keyframe_insert("scale", frame=106)
    key_location(shadow, 105, (2.0, -1.0, .05)); key_location(shadow, 106, (-.45, -.9, .05))
    for frame, angle, eye_x in ((106, 0, 0), (114, -12, -.06), (121, 13, .06), (126, 0, 0)):
        key_rotation(parts["head"], frame, angle)
        parts["eyes"].location.x = eye_x; parts["eyes"].keyframe_insert("location", frame=frame)
    # Blink proves the eye layer is independent.
    parts["eyes"].scale.z = 1; parts["eyes"].keyframe_insert("scale", frame=118)
    parts["eyes"].scale.z = .12; parts["eyes"].keyframe_insert("scale", frame=120)
    parts["eyes"].scale.z = 1; parts["eyes"].keyframe_insert("scale", frame=122)
    key_location(root, 126, (-.45, 0, 0)); key_location(root, 150, (-.12, 0, -.60))
    key_location(shadow, 126, (-.45, -.9, .05)); key_location(shadow, 150, (-.12, -.9, .05))
    for name in ("upper_leg_left", "upper_leg_right"): key_rotation(parts[name], 126, 0); key_rotation(parts[name], 150, -67)
    for name in ("lower_leg_left", "lower_leg_right"): key_rotation(parts[name], 126, 0); key_rotation(parts[name], 150, 86)
    key_rotation(parts["torso"], 126, 0); key_rotation(parts["torso"], 140, 9); key_rotation(parts["torso"], 150, 3)
    key_rotation(parts["head"], 140, -4); key_rotation(parts["head"], 150, 1)
    shadow.scale = (.62, .17, 1); shadow.keyframe_insert("scale", frame=126)
    shadow.scale = (.72, .15, 1); shadow.keyframe_insert("scale", frame=150)


def animate_environment(interior):
    fan_hub = bpy.data.objects.new("ENV_ceiling_fan", None); interior.objects.link(fan_hub); fan_hub.location = (3.7, -.4, 5.15)
    blade_mat = flat_material("mat_fan", (.12, .10, .08, 1))
    for i in range(4):
        bpy.ops.mesh.primitive_cube_add(location=(0, -.4, 5.0), scale=(.78, .025, .055))
        blade = bpy.context.object; blade.name = f"ENV_fan_blade_{i}"
        for c in list(blade.users_collection): c.objects.unlink(blade)
        interior.objects.link(blade); blade.parent = fan_hub; blade.location = (0, 0, 0)
        blade.rotation_euler.y = math.radians(i*90); blade.data.materials.append(blade_mat)
    set_visible(interior, 106, 150)
    key_rotation(fan_hub, 106, 0); key_rotation(fan_hub, 150, 1080)
    paper = ellipse("ENV_moving_paper", (.34, .12, 1), (3.2, -.3, 1.8), interior, (.88, .79, .60, 1))
    key_rotation(paper, 106, -2); key_rotation(paper, 128, 5); key_rotation(paper, 150, -3)
    # Restrained dust particles, each on its own animated path.
    dust_mat = flat_material("mat_dust", (1.0, .78, .42, .32))
    for i in range(11):
        bpy.ops.mesh.primitive_circle_add(vertices=12, radius=.022 + i*.002, fill_type="NGON", location=(-4+i*.75, -.5-i*.01, 1+(i%4)*.8))
        dot = bpy.context.object; dot.name = f"ATM_dust_{i:02d}"; dot.data.materials.append(dust_mat)
        for c in list(dot.users_collection): c.objects.unlink(dot)
        interior.objects.link(dot)
        key_location(dot, 106, tuple(dot.location)); key_location(dot, 150, (dot.location.x+.35, dot.location.y, dot.location.z+.5))
    set_visible(interior, 106, 150)


def create_camera():
    camera_data = bpy.data.cameras.new("Physical_2_5D_Camera")
    camera = bpy.data.objects.new("Physical_2_5D_Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera); bpy.context.scene.camera = camera
    camera.data.lens = 42
    key_location(camera, 1, (-1.15, -17.2, 3.2)); aim(camera, (0, 1.2, 3.0)); camera.keyframe_insert("rotation_euler", frame=1)
    key_location(camera, 45, (-.55, -14.6, 3.15)); aim(camera, (.1, 1.1, 3.0)); camera.keyframe_insert("rotation_euler", frame=45)
    key_location(camera, 46, (-2.0, -15.7, 3.0)); aim(camera, (-1.5, 0, 1.85)); camera.keyframe_insert("rotation_euler", frame=46)
    key_location(camera, 105, (1.4, -14.2, 3.0)); aim(camera, (1.3, 0, 1.85)); camera.keyframe_insert("rotation_euler", frame=105)
    key_location(camera, 106, (-1.4, -14.8, 3.0)); aim(camera, (-.2, 0, 2.55)); camera.keyframe_insert("rotation_euler", frame=106)
    key_location(camera, 150, (-.65, -12.6, 2.75)); aim(camera, (-.1, 0, 2.25)); camera.keyframe_insert("rotation_euler", frame=150)
    return camera


def configure(output: Path):
    scene = bpy.context.scene
    # Workbench renders the authored texture planes and mesh puppet in a few
    # milliseconds per frame on integrated graphics; the animation remains a
    # genuine Blender scene with a physical perspective camera.
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.show_specular_highlight = False
    scene.display.shading.background_type = "WORLD"
    scene.render.resolution_x = 640; scene.render.resolution_y = 360; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"; scene.render.film_transparent = False
    scene.render.fps = FPS; scene.frame_start = 1; scene.frame_end = END_FRAME
    scene.world.color = (.025, .022, .018)
    scene.render.filepath = str(output / "frames" / "frame_")
    scene.render.image_settings.color_mode = "RGB"
    return scene


def render(scene, output, camera, parts):
    frames = output / "frames"; frames.mkdir(parents=True, exist_ok=True)
    telemetry = []
    for frame in range(1, END_FRAME+1):
        scene.frame_set(frame)
        path = frames / f"frame_{frame:04d}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        joints = {}
        for name in ("head", "upper_arm_left", "upper_arm_right", "upper_leg_left", "upper_leg_right", "foot_left", "foot_right"):
            co = world_to_camera_view(scene, camera, parts[name].matrix_world.translation)
            joints[name] = [round(co.x*640, 2), round((1-co.y)*360, 2)]
        telemetry.append({"frame": frame, "camera": [round(v, 4) for v in camera.location], "joints": joints})
    (output / "animation_telemetry.json").write_text(json.dumps(telemetry, indent=2), encoding="utf-8")
    video = output / "cinematic_10s_proof.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "frame_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19", str(video)], check=True)
    return video


def main():
    args = parse_args(); manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8")); assets = manifest["assets"]
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    clear_scene(); scene = configure(output); build_layers(assets)
    root, parts, shadow = build_character(assets); animate_walk(root, parts, shadow); animate_look_and_sit(root, parts, shadow)
    interior = bpy.data.collections["SHOT_03_INTERIOR"]; animate_environment(interior)
    camera = create_camera()
    blend_path = output / "cinematic_10s_proof.blend"; bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    video = render(scene, output, camera, parts)
    print(json.dumps({"video": str(video), "blend": str(blend_path), "frames": END_FRAME, "fps": FPS}))


if __name__ == "__main__": main()
