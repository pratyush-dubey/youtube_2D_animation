"""Install verified MakeHuman asset-pack ZIPs into MPFB's local user library."""
import argparse
import json
import sys
import zipfile
from pathlib import Path

import bpy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", action="append", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

    import bl_ext.blender_org.mpfb as mpfb
    try:
        mpfb.register()
    except (RuntimeError, ValueError):
        pass
    from bl_ext.blender_org.mpfb.services.assetservice import AssetService
    from bl_ext.blender_org.mpfb.services.locationservice import LocationService

    user_data = Path(LocationService.get_user_data())
    user_data.mkdir(parents=True, exist_ok=True)
    installed = []
    for value in args.pack:
        pack = Path(value).resolve()
        check = AssetService.check_asset_pack_zip(str(pack))
        if check is not None:
            raise RuntimeError(f"Invalid MPFB asset pack {pack.name}: {check}")
        with zipfile.ZipFile(pack, "r") as archive:
            # Official packs contain only relative MPFB library paths.
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in archive.namelist()):
                raise RuntimeError(f"Unsafe path found in {pack.name}")
            archive.extractall(user_data)
        installed.append(pack.name)

    AssetService.update_all_asset_lists()
    report = {
        "status": "installed",
        "packs": installed,
        "mpfb_user_data": str(user_data),
        "pack_names": AssetService.get_pack_names(),
        "skins": len(AssetService.list_mhmat_assets("skins")),
        "eyes": len(AssetService.list_mhclo_assets("eyes")),
        "hair": len(AssetService.list_mhclo_assets("hair")),
        "teeth": len(AssetService.list_mhclo_assets("teeth")),
        "clothes": len(AssetService.list_mhclo_assets("clothes")),
        "faceunits_available": bool(AssetService.get_asset_names_in_pack_pattern("faceunits01")),
        "cost_inr": 0,
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
