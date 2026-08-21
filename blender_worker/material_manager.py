"""Toon/cel materials with controlled highlights."""
import bpy


def toon_material(name, color, roughness=0.75):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (*color, 1.0)
    diffuse.inputs["Roughness"].default_value = roughness
    shader = nodes.new("ShaderNodeShaderToRGB")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].position = 0.28
    ramp.color_ramp.elements[0].color = (*[channel * 0.23 for channel in color], 1.0)
    ramp.color_ramp.elements[1].position = 0.68
    ramp.color_ramp.elements[1].color = (*color, 1.0)
    emission = nodes.new("ShaderNodeEmission")
    links.new(diffuse.outputs[0], shader.inputs[0])
    links.new(shader.outputs[0], ramp.inputs[0])
    links.new(ramp.outputs[0], emission.inputs[0])
    links.new(emission.outputs[0], output.inputs[0])
    return material
