"""Strict Blender-side production gate for imported human assets."""
from mathutils import Vector

PRIMITIVE_WORDS = ("sphere", "ico", "cube", "capsule", "cylinder", "ellipsoid")
FACIAL_WORDS = ("jaw", "eye", "brow", "lip", "mouth", "face", "blink")
HUMANOID_WORD_GROUPS = (
    ("head",), ("spine", "chest"), ("arm", "shoulder"), ("hand", "wrist"),
    ("leg", "thigh", "calf"), ("foot", "ankle"),
)


def validate_imported_character(character):
    meshes = character["meshes"]
    armatures = character["armatures"]
    vertices = sum(len(obj.data.vertices) for obj in meshes)
    triangles = 0
    material_names = set()
    texture_paths = set()
    uv_meshes = 0
    primitive_meshes = 0
    shape_keys = set()
    bounds = []
    for obj in meshes:
        obj.data.calc_loop_triangles()
        triangles += len(obj.data.loop_triangles)
        if obj.data.uv_layers:
            uv_meshes += 1
        if any(word in obj.name.lower() for word in PRIMITIVE_WORDS):
            primitive_meshes += 1
        if obj.data.shape_keys:
            shape_keys.update(key.name.lower() for key in obj.data.shape_keys.key_blocks)
        for material in obj.data.materials:
            if not material:
                continue
            material_names.add(material.name)
            if material.use_nodes:
                for node in material.node_tree.nodes:
                    if node.type == "TEX_IMAGE" and node.image:
                        texture_paths.add(node.image.filepath or node.image.name)
        bounds.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    dimensions = [max(p[i] for p in bounds) - min(p[i] for p in bounds) for i in range(3)] if bounds else [0, 0, 0]
    height = max(dimensions)
    bones = {
        bone.name.lower()
        for armature in armatures
        for bone in armature.data.bones
    }
    humanoid_groups = sum(any(word in name for name in bones for word in group) for group in HUMANOID_WORD_GROUPS)
    facial_controls = {name for name in bones | shape_keys if any(word in name for word in FACIAL_WORDS)}
    reasons = []
    if vertices < 15000:
        reasons.append(f"vertex_count {vertices} is below the production minimum 15000")
    if triangles < 20000:
        reasons.append(f"triangle_count {triangles} is below the production minimum 20000")
    if not 0.5 <= height <= 3.0:
        reasons.append(f"bounding-box height {height:.3f} is implausible for a normalized human")
    if len(material_names) < 3:
        reasons.append("fewer than three materials; skin, hair, and clothing are not distinguishable")
    if uv_meshes == 0:
        reasons.append("no UV-mapped mesh found")
    if not texture_paths:
        reasons.append("no image textures found")
    if not armatures:
        reasons.append("no armature found")
    if armatures and humanoid_groups < 6:
        reasons.append("armature does not expose a complete recognizable humanoid structure")
    if not facial_controls:
        reasons.append("no facial bones or shape keys found")
    if primitive_meshes >= max(3, len(meshes) // 2):
        reasons.append("model is primarily named primitive geometry")
    return {
        "passed": not reasons,
        "quality_status": "accepted" if not reasons else "rejected",
        "model_format": "",
        "vertex_count": vertices,
        "triangle_count": triangles,
        "materials": sorted(material_names),
        "textures": sorted(texture_paths),
        "mesh_count": len(meshes),
        "uv_mesh_count": uv_meshes,
        "bounding_box_dimensions": [round(value, 4) for value in dimensions],
        "rig_status": "humanoid_validated" if armatures and humanoid_groups == 6 else "rejected",
        "facial_rig_status": "available" if facial_controls else "rejected",
        "animation_test_status": "not_tested",
        "primitive_mesh_count": primitive_meshes,
        "rejection_reasons": reasons,
    }
