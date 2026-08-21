"""Period-aware 1980s Bengaluru bank test environment."""
import bpy
from material_manager import toon_material


def _cube(name, location, scale, material):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name, obj.scale = name, scale
    obj.data.materials.append(material)
    return obj


def build_bank_environment(period="1980s"):
    stone = toon_material("BankStone", (0.34, 0.28, 0.18))
    plaster = toon_material("AgedPlaster", (0.44, 0.37, 0.24))
    wood = toon_material("DarkWood", (0.20, 0.07, 0.025))
    floor = toon_material("Terrazzo", (0.19, 0.20, 0.16))
    brass = toon_material("AgedBrass", (0.48, 0.26, 0.05), 0.5)
    _cube("Ground", (0, 0, -0.12), (20, 14, 0.12), floor)
    _cube("BankFacade", (0, 3.4, 2.3), (6.4, 0.25, 2.3), plaster)
    _cube("LeftWall", (-4.2, 0.3, 2.1), (0.2, 3.0, 2.1), stone)
    _cube("RightWall", (4.2, 0.3, 2.1), (0.2, 3.0, 2.1), stone)
    _cube("Counter", (0, 0.3, 0.72), (3.4, 0.42, 0.72), wood)
    for x in (-2.5, -1.25, 0, 1.25, 2.5):
        _cube(f"CounterGrille{x}", (x, 0.2, 1.75), (0.025, 0.025, 0.95), brass)
    for x in (-2.6, 0, 2.6):
        _cube(f"LedgerDesk{x}", (x, -2.0, 0.60), (0.8, 0.45, 0.06), wood)
        _cube(f"Ledger{x}", (x, -2.02, 0.69), (0.30, 0.20, 0.025), brass)
    # A real doorway opening is represented by framing columns and lintel.
    _cube("DoorFrameL", (-1.25, 3.08, 1.35), (0.18, 0.24, 1.35), wood)
    _cube("DoorFrameR", (1.25, 3.08, 1.35), (0.18, 0.24, 1.35), wood)
    _cube("DoorLintel", (0, 3.08, 2.68), (1.43, 0.24, 0.18), wood)
    return {"period": period, "location": "Bengaluru bank", "modern_objects": False}
