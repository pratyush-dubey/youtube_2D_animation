"""Physically positioned cinematic bank lighting."""
import bpy
from mathutils import Vector


def build_lighting():
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("CinematicWorld")
        bpy.context.scene.world = world
    world.color = (0.012, 0.018, 0.025)
    sun_data = bpy.data.lights.new("CoolAmbient", "SUN")
    sun_data.energy = 1.2
    sun_data.color = (0.42, 0.58, 0.78)
    sun = bpy.data.objects.new("CoolAmbient", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (0.7, -0.4, -0.6)
    for index, location in enumerate(((-3, -1, 3.4), (0, -1, 3.4), (3, -1, 3.4))):
        data = bpy.data.lights.new(f"WarmPractical{index}", "AREA")
        data.energy, data.shape, data.size = 520, "DISK", 2.0
        data.color = (1.0, 0.48, 0.18)
        light = bpy.data.objects.new(data.name, data)
        light.location = Vector(location)
        bpy.context.collection.objects.link(light)
    rim_data = bpy.data.lights.new("CharacterRim", "AREA")
    rim_data.energy, rim_data.size, rim_data.color = 700, 2.2, (0.25, 0.48, 1.0)
    rim = bpy.data.objects.new("CharacterRim", rim_data)
    rim.location = (2.4, 1.0, 2.8)
    rim.rotation_euler = (0.7, 0, 2.2)
    bpy.context.collection.objects.link(rim)
