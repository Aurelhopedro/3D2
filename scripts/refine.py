"""
refine.py — Fase 3: Refinamento Final do Personagem
=====================================================

Recebe o character.blend produzido pela Fase 2 e aplica todas as
operações de qualidade que transformam o resultado básico num
personagem de aspecto profissional:

  1. Carrega o character.blend da Fase 2
  2. Smooth shading em todos os meshes (elimina aspecto triangulado)
  3. Auto Smooth com ângulo de 60°
  4. Subdivision Surface nível 1 no corpo
  5. Materiais PBR com distinção clara: pele / roupa / cabelo / olhos
     — Detecção por nome E por geometria (ratio de vértices vs corpo)
     — Roughness alto na roupa para eliminar aspecto plástico
     — Cores completamente distintas: pele castanha, t-shirt cinza,
       calças azul escuro, sapatos pretos, cabelo escuro
  6. Verifica / cria rig completo de 20 ossos
  7. Olhos anatómicos: SEMPRE removidos e recriados correctamente
     (esclera + íris + pupila + córnea)
  8. Iluminação four-point cinematográfica
  9. Render final 1024x1024
 10. Exporta character_final.glb
 11. Relatório JSON de fase
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
# UTILITÁRIOS
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
    """
    Classifica um objecto para escolher o material correcto.
    Camada 1: nome (palavras-chave).
    Camada 2: geometria (ratio de vértices e posição relativa ao corpo).
    """
    n = obj.name.lower()

    # Camada 1 — nome
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

    # Camada 2 — geometria
    if obj != body:
        n_body = len(body.data.vertices)
        n_obj  = len(obj.data.vertices)
        ratio  = n_obj / max(n_body, 1)
        if 0.04 < ratio < 0.65:
            try:
                obj_coords  = [body.matrix_world @ v.co for v in obj.data.vertices]
                body_coords = [body.matrix_world @ v.co for v in body.data.vertices]
                obj_minz  = min(v.z for v in obj_coords)
                obj_maxz  = max(v.z for v in obj_coords)
                body_minz = min(v.z for v in body_coords)
                body_maxz = max(v.z for v in body_coords)
                margin = (body_maxz - body_minz) * 0.08
                if obj_minz >= body_minz - margin and obj_maxz <= body_maxz + margin:
                    return "cloth"
            except Exception:
                pass

    return "skin"


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

# Inventário inicial
all_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
all_arms   = [o for o in bpy.data.objects if o.type == "ARMATURE"]
log(f"Cena: {len(all_meshes)} meshes, {len(all_arms)} armaduras")

if not all_meshes:
    log("Nenhuma mesh encontrada", "ERROR")
    save_report()
    sys.exit(1)

body = max(all_meshes, key=lambda o: len(o.data.vertices))
log(f"Corpo: '{body.name}' ({len(body.data.vertices)} vértices)")

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
face_y     = -(head_r * 0.80)

log(f"Altura: {body_h:.3f} m")
report["body_height_m"] = round(body_h, 4)
report["loaded_meshes"] = len(all_meshes)


# ─────────────────────────────────────────────────────────────────────────────
# 2. SMOOTH SHADING
# ─────────────────────────────────────────────────────────────────────────────

step("Smooth shading")
for obj in all_meshes:
    smooth_obj(obj, 60.0)
log(f"Smooth aplicado a {len(all_meshes)} meshes")


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
# ─────────────────────────────────────────────────────────────────────────────

step("Criar paleta de materiais")
MATS = {
    "skin":       mat_pbr("Skin_Final",    "#B5651D", roughness=0.55, subsurface=0.22, specular=0.38),
    "face":       mat_pbr("Face_Final",    "#C0714A", roughness=0.52, subsurface=0.28, specular=0.40),
    "tshirt":     mat_pbr("TShirt_Final",  "#3A3A3A", roughness=0.95, specular=0.02),
    "pants":      mat_pbr("Pants_Final",   "#1A2235", roughness=0.92, specular=0.03),
    "shoes":      mat_pbr("Shoes_Final",   "#0A0A0A", roughness=0.55, specular=0.35),
    "cloth":      mat_pbr("Cloth_Final",   "#2C2C2C", roughness=0.93, specular=0.02),
    "hair":       mat_pbr("Hair_Final",    "#1A0D05", roughness=0.72, specular=0.28),
    "eye_sclera": mat_pbr("Eye_Sclera",    "#F0EBE2", roughness=0.03, specular=0.85),
    "eye_iris":   mat_pbr("Eye_Iris",      "#2E1A0A", roughness=0.05, specular=0.80),
    "eye_pupil":  mat_pbr("Eye_Pupil",     "#050302", roughness=0.00, specular=0.98),
    "eye_cornea": mat_pbr("Eye_Cornea",    "#FFFFFF",  roughness=0.00, specular=1.0, alpha=0.06),
    "teeth":      mat_pbr("Teeth_Final",   "#EDE8DC", roughness=0.20, specular=0.65),
    "nail":       mat_pbr("Nails_Final",   "#D4967A", roughness=0.16, specular=0.72),
}
log(f"Paleta criada: {len(MATS)} materiais")


# ─────────────────────────────────────────────────────────────────────────────
# 5. REMOVER OLHOS EXISTENTES (antes de iterar — evita ReferenceError)
#    Guardamos os NOMES antes de deletar; após delete o .name é inválido.
# ─────────────────────────────────────────────────────────────────────────────

step("Remover olhos existentes")
EYE_KW = ("eye", "sclera", "iris", "cornea", "pupil")
eye_names = [
    o.name for o in bpy.data.objects
    if o.type == "MESH" and any(k in o.name.lower() for k in EYE_KW)
]
for name in eye_names:
    obj_ref = bpy.data.objects.get(name)
    if obj_ref is not None:
        bpy.data.objects.remove(obj_ref, do_unlink=True)
        log(f"  Removido: {name}")

# Reconstruir all_meshes — referências antigas são inválidas após delete
all_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
log(f"Meshes após remover olhos: {len(all_meshes)}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. ATRIBUIR MATERIAIS
# ─────────────────────────────────────────────────────────────────────────────

step("Atribuir materiais")
cls_counts: dict = {}

for obj in all_meshes:
    cls = classify_obj(obj, body)
    cls_counts[cls] = cls_counts.get(cls, 0) + 1
    n_verts = len(obj.data.vertices)

    if cls == "eye":
        assign_mat(obj, MATS["eye_sclera"])

    elif cls == "teeth":
        assign_mat(obj, MATS["teeth"])

    elif cls in ("tongue",):
        assign_mat(obj, MATS["skin"])

    elif cls == "hair":
        assign_mat(obj, MATS["hair"])

    elif cls == "nail":
        assign_mat(obj, MATS["nail"])

    elif cls == "cloth":
        # Distinguir t-shirt / calças / sapatos pela posição Z
        try:
            vz_world = [obj.matrix_world @ v.co for v in obj.data.vertices]
            center_z = sum(v.z for v in vz_world) / len(vz_world)
            min_z    = min(v.z for v in vz_world)

            if min_z < body_minz + body_h * 0.08:
                sub_mat  = MATS["shoes"];  mat_name = "shoes"
            elif center_z > hip_z:
                sub_mat  = MATS["tshirt"]; mat_name = "tshirt"
            else:
                sub_mat  = MATS["pants"];  mat_name = "pants"
        except Exception:
            sub_mat  = MATS["cloth"];  mat_name = "cloth"

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
# 7. OLHOS ANATÓMICOS — recriados de raiz
#    4 camadas por olho: esclera + íris + pupila + córnea
# ─────────────────────────────────────────────────────────────────────────────

step("Olhos anatómicos")

sclera_r = head_r * 0.130
eye_sep  = head_r * 0.52
eye_z    = head_cz + head_r * 0.10
sclera_y = face_y - sclera_r * 0.30
iris_r   = sclera_r * 0.56
pupil_r  = sclera_r * 0.28

for side, sx in [("L", eye_sep / 2), ("R", -eye_sep / 2)]:

    # Esclera
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64, ring_count=32, radius=sclera_r,
        location=(sx, sclera_y, eye_z))
    sc = bpy.context.active_object
    sc.name = f"Eye_Sclera_{side}"
    assign_mat(sc, MATS["eye_sclera"])
    smooth_obj(sc, 60)

    # Iris
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64, radius=iris_r, depth=sclera_r * 0.04,
        location=(sx, sclera_y - sclera_r * 0.86, eye_z))
    ir = bpy.context.active_object
    ir.name = f"Eye_Iris_{side}"
    ir.rotation_euler = (math.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(rotation=True)
    assign_mat(ir, MATS["eye_iris"])
    smooth_obj(ir, 60)

    # Pupila
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48, radius=pupil_r, depth=sclera_r * 0.02,
        location=(sx, sclera_y - sclera_r * 0.88, eye_z))
    pu = bpy.context.active_object
    pu.name = f"Eye_Pupil_{side}"
    pu.rotation_euler = (math.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(rotation=True)
    assign_mat(pu, MATS["eye_pupil"])

    # Cornea
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64, ring_count=32, radius=sclera_r * 1.01,
        location=(sx, sclera_y, eye_z))
    co = bpy.context.active_object
    co.name = f"Eye_Cornea_{side}"
    assign_mat(co, MATS["eye_cornea"])
    smooth_obj(co, 60)

log("Olhos criados (esclera + iris + pupila + cornea x2)")


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
        log("  Modifier de armadura adicionado ao corpo")

    head_bone = arm.data.bones.get("Head") or arm.data.bones.get("head")
    if head_bone:
        for obj in bpy.data.objects:
            if obj.type == "MESH" and "hair" in obj.name.lower():
                if obj.parent != arm:
                    obj.parent      = arm
                    obj.parent_type = "BONE"
                    obj.parent_bone = head_bone.name
                    log(f"  Cabelo '{obj.name}' → osso Head")

else:
    log("Sem armadura — a criar rig de 20 ossos …")
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm_obj  = bpy.context.active_object
    arm_obj.name = "Armature"
    arm_data = arm_obj.data
    arm_data.name = "Skeleton"

    edit_bones = arm_data.edit_bones
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
# 9. ILUMINAÇÃO FOUR-POINT
# ─────────────────────────────────────────────────────────────────────────────

step("Iluminacao")
for obj in list(bpy.data.objects):
    if obj.type == "LIGHT":
        bpy.data.objects.remove(obj, do_unlink=True)

center = Vector((0, 0, body_h * 0.55))

def add_light(name, loc, energy, size, color):
    bpy.ops.object.light_add(type="AREA", location=loc)
    light = bpy.context.active_object
    light.name       = name
    light.data.energy = energy
    light.data.size   = size
    light.data.color  = color
    d = center - Vector(loc)
    light.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

add_light("Key",  ( 2.2, -3.0,  1.8), 1600, 2.0, (1.00, 0.95, 0.88))
add_light("Fill", (-2.0, -1.5,  1.2),  700, 3.5, (0.86, 0.91, 1.00))
add_light("Rim",  ( 0.2,  3.0,  2.2),  900, 1.5, (1.00, 0.98, 0.94))
add_light("Top",  ( 0.0,  0.0,  3.5),  400, 4.0, (1.00, 1.00, 1.00))
log("Iluminacao four-point configurada")


# ─────────────────────────────────────────────────────────────────────────────
# 10. CAMARA
# ─────────────────────────────────────────────────────────────────────────────

step("Camara")
for obj in list(bpy.data.objects):
    if obj.type == "CAMERA":
        bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.object.camera_add(location=(0, -3.8, body_h * 0.54))
cam = bpy.context.active_object
cam.name       = "Camera_Final"
cam.data.type  = "PERSP"
cam.data.lens  = 85
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
log("Camara 85mm + world configurados")


# ─────────────────────────────────────────────────────────────────────────────
# 11. RENDER PREVIEW
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
    log(f"Render falhou (nao critico): {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 12. GUARDAR BLEND FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Guardar blend final")
blend_final = str(OUTDIR / "character_final.blend")
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_final)
    report["output_files"].append("character_final.blend")
    log(f"Blend gravado → {blend_final}")
except Exception as exc:
    log(f"Blend falhou: {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 13. EXPORTAR GLB FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Exportar GLB final")
glb_final = str(OUTDIR / "character_final.glb")

try:
    bpy.ops.export_scene.gltf(
        filepath=glb_final,
        export_format="GLB",
        export_apply=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_skins=True,
        export_animations=False,
        export_morph=True,
        export_yup=True,
    )
    log("GLB exportado (parametros completos)")
except TypeError:
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_final,
            export_format="GLB",
            export_apply=True,
            export_skins=True,
        )
        log("GLB exportado (modo minimo)")
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
    log("GLB final nao encontrado", "ERROR")
    save_report()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 14. RELATORIO
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
print(f"  Blender   : {bpy.app.version_string}")
print(f"  Meshes    : {total_meshes}  |  Vertices: {total_verts}")
print(f"  Materiais : {total_mats}  |  Rig: {report.get('rig_bones',0)} ossos")
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
