"""
Medieval Character Generator — Blender 4.2 LTS headless
========================================================
Gera um personagem medieval masculino completo:
  - Basemesh humano via MPFB2 (HumanService)
  - Rig Rigify completo via MPFB2 (RigService)
  - Armadura medieval em low-poly (criada via bpy)
  - Materiais PBR compatíveis com glTF
  - Câmara e iluminação de estúdio
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
from mathutils import Vector, Matrix

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
# 1. Utilitário: importação dinâmica dos módulos MPFB2
#    (necessário porque as extensões Blender ficam em caminhos variáveis)
# ─────────────────────────────────────────────────────────────────────────────

def dynamic_import(absolute_package_str, key):
    """
    Importa um símbolo de um módulo MPFB2 pelo sufixo do nome do módulo.
    Padrão obrigatório para extensões Blender 4.x.
    """
    for amod in sys.modules:
        if amod.endswith(absolute_package_str):
            mod = importlib.import_module(amod)
            if not hasattr(mod, key):
                raise AttributeError(f"Module {amod} has no attribute '{key}'")
            return getattr(mod, key)
    raise ValueError(f"No loaded module ends with '{absolute_package_str}'. "
                     "Is MPFB2 installed and registered?")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Cena limpa
# ─────────────────────────────────────────────────────────────────────────────

step("Clean scene")
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "MedievalCharacter"
log("Scene cleared")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Ativar add-ons necessários
# ─────────────────────────────────────────────────────────────────────────────

step("Enable add-ons")

# Rigify (vem com o Blender)
bpy.ops.preferences.addon_enable(module="rigify")
log("Rigify enabled")

# MPFB2 (instalado como extensão pelo workflow)
mpfb_enabled = False
for addon in bpy.context.preferences.addons.keys():
    if "mpfb" in addon.lower():
        mpfb_enabled = True
        log(f"MPFB2 already registered as: {addon}")
        break

if not mpfb_enabled:
    try:
        bpy.ops.preferences.addon_enable(module="mpfb")
        mpfb_enabled = True
        log("MPFB2 enabled via addon_enable")
    except Exception as e:
        log(f"addon_enable failed: {e}", "WARN")

    # Tentar via extensions
    if not mpfb_enabled:
        try:
            bpy.ops.extensions.package_enable(package="mpfb", repo_index=0)
            mpfb_enabled = True
            log("MPFB2 enabled via extensions")
        except Exception as e:
            log(f"extensions enable failed: {e}", "WARN")

bpy.ops.wm.save_userpref()

# ─────────────────────────────────────────────────────────────────────────────
# 4. Gerar basemesh humano com MPFB2
# ─────────────────────────────────────────────────────────────────────────────

step("Generate human basemesh via MPFB2")

basemesh = None
use_mpfb = False

if mpfb_enabled:
    try:
        HumanService = dynamic_import("mpfb.services.humanservice", "HumanService")
        basemesh = HumanService.create_human()
        basemesh.name = "MedievalHuman"
        use_mpfb = True
        log(f"Basemesh created: {basemesh.name} ({len(basemesh.data.vertices)} verts)")
    except Exception as e:
        log(f"MPFB2 HumanService failed: {e}", "WARN")
        log("Falling back to parametric basemesh", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# 4b. Fallback: basemesh paramétrico (humano ~1.80m) se MPFB2 falhar
# ─────────────────────────────────────────────────────────────────────────────

if basemesh is None:
    log("Building parametric human body")

    mesh = bpy.data.meshes.new("HumanMesh")
    basemesh = bpy.data.objects.new("MedievalHuman", mesh)
    scene.collection.objects.link(basemesh)

    bm = bmesh.new()

    def add_capsule(bm, radius, height, segments=8, rings=4, offset_z=0.0):
        """Adiciona uma cápsula (cilindro com hemisférios) ao bmesh."""
        verts = []
        # Corpo cilíndrico
        for r in range(rings + 1):
            z = offset_z + (r / rings) * height
            ring_verts = []
            for s in range(segments):
                angle = (s / segments) * 2 * math.pi
                x = radius * math.cos(angle)
                y = radius * math.sin(angle)
                ring_verts.append(bm.verts.new((x, y, z)))
            verts.append(ring_verts)
        # Faces laterais
        for r in range(rings):
            for s in range(segments):
                v0 = verts[r][s]
                v1 = verts[r][(s + 1) % segments]
                v2 = verts[r + 1][(s + 1) % segments]
                v3 = verts[r + 1][s]
                bm.faces.new([v0, v1, v2, v3])
        # Tampas
        bot_center = bm.verts.new((0, 0, offset_z))
        top_center = bm.verts.new((0, 0, offset_z + height))
        for s in range(segments):
            bm.faces.new([bot_center, verts[0][(s + 1) % segments], verts[0][s]])
            bm.faces.new([top_center, verts[-1][s], verts[-1][(s + 1) % segments]])
        return top_center.co.z

    # Pernas
    add_capsule(bm, 0.07, 0.42, offset_z=0.0)      # perna direita
    # Perna esquerda (offset X)
    for r in range(5):
        z = r * 0.42 / 4
        for s in range(8):
            angle = (s / 8) * 2 * math.pi
            bm.verts.new((0.15 + 0.07 * math.cos(angle), 0.07 * math.sin(angle), z))

    # Torso
    add_capsule(bm, 0.18, 0.55, offset_z=0.42)
    # Cabeça
    add_capsule(bm, 0.12, 0.24, offset_z=1.42)
    # Pescoço
    add_capsule(bm, 0.055, 0.14, offset_z=1.28)
    # Braços
    add_capsule(bm, 0.055, 0.60, offset_z=0.75)   # braço direito
    add_capsule(bm, 0.055, 0.60, offset_z=0.75)   # braço esquerdo

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    log(f"Parametric basemesh created: {len(mesh.vertices)} verts")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Rig Rigify
# ─────────────────────────────────────────────────────────────────────────────

step("Generate Rigify rig")

rig_object = None

if use_mpfb:
    try:
        SystemService = dynamic_import("mpfb.services.systemservice", "SystemService")
        RigService = dynamic_import("mpfb.services.rigservice", "RigService")

        if not SystemService.check_for_rigify():
            raise RuntimeError("Rigify not available inside MPFB")

        metarig = dynamic_import("mpfb.services.humanservice", "HumanService")\
            .__class__  # reload
        HumanService2 = dynamic_import("mpfb.services.humanservice", "HumanService")
        metarig = HumanService2.add_builtin_rig(basemesh, "rigify.human")
        rig_object = RigService.generate_rigify_rig(metarig, meta_rig_action="delete")
        log(f"Rigify rig generated via MPFB2: {rig_object.name}")
    except Exception as e:
        log(f"MPFB2 rig generation failed: {e}", "WARN")
        use_mpfb = False

if rig_object is None:
    log("Building Rigify metarig manually")
    try:
        # Adicionar metarig humano padrão do Rigify
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.armature_human_metarig_add()
        metarig = bpy.context.active_object
        metarig.name = "metarig"

        # Escalar para altura ~1.80m
        metarig.scale = (1.0, 1.0, 1.0)
        bpy.ops.object.transform_apply(scale=True)

        # Gerar rig completo
        bpy.context.view_layer.objects.active = metarig
        import rigify
        rigify.generate.generate_rig(bpy.context, metarig)
        rig_object = bpy.context.active_object
        log(f"Rigify rig generated manually: {rig_object.name}")

        # Parear basemesh ao rig com pesos automáticos
        bpy.ops.object.select_all(action='DESELECT')
        basemesh.select_set(True)
        rig_object.select_set(True)
        bpy.context.view_layer.objects.active = rig_object
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        log("Basemesh parented to rig with automatic weights")
    except Exception as e:
        log(f"Manual Rigify generation failed: {e}", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Armadura medieval (geometria low-poly)
# ─────────────────────────────────────────────────────────────────────────────

step("Build medieval armor")

def make_armor_piece(name, location, scale, segments=8):
    """Cria uma peça de armadura cilíndrica baixo-polígono."""
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)

    bm = bmesh.new()
    # Cilindro simples como base da peça
    verts_bot = []
    verts_top = []
    h = scale[2]
    r = max(scale[0], scale[1])
    for i in range(segments):
        angle = (i / segments) * 2 * math.pi
        x = r * math.cos(angle)
        y = r * math.sin(angle)
        verts_bot.append(bm.verts.new((x, y, 0.0)))
        verts_top.append(bm.verts.new((x, y, h)))
    for i in range(segments):
        bm.faces.new([verts_bot[i], verts_bot[(i+1) % segments],
                      verts_top[(i+1) % segments], verts_top[i]])
    # Tampas
    bc = bm.verts.new((0, 0, 0))
    tc = bm.verts.new((0, 0, h))
    for i in range(segments):
        bm.faces.new([bc, verts_bot[(i+1) % segments], verts_bot[i]])
        bm.faces.new([tc, verts_top[i], verts_top[(i+1) % segments]])

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj.location = location
    return obj

# Peças da armadura posicionadas sobre o basemesh
armor_pieces = {
    "Helmet":        ((0, 0, 1.55), (0.145, 0.145, 0.22)),
    "Breastplate":   ((0, 0, 0.72), (0.21,  0.18,  0.50)),
    "Shoulder_R":    ((-0.30, 0, 1.00), (0.09, 0.09, 0.18)),
    "Shoulder_L":    (( 0.30, 0, 1.00), (0.09, 0.09, 0.18)),
    "Gauntlet_R":    ((-0.32, 0, 0.42), (0.065, 0.065, 0.20)),
    "Gauntlet_L":    (( 0.32, 0, 0.42), (0.065, 0.065, 0.20)),
    "Greave_R":      ((-0.10, 0, 0.0),  (0.08, 0.08, 0.40)),
    "Greave_L":      (( 0.10, 0, 0.0),  (0.08, 0.08, 0.40)),
}

armor_objects = []
for pname, (loc, sc) in armor_pieces.items():
    obj = make_armor_piece(pname, Vector(loc), sc)
    armor_objects.append(obj)
    log(f"  Armor piece: {pname}")

log(f"Armor built: {len(armor_objects)} pieces")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Materiais PBR (compatíveis com glTF)
# ─────────────────────────────────────────────────────────────────────────────

step("Apply PBR materials")

def make_material(name, base_color, metallic=0.0, roughness=0.5, emission=None):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 0.5

    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat

# Paleta medieval
mat_skin     = make_material("Skin",        (0.80, 0.60, 0.45), metallic=0.0, roughness=0.6)
mat_steel    = make_material("Steel",       (0.72, 0.72, 0.75), metallic=0.95, roughness=0.25)
mat_leather  = make_material("Leather",     (0.28, 0.14, 0.06), metallic=0.0, roughness=0.85)
mat_eyes     = make_material("Eyes",        (0.05, 0.25, 0.60), metallic=0.0, roughness=0.05)

# Atribuir material ao basemesh
if basemesh.data.materials:
    basemesh.data.materials[0] = mat_skin
else:
    basemesh.data.materials.append(mat_skin)
log("Skin material applied")

# Atribuir aço às peças de armadura
for obj in armor_objects:
    if obj.data.materials:
        obj.data.materials[0] = mat_steel
    else:
        obj.data.materials.append(mat_steel)
log("Steel material applied to armor")

# ─────────────────────────────────────────────────────────────────────────────
# 8. Iluminação de estúdio
# ─────────────────────────────────────────────────────────────────────────────

step("Studio lighting")

# Luz principal (key light)
bpy.ops.object.light_add(type='AREA', location=(2.5, -2.5, 3.5))
key_light = bpy.context.active_object
key_light.name = "KeyLight"
key_light.data.energy = 800
key_light.data.size = 2.0
key_light.rotation_euler = (math.radians(50), 0, math.radians(45))

# Luz de preenchimento (fill light)
bpy.ops.object.light_add(type='AREA', location=(-2.0, -1.5, 2.0))
fill_light = bpy.context.active_object
fill_light.name = "FillLight"
fill_light.data.energy = 300
fill_light.data.size = 3.0
fill_light.rotation_euler = (math.radians(40), 0, math.radians(-45))

# Luz de contorno (rim light)
bpy.ops.object.light_add(type='SPOT', location=(0, 3.0, 2.5))
rim_light = bpy.context.active_object
rim_light.name = "RimLight"
rim_light.data.energy = 500
rim_light.data.spot_size = math.radians(45)
rim_light.rotation_euler = (math.radians(-45), 0, 0)

log("Studio lights added (key + fill + rim)")

# ─────────────────────────────────────────────────────────────────────────────
# 9. Câmara de apresentação
# ─────────────────────────────────────────────────────────────────────────────

step("Camera setup")

bpy.ops.object.camera_add(location=(0, -4.0, 1.0))
camera = bpy.context.active_object
camera.name = "PresentationCamera"
camera.rotation_euler = (math.radians(90), 0, 0)
scene.camera = camera

# Ajustar câmara para enquadrar o personagem
camera.data.lens = 50
camera.data.clip_start = 0.1
camera.data.clip_end = 100.0
log("Camera configured (50mm, full body shot)")

# ─────────────────────────────────────────────────────────────────────────────
# 10. Configuração de render para preview PNG
# ─────────────────────────────────────────────────────────────────────────────

step("Render preview")

scene.render.engine = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x = 1024
scene.render.resolution_y = 1024
scene.render.resolution_percentage = 100
preview_path = os.path.join(OUTPUT_DIR, "character_preview.png")
scene.render.filepath = preview_path
scene.render.image_settings.file_format = 'PNG'

try:
    bpy.ops.render.render(write_still=True)
    log(f"Preview rendered: {preview_path}")
    report["output_files"].append("character_preview.png")
except Exception as e:
    log(f"Render failed (non-critical): {e}", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# 11. Guardar ficheiro .blend
# ─────────────────────────────────────────────────────────────────────────────

step("Save .blend file")

blend_path = os.path.join(OUTPUT_DIR, "character.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
log(f"Blend saved: {blend_path}")
report["output_files"].append("character.blend")

# ─────────────────────────────────────────────────────────────────────────────
# 12. Exportar GLB
# ─────────────────────────────────────────────────────────────────────────────

step("Export GLB")

glb_path = os.path.join(OUTPUT_DIR, "character.glb")

bpy.ops.export_scene.gltf(
    filepath=glb_path,
    export_format='GLB',
    export_apply=True,
    export_materials='EXPORT',
    export_texcoords=True,
    export_normals=True,
    export_colors=True,
    export_animations=True,
    export_skins=True,
    export_all_influences=False,
    export_def_bones=True,
)

if os.path.exists(glb_path):
    size_mb = os.path.getsize(glb_path) / (1024 * 1024)
    log(f"GLB exported: {glb_path} ({size_mb:.2f} MB)")
    report["output_files"].append("character.glb")
else:
    log("GLB export failed — file not found", "ERROR")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 13. Relatório JSON
# ─────────────────────────────────────────────────────────────────────────────

step("Write report")

report["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
report["success"] = len(report["errors"]) == 0
report["blender_version"] = bpy.app.version_string
report["mpfb2_used"] = use_mpfb
report["character_type"] = "medieval_warrior"
report["armor_pieces"] = len(armor_objects)

report_path = os.path.join(OUTPUT_DIR, "character_report.json")
with open(report_path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
log(f"Report written: {report_path}")
report["output_files"].append("character_report.json")

# ─────────────────────────────────────────────────────────────────────────────
# Sumário final
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("MEDIEVAL CHARACTER GENERATION COMPLETE")
print("="*60)
for f in report["output_files"]:
    full = os.path.join(OUTPUT_DIR, f)
    size = os.path.getsize(full) if os.path.exists(full) else 0
    print(f"  {f:40s} {size/1024:.1f} KB")
print(f"\nSteps:   {len(report['steps'])}")
print(f"Errors:  {len(report['errors'])}")
print(f"Warnings:{len(report['warnings'])}")
print(f"MPFB2:   {'yes' if use_mpfb else 'no (parametric fallback)'}")
if report["errors"]:
    print("\nERRORS:")
    for e in report["errors"]:
        print(f"  - {e}")
    sys.exit(1)
print("="*60)
