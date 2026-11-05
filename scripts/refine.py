"""
refine.py — Fase 3: Refinamento Final do Personagem
=====================================================

Melhorias chave nesta versão:
  - Olhos posicionados via grupos de vértices do corpo (helper-l-eye,
    joint-l-eye, joint-l-eye-target) usando coordenadas avaliadas via
    depsgraph — exactamente como o repositório 3D/b10_atlas_eye_diagnostic.py
  - Tom de pele quente e realista (não plástico)
  - Cores de roupa completamente distintas (t-shirt cinza, calças azul navy,
    sapatos pretos)
  - Roughness alto na roupa (elimina aspecto plástico)
  - Smooth shading + Subdivision Surface
  - Rig verificado / criado
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
# ARGUMENTOS
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
    "phase":           "refine",
    "start_time":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "blender":         bpy.app.version_string,
    "success":         False,
    "steps":           [],
    "errors":          [],
    "warnings":        [],
    "output_files":    [],
    "mat_assignments": [],
    "eye_method":      "unknown",
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
    report["steps"].append(name)


def save_report() -> None:
    report["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = OUTDIR / "refine_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    log(f"Relatório escrito → {path}")


# ─────────────────────────────────────────────────────────────────────────────
# UTILITÁRIOS DE MATERIAL
# ─────────────────────────────────────────────────────────────────────────────

def srgb2lin(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def hex2rgba(h: str, a: float = 1.0) -> tuple:
    h = h.lstrip("#")
    return (srgb2lin(int(h[0:2], 16) / 255),
            srgb2lin(int(h[2:4], 16) / 255),
            srgb2lin(int(h[4:6], 16) / 255), a)


def mat_pbr(
    name: str, base_hex: str,
    roughness: float = 0.5, metallic: float = 0.0,
    subsurface: float = 0.0, specular: float = 0.5,
    alpha: float = 1.0,
) -> bpy.types.Material:
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nodes = m.node_tree.nodes
    links = m.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = hex2rgba(base_hex, alpha)
    bsdf.inputs["Roughness"].default_value  = roughness
    bsdf.inputs["Metallic"].default_value   = metallic
    for sp in ("Specular IOR Level", "Specular"):
        if sp in bsdf.inputs:
            bsdf.inputs[sp].default_value = specular
            break
    if subsurface > 0:
        for ss in ("Subsurface Weight", "Subsurface"):
            if ss in bsdf.inputs:
                bsdf.inputs[ss].default_value = subsurface
                break
        for sc in ("Subsurface Radius",):
            if sc in bsdf.inputs:
                bsdf.inputs[sc].default_value = (1.0, 0.2, 0.1)
                break
        for sc2 in ("Subsurface Scale",):
            if sc2 in bsdf.inputs:
                bsdf.inputs[sc2].default_value = 0.05
                break
    if alpha < 1.0:
        m.blend_method = "BLEND"
        for al in ("Alpha",):
            if al in bsdf.inputs:
                bsdf.inputs[al].default_value = alpha
                break
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def smooth_obj(obj: bpy.types.Object, angle_deg: float = 60.0) -> None:
    if obj.type != "MESH":
        return
    for poly in obj.data.polygons:
        poly.use_smooth = True
    obj.data.update()
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if not any(m.type == "SMOOTH_BY_ANGLE" for m in obj.modifiers):
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle_deg))
    except Exception:
        try:
            obj.data.use_auto_smooth = True
            obj.data.auto_smooth_angle = math.radians(angle_deg)
        except Exception:
            pass


def assign_mat(obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def classify_obj(obj: bpy.types.Object, body: bpy.types.Object) -> str:
    n = obj.name.lower()
    if any(k in n for k in ("eye", "iris", "cornea", "sclera", "pupil")):
        return "eye"
    if any(k in n for k in ("teeth", "tooth", "gum")):
        return "teeth"
    if "tongue" in n:
        return "tongue"
    if any(k in n for k in ("hair", "brow", "lash", "haircard")):
        return "hair"
    if "nail" in n:
        return "nail"
    if any(k in n for k in (
        "cloth", "shirt", "top", "skirt", "pant", "belt",
        "dress", "boot", "shoe", "jacket", "coat",
        "trouser", "jeans", "sock", "glove",
        "proxy", "mhclo", "clothes",
    )):
        return "cloth"
    # Detecção geométrica
    if obj != body:
        n_body = len(body.data.vertices)
        n_obj  = len(obj.data.vertices)
        ratio  = n_obj / max(n_body, 1)
        if 0.04 < ratio < 0.65:
            try:
                obj_coords  = [body.matrix_world @ v.co for v in obj.data.vertices]
                body_coords = [body.matrix_world @ v.co for v in body.data.vertices]
                obj_minz    = min(v.z for v in obj_coords)
                obj_maxz    = max(v.z for v in obj_coords)
                body_minz   = min(v.z for v in body_coords)
                body_maxz   = max(v.z for v in body_coords)
                margin = (body_maxz - body_minz) * 0.08
                if obj_minz >= body_minz - margin and obj_maxz <= body_maxz + margin:
                    return "cloth"
            except Exception:
                pass
    return "skin"


# ─────────────────────────────────────────────────────────────────────────────
# OLHOS — POR GRUPOS DE VÉRTICES (método do repositório 3D)
# ─────────────────────────────────────────────────────────────────────────────

def get_group_centroid_evaluated(obj: bpy.types.Object, group_name: str) -> Vector | None:
    """
    Calcula centróide de um grupo de vértices usando coordenadas mundiais
    avaliadas via depsgraph (shape keys + modifiers activos).
    Exactamente como b10_atlas_eye_diagnostic.py no repositório 3D.
    """
    if group_name not in obj.vertex_groups:
        return None
    gidx = obj.vertex_groups[group_name].index

    # Coordenadas avaliadas (depsgraph)
    bpy.context.view_layer.update()
    dep   = bpy.context.evaluated_depsgraph_get()
    ev    = obj.evaluated_get(dep)
    emesh = ev.to_mesh()
    wm    = obj.matrix_world

    coords = []
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gidx and g.weight > 0:
                # Usar coordenada avaliada se disponível, senão base
                if v.index < len(emesh.vertices):
                    coords.append(wm @ emesh.vertices[v.index].co)
                else:
                    coords.append(wm @ v.co)
                break

    ev.to_mesh_clear()

    if not coords:
        return None

    cx = sum(c.x for c in coords) / len(coords)
    cy = sum(c.y for c in coords) / len(coords)
    cz = sum(c.z for c in coords) / len(coords)
    return Vector((cx, cy, cz))


def find_eye_centers(body: bpy.types.Object, head_cz: float, head_r: float, face_y: float):
    """
    Tenta encontrar os centros dos olhos usando:
    1. Grupos de vértices helper-l/r-eye (mais fiável — 72 verts)
    2. Grupos joint-l/r-eye (8 verts)
    3. Fallback proporcional baseado na cabeça

    Retorna (center_L, center_R, orient_L, orient_R, method_used)
    """
    # Tentativa 1: helper groups (72 verts, mais fiáveis)
    cL = get_group_centroid_evaluated(body, "helper-l-eye")
    cR = get_group_centroid_evaluated(body, "helper-r-eye")

    if cL and cR:
        log(f"  Olhos via helper groups: L={[round(x,4) for x in cL]} R={[round(x,4) for x in cR]}")
        report["eye_method"] = "helper_vertex_groups"
    else:
        # Tentativa 2: joint groups (8 verts)
        cL = get_group_centroid_evaluated(body, "joint-l-eye")
        cR = get_group_centroid_evaluated(body, "joint-r-eye")
        if cL and cR:
            log(f"  Olhos via joint groups: L={[round(x,4) for x in cL]} R={[round(x,4) for x in cR]}")
            report["eye_method"] = "joint_vertex_groups"
        else:
            # Fallback: posição proporcional (último recurso)
            eye_z   = head_cz + head_r * 0.10
            eye_sep = head_r * 0.52
            sclera_r_est = head_r * 0.130
            ey = face_y - sclera_r_est * 0.30
            cL = Vector(( eye_sep / 2, ey, eye_z))
            cR = Vector((-eye_sep / 2, ey, eye_z))
            log(f"  Olhos via proporção (fallback): sep={eye_sep:.4f}", "WARN")
            report["eye_method"] = "proportional_fallback"
            report["warnings"].append("Grupos de vértices oculares não encontrados — usando posição proporcional")

    # Orientação: joint → target (direcção do olhar)
    tL = get_group_centroid_evaluated(body, "joint-l-eye-target")
    tR = get_group_centroid_evaluated(body, "joint-r-eye-target")

    orient_L = (tL - cL).normalized() if tL else Vector((0, -1, 0))
    orient_R = (tR - cR).normalized() if tR else Vector((0, -1, 0))

    return cL, cR, orient_L, orient_R


# ─────────────────────────────────────────────────────────────────────────────
# 1. CARREGAR BLEND
# ─────────────────────────────────────────────────────────────────────────────

step("Carregar blend da Fase 2")

input_path = Path(ARGS.input) if ARGS.input else None
if not input_path or not input_path.exists():
    for candidate in ["character.blend", "character.glb", "character.fbx", "character.obj"]:
        p = OUTDIR / candidate
        if p.exists():
            input_path = p
            break

if not input_path or not input_path.exists():
    log("Nenhum ficheiro de entrada encontrado", "ERROR")
    save_report()
    sys.exit(1)

log(f"Entrada: {input_path} ({input_path.stat().st_size // 1024} KB)")
ext = input_path.suffix.lower()

if ext == ".blend":
    bpy.ops.wm.open_mainfile(filepath=str(input_path))
elif ext == ".glb":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
elif ext == ".fbx":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(input_path),
                              automatic_bone_orientation=True,
                              ignore_leaf_bones=True)
elif ext == ".obj":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.obj(filepath=str(input_path))
else:
    log(f"Formato não suportado: {ext}", "ERROR")
    save_report()
    sys.exit(1)

scene = bpy.context.scene
all_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
all_arms   = [o for o in bpy.data.objects if o.type == "ARMATURE"]
log(f"Cena: {len(all_meshes)} meshes, {len(all_arms)} armaduras")

if not all_meshes:
    log("Nenhuma mesh encontrada", "ERROR")
    save_report()
    sys.exit(1)

body = max(all_meshes, key=lambda o: len(o.data.vertices))
log(f"Corpo: '{body.name}' ({len(body.data.vertices)} vértices, {len(body.vertex_groups)} grupos)")

bpy.context.view_layer.update()
body_coords_w = [body.matrix_world @ v.co for v in body.data.vertices]
body_minz = min(v.z for v in body_coords_w)
body_maxz = max(v.z for v in body_coords_w)
body_h    = body_maxz - body_minz

head_cz    = body_minz + body_h * 0.930
head_r     = body_h * 0.068
shoulder_z = body_minz + body_h * 0.802
bust_z     = body_minz + body_h * 0.720
waist_z    = body_minz + body_h * 0.590
hip_z      = body_minz + body_h * 0.530
elbow_z    = body_minz + body_h * 0.620
wrist_z    = body_minz + body_h * 0.420
ankle_z    = body_minz + body_h * 0.058

# Face Y: ponto mais frontal da cabeça (zona dos olhos)
head_verts = [body.matrix_world @ v.co for v in body.data.vertices
              if (body.matrix_world @ v.co).z > body_minz + body_h * 0.80]
face_y = min(v.y for v in head_verts) if head_verts else -(head_r * 0.80)

log(f"Altura: {body_h:.3f} m | face_y: {face_y:.4f}")
log(f"Grupos de vértices: {[vg.name for vg in body.vertex_groups[:15]]}")
report["body_height_m"]  = round(body_h, 4)
report["loaded_meshes"]  = len(all_meshes)
report["vertex_groups"]  = [vg.name for vg in body.vertex_groups]


# ─────────────────────────────────────────────────────────────────────────────
# 2. SMOOTH SHADING
# ─────────────────────────────────────────────────────────────────────────────

step("Smooth shading")
for obj in all_meshes:
    smooth_obj(obj, 60.0)
log(f"Smooth: {len(all_meshes)} meshes")


# ─────────────────────────────────────────────────────────────────────────────
# 3. SUBDIVISION SURFACE
# ─────────────────────────────────────────────────────────────────────────────

step("Subdivision Surface")
SKIP_SUBDIV = ("hair", "belt", "card", "eye", "teeth", "tongue", "nail", "cornea")
for obj in all_meshes:
    if any(k in obj.name.lower() for k in SKIP_SUBDIV):
        continue
    if not any(m.type == "SUBSURF" for m in obj.modifiers):
        mod = obj.modifiers.new("Subdivision", "SUBSURF")
        mod.levels           = 1
        mod.render_levels    = 2
        mod.subdivision_type = "CATMULL_CLARK"
log("Subdivision aplicada")


# ─────────────────────────────────────────────────────────────────────────────
# 4. PALETA DE MATERIAIS
#    Tom de pele: baseado em referências reais de pele média africana/angolana
#    Roupa: cores completamente distintas e com roughness alto (anti-plástico)
# ─────────────────────────────────────────────────────────────────────────────

step("Criar paleta de materiais")
MATS = {
    # Pele — tom quente médio (nem demasiado escuro nem demasiado claro)
    # #8B5A2B = castanho médio quente; SSS para profundidade realista
    "skin":       mat_pbr("Skin_Final",    "#8B5A2B",
                          roughness=0.58, subsurface=0.20, specular=0.35),

    # Rosto — ligeiramente mais quente e rosado que o corpo
    "face":       mat_pbr("Face_Final",    "#9B6535",
                          roughness=0.55, subsurface=0.26, specular=0.38),

    # T-shirt — cinza médio (claramente distinto da pele escura)
    "tshirt":     mat_pbr("TShirt_Final",  "#5A5A5A",
                          roughness=0.94, specular=0.02),

    # Calças — azul navy escuro (ganga)
    "pants":      mat_pbr("Pants_Final",   "#1E2D45",
                          roughness=0.90, specular=0.03),

    # Sapatos — castanho couro (distinto das calças pretas)
    "shoes":      mat_pbr("Shoes_Final",   "#3D1A0A",
                          roughness=0.60, specular=0.30),

    # Roupa genérica fallback
    "cloth":      mat_pbr("Cloth_Final",   "#4A4A4A",
                          roughness=0.92, specular=0.02),

    # Cabelo — castanho muito escuro com brilho subtil
    "hair":       mat_pbr("Hair_Final",    "#1E0E04",
                          roughness=0.70, specular=0.30),

    # Olhos
    "eye_sclera": mat_pbr("Eye_Sclera",   "#F2EDE4",
                          roughness=0.03, specular=0.90),
    "eye_iris":   mat_pbr("Eye_Iris",     "#3B2008",
                          roughness=0.04, specular=0.85),
    "eye_pupil":  mat_pbr("Eye_Pupil",    "#060302",
                          roughness=0.00, specular=0.98),
    "eye_cornea": mat_pbr("Eye_Cornea",   "#FFFFFF",
                          roughness=0.00, specular=1.0, alpha=0.05),

    # Dentes e unhas
    "teeth":      mat_pbr("Teeth_Final",  "#EDE8DC",
                          roughness=0.20, specular=0.65),
    "nail":       mat_pbr("Nails_Final",  "#C4846A",
                          roughness=0.18, specular=0.70),
}
log(f"Paleta: {len(MATS)} materiais")


# ─────────────────────────────────────────────────────────────────────────────
# 5. REMOVER OLHOS EXISTENTES (guardar nomes antes — evita ReferenceError)
# ─────────────────────────────────────────────────────────────────────────────

step("Remover olhos existentes")
EYE_KW    = ("eye", "sclera", "iris", "cornea", "pupil")
eye_names = [o.name for o in bpy.data.objects
             if o.type == "MESH" and any(k in o.name.lower() for k in EYE_KW)]
for name in eye_names:
    obj_ref = bpy.data.objects.get(name)
    if obj_ref is not None:
        bpy.data.objects.remove(obj_ref, do_unlink=True)
        log(f"  Removido: {name}")

# Reconstruir lista — referências antigas inválidas após delete
all_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
log(f"Meshes após remoção: {len(all_meshes)}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. ATRIBUIR MATERIAIS
# ─────────────────────────────────────────────────────────────────────────────

step("Atribuir materiais")
cls_counts: dict = {}

for obj in all_meshes:
    cls    = classify_obj(obj, body)
    n_verts = len(obj.data.vertices)
    cls_counts[cls] = cls_counts.get(cls, 0) + 1

    if cls == "eye":
        assign_mat(obj, MATS["eye_sclera"])

    elif cls == "teeth":
        assign_mat(obj, MATS["teeth"])

    elif cls == "tongue":
        assign_mat(obj, MATS["skin"])

    elif cls == "hair":
        assign_mat(obj, MATS["hair"])

    elif cls == "nail":
        assign_mat(obj, MATS["nail"])

    elif cls == "cloth":
        # Distinguir por posição Z
        try:
            vz_world = [obj.matrix_world @ v.co for v in obj.data.vertices]
            center_z = sum(v.z for v in vz_world) / len(vz_world)
            min_z    = min(v.z for v in vz_world)

            if min_z < body_minz + body_h * 0.08:
                sub_mat = MATS["shoes"];  mat_name = "shoes"
            elif center_z > hip_z:
                sub_mat = MATS["tshirt"]; mat_name = "tshirt"
            else:
                sub_mat = MATS["pants"];  mat_name = "pants"
        except Exception:
            sub_mat = MATS["cloth"];  mat_name = "cloth"

        assign_mat(obj, sub_mat)
        log(f"  CLOTH '{obj.name}' ({n_verts}v) → {mat_name}")
        report["mat_assignments"].append({"obj": obj.name, "mat": mat_name})
        continue

    else:  # skin
        mat = MATS["face"] if obj == body else MATS["skin"]
        assign_mat(obj, mat)

    log(f"  {cls.upper():8s} '{obj.name}' ({n_verts}v)")
    report["mat_assignments"].append({"obj": obj.name, "mat": cls})

log(f"Classificações: {cls_counts}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. OLHOS ANATÓMICOS
#    Posicionados via grupos de vértices do corpo (método do repo 3D).
#    4 camadas: esclera + íris + pupila + córnea
# ─────────────────────────────────────────────────────────────────────────────

step("Olhos anatómicos")

# Raio dos olhos baseado na distância interocular real (se disponível)
cL_j = get_group_centroid_evaluated(body, "joint-l-eye")
cR_j = get_group_centroid_evaluated(body, "joint-r-eye")
if cL_j and cR_j:
    interocular = (cR_j - cL_j).length
    sclera_r    = interocular * 0.30   # ~30% da distância interocular
    log(f"  Distância interocular: {interocular:.4f} m → raio esclera: {sclera_r:.4f} m")
else:
    sclera_r = head_r * 0.130
    log(f"  Raio esclera por proporção: {sclera_r:.4f} m")

iris_r  = sclera_r * 0.56
pupil_r = sclera_r * 0.28

# Centros e orientação
cL, cR, orient_L, orient_R = find_eye_centers(body, head_cz, head_r, face_y)
log(f"  Centro L: {[round(x,4) for x in cL]}")
log(f"  Centro R: {[round(x,4) for x in cR]}")
log(f"  Orientação L: {[round(x,4) for x in orient_L]}")

for side, center, orient in [("L", cL, orient_L), ("R", cR, orient_R)]:

    # Esclera
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64, ring_count=32, radius=sclera_r,
        location=center)
    sc = bpy.context.active_object
    sc.name = f"Eye_Sclera_{side}"
    assign_mat(sc, MATS["eye_sclera"])
    smooth_obj(sc, 60)

    # Iris — disco orientado pela direcção joint→target
    iris_pos = Vector(center) + orient.normalized() * sclera_r * 0.86
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64, radius=iris_r, depth=sclera_r * 0.04,
        location=iris_pos)
    ir = bpy.context.active_object
    ir.name = f"Eye_Iris_{side}"
    if orient.length > 1e-6:
        ir.rotation_euler = orient.to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.transform_apply(rotation=True)
    assign_mat(ir, MATS["eye_iris"])
    smooth_obj(ir, 60)

    # Pupila
    pupil_pos = Vector(center) + orient.normalized() * sclera_r * 0.88
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48, radius=pupil_r, depth=sclera_r * 0.02,
        location=pupil_pos)
    pu = bpy.context.active_object
    pu.name = f"Eye_Pupil_{side}"
    if orient.length > 1e-6:
        pu.rotation_euler = orient.to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.transform_apply(rotation=True)
    assign_mat(pu, MATS["eye_pupil"])

    # Cornea — esfera levemente maior, quase transparente
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64, ring_count=32, radius=sclera_r * 1.01,
        location=center)
    co = bpy.context.active_object
    co.name = f"Eye_Cornea_{side}"
    assign_mat(co, MATS["eye_cornea"])
    smooth_obj(co, 60)

log(f"Olhos criados via método: {report['eye_method']}")


# ─────────────────────────────────────────────────────────────────────────────
# 8. VERIFICAR / CRIAR RIG
# ─────────────────────────────────────────────────────────────────────────────

step("Verificar / criar rig")
all_arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]

if all_arms:
    arm = all_arms[0]
    n_bones = len(arm.data.bones)
    log(f"Armadura existente: '{arm.name}' — {n_bones} ossos")
    report["rig_source"] = "imported"
    report["rig_bones"]  = n_bones
    if not any(m.type == "ARMATURE" for m in body.modifiers):
        mod = body.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
    head_bone = arm.data.bones.get("Head") or arm.data.bones.get("head")
    if head_bone:
        for obj in bpy.data.objects:
            if obj.type == "MESH" and "hair" in obj.name.lower():
                if obj.parent != arm:
                    obj.parent      = arm
                    obj.parent_type = "BONE"
                    obj.parent_bone = head_bone.name
else:
    log("Sem armadura — a criar rig de 20 ossos …")
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm_obj  = bpy.context.active_object
    arm_obj.name = "Armature"
    arm_obj.data.name = "Skeleton"
    edit_bones = arm_obj.data.edit_bones
    for b in list(edit_bones):
        edit_bones.remove(b)
    BONES = [
        ("Hips",       (0,      0, hip_z),          (0,      0, waist_z),                None),
        ("Spine",      (0,      0, waist_z),         (0,      0, waist_z + 0.14),         "Hips"),
        ("Spine1",     (0,      0, waist_z + 0.14),  (0,      0, bust_z),                 "Spine"),
        ("Chest",      (0,      0, bust_z),           (0,      0, shoulder_z),             "Spine1"),
        ("Neck",       (0,      0, shoulder_z),       (0,      0, head_cz - head_r),       "Chest"),
        ("Head",       (0,      0, head_cz - head_r),(0,      0, head_cz + head_r * 1.1), "Neck"),
        ("UpperLeg_L", (-0.090, 0, hip_z),           (-0.090, 0, hip_z * 0.55),           "Hips"),
        ("LowerLeg_L", (-0.090, 0, hip_z * 0.55),   (-0.090, 0, ankle_z + 0.06),         "UpperLeg_L"),
        ("Foot_L",     (-0.090, 0, ankle_z + 0.06),  (-0.075, -0.08, ankle_z),            "LowerLeg_L"),
        ("UpperLeg_R", (0.090,  0, hip_z),           (0.090,  0, hip_z * 0.55),           "Hips"),
        ("LowerLeg_R", (0.090,  0, hip_z * 0.55),   (0.090,  0, ankle_z + 0.06),         "UpperLeg_R"),
        ("Foot_R",     (0.090,  0, ankle_z + 0.06),  (0.075,  -0.08, ankle_z),            "LowerLeg_R"),
        ("Shoulder_L", (-0.080, 0, shoulder_z),      (-0.180, 0, shoulder_z),             "Chest"),
        ("UpperArm_L", (-0.180, 0, shoulder_z),      (-0.260, 0, elbow_z),                "Shoulder_L"),
        ("LowerArm_L", (-0.260, 0, elbow_z),         (-0.280, 0, wrist_z),                "UpperArm_L"),
        ("Hand_L",     (-0.280, 0, wrist_z),         (-0.285, 0, wrist_z - 0.09),         "LowerArm_L"),
        ("Shoulder_R", (0.080,  0, shoulder_z),      (0.180,  0, shoulder_z),             "Chest"),
        ("UpperArm_R", (0.180,  0, shoulder_z),      (0.260,  0, elbow_z),                "Shoulder_R"),
        ("LowerArm_R", (0.260,  0, elbow_z),         (0.280,  0, wrist_z),                "UpperArm_R"),
        ("Hand_R",     (0.280,  0, wrist_z),         (0.285,  0, wrist_z - 0.09),         "LowerArm_R"),
    ]
    created = {}
    for bname, head, tail, parent in BONES:
        eb = edit_bones.new(bname)
        eb.head = Vector(head)
        eb.tail = Vector(tail)
        if parent and parent in created:
            eb.parent = created[parent]
        created[bname] = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    report["rig_source"] = "created"
    report["rig_bones"]  = len(BONES)
    log(f"Armadura criada: {len(BONES)} ossos")
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        log("Pesos automáticos aplicados")
    except Exception as exc:
        log(f"Pesos automáticos: {exc}", "WARN")
        body.parent = arm_obj
        mod = body.modifiers.new("Armature", "ARMATURE")
        mod.object = arm_obj


# ─────────────────────────────────────────────────────────────────────────────
# 9. ILUMINAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

step("Iluminacao")
for obj in list(bpy.data.objects):
    if obj.type == "LIGHT":
        bpy.data.objects.remove(obj, do_unlink=True)

center = Vector((0, 0, body_h * 0.55))

def add_light(name, loc, energy, size, color):
    bpy.ops.object.light_add(type="AREA", location=loc)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.size   = size
    light.data.color  = color
    d = center - Vector(loc)
    light.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

add_light("Key",  ( 2.2, -3.0,  1.8), 1600, 2.0, (1.00, 0.95, 0.88))
add_light("Fill", (-2.0, -1.5,  1.2),  700, 3.5, (0.86, 0.91, 1.00))
add_light("Rim",  ( 0.2,  3.0,  2.2),  900, 1.5, (1.00, 0.98, 0.94))
add_light("Top",  ( 0.0,  0.0,  3.5),  400, 4.0, (1.00, 1.00, 1.00))
log("Iluminacao four-point")


# ─────────────────────────────────────────────────────────────────────────────
# 10. CAMARA
# ─────────────────────────────────────────────────────────────────────────────

step("Camara")
for obj in list(bpy.data.objects):
    if obj.type == "CAMERA":
        bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.object.camera_add(location=(0, -3.8, body_h * 0.54))
cam = bpy.context.active_object
cam.name = "Camera_Final"
cam.data.type = "PERSP"
cam.data.lens = 85
d = center - Vector(cam.location)
cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
wn = world.node_tree.nodes
wl = world.node_tree.links
wn.clear()
bg = wn.new("ShaderNodeBackground")
bg.inputs["Color"].default_value    = (0.03, 0.03, 0.05, 1.0)
bg.inputs["Strength"].default_value = 0.15
wo = wn.new("ShaderNodeOutputWorld")
wl.new(bg.outputs["Background"], wo.inputs["Surface"])


# ─────────────────────────────────────────────────────────────────────────────
# 11. RENDER
# ─────────────────────────────────────────────────────────────────────────────

step("Render")
scene.render.engine                            = "BLENDER_WORKBENCH"
scene.render.resolution_x                     = 1024
scene.render.resolution_y                     = 1024
scene.render.resolution_percentage            = 100
scene.render.image_settings.file_format       = "PNG"
scene.display.shading.light                   = "STUDIO"
scene.display.shading.color_type              = "MATERIAL"
scene.display.shading.show_specular_highlight = True
scene.display.shading.show_shadows            = True
for sl in ("paint.sl", "outdoor.sl", "rim.sl"):
    try:
        scene.display.shading.studio_light = sl
        break
    except Exception:
        continue

preview_path = str(OUTDIR / "character_final_preview.png")
scene.render.filepath = preview_path
try:
    bpy.ops.render.render(write_still=True)
    if Path(preview_path).exists():
        log(f"Preview: {Path(preview_path).stat().st_size // 1024} KB")
        report["output_files"].append("character_final_preview.png")
except Exception as exc:
    log(f"Render falhou: {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 12. GUARDAR BLEND FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Blend final")
blend_final = str(OUTDIR / "character_final.blend")
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_final)
    report["output_files"].append("character_final.blend")
    log(f"Blend → {blend_final}")
except Exception as exc:
    log(f"Blend falhou: {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 13. EXPORTAR GLB FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Exportar GLB final")
glb_final = str(OUTDIR / "character_final.glb")

try:
    bpy.ops.export_scene.gltf(
        filepath=glb_final, export_format="GLB",
        export_apply=True, export_materials="EXPORT",
        export_texcoords=True, export_normals=True,
        export_skins=True, export_animations=False,
        export_morph=True, export_yup=True,
    )
    log("GLB exportado (completo)")
except TypeError:
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_final, export_format="GLB",
            export_apply=True, export_skins=True,
        )
        log("GLB exportado (mínimo)")
    except Exception as exc2:
        log(f"GLB falhou: {exc2}", "ERROR")
        save_report()
        sys.exit(1)
except Exception as exc:
    log(f"GLB falhou: {exc}", "ERROR")
    save_report()
    sys.exit(1)

if Path(glb_final).exists():
    kb = Path(glb_final).stat().st_size // 1024
    log(f"GLB final: {kb} KB")
    report["output_files"].append("character_final.glb")
    report["glb_final_kb"] = kb
else:
    log("GLB final não encontrado", "ERROR")
    save_report()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 14. RELATÓRIO
# ─────────────────────────────────────────────────────────────────────────────

step("Relatorio")
total_verts  = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH")
total_meshes = len([o for o in bpy.data.objects if o.type == "MESH"])
total_mats   = len(bpy.data.materials)

report.update({
    "success":   len(report["errors"]) == 0,
    "meshes":    total_meshes,
    "vertices":  total_verts,
    "materials": total_mats,
    "rig_bones": report.get("rig_bones", 0),
})
report["output_files"].append("refine_report.json")
save_report()

print("\n" + "=" * 60)
print("REFINE - FASE 3 COMPLETA")
print("=" * 60)
print(f"  Blender    : {bpy.app.version_string}")
print(f"  Meshes     : {total_meshes}  |  Vertices: {total_verts}")
print(f"  Materiais  : {total_mats}")
print(f"  Rig        : {report.get('rig_bones',0)} ossos ({report.get('rig_source','?')})")
print(f"  Olhos      : {report.get('eye_method','?')}")
for fn in report["output_files"]:
    fp = OUTDIR / fn
    sz = fp.stat().st_size if fp.exists() else 0
    print(f"  {fn:44s}  {sz // 1024} KB")
if report["warnings"]:
    print(f"\n  Avisos: {len(report['warnings'])}")
if report["errors"]:
    print(f"\n  ERROS: {report['errors']}")
    sys.exit(1)
print("=" * 60)
print("-> Produto final: character_final.glb")
