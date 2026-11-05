"""
pipeline.py — Fase 2: Pipeline Blender Headless
=================================================

Recebe o FBX produzido pelo generate.py (Fase 1) e executa dentro do
Blender 4.2 LTS em modo headless todas as operações que só o Blender
consegue fazer:

  1. Importa o FBX (corpo + rig da Fase 1)
  2. Aplica materiais PBR com Subsurface Scattering (pele realista)
  3. Constrói cabelo em hair cards de geometria (compatível GLB/glTF)
  4. Adiciona vestuário com geometria própria e pregas
  5. Configura iluminação three-point cinematográfica
  6. Render de pré-visualização 1024×1024 (WORKBENCH, sem GPU)
  7. Exporta GLB com geometria + materiais + esqueleto + pesos
  8. Valida o GLB e escreve relatório JSON de fase

Uso:
    blender -b --python scripts/pipeline.py -- \\
        --input  /tmp/char_out/character.fbx \\
        --output /tmp/char_out

    Se --input não for fornecido, procura character.fbx ou character.obj
    no --output (compatibilidade com o workflow).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


# ─────────────────────────────────────────────────────────────────────────────
# ARGUMENTOS (passados após --)
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--input",  "-i", default="")
    p.add_argument("--output", "-o", default="/tmp/char_out")
    return p.parse_args(argv)


ARGS   = parse_args()
OUTDIR = Path(ARGS.output)
OUTDIR.mkdir(parents=True, exist_ok=True)

report: dict = {
    "phase":      "pipeline",
    "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "blender":    bpy.app.version_string,
    "success":    False,
    "errors":     [],
    "warnings":   [],
    "output_files": [],
}


def log(msg: str, level: str = "INFO") -> None:
    prefix = {"INFO": "✓", "WARN": "⚠", "ERROR": "✗"}.get(level, "·")
    print(f"[{prefix}] {msg}", flush=True)
    if level == "ERROR":
        report["errors"].append(msg)
    elif level == "WARN":
        report["warnings"].append(msg)


def step(name: str) -> None:
    log(f"── {name}")
    report.setdefault("steps", []).append(name)


def save_report() -> None:
    report["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = OUTDIR / "pipeline_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    log(f"Relatório escrito → {path}")


# ─────────────────────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────────────────────────────────────

def srgb2lin(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def hex2rgba(h: str, a: float = 1.0) -> tuple:
    h = h.lstrip("#")
    return (
        srgb2lin(int(h[0:2], 16) / 255),
        srgb2lin(int(h[2:4], 16) / 255),
        srgb2lin(int(h[4:6], 16) / 255),
        a,
    )


def mat_pbr(
    name: str, base_hex: str,
    roughness: float = 0.5, metallic: float = 0.0,
    subsurface: float = 0.0, specular: float = 0.5,
) -> bpy.types.Material:
    """Cria ou reutiliza um material Principled BSDF."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nodes = m.node_tree.nodes
    links = m.node_tree.links
    nodes.clear()

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = hex2rgba(base_hex)
    bsdf.inputs["Roughness"].default_value  = roughness
    bsdf.inputs["Metallic"].default_value   = metallic

    # Specular — nome mudou em 4.x
    for sp_name in ("Specular IOR Level", "Specular"):
        if sp_name in bsdf.inputs:
            bsdf.inputs[sp_name].default_value = specular
            break

    # Subsurface — nome mudou em 4.x
    if subsurface > 0:
        for ss_name in ("Subsurface Weight", "Subsurface"):
            if ss_name in bsdf.inputs:
                bsdf.inputs[ss_name].default_value = subsurface
                break
        for sc_name in ("Subsurface Radius",):
            if sc_name in bsdf.inputs:
                bsdf.inputs[sc_name].default_value = (1.0, 0.2, 0.1)
                break

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def smooth_all(obj: bpy.types.Object) -> None:
    for poly in obj.data.polygons:
        poly.use_smooth = True
    obj.data.update()


def set_active(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_mat(obj: bpy.types.Object, mat: bpy.types.Material, slot: int = 0) -> None:
    if slot < len(obj.data.materials):
        obj.data.materials[slot] = mat
    else:
        obj.data.materials.append(mat)


# ─────────────────────────────────────────────────────────────────────────────
# 1. LIMPAR CENA
# ─────────────────────────────────────────────────────────────────────────────

step("Limpar cena")
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "CharacterScene"
log("Cena limpa")


# ─────────────────────────────────────────────────────────────────────────────
# 2. IMPORTAR FBX (ou OBJ como fallback)
# ─────────────────────────────────────────────────────────────────────────────

step("Importar FBX da Fase 1")

# Descobrir ficheiro de entrada
input_path = Path(ARGS.input) if ARGS.input else None

if not input_path or not input_path.exists():
    # Procurar no directório de saída
    for candidate in ["character.fbx", "character.obj", "character.dae"]:
        p = OUTDIR / candidate
        if p.exists():
            input_path = p
            break

if not input_path or not input_path.exists():
    log("Nenhum ficheiro de entrada encontrado (FBX/OBJ/DAE)", "ERROR")
    save_report()
    sys.exit(1)

log(f"Ficheiro de entrada: {input_path} ({input_path.stat().st_size // 1024} KB)")

ext = input_path.suffix.lower()
imported_ok = False
body = None

try:
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(
            filepath=str(input_path),
            use_anim=False,
            automatic_bone_orientation=True,
            ignore_leaf_bones=True,
        )
        imported_ok = True
        log("FBX importado")

    elif ext in (".obj", ".glb", ".gltf"):
        bpy.ops.import_scene.obj(filepath=str(input_path)) if ext == ".obj" \
            else bpy.ops.import_scene.gltf(filepath=str(input_path))
        imported_ok = True
        log(f"{ext.upper()} importado")

    elif ext == ".dae":
        bpy.ops.wm.collada_import(filepath=str(input_path))
        imported_ok = True
        log("DAE importado")

    else:
        log(f"Formato não suportado: {ext}", "ERROR")
        save_report()
        sys.exit(1)

except Exception as exc:
    log(f"Importação falhou: {exc}", "ERROR")
    save_report()
    sys.exit(1)

# Identificar a mesh principal (maior número de vértices)
meshes = [(o, len(o.data.vertices)) for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    log("Nenhuma mesh encontrada após importação", "ERROR")
    save_report()
    sys.exit(1)

body = max(meshes, key=lambda x: x[1])[0]
log(f"Body identificado: '{body.name}' ({len(body.data.vertices)} vértices)")

# Recolher referências anatómicas a partir da geometria importada
bpy.context.view_layer.update()
vz = [v.co.z + body.location.z for v in body.data.vertices]
body_minz = min(vz)
body_maxz = max(vz)
body_h    = body_maxz - body_minz

log(f"Altura importada: {body_h:.3f} m")
report["imported_height_m"] = round(body_h, 4)
report["imported_vertices"]  = len(body.data.vertices)

# Pontos anatómicos de referência (proporções padrão)
head_cz    = body_minz + body_h * 0.930
head_r     = body_h * 0.068
shoulder_z = body_minz + body_h * 0.802
bust_z     = body_minz + body_h * 0.720
waist_z    = body_minz + body_h * 0.590
hip_z      = body_minz + body_h * 0.530
knee_z     = body_minz + body_h * 0.300
ankle_z    = body_minz + body_h * 0.058


# ─────────────────────────────────────────────────────────────────────────────
# 3. MATERIAIS PBR
#    Aplica materiais Principled BSDF a todas as meshes importadas.
#    O mhcore gera UVs e referencia texturas por path; aqui usamos
#    cores sólidas PBR como base (compatível GLB sem texturas externas).
# ─────────────────────────────────────────────────────────────────────────────

step("Materiais PBR")

# Material base de pele — tom médio com SSS
skin_mat = mat_pbr(
    "Skin_PBR",
    base_hex="#C68642",   # tom médio-dourado
    roughness=0.48,
    metallic=0.0,
    subsurface=0.22,      # SSS para pele realista
    specular=0.42,
)

# Materiais secundários para sub-meshes (olhos, cabelo, etc.)
eye_white_mat = mat_pbr("Eye_Sclera",    "#F0EDE8", roughness=0.06, specular=0.70)
eye_iris_mat  = mat_pbr("Eye_Iris",      "#3A2820", roughness=0.08, specular=0.65)
hair_mat      = mat_pbr("Hair_PBR",      "#2C1A0E", roughness=0.76, specular=0.30)
teeth_mat     = mat_pbr("Teeth_PBR",     "#F5F0E0", roughness=0.25, specular=0.55)
nail_mat      = mat_pbr("Nails_PBR",     "#E8B8A8", roughness=0.20, specular=0.65)

def classify_mesh(name: str) -> str:
    """Classifica uma mesh importada pelo nome."""
    n = name.lower()
    if any(k in n for k in ("eye", "iris", "cornea", "pupil")):
        return "eye"
    if any(k in n for k in ("teeth", "tooth", "gum", "tongue")):
        return "teeth"
    if any(k in n for k in ("hair", "brow", "lash")):
        return "hair"
    if any(k in n for k in ("nail", "fingernail", "toenail")):
        return "nail"
    return "skin"

for obj in bpy.data.objects:
    if obj.type != "MESH":
        continue
    cls = classify_mesh(obj.name)
    mat = {
        "eye":   eye_white_mat,
        "teeth": teeth_mat,
        "hair":  hair_mat,
        "nail":  nail_mat,
    }.get(cls, skin_mat)
    # Substituir todos os slots de material existentes
    if obj.data.materials:
        for i in range(len(obj.data.materials)):
            obj.data.materials[i] = mat
    else:
        obj.data.materials.append(mat)
    smooth_all(obj)

log(f"Materiais aplicados a {len([o for o in bpy.data.objects if o.type == 'MESH'])} meshes")


# ─────────────────────────────────────────────────────────────────────────────
# 4. HAIR CARDS DE GEOMETRIA
#    Cabelo em quads de geometria — única abordagem compatível com GLB/glTF.
#    Partículas de cabelo do Blender não são exportadas pelo exporter glTF.
# ─────────────────────────────────────────────────────────────────────────────

step("Hair cards")

# Verificar se já existe cabelo importado (mhcore pode ter incluído)
existing_hair = [o for o in bpy.data.objects
                 if o.type == "MESH" and "hair" in o.name.lower()]

if existing_hair:
    log(f"Cabelo importado detectado ({len(existing_hair)} objecto(s)) — a reforçar com cards")

# Sempre adicionar hair cards de suporte (completam o cabelo importado)
CARD_COUNT = 48
card_width  = head_r * 0.055
tip_width   = card_width * 0.40

hair_verts: list = []
hair_faces: list = []
offset = 0

for ci in range(CARD_COUNT):
    az = 2 * math.pi * ci / CARD_COUNT

    # Raiz no couro cabeludo (ligeiramente acima do centro da cabeça)
    phi_root = math.pi * 0.15
    rx_root  = head_r * 1.02 * math.sin(phi_root) * math.cos(az)
    ry_root  = head_r * 1.02 * math.sin(phi_root) * math.sin(az)
    rz_root  = head_cz + head_r * 1.02 * math.cos(phi_root)

    # Comprimento e queda: franja na frente, comprido atrás
    is_fringe = abs(math.atan2(ry_root, rx_root)) < math.radians(50)
    length    = head_r * (1.5 if is_fringe else 2.6)
    sway_x    = rx_root * 0.22   # queda para o lado
    sway_y    = ry_root * 0.22
    end_z     = rz_root - length

    # Quad por card (4 vértices)
    n       = Vector((math.cos(az), math.sin(az), 0)).normalized()
    right_x = -n.y * card_width / 2
    right_y =  n.x * card_width / 2
    tw      = tip_width / 2

    v0 = (rx_root - right_x,        ry_root - right_y,        rz_root)
    v1 = (rx_root + right_x,        ry_root + right_y,        rz_root)
    v2 = (rx_root + sway_x + tw,    ry_root + sway_y + tw,    end_z)
    v3 = (rx_root + sway_x - tw,    ry_root + sway_y - tw,    end_z)

    hair_verts.extend([v0, v1, v2, v3])
    b = offset
    hair_faces.append([b, b + 1, b + 2, b + 3])
    offset += 4

hair_mesh = bpy.data.meshes.new("HairCards_mesh")
hair_obj  = bpy.data.objects.new("HairCards", hair_mesh)
scene.collection.objects.link(hair_obj)
hair_mesh.from_pydata(hair_verts, [], hair_faces)
hair_mesh.update()
apply_mat(hair_obj, hair_mat)
smooth_all(hair_obj)

log(f"Hair cards: {CARD_COUNT} quads, {len(hair_verts)} vértices")


# ─────────────────────────────────────────────────────────────────────────────
# 5. VESTUÁRIO — GEOMETRIA PRÓPRIA
#    O mhcore pode já incluir roupa importada. Adicionamos peças de suporte
#    (saia, top, cinto) com geometria própria e pregas subtis.
# ─────────────────────────────────────────────────────────────────────────────

step("Vestuário")

cloth_mat  = mat_pbr("Cloth",  "#1A1A28", roughness=0.92, specular=0.05)
top_mat    = mat_pbr("Top",    "#0D0D1A", roughness=0.88, specular=0.08)
detail_mat = mat_pbr("Detail", "#8A7A5A", roughness=0.65, specular=0.25)


def build_clothing_ring_mesh(
    name: str,
    ring_specs: list[tuple[float, float, float]],
    mat: bpy.types.Material,
    segs: int = 36,
    close_bottom: bool = False,
    close_top:    bool = False,
) -> bpy.types.Object:
    """
    Constrói uma peça de roupa a partir de anéis (z_abs, rx, ry).
    Adiciona pregas subtis para aspeto orgânico.
    """
    md  = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, md)
    scene.collection.objects.link(obj)
    bm  = bmesh.new()

    rings = []
    for z_abs, rx, ry in ring_specs:
        ring = []
        for s in range(segs):
            a    = 2 * math.pi * s / segs
            fold = 1.0 + 0.018 * math.sin(a * 6) + 0.006 * math.cos(a * 3)
            ring.append(bm.verts.new((rx * fold * math.cos(a),
                                      ry * fold * math.sin(a),
                                      z_abs)))
        rings.append(ring)

    for ri in range(len(rings) - 1):
        for s in range(segs):
            sn = (s + 1) % segs
            bm.faces.new([rings[ri][s], rings[ri][sn],
                          rings[ri + 1][sn], rings[ri + 1][s]])

    if close_bottom:
        c = bm.verts.new((0, 0, ring_specs[0][0]))
        for s in range(segs):
            bm.faces.new([c, rings[0][(s + 1) % segs], rings[0][s]])
    if close_top:
        c = bm.verts.new((0, 0, ring_specs[-1][0]))
        for s in range(segs):
            bm.faces.new([c, rings[-1][s], rings[-1][(s + 1) % segs]])

    bm.normal_update()
    bm.to_mesh(md)
    bm.free()
    md.update()
    smooth_all(obj)
    apply_mat(obj, mat)
    return obj


# Verificar se o mhcore já importou roupa
imported_clothes = [
    o for o in bpy.data.objects
    if o.type == "MESH" and any(
        k in o.name.lower()
        for k in ("shirt", "skirt", "top", "pants", "cloth", "dress", "boot", "shoe")
    )
]

if imported_clothes:
    log(f"Roupa importada detectada: {[o.name for o in imported_clothes]}")
    # Apenas adicionar cinto como detalhe
    belt_specs = [
        (waist_z + 0.005, 0.166, 0.126),
        (waist_z + 0.015, 0.168, 0.128),
    ]
    build_clothing_ring_mesh("Belt", belt_specs, detail_mat, segs=36, close_bottom=False)
    log("Cinto de detalhe adicionado")
else:
    log("Sem roupa importada — a construir vestuário completo")

    # Saia midi (cintura → joelho)
    skirt_specs = [
        (waist_z + 0.010, 0.168, 0.128),
        (waist_z - 0.030, 0.178, 0.135),
        (hip_z   + 0.040, 0.212, 0.162),
        (hip_z,           0.220, 0.168),
        (hip_z   - 0.060, 0.218, 0.166),
        (knee_z  + 0.080, 0.212, 0.160),
        (knee_z,          0.208, 0.158),
        (knee_z  - 0.040, 0.206, 0.156),
    ]
    build_clothing_ring_mesh("Skirt", skirt_specs, cloth_mat, segs=48)
    log("Saia midi criada")

    # Top strapless (cintura → busto)
    top_specs = [
        (waist_z + 0.015, 0.162, 0.122),
        (waist_z + 0.060, 0.168, 0.128),
        (waist_z + 0.120, 0.175, 0.135),
        (bust_z  - 0.040, 0.182, 0.142),
        (bust_z,          0.185, 0.145),
        (bust_z  + 0.050, 0.182, 0.142),
        (bust_z  + 0.090, 0.178, 0.138),
    ]
    build_clothing_ring_mesh("Top", top_specs, top_mat, segs=48)
    log("Top strapless criado")

    # Cinto
    belt_specs = [
        (waist_z + 0.005, 0.166, 0.126),
        (waist_z + 0.015, 0.168, 0.128),
    ]
    build_clothing_ring_mesh("Belt", belt_specs, detail_mat, segs=36)
    log("Cinto criado")

log("Vestuário completo")


# ─────────────────────────────────────────────────────────────────────────────
# 6. ILUMINAÇÃO THREE-POINT CINEMATOGRÁFICA
# ─────────────────────────────────────────────────────────────────────────────

step("Iluminação")

center = Vector((0, 0, body_h * 0.52))

def add_area_light(
    name: str, loc: tuple, energy: float, size: float, color: tuple
) -> bpy.types.Object:
    bpy.ops.object.light_add(type="AREA", location=loc)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.size   = size
    light.data.color  = color
    # Apontar para o centro do corpo
    direction = center - Vector(loc)
    light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return light


add_area_light("Key_Light",  ( 2.0, -2.8, 1.5), 1400, 2.0, (1.00, 0.95, 0.88))
add_area_light("Fill_Light", (-2.0, -1.6, 1.0),  600, 3.0, (0.85, 0.90, 1.00))
add_area_light("Rim_Light",  ( 0.0,  2.8, 2.0),  800, 1.5, (1.00, 0.98, 0.92))
log("Iluminação three-point configurada")


# ─────────────────────────────────────────────────────────────────────────────
# 7. CÂMARA E WORLD
# ─────────────────────────────────────────────────────────────────────────────

step("Câmara")

bpy.ops.object.camera_add(location=(0, -4.0, body_h * 0.52))
cam = bpy.context.active_object
cam.name = "Camera"
cam.data.type = "PERSP"
cam.data.lens = 85   # 85mm — comprime perspetiva, flattering para retratos
direction = center - Vector(cam.location)
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

# World escuro subtil
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
wn = world.node_tree.nodes
wl = world.node_tree.links
wn.clear()
bg = wn.new("ShaderNodeBackground")
bg.inputs["Color"].default_value    = (0.04, 0.04, 0.06, 1.0)
bg.inputs["Strength"].default_value = 0.18
wo = wn.new("ShaderNodeOutputWorld")
wl.new(bg.outputs["Background"], wo.inputs["Surface"])

log("Câmara 85mm + world configurados")


# ─────────────────────────────────────────────────────────────────────────────
# 8. RENDER PREVIEW
#    WORKBENCH — único motor garantido em headless sem GPU.
#    Cycles e EEVEE-Next exigem GPU ou dependências que faltam no runner.
# ─────────────────────────────────────────────────────────────────────────────

step("Render preview (WORKBENCH)")

scene.render.engine                     = "BLENDER_WORKBENCH"
scene.render.resolution_x               = 1024
scene.render.resolution_y               = 1024
scene.render.resolution_percentage      = 100
scene.render.image_settings.file_format = "PNG"
scene.display.shading.light             = "STUDIO"
scene.display.shading.color_type        = "MATERIAL"
scene.display.shading.show_specular_highlight = True

preview_path = str(OUTDIR / "character_preview.png")
scene.render.filepath = preview_path

try:
    bpy.ops.render.render(write_still=True)
    if Path(preview_path).exists():
        kb = Path(preview_path).stat().st_size // 1024
        log(f"Preview OK: {kb} KB → {preview_path}")
        report["output_files"].append("character_preview.png")
    else:
        log("Preview não encontrado após render", "WARN")
except Exception as exc:
    log(f"Preview falhou (não crítico): {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 9. GUARDAR .BLEND
# ─────────────────────────────────────────────────────────────────────────────

step("Guardar .blend")

blend_path = str(OUTDIR / "character.blend")
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    log(f"Blend gravado → {blend_path}")
    report["output_files"].append("character.blend")
except Exception as exc:
    log(f"Blend falhou: {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 10. EXPORTAR GLB
#     Incluir: geometria, UVs, materiais, armadura, pesos
#     Excluir: animações (não produzidas nesta fase)
# ─────────────────────────────────────────────────────────────────────────────

step("Exportar GLB")

glb_path = str(OUTDIR / "character.glb")

# Parâmetros base do exporter glTF 4.2
glb_kwargs: dict = {
    "filepath":           glb_path,
    "export_format":      "GLB",
    "export_apply":       True,      # aplicar modifiers antes de exportar
    "export_materials":   "EXPORT",
    "export_texcoords":   True,
    "export_normals":     True,
    "export_skins":       True,
    "export_animations":  False,
    "export_morph":       True,
    "export_yup":         True,      # Y-up = padrão glTF
}

try:
    bpy.ops.export_scene.gltf(**glb_kwargs)
    log("GLB exportado com parâmetros completos")
except TypeError:
    # Blender 4.2 pode usar nomes diferentes nalguns parâmetros
    log("Export completo falhou — a tentar export mínimo", "WARN")
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_path,
            export_format="GLB",
            export_apply=True,
            export_skins=True,
        )
        log("GLB exportado (modo mínimo)")
    except Exception as exc2:
        log(f"GLB export mínimo falhou: {exc2}", "ERROR")
        save_report()
        sys.exit(1)
except Exception as exc:
    log(f"GLB export falhou: {exc}", "ERROR")
    save_report()
    sys.exit(1)

if Path(glb_path).exists():
    kb = Path(glb_path).stat().st_size // 1024
    log(f"GLB: {kb} KB → {glb_path}")
    report["output_files"].append("character.glb")
    report["glb_kb"] = kb
else:
    log("GLB não encontrado após export", "ERROR")
    save_report()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 11. MÉTRICAS E RELATÓRIO FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Relatório")

total_verts = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH")
total_mats  = len(bpy.data.materials)
total_meshes = len([o for o in bpy.data.objects if o.type == "MESH"])

report.update({
    "success":       len(report["errors"]) == 0,
    "meshes":        total_meshes,
    "vertices":      total_verts,
    "materials":     total_mats,
    "hair_cards":    CARD_COUNT,
})

report["output_files"].append("pipeline_report.json")
save_report()

print("\n" + "=" * 60)
print("PIPELINE — FASE 2 COMPLETA")
print("=" * 60)
print(f"  Blender   : {bpy.app.version_string}")
print(f"  Meshes    : {total_meshes}")
print(f"  Vértices  : {total_verts}")
print(f"  Materiais : {total_mats}")
print(f"  Hair cards: {CARD_COUNT}")
for fn in report["output_files"]:
    fp = OUTDIR / fn
    sz = fp.stat().st_size if fp.exists() else 0
    print(f"  {fn:38s}  {sz // 1024} KB")
if report["warnings"]:
    print(f"\n  Avisos: {len(report['warnings'])}")
    for w in report["warnings"]:
        print(f"    ⚠ {w}")
if report["errors"]:
    print("\n  ERROS:")
    for e in report["errors"]:
        print(f"    ✗ {e}")
    sys.exit(1)

print("=" * 60)
print("→ Personagem pronto: character.glb + character.blend + character_preview.png")
