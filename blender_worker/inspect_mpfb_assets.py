"""Write a compact inventory of locally installed MPFB assets."""
import argparse
import json
import os
import sys
from pathlib import Path

import bpy


def records(paths):
    return [
        {"name": Path(value).stem, "path": str(value), "folder": Path(value).parent.name}
        for value in paths
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    import bl_ext.blender_org.mpfb as mpfb
    try:
        mpfb.register()
    except (RuntimeError, ValueError):
        pass
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService
    from bl_ext.blender_org.mpfb.services.faceservice import FaceService
    inventory = {
        "packs": AssetService.get_pack_names(),
        "skins": records(AssetService.list_mhmat_assets("skins")),
        "eyes": records(AssetService.list_mhclo_assets("eyes")),
        "hair": records(AssetService.list_mhclo_assets("hair")),
        "teeth": records(AssetService.list_mhclo_assets("teeth")),
        "eyebrows": records(AssetService.list_mhclo_assets("eyebrows")),
        "eyelashes": records(AssetService.list_mhclo_assets("eyelashes")),
        "clothes": records(AssetService.list_mhclo_assets("clothes")),
        "faceunits_available": FaceService.is_faceunits01_installed(force_recheck=True),
    }
    Path(args.output).write_text(json.dumps(inventory, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
