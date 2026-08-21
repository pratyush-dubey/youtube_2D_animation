"""Generate a genuine parametric human with the free MPFB Blender extension."""
import argparse
import json
import sys
from pathlib import Path

import bpy


def _load_mpfb():
    try:
        import bl_ext.blender_org.mpfb as mpfb
    except ImportError as exc:
        raise RuntimeError(
            "MPFB is not installed. Install the free Blender extension named 'mpfb'."
        ) from exc
    try:
        mpfb.register()
    except (RuntimeError, ValueError):
        pass
    from bl_ext.blender_org.mpfb.services.humanservice import HumanService
    from bl_ext.blender_org.mpfb.services.targetservice import TargetService
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService
    from bl_ext.blender_org.mpfb.services.faceservice import FaceService

    return HumanService, TargetService, AssetService, FaceService


def _named_asset(AssetService, kind, name, extension):
    paths = (
        AssetService.list_mhmat_assets(kind)
        if extension == ".mhmat"
        else AssetService.list_mhclo_assets(kind)
    )
    match = next((str(path) for path in paths if Path(path).stem == name), None)
    if not match:
        raise RuntimeError(f"Required CC0 MPFB asset is missing: {kind}/{name}{extension}")
    return match


def generate(specification):
    HumanService, TargetService, AssetService, FaceService = _load_mpfb()
    macro = TargetService.get_default_macro_info_dict()
    phenotype = specification.get("phenotype", {})
    macro.update({
        "gender": float(phenotype.get("gender", 1.0)),
        "age": float(phenotype.get("age", 0.55)),
        "muscle": float(phenotype.get("muscle", 0.52)),
        "weight": float(phenotype.get("weight", 0.48)),
        "height": float(phenotype.get("height", 0.52)),
        "proportions": float(phenotype.get("proportions", 0.52)),
    })
    race = phenotype.get("race", {"asian": 0.55, "african": 0.25, "caucasian": 0.20})
    macro["race"].update({key: float(value) for key, value in race.items()})
    basemesh = HumanService.create_human(
        mask_helpers=True,
        detailed_helpers=True,
        extra_vertex_groups=True,
        feet_on_ground=True,
        scale=0.1,
        macro_detail_dict=macro,
    )
    basemesh.name = specification.get("character_id", "fictional_indian_adult") + ".body"
    subdivision = basemesh.modifiers.new("ProductionSubdivision", "SUBSURF")
    subdivision.levels = 1
    subdivision.render_levels = 2
    armature = HumanService.add_builtin_rig(basemesh, "default", import_weights=True)
    if armature is None:
        raise RuntimeError("MPFB failed to create the weighted default humanoid rig")

    selected = {
        "skin": "middleage_asian_male",
        "eyes": "high-poly",
        "eyebrows": "eyebrow004",
        "eyelashes": "eyelashes01",
        "hair": "short02",
        "teeth": "teeth_base",
        "clothing": "male_casualsuit04",
        "shoes": "shoes02",
    }
    HumanService.set_character_skin(
        _named_asset(AssetService, "skins", selected["skin"], ".mhmat"),
        basemesh,
        skin_type="MAKESKIN",
        material_instances=False,
    )
    for kind, key, asset_type in (
        ("eyes", "eyes", "eyes"),
        ("eyebrows", "eyebrows", "eyebrows"),
        ("eyelashes", "eyelashes", "eyelashes"),
        ("hair", "hair", "hair"),
        ("teeth", "teeth", "teeth"),
        ("clothes", "clothing", "Clothes"),
        ("clothes", "shoes", "Clothes"),
    ):
        HumanService.add_mhclo_asset(
            _named_asset(AssetService, kind, selected[key], ".mhclo"),
            basemesh,
            asset_type=asset_type,
            subdiv_levels=1,
            material_type="MAKESKIN",
        )
    FaceService.load_targets(
        basemesh,
        load_microsoft_visemes=False,
        load_meta_visemes=False,
        load_arkit_faceunits=True,
    )
    return basemesh, armature, selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    basemesh, armature, selected = generate(spec)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix(".blend")))
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        export_skins=True,
        export_morph=True,
        export_animations=True,
    )
    basemesh.data.calc_loop_triangles()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    materials = sorted({slot.material.name for obj in meshes for slot in obj.material_slots if slot.material})
    textures = sorted({image.filepath for image in bpy.data.images if image.filepath})
    report = {
        "provider": "mpfb_local",
        "generation_status": "generated",
        "model_format": "glb",
        "model_path": str(output),
        "vertex_count": len(basemesh.data.vertices),
        "triangle_count": len(basemesh.data.loop_triangles),
        "material_count": len(materials),
        "materials": materials,
        "textures": textures,
        "uv_layer_count": len(basemesh.data.uv_layers),
        "bone_count": len(armature.data.bones),
        "shape_key_count": len(basemesh.data.shape_keys.key_blocks) if basemesh.data.shape_keys else 0,
        "selected_assets": selected,
        "quality_status": "requires_assets_and_beauty_test",
        "production_ready": False,
        "cost_inr": 0,
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
