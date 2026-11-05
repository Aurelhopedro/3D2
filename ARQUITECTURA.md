# ARQUITECTURA DO PIPELINE — 3D2
## Produção Automatizada de Personagens 3D Realistas

> Este documento descreve como o pipeline vai funcionar, que ferramentas usa, porquê cada uma foi escolhida, e como todas comunicam entre si para produzir um personagem de qualidade próxima da profissional — de forma 100% automatizada, sem nenhum ficheiro de asset no repositório.

---

## 1. FILOSOFIA

### Repositório Limpo
O repositório contém **apenas** workflows e scripts de execução.
- Zero assets, zero modelos, zero texturas armazenadas
- Tudo é descarregado no runner durante a execução
- O resultado sai como artefacto do GitHub Actions

### Especialista por Tarefa
Cada programa faz **apenas o que faz melhor**.
- Não usamos um só programa para tudo
- Cada fase tem a ferramenta mais capaz para aquela tarefa específica
- As ferramentas comunicam entre si via ficheiros temporários

### Máximo Poder em Cada Abertura
Quando um programa é aberto, abre **com tudo**:
- Todos os plugins relevantes activados
- Todas as bibliotecas da área descarregadas
- Todos os assets e padrões disponíveis para aquela tarefa
- Algoritmos e extensões que ampliam as capacidades base

### Apenas CC0 — Uso Comercial Livre
**Todos** os assets, texturas, modelos e ferramentas usados produzem resultados que podem ser vendidos ou usados comercialmente sem restrições.

---

## 2. LICENÇAS VERIFICADAS

| Ferramenta / Asset | Licença | Output Vendável |
|---|---|---|
| MakeHuman | Software AGPL, Output **CC0** | ✅ Sim |
| Blender | GPL | ✅ Sim |
| MPFB2 | GPL | ✅ Sim |
| MB-Lab | GPL | ✅ Sim |
| ArmorPaint | zlib/libpng (comercial permitido) | ✅ Sim |
| Polyhaven Textures | **CC0** | ✅ Sim |
| AmbientCG Textures | **CC0** | ✅ Sim |
| Blender Studio Assets | **CC0** | ✅ Sim |
| Blender Human Base Meshes | **CC0** | ✅ Sim |
| Rigify (addon nativo) | GPL | ✅ Sim |

---

## 3. FLUXO COMPLETO DO PIPELINE

```
┌─────────────────────────────────────────┐
│  FASE 1 — CORPO BASE                    │
│  MakeHuman (headless)                   │
│  + Todos os morphs da comunidade        │
│  + Assets de pele, olhos, dentes        │
│  → Exporta: base_human.mhx2 / .obj      │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  FASE 2 — REFINAMENTO ANATÓMICO         │
│  Blender + MPFB2 + MB-Lab               │
│  + Morphs faciais detalhados (52 FACS)  │
│  + Correcção de proporções              │
│  + Subdivisão de mesh para detalhe      │
│  → Exporta: body_refined.blend          │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  FASE 3 — TEXTURIZAÇÃO PBR              │
│  ArmorPaint (compilado de source)       │
│  + Texturas de pele CC0 (Polyhaven)     │
│  + Normal maps de poros (AmbientCG)     │
│  + Pincéis de pele da comunidade        │
│  + Subsurface scattering maps           │
│  → Exporta: skin_albedo.png             │
│             skin_normal.png             │
│             skin_roughness.png          │
│             skin_subsurface.png         │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  FASE 4 — CABELO                        │
│  Blender 4.2 LTS (Hair Curves System)   │
│  + Blender Studio Hair Assets (CC0)     │
│  + Hair Card Generator scripts          │
│  + Alpha maps de fio (CC0)              │
│  + Padrões de crescimento capilar       │
│  + Material PBR de cabelo               │
│  → Exporta: hair.blend                  │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  FASE 5 — VESTUÁRIO                     │
│  Blender (Cloth Simulation)             │
│  + Geometria base de roupa paramétrica  │
│  + Simulação de física de tecido        │
│  + Texturas PBR de tecido (CC0)         │
│  + Presets por tipo (denim, algodão...) │
│  → Exporta: clothing.blend              │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  FASE 6 — RIGGING                       │
│  Blender + Rigify                       │
│  + Metarig humano completo              │
│  + 20+ ossos essenciais                 │
│  + Pesos automáticos avançados          │
│  + Blend shapes faciais (52 FACS)       │
│  + Compatível com glTF/GLB              │
│  → Exporta: rigged_character.blend      │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  FASE 7 — COMPILAÇÃO FINAL              │
│  Blender (orquestrador)                 │
│  + Importa todos os componentes         │
│  + Aplica texturas PBR                  │
│  + Baking quando necessário             │
│  + Iluminação three-point               │
│  + Render de pré-visualização           │
│  + Validação GLB (pygltflib)            │
│  → Exporta: character.glb              │
│             character.blend             │
│             character_preview.png       │
│             character_report.json       │
└─────────────────────────────────────────┘
```

---

## 4. FERRAMENTAS POR FASE — DETALHE

### FASE 1 — MakeHuman (Corpo Base)
**Repositório:** https://github.com/makehumancommunity/makehuman
**Licença output:** CC0 — pode ser vendido sem restrições

**O que descarrega junto:**
- MakeHuman completo (binário headless)
- Plugin `mhx2` para exportação perfeita ao Blender
- Repositório de morphs da comunidade (`makehuman-community-plugins`)
- Assets oficiais: pele, olhos, dentes, unhas, sobrancelhas
- Assets da comunidade CC0: texturas de pele variadas, etnias
- Poses base para posicionamento neutro

**O que faz:**
- Gera corpo humano feminino com morfologia paramétrica
- Aplica proporções anatómicas realistas
- Configura UVs organizados
- Gera esqueleto base para Blender

---

### FASE 2 — Blender + MPFB2 + MB-Lab (Refinamento)
**Repositórios:**
- MPFB2: https://github.com/makehumancommunity/mpfb2
- MB-Lab: https://github.com/animate1978/MB-Lab

**O que descarrega junto:**
- Blender 4.2 LTS (com cache)
- MPFB2 como extensão Blender
- MB-Lab addon completo
- Biblioteca de morphs faciais (52 FACS — Facial Action Coding System)
- Scripts de subdivisão de mesh adaptativa
- Algoritmos de suavização orgânica

**O que faz:**
- Importa o corpo do MakeHuman
- Aplica morphs faciais de alta precisão
- Refina proporções corporais
- Subdivide mesh para detalhe extra
- Corrige topology para animação

---

### FASE 3 — ArmorPaint (Texturização PBR)
**Repositório:** https://github.com/armory3d/armortools
**Licença:** zlib/libpng — uso comercial permitido

**O que descarrega junto:**
- ArmorPaint compilado de source (Linux headless)
- Biblioteca de pincéis de pele da comunidade
- Polyhaven skin textures CC0 (albedo, normal, roughness)
- AmbientCG pore detail maps CC0
- Presets de pele: clara, média, escura, várias etnias
- Scripts de automação de layers

**O que faz:**
- Aplica textura de pele PBR realista ao mesh
- Gera mapas: Albedo, Normal, Roughness, Metallic, Subsurface
- Poros, imperfeições subtis, variação de tom
- Lábios, olhos, sobrancelhas — cada área tratada separadamente

---

### FASE 4 — Blender Hair System (Cabelo)
**Assets:** https://www.blender.org/download/demo-files/ (CC0)

**O que descarrega junto:**
- Blender 4.2 LTS (já em cache)
- Blender Studio Hair Assets (CC0 oficial)
- Human Base Meshes v1.2 (CC0 — Blender Studio)
- Scripts de Hair Card Generator
- Alpha maps de fio de cabelo (CC0)
- Texturas de cabelo: cor, especular, normal
- Padrões de crescimento: liso, ondulado, encaracolado
- Biblioteca de estilos base

**O que faz:**
- Usa o novo sistema de Hair Curves do Blender 4.x
- Coloca cabelo com física de queda realista
- Gera hair cards compatíveis com GLB export
- Aplica material PBR de cabelo com especular e transmissão

---

### FASE 5 — Blender Cloth (Vestuário)
**O que descarrega junto:**
- Scripts de geometria paramétrica de roupa
- Texturas PBR de tecido CC0 (Polyhaven, AmbientCG)
- Presets de física por material (denim, algodão, seda, couro)
- Padrões base de peças: calças, top, saia, casaco

**O que faz:**
- Gera geometria base de cada peça de roupa
- Simula física de tecido para ajuste ao corpo
- Aplica texturas PBR realistas
- Adiciona detalhes: costuras, dobras, pregas

---

### FASE 6 — Blender + Rigify (Esqueleto)
**O que descarrega junto:**
- Rigify (addon nativo — activado por script)
- Metarig humano completo
- Scripts de transfer de pesos avançado
- Configuração de blend shapes faciais
- Scripts de exportação glTF compatível

**O que faz:**
- Cria armadura com 20+ ossos essenciais
- Calcula pesos de deformação automáticos
- Adiciona 52 blend shapes faciais (FACS)
- Garante compatibilidade total com GLB/glTF

---

### FASE 7 — Blender Final (Compilação)
**O que faz:**
- Importa e une todos os componentes
- Aplica todas as texturas PBR
- Executa baking quando necessário
- Configura iluminação three-point cinematográfica
- Render de pré-visualização 1024×1024
- Validação GLB com pygltflib
- Gera relatório detalhado de cada fase

---

## 5. REGRAS DE IMPLEMENTAÇÃO

### Cache Inteligente
Cada ferramenta e cada conjunto de assets tem o seu próprio cache no GitHub Actions, identificado por versão fixa. Na segunda execução, o tempo cai de ~30 min para ~10 min.

### Fallback por Fase
Se uma fase falhar, o workflow não para — activa o fallback dessa fase e continua. O relatório final indica quais fases usaram fallback.

### Passagem de Dados Entre Fases
```
Fase 1 → gera → /tmp/makehuman/base_human.obj
Fase 2 → lê   → /tmp/makehuman/base_human.obj
        → gera → /tmp/blender/body_refined.blend
Fase 3 → lê   → /tmp/blender/body_refined.blend
        → gera → /tmp/textures/*.png
...e assim sucessivamente
```

### Zero Ficheiros no Repositório
O repositório **nunca** armazena:
- Modelos 3D
- Texturas
- Assets de cabelo ou roupa
- Binários de ferramentas

Tudo é descarregado, usado e descartado no runner.

---

## 6. ARTEFACTOS FINAIS

Cada execução produz como artefacto para download:

| Ficheiro | Descrição |
|---|---|
| `character.glb` | Modelo completo — corpo, cabelo, roupa, rig, texturas |
| `character.blend` | Ficheiro Blender de origem |
| `character_preview.png` | Render de pré-visualização |
| `character_report.json` | Relatório detalhado de cada fase |

---

## 7. O QUE ESTE PIPELINE REPRESENTA

Este pipeline não substitui um artista 3D manual — mas aproxima-se do resultado de forma automatizada, usando:

- O melhor gerador de corpo humano open source (MakeHuman)
- O melhor sistema de cabelo disponível gratuitamente (Blender 4.x Hair)
- A alternativa open source mais capaz ao Substance Painter (ArmorPaint)
- Texturas CC0 de qualidade profissional (Polyhaven, AmbientCG)
- O sistema de rigging mais completo open source (Rigify)
- A filosofia de especialista por tarefa usada pelos estúdios profissionais

> *Cada programa faz o que sabe fazer melhor. O resultado é maior que a soma das partes.*
