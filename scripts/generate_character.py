"""
Medieval Character Generator — Blender 4.2 LTS headless
========================================================
Personagem medieval masculino completo:
  - Basemesh humano via MPFB2 (com fallback paramétrico)
  - Rig Rigify
  - Armadura medieval low-poly (8 peças)
  - Materiais PBR compatíveis com glTF
  - Câmara + iluminação de estúdio
  - Exportação: character.glb + character.blend + character_preview.png + character_report.json

Uso:
    blender -b --python scripts/generate_character.py -- --output /caminho/para/output
"""

import sys
import os
import json
import math
import time
import importlib
import argparse

import bpy
import bmesh
from mathutils import Vector

# ─────────────────────────────────────────────────────────────────────────────
# 0. Argumentos
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Medieval character generator")
    parser.add_argument("--output", default="/tmp/character_output", help="Output directory")
    return parser.parse_args(argv)

ARGS = parse_args()
OUTPUT_DIR = ARGS.output
os.makedirs(OUTPUT_DIR, exist_ok=True)

report = {
    "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "steps": [],
    "errors": [],
    "warnings": [],
    "output_files": [],
}

def log(msg, level="INFO"):
    prefix = {"INFO": "✓", "WARN": "⚠", "ERROR": "✗"}.get(level, "·")
    print(f"[{prefix}] {msg}", flush=True)
    if level == "ERROR":
        report["errors"].append(msg)
    elif level == "WARN":
        report["warnings"].append(msg)

def step(name):
    log(f"── {name}")
    report["steps"].append(name)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Importação dinâmica dos módulos MPFB2
# ─────────────────────────────────────────────────────────────────────────────

def dynamic_import(absolute_package_str, key):
    for amod in sys.modules:
        if amod.endswith(absolute_package_str):
            mod = importlib.import_module(amod)
            if not hasattr(mod, key):
                raise AttributeError(f"Module {amod} has no attribute '{key}'")
            return getattr(mod, key)
    raise ValueError(f"No loaded module ends with '{absolute_package_str}'")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Cena limpa
# ─────────────────────────────────────────────────────────────────────────────

step("Clean scene")
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "MedievalCharacter"
log("Scene cleared")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Ativar add-ons
# ─────────────────────────────────────────────────────────────────────────────

step("Enable add-ons")

try:
    bpy.ops.preferences.addon_enable(module="rigify")
    log("Rigify enabled")
except Exception as e:
    log(f"Rigify enable failed: {e}", "WARN")

mpfb_enabled = False
for addon in bpy.context.preferences.addons.keys():
    if "mpfb" in addon.lower():
        mpfb_enabled = True
        log(f"MPFB2 already registered: {addon}")
        break

if not mpfb_enabled:
    for method, kwargs in [
        ("addon_enable", {"module": "mpfb"}),
        ("extensions.package_enable", {"package": "mpfb", "repo_index": 0}),
    ]:
        try:
            op = bpy.ops
            for part in method.split("."):
                op = getattr(op, part)
            op(**kwargs)
            mpfb_enabled = True
            log(f"MPFB2 enabled via {method}")
            break
        except Exception as e:
            log(f"{method} failed: {e}", "WARN")

try:
    bpy.ops.wm.save_userpref()
except Exception:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# 4. Basemesh humano via MPFB2
# ─────────────────────────────────────────────────────────────────────────────

step("Generate human basemesh")

basemesh = None
use_mpfb = False

if mpfb_enabled:
    try:
        HumanService = dynamic_import("mpfb.services.humanservice", "HumanService")
        basemesh = HumanService.create_human()
        basemesh.name = "MedievalHuman"
        use_mpfb = True
        log(f"MPFB2 basemesh: {basemesh.name} ({len(basemesh.data.vertices)} verts)")
    except Exception as e:
        log(f"MPFB2 HumanService failed: {e}", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# 4b. Fallback paramétrico
# ─────────────────────────────────────────────────────────────────────────────

if basemesh is None:
    log("Building parametric human body (fallback)")
    mesh = bpy.data.meshes.new("HumanMesh")
    basemesh = bpy.data.objects.new("MedievalHuman", mesh)
    scene.collection.objects.link(basemesh)
    bm = bmesh.new()

    def add_cylinder(bm, radius, height, segments=12, offset_z=0.0, offset_x=0.0):
        bot, top = [], []
        for s in range(segments):
            a = (s / segments) * 2 * math.pi
            x, y = offset_x + radius * math.cos(a), radius * math.sin(a)
            bot.append(bm.verts.new((x, y, offset_z)))
            top.append(bm.verts.new((x, y, offset_z + height)))
        for s in range(segments):
            bm.faces.new([bot[s], bot[(s+1) % segments],
                          top[(s+1) % segments], top[s]])
        bc = bm.verts.new((offset_x, 0, offset_z))
        tc = bm.verts.new((offset_x, 0, offset_z + height))
        for s in range(segments):
            bm.faces.new([bc, bot[(s+1) % segments], bot[s]])
            bm.faces.new([tc, top[s], top[(s+1) % segments]])

    add_cylinder(bm, 0.07, 0.42, offset_z=0.0,  offset_x=-0.09)  # perna esq
    add_cylinder(bm, 0.07, 0.42, offset_z=0.0,  offset_x= 0.09)  # perna dir
    add_cylinder(bm, 0.18, 0.55, offset_z=0.42)                   # torso
    add_cylinder(bm, 0.055, 0.14, offset_z=0.97)                  # pescoço
    add_cylinder(bm, 0.12, 0.24, offset_z=1.11)                   # cabeça
    add_cylinder(bm, 0.055, 0.55, offset_z=0.72, offset_x=-0.26)  # braço esq
    add_cylinder(bm, 0.055, 0.55, offset_z=0.72, offset_x= 0.26)  # braço dir

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    log(f"Parametric basemesh: {len(mesh.vertices)} verts")

# Garantir que o basemesh está na coleção
if basemesh.name not in scene.collection.objects:
    scene.collection.objects.link(basemesh)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Rig Rigify
# ─────────────────────────────────────────────────────────────────────────────

step("Generate Rigify rig")

rig_object = None

if use_mpfb:
    try:
        SystemService = dynamic_import("mpfb.services.systemservice", "SystemService")
        RigService    = dynamic_import("mpfb.services.rigservice",    "RigService")
        HumanService2 = dynamic_import("mpfb.services.humanservice",  "HumanService")

        if not SystemService.check_for_rigify():
            raise RuntimeError("Rigify not available")

        metarig    = HumanService2.add_builtin_rig(basemesh, "rigify.human")
        rig_object = RigService.generate_rigify_rig(metarig, meta_rig_action="delete")
        log(f"Rigify rig via MPFB2: {rig_object.name}")
    except Exception as e:
        log(f"MPFB2 rig failed: {e}", "WARN")

if rig_object is None:
    try:
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.armature_human_metarig_add()
        metarig = bpy.context.active_object
        metarig.name = "metarig"
        bpy.context.view_layer.objects.active = metarig

        import rigify
        rigify.generate.generate_rig(bpy.context, metarig)
        rig_object = bpy.context.active_object
        log(f"Rigify rig manual: {rig_object.name}")

        bpy.ops.object.select_all(action='DESELECT')
        basemesh.select_set(True)
        rig_object.select_set(True)
        bpy.context.view_layer.objects.active = rig_object
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        log("Basemesh parented with automatic weights")
    except Exception as e:
        log(f"Manual Rigify failed: {e}", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Armadura medieval (8 peças low-poly)
# ─────────────────────────────────────────────────────────────────────────────

step("Build medieval armor")

def make_armor_piece(name, location, radius, height, segments=10):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    obj  = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    bm = bmesh.new()
    bot, top = [], []
    for i in range(segments):
        a = (i / segments) * 2 * math.pi
        x, y = radius * math.cos(a), radius * math.sin(a)
        bot.append(bm.verts.new((x, y, 0.0)))
        top.append(bm.verts.new((x, y, height)))
    for i in range(segments):
        bm.faces.new([bot[i], bot[(i+1) % segments],
                      top[(i+1) % segments], top[i]])
    bc = bm.verts.new((0, 0, 0))
    tc = bm.verts.new((0, 0, height))
    for i in range(segments):
        bm.faces.new([bc, bot[(i+1) % segments], bot[i]])
        bm.faces.new([tc, top[i], top[(i+1) % segments]])
    bm.to_mesh(mesh); bm.free(); mesh.update()
    obj.location = Vector(location)
    return obj

armor_defs = [
    ("Helmet",      ( 0.00, 0, 1.55), 0.145, 0.22),
    ("Breastplate", ( 0.00, 0, 0.72), 0.21,  0.50),
    ("Shoulder_L",  (-0.30, 0, 1.00), 0.09,  0.18),
    ("Shoulder_R",  ( 0.30, 0, 1.00), 0.09,  0.18),
    ("Gauntlet_L",  (-0.32, 0, 0.42), 0.065, 0.20),
    ("Gauntlet_R",  ( 0.32, 0, 0.42), 0.065, 0.20),
    ("Greave_L",    (-0.10, 0, 0.00), 0.08,  0.40),
    ("Greave_R",    ( 0.10, 0, 0.00), 0.08,  0.40),
]

armor_objects = []
for name, loc, r, h in armor_defs:
    obj = make_armor_piece(name, loc, r, h)
    armor_objects.append(obj)
    log(f"  {name}")

log(f"Armor: {len(armor_objects)} pieces")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Materiais PBR (compatíveis glTF)
# ─────────────────────────────────────────────────────────────────────────────

step("Apply PBR materials")

def make_material(name, base_color, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Metallic"].default_value   = metallic
    bsdf.inputs["Roughness"].default_value  = roughness
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat

mat_skin  = make_material("Skin",    (0.80, 0.60, 0.45), 0.0,  0.60)
mat_steel = make_material("Steel",   (0.72, 0.72, 0.75), 0.95, 0.25)

def assign_mat(obj, mat):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

assign_mat(basemesh, mat_skin)
for obj in armor_objects:
    assign_mat(obj, mat_steel)
log("Materials assigned")

# ─────────────────────────────────────────────────────────────────────────────
# 8. Iluminação de estúdio
# ─────────────────────────────────────────────────────────────────────────────

step("Studio lighting")

bpy.ops.object.light_add(type='AREA', location=(2.5, -2.5, 3.5))
key = bpy.context.active_object
key.name = "KeyLight"; key.data.energy = 800; key.data.size = 2.0

bpy.ops.object.light_add(type='AREA', location=(-2.0, -1.5, 2.0))
fill = bpy.context.active_object
fill.name = "FillLight"; fill.data.energy = 300; fill.data.size = 3.0

bpy.ops.object.light_add(type='SPOT', location=(0, 3.0, 2.5))
rim = bpy.context.active_object
rim.name = "RimLight"; rim.data.energy = 500
rim.data.spot_size = math.radians(45)

log("Key + fill + rim lights added")

# ─────────────────────────────────────────────────────────────────────────────
# 9. Câmara
# ─────────────────────────────────────────────────────────────────────────────

step("Camera setup")

bpy.ops.object.camera_add(location=(0, -4.0, 0.9))
camera = bpy.context.active_object
camera.name = "PresentationCamera"
camera.rotation_euler = (math.radians(90), 0, 0)
camera.data.lens = 50
scene.camera = camera
log("Camera ready")

# ─────────────────────────────────────────────────────────────────────────────
# 10. Preview PNG (WORKBENCH — sem GPU, funciona headless)
# ─────────────────────────────────────────────────────────────────────────────

step("Render preview")

# WORKBENCH é o único motor garantido headless sem GPU no runner do GitHub
scene.render.engine             = 'BLENDER_WORKBENCH'
scene.render.resolution_x       = 1024
scene.render.resolution_y       = 1024
scene.render.resolution_percentage = 100
preview_path = os.path.join(OUTPUT_DIR, "character_preview.png")
scene.render.filepath           = preview_path
scene.render.image_settings.file_format = 'PNG'

# Workbench: iluminação por Studio
scene.display.shading.light     = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'

try:
    bpy.ops.render.render(write_still=True)
    if os.path.exists(preview_path):
        log(f"Preview rendered: {preview_path}")
        report["output_files"].append("character_preview.png")
    else:
        log("Preview file not found after render", "WARN")
except Exception as e:
    log(f"Preview render failed (non-critical): {e}", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# 11. Guardar .blend
# ─────────────────────────────────────────────────────────────────────────────

step("Save .blend")

blend_path = os.path.join(OUTPUT_DIR, "character.blend")
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    log(f"Blend saved: {blend_path}")
    report["output_files"].append("character.blend")
except Exception as e:
    log(f"Blend save failed: {e}", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# 12. Exportar GLB
#
#  Parâmetros válidos no Blender 4.2 LTS:
#  - export_colors foi REMOVIDO na 4.1+ (substituído por export_attributes)
#  - export_texcoords, export_normals, export_apply, export_skins: OK
#  - export_def_bones: OK no 4.2
#  - export_attributes: exporta color attributes se existirem
# ─────────────────────────────────────────────────────────────────────────────

step("Export GLB")

glb_path = os.path.join(OUTPUT_DIR, "character.glb")

try:
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format='GLB',
        export_apply=True,
        export_materials='EXPORT',
        export_texcoords=True,
        export_normals=True,
        export_animations=True,
        export_skins=True,
        export_all_influences=False,
        export_def_bones=True,
        export_attributes=True,     # substitui export_colors no Blender 4.2+
        export_yup=True,
    )
except Exception as e:
    log(f"GLB export with full params failed: {e}", "WARN")
    log("Retrying with minimal params...", "WARN")
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_path,
            export_format='GLB',
            export_apply=True,
        )
    except Exception as e2:
        log(f"GLB export minimal also failed: {e2}", "ERROR")
        sys.exit(1)

if os.path.exists(glb_path):
    size_mb = os.path.getsize(glb_path) / (1024 * 1024)
    log(f"GLB exported: {glb_path} ({size_mb:.2f} MB)")
    report["output_files"].append("character.glb")
else:
    log("GLB file not found after export", "ERROR")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 13. Relatório JSON
# ─────────────────────────────────────────────────────────────────────────────

step("Write report")

report["end_time"]        = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
report["success"]         = len(report["errors"]) == 0
report["blender_version"] = bpy.app.version_string
report["mpfb2_used"]      = use_mpfb
report["character_type"]  = "medieval_warrior"
report["armor_pieces"]    = len(armor_objects)

report_path = os.path.join(OUTPUT_DIR, "character_report.json")
with open(report_path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
log(f"Report: {report_path}")
report["output_files"].append("character_report.json")

# ─────────────────────────────────────────────────────────────────────────────
# Sumário
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("MEDIEVAL CHARACTER — COMPLETE")
print("="*60)
for f in report["output_files"]:
    full = os.path.join(OUTPUT_DIR, f)
    size = os.path.getsize(full) if os.path.exists(full) else 0
    print(f"  {f:40s}  {size/1024:.1f} KB")
print(f"\nSteps:    {len(report['steps'])}")
print(f"Errors:   {len(report['errors'])}")
print(f"Warnings: {len(report['warnings'])}")
print(f"MPFB2:    {'yes' if use_mpfb else 'no (parametric fallback)'}")
if report["errors"]:
    print("\nERRORS:")
    for e in report["errors"]:
        print(f"  - {e}")
    sys.exit(1)
print("="*60)
