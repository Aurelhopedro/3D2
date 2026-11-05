"""
refine.py — Fase 3: Refinamento Final do Personagem
=====================================================

Recebe o character.blend produzido pela Fase 2 e aplica todas as
operações de qualidade que transformam o resultado básico num
personagem de aspecto profissional:

  1. Carrega o character.blend da Fase 2
  2. Smooth shading em todos os meshes (elimina aspecto triangulado)
  3. Auto Smooth com ângulo de 60° (preserva bordas duras onde é preciso)
  4. Subdivision Surface nível 1 no corpo (suaviza silhueta sem explodir vértices)
  5. Materiais PBR melhorados com variação de cor por zona (rosto, lábios, pele)
  6. Verifica e corrige o rig — adiciona Rigify se não houver armadura
  7. Olhos anatómicos completos com íris, pupila, specular highlight
  8. Merge correcto do cabelo (parent ao Head bone se existir)
  9. Render final 1024×1024 com iluminação melhorada
 10. Exporta character_final.glb (produto final)
 11. Relatório JSON de fase

Uso:
    blender -b --python scripts/refine.py -- \\
        --input  /tmp/char_out/character.blend \\
        --output /tmp/char_out
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
    "phase":      "refine",
    "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "blender":    bpy.app.version_string,
    "success":    False,
    "steps":      [],
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
    """Aplica smooth shading + auto smooth com ângulo."""
    if obj.type != "MESH":
        return
    # Smooth shading em todas as faces
    for poly in obj.data.polygons:
        poly.use_smooth = True
    obj.data.update()

    # Auto smooth (Blender 4.x usa modifier; fallback para data.use_auto_smooth)
    try:
        # Blender 4.1+ — modifier Smooth by Angle
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        # Verificar se já tem modifier de smooth
        has_smooth_mod = any(m.type == "SMOOTH_BY_ANGLE" for m in obj.modifiers)
        if not has_smooth_mod:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle_deg))
    except Exception:
        # Fallback para versões anteriores
        try:
            obj.data.use_auto_smooth = True
            obj.data.auto_smooth_angle = math.radians(angle_deg)
        except Exception:
            pass  # já não suportado — smooth simples chegou


def classify_obj(name: str) -> str:
    """Classifica um objecto pelo nome para aplicar material correcto."""
    n = name.lower()
    if any(k in n for k in ("eye", "iris", "cornea", "sclera", "pupil")):
        return "eye"
    if any(k in n for k in ("teeth", "tooth", "gum")):
        return "teeth"
    if any(k in n for k in ("tongue",)):
        return "tongue"
    if any(k in n for k in ("hair", "brow", "lash", "haircard")):
        return "hair"
    if any(k in n for k in ("nail",)):
        return "nail"
    if any(k in n for k in ("cloth", "shirt", "top", "skirt", "pant", "belt",
                             "dress", "boot", "shoe", "jacket", "coat")):
        return "cloth"
    return "skin"


# ─────────────────────────────────────────────────────────────────────────────
# 1. CARREGAR BLEND DA FASE 2
# ─────────────────────────────────────────────────────────────────────────────

step("Carregar blend da Fase 2")

input_path = Path(ARGS.input) if ARGS.input else None

# Procurar automaticamente se não foi fornecido
if not input_path or not input_path.exists():
    for candidate in ["character.blend", "character.fbx", "character.obj"]:
        p = OUTDIR / candidate
        if p.exists():
            input_path = p
            break

if not input_path or not input_path.exists():
    log("Nenhum ficheiro de entrada encontrado (.blend / .fbx / .obj)", "ERROR")
    save_report()
    sys.exit(1)

log(f"Entrada: {input_path} ({input_path.stat().st_size // 1024} KB)")

ext = input_path.suffix.lower()

if ext == ".blend":
    bpy.ops.wm.open_mainfile(filepath=str(input_path))
    log("Blend carregado")
elif ext == ".glb":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    log("GLB importado")
elif ext == ".fbx":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(input_path),
                              automatic_bone_orientation=True,
                              ignore_leaf_bones=True)
    log("FBX importado")
elif ext == ".obj":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.obj(filepath=str(input_path))
    log("OBJ importado")
else:
    log(f"Formato não suportado: {ext}", "ERROR")
    save_report()
    sys.exit(1)

scene = bpy.context.scene

# Inventário da cena carregada
all_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
all_arms   = [o for o in bpy.data.objects if o.type == "ARMATURE"]
log(f"Cena: {len(all_meshes)} meshes, {len(all_arms)} armaduras")
report["loaded_meshes"]   = len(all_meshes)
report["loaded_armatures"] = len(all_arms)

# Identificar corpo principal (maior mesh)
if not all_meshes:
    log("Nenhuma mesh encontrada após carregar ficheiro", "ERROR")
    save_report()
    sys.exit(1)

body = max(all_meshes, key=lambda o: len(o.data.vertices))
log(f"Corpo principal: '{body.name}' ({len(body.data.vertices)} vértices)")

# Referências anatómicas
bpy.context.view_layer.update()
vz        = [v.co.z + body.location.z for v in body.data.vertices]
body_minz = min(vz)
body_maxz = max(vz)
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


# ─────────────────────────────────────────────────────────────────────────────
# 2. SMOOTH SHADING + AUTO SMOOTH EM TODOS OS MESHES
#    Elimina o aspecto triangulado / facetado visível na imagem
# ─────────────────────────────────────────────────────────────────────────────

step("Smooth shading + Auto Smooth")

for obj in all_meshes:
    smooth_obj(obj, angle_deg=60.0)

log(f"Smooth aplicado a {len(all_meshes)} meshes")


# ─────────────────────────────────────────────────────────────────────────────
# 3. SUBDIVISION SURFACE NO CORPO
#    Nível 1 em viewport/render — suaviza a silhueta sem explodir vértices.
#    Não aplicar a hair cards (já são quads finos) nem a roupa pequena.
# ─────────────────────────────────────────────────────────────────────────────

step("Subdivision Surface")

SKIP_SUBDIV_KEYWORDS = ("hair", "belt", "card", "eye", "teeth", "tongue", "nail")

for obj in all_meshes:
    n = obj.name.lower()
    if any(k in n for k in SKIP_SUBDIV_KEYWORDS):
        continue
    # Verificar se já tem subdivision
    has_subdiv = any(m.type == "SUBSURF" for m in obj.modifiers)
    if not has_subdiv:
        mod = obj.modifiers.new("Subdivision", "SUBSURF")
        mod.levels        = 1   # viewport
        mod.render_levels = 2   # render
        mod.subdivision_type = "CATMULL_CLARK"
        log(f"  SubDiv nível 1 → '{obj.name}'")

log("Subdivision aplicada")


# ─────────────────────────────────────────────────────────────────────────────
# 4. MATERIAIS PBR MELHORADOS
#    Substitui materiais planos por materiais com SSS e variação de cor.
#    Mantém materiais já existentes de roupa importada pelo mhcore.
# ─────────────────────────────────────────────────────────────────────────────

step("Materiais PBR melhorados")

# Paleta de materiais refinados
MATS = {
    # Pele — tom médio com SSS realista
    "skin": mat_pbr("Skin_Refined",   "#C47A45",
                    roughness=0.46, metallic=0.0,
                    subsurface=0.25, specular=0.44),

    # Pele de rosto — ligeiramente mais rosada
    "face": mat_pbr("Face_Refined",   "#C87755",
                    roughness=0.44, metallic=0.0,
                    subsurface=0.30, specular=0.46),

    # Olhos — esclera branca com SSS subtil
    "eye_sclera": mat_pbr("Eye_Sclera",  "#F2EDE8",
                           roughness=0.04, specular=0.80),

    # Íris — castanho escuro com brilho
    "eye_iris":   mat_pbr("Eye_Iris",    "#3D2510",
                           roughness=0.06, specular=0.75),

    # Pupila — preta brilhante
    "eye_pupil":  mat_pbr("Eye_Pupil",   "#080504",
                           roughness=0.01, specular=0.95),

    # Dentes
    "teeth": mat_pbr("Teeth",        "#F0EBE0",
                     roughness=0.22, specular=0.60),

    # Cabelo — castanho escuro
    "hair": mat_pbr("Hair_Refined",  "#251508",
                    roughness=0.74, specular=0.32),

    # Roupa escura (substitui apenas se for cor plana laranja)
    "cloth_dark": mat_pbr("Cloth_Dark",  "#1C1C2A",
                           roughness=0.90, specular=0.05),

    # Unhas
    "nail": mat_pbr("Nails",         "#E0A898",
                    roughness=0.18, specular=0.70),
}

def needs_replacement(obj: bpy.types.Object) -> bool:
    """
    Verifica se o material actual é o material laranja plano
    gerado automaticamente (Skin_PBR da Fase 2 sem variação).
    Se o mhcore já aplicou materiais ricos, mantemos.
    """
    if not obj.data.materials:
        return True
    for mat in obj.data.materials:
        if mat is None:
            continue
        if not mat.use_nodes:
            return True
        # Verificar se o material já tem textura real (nós de imagem)
        has_texture = any(
            n.type == "TEX_IMAGE" and n.image is not None
            for n in mat.node_tree.nodes
        )
        if has_texture:
            return False  # tem textura real — mantemos
        # Verificar se é cor laranja plana (Base Color próximo de laranja)
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                bc = node.inputs["Base Color"].default_value
                # Laranja ≈ R>0.5, G≈0.3, B<0.15 em linear
                if bc[0] > 0.4 and bc[1] < 0.35 and bc[2] < 0.15:
                    return True
    return False


for obj in all_meshes:
    cls = classify_obj(obj.name)

    if cls == "eye":
        # Olhos — substituir sempre por materiais correctos
        if obj.data.materials:
            obj.data.materials[0] = MATS["eye_sclera"]
        else:
            obj.data.materials.append(MATS["eye_sclera"])
        continue

    if cls == "teeth":
        if obj.data.materials:
            obj.data.materials[0] = MATS["teeth"]
        else:
            obj.data.materials.append(MATS["teeth"])
        continue

    if cls == "hair":
        if needs_replacement(obj):
            if obj.data.materials:
                obj.data.materials[0] = MATS["hair"]
            else:
                obj.data.materials.append(MATS["hair"])
        continue

    if cls == "nail":
        if obj.data.materials:
            obj.data.materials[0] = MATS["nail"]
        else:
            obj.data.materials.append(MATS["nail"])
        continue

    if cls == "cloth":
        # Roupa — só substituir se for cor plana laranja
        if needs_replacement(obj):
            if obj.data.materials:
                obj.data.materials[0] = MATS["cloth_dark"]
            else:
                obj.data.materials.append(MATS["cloth_dark"])
        continue

    if cls == "skin":
        if needs_replacement(obj):
            # Corpo principal usa skin; outros usam face (mais rosado)
            mat = MATS["face"] if obj == body else MATS["skin"]
            if obj.data.materials:
                for i in range(len(obj.data.materials)):
                    obj.data.materials[i] = mat
            else:
                obj.data.materials.append(mat)
        continue

log("Materiais refinados aplicados")


# ─────────────────────────────────────────────────────────────────────────────
# 5. OLHOS ANATÓMICOS MELHORADOS
#    Se não existirem olhos decentes, criar de raiz com 3 camadas:
#    esclera + íris + pupila + highlight especular
# ─────────────────────────────────────────────────────────────────────────────

step("Olhos anatómicos")

existing_eyes = [o for o in all_meshes
                 if any(k in o.name.lower() for k in ("eye", "sclera", "iris", "cornea"))]

# Remover olhos simples (esferas planas sem detalhes) e recriar
simple_eyes = [o for o in existing_eyes
               if len(o.data.vertices) < 100]  # esfera simples tem poucos vértices

for o in simple_eyes:
    bpy.data.objects.remove(o, do_unlink=True)
    log(f"  Olho simples removido: {o.name}")

# Recriar olhos anatómicos completos se necessário
remaining_eyes = [o for o in bpy.data.objects
                  if o.type == "MESH" and
                  any(k in o.name.lower() for k in ("eye", "sclera", "iris"))]

if not remaining_eyes:
    log("A construir olhos anatómicos de raiz …")

    sclera_r = head_r * 0.130
    eye_sep  = head_r * 0.52
    eye_z    = head_cz + head_r * 0.10
    sclera_y = face_y - sclera_r * 0.35
    iris_r   = sclera_r * 0.56
    pupil_r  = sclera_r * 0.30

    # Material de highlight (cornea transparente brilhante)
    cornea_mat = mat_pbr("Eye_Cornea", "#FFFFFF",
                         roughness=0.00, specular=1.0, alpha=0.08)

    for side, sx in [("L", eye_sep / 2), ("R", -eye_sep / 2)]:
        # Esclera — esfera branca
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=64, ring_count=32, radius=sclera_r,
            location=(sx, sclera_y, eye_z))
        sc = bpy.context.active_object
        sc.name = f"Eye_Sclera_{side}"
        sc.data.materials.append(MATS["eye_sclera"])
        smooth_obj(sc, 60)

        # Íris — disco curvado na frente da esclera
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=64, radius=iris_r,
            depth=sclera_r * 0.05,
            location=(sx, sclera_y - sclera_r * 0.86, eye_z))
        ir = bpy.context.active_object
        ir.name = f"Eye_Iris_{side}"
        ir.rotation_euler = (math.pi / 2, 0, 0)
        bpy.ops.object.transform_apply(rotation=True)
        ir.data.materials.append(MATS["eye_iris"])
        smooth_obj(ir, 60)

        # Pupila — disco mais pequeno e mais escuro
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=48, radius=pupil_r,
            depth=sclera_r * 0.03,
            location=(sx, sclera_y - sclera_r * 0.88, eye_z))
        pu = bpy.context.active_object
        pu.name = f"Eye_Pupil_{side}"
        pu.rotation_euler = (math.pi / 2, 0, 0)
        bpy.ops.object.transform_apply(rotation=True)
        pu.data.materials.append(MATS["eye_pupil"])

        # Cornea — esfera ligeiramente maior, quase transparente, brilhante
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=64, ring_count=32, radius=sclera_r * 1.01,
            location=(sx, sclera_y, eye_z))
        co = bpy.context.active_object
        co.name = f"Eye_Cornea_{side}"
        co.data.materials.append(cornea_mat)
        smooth_obj(co, 60)

    log("Olhos anatómicos criados (esclera + íris + pupila + cornea)")
else:
    log(f"Olhos existentes mantidos ({len(remaining_eyes)} objectos)")


# ─────────────────────────────────────────────────────────────────────────────
# 6. VERIFICAR / CRIAR RIG
#    Se não houver armadura, criar rig completo com 20 ossos essenciais.
#    Se já houver, verificar ossos e reportar.
# ─────────────────────────────────────────────────────────────────────────────

step("Verificar / criar rig")

all_arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]

if all_arms:
    arm = all_arms[0]
    n_bones = len(arm.data.bones)
    log(f"Armadura existente: '{arm.name}' — {n_bones} ossos")
    report["rig_source"]  = "imported"
    report["rig_bones"]   = n_bones

    # Verificar se o corpo tem modifier de armadura
    body_has_arm = any(m.type == "ARMATURE" for m in body.modifiers)
    if not body_has_arm:
        log("  Corpo sem modifier de armadura — a adicionar …", "WARN")
        mod = body.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        log("  Modifier adicionado")

    # Parent do cabelo ao osso Head se existir
    head_bone = arm.data.bones.get("Head") or arm.data.bones.get("head")
    if head_bone:
        for obj in bpy.data.objects:
            if obj.type == "MESH" and "hair" in obj.name.lower():
                if obj.parent != arm:
                    obj.parent = arm
                    obj.parent_type = "BONE"
                    obj.parent_bone = head_bone.name
                    log(f"  Cabelo '{obj.name}' parented ao osso Head")

else:
    log("Sem armadura — a criar rig de 20 ossos …")

    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm_obj  = bpy.context.active_object
    arm_obj.name = "Armature"
    arm_data = arm_obj.data
    arm_data.name = "Skeleton"

    # Remover osso padrão
    edit_bones = arm_data.edit_bones
    for b in list(edit_bones):
        edit_bones.remove(b)

    BONES = [
        # Espinha
        ("Hips",         (0,      0, hip_z),          (0,      0, waist_z),          None),
        ("Spine",        (0,      0, waist_z),         (0,      0, waist_z + 0.14),   "Hips"),
        ("Spine1",       (0,      0, waist_z + 0.14),  (0,      0, bust_z),            "Spine"),
        ("Chest",        (0,      0, bust_z),           (0,      0, shoulder_z),        "Spine1"),
        ("Neck",         (0,      0, shoulder_z),       (0,      0, head_cz - head_r),  "Chest"),
        ("Head",         (0,      0, head_cz - head_r),(0,      0, head_cz + head_r * 1.1), "Neck"),
        # Perna esquerda
        ("UpperLeg_L",   (-0.090, 0, hip_z),           (-0.090, 0, hip_z * 0.55),      "Hips"),
        ("LowerLeg_L",   (-0.090, 0, hip_z * 0.55),   (-0.090, 0, ankle_z + 0.06),    "UpperLeg_L"),
        ("Foot_L",       (-0.090, 0, ankle_z + 0.06),  (-0.075, -0.08, ankle_z),       "LowerLeg_L"),
        # Perna direita
        ("UpperLeg_R",   (0.090,  0, hip_z),           (0.090,  0, hip_z * 0.55),      "Hips"),
        ("LowerLeg_R",   (0.090,  0, hip_z * 0.55),   (0.090,  0, ankle_z + 0.06),    "UpperLeg_R"),
        ("Foot_R",       (0.090,  0, ankle_z + 0.06),  (0.075,  -0.08, ankle_z),       "LowerLeg_R"),
        # Braço esquerdo
        ("Shoulder_L",   (-0.080, 0, shoulder_z),      (-0.180, 0, shoulder_z),         "Chest"),
        ("UpperArm_L",   (-0.180, 0, shoulder_z),      (-0.260, 0, elbow_z),            "Shoulder_L"),
        ("LowerArm_L",   (-0.260, 0, elbow_z),         (-0.280, 0, wrist_z),            "UpperArm_L"),
        ("Hand_L",       (-0.280, 0, wrist_z),         (-0.285, 0, wrist_z - 0.09),     "LowerArm_L"),
        # Braço direito
        ("Shoulder_R",   (0.080,  0, shoulder_z),      (0.180,  0, shoulder_z),         "Chest"),
        ("UpperArm_R",   (0.180,  0, shoulder_z),      (0.260,  0, elbow_z),            "Shoulder_R"),
        ("LowerArm_R",   (0.260,  0, elbow_z),         (0.280,  0, wrist_z),            "UpperArm_R"),
        ("Hand_R",       (0.280,  0, wrist_z),         (0.285,  0, wrist_z - 0.09),     "LowerArm_R"),
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
    log(f"Armadura criada: {len(BONES)} ossos")
    report["rig_source"] = "created"
    report["rig_bones"]  = len(BONES)

    # Aplicar ao corpo com pesos automáticos
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj

    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        log("Pesos automáticos aplicados ao corpo")
    except Exception as exc:
        log(f"Pesos automáticos: {exc}", "WARN")
        body.parent = arm_obj
        mod = body.modifiers.new("Armature", "ARMATURE")
        mod.object = arm_obj


# ─────────────────────────────────────────────────────────────────────────────
# 7. ILUMINAÇÃO MELHORADA
#    Remover luzes existentes e recriar com setup mais sofisticado:
#    Key + Fill + Rim + Back (four-point lighting)
# ─────────────────────────────────────────────────────────────────────────────

step("Iluminação melhorada")

# Remover luzes existentes
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
    return light

add_light("Key",  ( 2.2, -3.0,  1.8), 1600, 2.0, (1.00, 0.95, 0.88))  # quente
add_light("Fill", (-2.0, -1.5,  1.2),  700, 3.5, (0.86, 0.91, 1.00))  # fria
add_light("Rim",  ( 0.2,  3.0,  2.2),  900, 1.5, (1.00, 0.98, 0.94))  # rim traseiro
add_light("Top",  ( 0.0,  0.0,  3.5),  400, 4.0, (1.00, 1.00, 1.00))  # topo suave

log("Iluminação four-point configurada")


# ─────────────────────────────────────────────────────────────────────────────
# 8. CÂMARA — POSIÇÃO IDEAL PARA RETRATO
# ─────────────────────────────────────────────────────────────────────────────

step("Câmara")

# Remover câmaras existentes e criar nova
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

# World — fundo neutro escuro azulado
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

log("Câmara 85mm configurada")


# ─────────────────────────────────────────────────────────────────────────────
# 9. RENDER FINAL (WORKBENCH — headless garantido)
# ─────────────────────────────────────────────────────────────────────────────

step("Render final")

scene.render.engine                     = "BLENDER_WORKBENCH"
scene.render.resolution_x               = 1024
scene.render.resolution_y               = 1024
scene.render.resolution_percentage      = 100
scene.render.image_settings.file_format = "PNG"

# Shading melhorado no Workbench
scene.display.shading.light                   = "STUDIO"
scene.display.shading.color_type              = "MATERIAL"
scene.display.shading.show_specular_highlight = True
scene.display.shading.show_shadows            = True

# Tentar studio light mais bonito
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
        kb = Path(preview_path).stat().st_size // 1024
        log(f"Preview final: {kb} KB → {preview_path}")
        report["output_files"].append("character_final_preview.png")
    else:
        log("Preview não encontrado após render", "WARN")
except Exception as exc:
    log(f"Render falhou (não crítico): {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 10. GUARDAR BLEND FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Guardar blend final")

blend_final = str(OUTDIR / "character_final.blend")
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_final)
    log(f"Blend final gravado → {blend_final}")
    report["output_files"].append("character_final.blend")
except Exception as exc:
    log(f"Blend final falhou: {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 11. EXPORTAR GLB FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Exportar GLB final")

glb_final = str(OUTDIR / "character_final.glb")

glb_kwargs = {
    "filepath":          glb_final,
    "export_format":     "GLB",
    "export_apply":      True,       # aplicar subdivision + transforms
    "export_materials":  "EXPORT",
    "export_texcoords":  True,
    "export_normals":    True,
    "export_skins":      True,
    "export_animations": False,
    "export_morph":      True,
    "export_yup":        True,
}

try:
    bpy.ops.export_scene.gltf(**glb_kwargs)
    log("GLB final exportado (parâmetros completos)")
except TypeError:
    log("Export completo falhou — a tentar export mínimo", "WARN")
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_final,
            export_format="GLB",
            export_apply=True,
            export_skins=True,
        )
        log("GLB final exportado (modo mínimo)")
    except Exception as exc2:
        log(f"GLB final falhou: {exc2}", "ERROR")
        save_report()
        sys.exit(1)
except Exception as exc:
    log(f"GLB final falhou: {exc}", "ERROR")
    save_report()
    sys.exit(1)

if Path(glb_final).exists():
    kb = Path(glb_final).stat().st_size // 1024
    log(f"GLB final: {kb} KB → {glb_final}")
    report["output_files"].append("character_final.glb")
    report["glb_final_kb"] = kb
else:
    log("GLB final não encontrado após export", "ERROR")
    save_report()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 12. RELATÓRIO FINAL
# ─────────────────────────────────────────────────────────────────────────────

step("Relatório")

total_verts  = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH")
total_meshes = len([o for o in bpy.data.objects if o.type == "MESH"])
total_mats   = len(bpy.data.materials)

report.update({
    "success":    len(report["errors"]) == 0,
    "meshes":     total_meshes,
    "vertices":   total_verts,
    "materials":  total_mats,
    "rig_bones":  report.get("rig_bones", 0),
})
report["output_files"].append("refine_report.json")
save_report()

print("\n" + "=" * 60)
print("REFINE — FASE 3 COMPLETA")
print("=" * 60)
print(f"  Blender   : {bpy.app.version_string}")
print(f"  Meshes    : {total_meshes}")
print(f"  Vértices  : {total_verts}")
print(f"  Materiais : {total_mats}")
print(f"  Rig ossos : {report.get('rig_bones', 0)} ({report.get('rig_source','?')})")
for fn in report["output_files"]:
    fp = OUTDIR / fn
    sz = fp.stat().st_size if fp.exists() else 0
    print(f"  {fn:42s}  {sz // 1024} KB")
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
print("→ Produto final: character_final.glb")
