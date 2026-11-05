"""
generate.py — Fase 1: Geração de Personagem com makehuman-mcp (mhcore)
========================================================================

Usa a biblioteca Python pura `mhcore` (makehuman-mcp) para construir um
personagem humano feminino completo SEM GUI, SEM OpenGL, SEM Blender.

O que este script faz:
  1. Inicializa o mhcore em modo headless
  2. Cria um humano feminino com proporções paramétricas
  3. Aplica morfologias corporais e faciais (~269 modifiers disponíveis)
  4. Aplica assets: esqueleto, olhos, pele, cabelo, roupa
  5. Exporta FBX (Blender-ready, rig limpo, tamanho real ~1.70m)
  6. Escreve relatório JSON de fase

Uso:
    pip install makehuman-mcp
    python scripts/generate.py --output /tmp/char_out

Saída:
    <output>/character.fbx         — mesh + rig, pronto para o Blender
    <output>/character.mhm         — ficheiro nativo MakeHuman (round-trip)
    <output>/generate_report.json  — estado, morfologias, assets, versões
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# ARGUMENTOS
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gerador de personagem mhcore")
    p.add_argument(
        "--output", "-o",
        default="/tmp/char_out",
        help="Directório de saída (criado se não existir)",
    )
    p.add_argument(
        "--gender",
        default="female",
        choices=["female", "male"],
        help="Género do personagem (default: female)",
    )
    p.add_argument(
        "--age",
        type=float,
        default=0.35,
        help="Idade normalizada 0.0–1.0  (0.0=criança, 0.35≈25a, 1.0=idoso)",
    )
    return p.parse_args()


ARGS   = parse_args()
OUTDIR = Path(ARGS.output)
OUTDIR.mkdir(parents=True, exist_ok=True)

report: dict = {
    "phase":        "generate",
    "start_time":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "success":      False,
    "mhcore_version": "unknown",
    "morphs_applied": [],
    "assets_applied": [],
    "errors":       [],
    "warnings":     [],
    "output_files": [],
}


def log(msg: str, level: str = "INFO") -> None:
    prefix = {"INFO": "✓", "WARN": "⚠", "ERROR": "✗"}.get(level, "·")
    print(f"[{prefix}] {msg}", flush=True)
    if level == "ERROR":
        report["errors"].append(msg)
    elif level == "WARN":
        report["warnings"].append(msg)


def save_report() -> None:
    report["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = OUTDIR / "generate_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Relatório escrito → {path}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. IMPORTAR mhcore
# ─────────────────────────────────────────────────────────────────────────────

log("A importar mhcore …")
try:
    import mhcore  # type: ignore
    ver = getattr(mhcore, "__version__", "desconhecida")
    report["mhcore_version"] = ver
    log(f"mhcore carregado (versão {ver})")
except ImportError as exc:
    log(
        f"mhcore não encontrado: {exc}\n"
        "  → Instala com:  pip install makehuman-mcp",
        "ERROR",
    )
    save_report()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 2. CRIAR HUMANO
# ─────────────────────────────────────────────────────────────────────────────

log("A criar humano …")
h = mhcore.new_human()
log("Humano inicializado")


# ─────────────────────────────────────────────────────────────────────────────
# 3. MACROS CORPORAIS
#    Todos os valores são float 0.0–1.0
#    0.5 = valor médio / neutro para a maioria dos parâmetros
# ─────────────────────────────────────────────────────────────────────────────

log("A aplicar macros corporais …")

gender_val = 1.0 if ARGS.gender == "female" else 0.0

macros = {
    "gender":  gender_val,  # 1.0 = totalmente feminino
    "age":     ARGS.age,    # 0.35 ≈ 25 anos
    "weight":  0.42,        # ligeiramente abaixo do médio
    "muscle":  0.38,        # tom muscular moderado
    "height":  0.62,        # ligeiramente acima do médio
}

(
    h.set_gender(macros["gender"])
     .set_age(macros["age"])
     .set_weight(macros["weight"])
     .set_muscle(macros["muscle"])
     .set_height(macros["height"])
)

for key, val in macros.items():
    log(f"  macro {key:10s} = {val}")
    report["morphs_applied"].append({"type": "macro", "name": key, "value": val})


# ─────────────────────────────────────────────────────────────────────────────
# 4. MODIFIERS DE DETALHE FINO
#    list_modifiers() retorna ~269 nomes disponíveis.
#    apply_modifier(name, power) com power entre -1.0 e 1.0
# ─────────────────────────────────────────────────────────────────────────────

log("A aplicar modifiers de detalhe …")

available_mods: list[str] = h.list_modifiers()
log(f"Modifiers disponíveis: {len(available_mods)}")

# Tabela de modifiers pretendidos com fallbacks alternativos
# Formato: (nome_preferido, [alternativas], valor)
DETAIL_MODIFIERS: list[tuple[str, list[str], float]] = [
    # Rosto
    ("head/head-oval",          ["head/head-round"],          0.35),
    ("head/head-width",         [],                           -0.12),
    ("head/forehead-height",    [],                            0.10),
    ("eyes/eyes-almond",        ["eyes/eyes-normal"],          0.28),
    ("eyes/eyes-width",         [],                            0.08),
    ("nose/nose-straight",      ["nose/nose-curve-down"],      0.20),
    ("nose/nose-width",         [],                           -0.15),
    ("mouth/mouth-width",       [],                            0.05),
    ("mouth/mouth-lips-full",   ["mouth/mouth-lips-upper"],    0.30),
    ("jaw/jaw-width",           [],                           -0.10),
    ("chin/chin-round",         ["chin/chin-width"],           0.18),
    # Corpo feminino
    ("breast/breast-size",      ["torso/breast-size"],         0.58),
    ("breast/breast-firmness",  ["torso/breast-firmness"],     0.45),
    ("pelvis/pelvis-size",      ["hips/hips-size"],            0.40),
    ("hip/hip-waist",           [],                            0.22),
    ("shoulder/shoulder-width", [],                           -0.10),
    ("arm/arm-length",          [],                            0.08),
    ("leg/leg-length",          [],                            0.10),
]

for pref_name, alts, power in DETAIL_MODIFIERS:
    # Tentar o nome preferido primeiro, depois os alternativos
    candidates = [pref_name] + alts
    applied = False
    for candidate in candidates:
        if candidate in available_mods:
            try:
                h.apply_modifier(candidate, power)
                log(f"  modifier {candidate:40s} = {power:+.2f}")
                report["morphs_applied"].append(
                    {"type": "modifier", "name": candidate, "value": power}
                )
                applied = True
                break
            except Exception as exc:
                log(f"  modifier {candidate} falhou: {exc}", "WARN")
    if not applied:
        log(f"  modifier não encontrado: {pref_name}", "WARN")
        report["warnings"].append(f"Modifier não disponível: {pref_name}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. ESQUELETO
#    O rig "default" produz ~163 ossos; FBX exporta apenas os de deformação.
#    Com rig="default" o FBX importa em Blender com rig limpo e skinning.
# ─────────────────────────────────────────────────────────────────────────────

log("A configurar esqueleto …")

try:
    skel_path = mhcore.data_path("rigs/default.mhskel")
    h.set_skeleton(skel_path)
    log(f"Esqueleto: {skel_path}")
    report["assets_applied"].append({"type": "skeleton", "path": str(skel_path)})
except Exception as exc:
    log(f"Esqueleto padrão falhou: {exc}", "WARN")
    # Tentar alternativa sem caminho explícito
    try:
        h.set_skeleton("default")
        log("Esqueleto alternativo aplicado")
        report["assets_applied"].append({"type": "skeleton", "path": "default"})
    except Exception as exc2:
        log(f"Esqueleto alternativo também falhou: {exc2}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 6. ASSETS — OLHOS, PELE, CABELO, ROUPA
#    list_available(kind) retorna lista de caminhos disponíveis.
#    Categorias: clothes, hair, eyes, eyebrows, eyelashes,
#                teeth, tongue, skins, poses, expressions
# ─────────────────────────────────────────────────────────────────────────────

log("A aplicar assets …")

def apply_first(kind: str, equip_fn, label: str) -> bool:
    """Aplica o primeiro asset disponível de uma categoria."""
    try:
        assets = h.list_available(kind)
        if not assets:
            log(f"  {label}: nenhum asset disponível", "WARN")
            report["warnings"].append(f"Sem assets para: {kind}")
            return False
        chosen = assets[0]
        equip_fn(chosen)
        name = Path(str(chosen)).stem
        log(f"  {label:12s} → {name}")
        report["assets_applied"].append({"type": kind, "asset": str(chosen)})
        return True
    except Exception as exc:
        log(f"  {label} falhou: {exc}", "WARN")
        report["warnings"].append(f"Asset {kind} falhou: {exc}")
        return False


apply_first("eyes",       h.equip_eyes,       "olhos")
apply_first("eyebrows",   h.equip_eyebrows,   "sobrancelhas")
apply_first("eyelashes",  h.equip_eyelashes,  "pestanas")
apply_first("teeth",      h.equip_teeth,      "dentes")
apply_first("skins",      h.set_skin,         "pele")
apply_first("hair",       h.equip_hair,       "cabelo")

# Roupa: tentar aplicar top e calças (os primeiros disponíveis)
try:
    clothes = h.list_available("clothes")
    if clothes:
        # Aplicar no máximo 2 peças para não sobrecarregar
        for piece in clothes[:2]:
            try:
                h.equip_clothes(piece)
                name = Path(str(piece)).stem
                log(f"  roupa       → {name}")
                report["assets_applied"].append({"type": "clothes", "asset": str(piece)})
            except Exception as exc:
                log(f"  peça de roupa falhou ({Path(str(piece)).stem}): {exc}", "WARN")
    else:
        log("  roupa: nenhum asset disponível", "WARN")
except Exception as exc:
    log(f"  roupa geral falhou: {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 7. GUARDAR FICHEIRO NATIVO .mhm
#    Guarda todas as morfologias, assets e esqueleto — permite reprodução exata.
# ─────────────────────────────────────────────────────────────────────────────

log("A guardar .mhm …")

mhm_path = str(OUTDIR / "character.mhm")
try:
    h.save_mhm(mhm_path)
    sz = Path(mhm_path).stat().st_size
    log(f"MHM gravado: {sz // 1024} KB → {mhm_path}")
    report["output_files"].append("character.mhm")
except Exception as exc:
    log(f"MHM falhou (não crítico): {exc}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 8. EXPORTAR FBX
#    - Blender-ready por defeito (tamanho real ~1.70m, rig de deformação limpo)
#    - FBX é o formato com melhor fidelidade rig+skinning para Blender
#    - O Blender da Fase 2 importa este FBX e faz o resto
# ─────────────────────────────────────────────────────────────────────────────

log("A exportar FBX …")

fbx_path = str(OUTDIR / "character.fbx")
try:
    # rig="default" = rig de deformação limpo (sem ossos de controlo)
    # scale não passado = escala real em metros (~1.70m)
    h.export(fbx_path, format="fbx")
    sz = Path(fbx_path).stat().st_size
    log(f"FBX exportado: {sz // 1024} KB → {fbx_path}")
    report["output_files"].append("character.fbx")
    report["fbx_kb"] = sz // 1024
except Exception as exc:
    log(f"FBX falhou: {exc}", "ERROR")
    # Tentar OBJ como fallback
    log("A tentar OBJ como fallback …", "WARN")
    obj_path = str(OUTDIR / "character.obj")
    try:
        h.export(obj_path, format="obj")
        sz = Path(obj_path).stat().st_size
        log(f"OBJ exportado (fallback): {sz // 1024} KB → {obj_path}")
        report["output_files"].append("character.obj")
        report["fallback_format"] = "obj"
    except Exception as exc2:
        log(f"OBJ também falhou: {exc2}", "ERROR")
        save_report()
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 9. SUMÁRIO FINAL
# ─────────────────────────────────────────────────────────────────────────────

report["success"] = len(report["errors"]) == 0
report["morphs_total"]  = len(report["morphs_applied"])
report["assets_total"]  = len(report["assets_applied"])

save_report()

print("\n" + "=" * 60)
print("GENERATE — FASE 1 COMPLETA")
print("=" * 60)
print(f"  mhcore    : {report['mhcore_version']}")
print(f"  Género    : {ARGS.gender}")
print(f"  Morfologias aplicadas : {report['morphs_total']}")
print(f"  Assets aplicados      : {report['assets_total']}")
for fn in report["output_files"]:
    fp = OUTDIR / fn
    sz = fp.stat().st_size if fp.exists() else 0
    print(f"  {fn:38s}  {sz // 1024} KB")
if report["warnings"]:
    print(f"\n  Avisos : {len(report['warnings'])}")
    for w in report["warnings"]:
        print(f"    ⚠ {w}")
if report["errors"]:
    print("\n  ERROS:")
    for e in report["errors"]:
        print(f"    ✗ {e}")
    sys.exit(1)

print("=" * 60)
print("→ Fase 2: pipeline.py recebe o FBX e conclui no Blender")
