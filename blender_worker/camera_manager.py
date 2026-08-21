"""Seven-shot perspective-camera direction with physical movement."""
import bpy
from mathutils import Vector


def _look_at(camera, point):
    camera.rotation_euler = (Vector(point) - camera.location).to_track_quat("-Z", "Y").to_euler()


def create_camera(fps):
    data = bpy.data.cameras.new("CinematicCamera")
    data.lens, data.dof.use_dof, data.dof.aperture_fstop = 48, True, 3.2
    camera = bpy.data.objects.new("CinematicCamera", data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    shots = [
        (0, (6.0, -10.0, 3.2), (0, -2.8, 1.25), 52),
        (5, (3.0, -6.0, 1.8), (0, -2.7, 1.20), 46),
        (11, (3.0, -6.0, 1.90), (0, -2.2, 1.25), 40),
        (16, (3.0, -5.5, 1.90), (0, -1.55, 1.30), 46),
        (21, (0.8, -2.8, 1.90), (0, -1.10, 1.82), 70),
        (25, (-2.5, -5.0, 2.00), (0, -1.10, 1.45), 45),
        (30, (5.0, -8.0, 3.0), (0, -1.10, 1.30), 52),
    ]
    for seconds, location, target, lens in shots:
        frame = seconds * fps + 1
        camera.location, data.lens = location, lens
        _look_at(camera, target)
        camera.keyframe_insert("location", frame=frame)
        camera.keyframe_insert("rotation_euler", frame=frame)
        data.keyframe_insert("lens", frame=frame)
    return camera
