"""Import genuine provider assets. Primitive construction is intentionally unavailable."""
from pathlib import Path

import bpy

REJECTION = "Generated character is a procedural placeholder and cannot be used for production rendering."


def create_character(*_args, **_kwargs):
    """Retained only to turn calls to the retired path into an explicit failure."""
    raise RuntimeError(REJECTION)


def import_character(model_path):
    path = Path(model_path)
    if not path.is_file():
        raise RuntimeError(f"Production character model does not exist: {path}")
    before = set(bpy.data.objects)
    suffix = path.suffix.lower()
    if suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        raise RuntimeError(f"Unsupported production character format: {suffix}")
    imported = [obj for obj in bpy.data.objects if obj not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported character contains no mesh objects")
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    focus = max(meshes, key=lambda obj: len(obj.data.vertices))
    return {"objects": imported, "meshes": meshes, "armatures": armatures, "focus": focus}
