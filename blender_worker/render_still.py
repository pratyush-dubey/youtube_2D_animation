"""Quick sanity-check render of a saved puppet .blend at its current pose.

Run: blender --background <puppet.blend> --python render_still.py -- --out <frame.png>
"""
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
out_path = args[args.index("--out") + 1]

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 1280
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("World") if not scene.world else scene.world
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.07, 1.0)
scene.render.filepath = out_path
bpy.ops.render.render(write_still=True)
print(f"rendered {out_path}")
