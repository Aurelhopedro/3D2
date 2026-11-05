# 3D2 — Produção Automatizada de Personagens 3D Realistas

> Pipeline GitHub Actions para geração de personagens humanos tridimensionais de qualidade profissional, utilizando Blender como motor principal e ferramentas open-source especializadas.

---

## 1. O Objetivo

Desenvolver um único workflow GitHub Actions capaz de produzir personagens humanos tridimensionais realistas, utilizando o Blender como motor principal e aproveitando o máximo possível das ferramentas open-source disponíveis.

O resultado pretendido é um personagem com:

- Anatomia humana convincente
- Proporções corporais naturais
- Rosto detalhado e expressivo
- Olhos realistas
- Pele com materiais e propriedades visuais adequadas
- Cabelo bem construído
- Mãos e pés anatomicamente convincentes
- Roupas com geometria própria e bom ajuste ao corpo
- Calçado e acessórios quando solicitados
- Topologia adequada à finalidade do modelo
- UVs e texturas organizadas
- Materiais PBR
- Esqueleto e pesos de deformação
- Possibilidade de animação
- Exportação final em GLB/glTF

O objetivo é alcançar qualidade profissional, sem recorrer a personagens básicos de aparência artificial produzidos apenas com esferas, cubos, cilindros e operações primitivas.

---

## 2. Restrição Fundamental do Repositório

Este repositório contém **apenas workflows e scripts de execução**.

- Não é uma aplicação própria
- Não possui uma biblioteca permanente de scripts Python
- Não contém dezenas de ficheiros de configuração desnecessários

O único workflow desta fase é:

```
.github/workflows/character-production.yml
```

Quando a execução começa, o workflow prepara o ambiente, descarrega os projetos externos necessários, instala as dependências, cria temporariamente os scripts de execução no runner e executa o pipeline completo.

Os resultados são disponibilizados através dos **GitHub Actions Artifacts**.

---

## 3. Estrutura do Repositório

```
3D2/
├── .github/
│   └── workflows/
│       └── character-production.yml   ← único workflow
├── scripts/
│   └── generate_character.py          ← script principal Blender
└── README.md
```

---

## 4. Ferramentas Integradas

### A. Geração de Personagens

| Ferramenta | Repositório | Função | Licença |
|---|---|---|---|
| **MPFB2** | [makehumancommunity/mpfb2](https://github.com/makehumancommunity/mpfb2) | Gerador humano paramétrico para Blender 4.2+ | GPLv3 |
| CharMorph | [Upliner/CharMorph](https://github.com/Upliner/CharMorph) | Alternativa com suporte a Rigify e encaixe de roupa | GPLv3 |

O **MPFB2** é o candidato principal. Gera corpos humanos reais com morfologia paramétrica (sexo, idade, peso, proporções faciais) directamente dentro do Blender, sem necessidade de interface gráfica.

### B. Assets de Sistema

Os assets do MakeHuman (pele, olhos, dentes, cabelo) são descarregados separadamente e instalados no MPFB2 durante a execução. A instalação do add-on não garante a presença destes assets — têm de ser obtidos explicitamente.

### C. Cabelo

O cabelo é construído em **cards de geometria** (hair cards) — a única abordagem compatível com exportação GLB/glTF. Os sistemas de partículas de cabelo do Blender não são exportados pelo formato glTF.

### D. Vestuário

O vestuário possui **geometria própria**, separada do corpo. Não é gerado automaticamente pelo gerador de corpo. Cada peça (saia, top, cinto) é construída com anéis paramétricos e pregas subtis.

### E. Rigging

O esqueleto é construído manualmente com **20 ossos essenciais** (espinha, pescoço, cabeça, braços, pernas, pés, mãos) e os pesos de deformação são calculados automaticamente via `ARMATURE_AUTO` do Blender. O rig é compatível com exportação glTF.

### F. Materiais e Texturas

- Materiais **PBR** com nós Principled BSDF
- **Subsurface scattering** para pele realista
- Separação entre qualidade dentro do Blender e o que o formato GLB consegue representar
- Baking executado quando necessário para garantir compatibilidade

---

## 5. Pipeline Completo

### Etapa 1 — Preparação
- Instalar dependências headless do Blender no runner Ubuntu
- Descarregar Blender 4.2.9 LTS (com cache)
- Clonar e instalar o MPFB2 como extensão Blender
- Descarregar os system assets do MakeHuman (com cache)
- Instalar `pygltflib` para validação

### Etapa 2 — Geração Anatómica (MPFB2)
- Ativar a extensão MPFB2 via API Blender
- Criar humano feminino com `HumanService.create_human()`
- Aplicar morfologias: sexo, idade, peso, proporções faciais e corporais
- Aplicar assets de sistema: olhos, pele

### Etapa 3 — Fallback Anatómico
- Activado apenas se o MPFB2 falhar
- Mesh de alta resolução com 32+ segmentos por secção
- Curvas orgânicas com perturbação natural
- Mãos e pés proporcionais

### Etapa 4 — Materiais
- Material de pele PBR com subsurface scattering
- Materiais de roupa, cabelo e acessórios

### Etapa 5 — Cabelo
- 48 cards de geometria distribuídos pelo couro cabeludo
- Comprimento e queda diferenciados (franja vs comprido)
- Compatível com exportação GLB

### Etapa 6 — Vestuário
- Saia midi com 48 segmentos e pregas subtis
- Top strapless ajustado ao busto
- Cinto de detalhe na cintura
- Geometria própria, separada do corpo

### Etapa 7 — Rigging
- Armadura com 20 ossos
- Pesos automáticos aplicados ao corpo
- Compatível com glTF/GLB

### Etapa 8 — Iluminação
- Sistema three-point cinematográfico
- Key light quente (1400W), fill light fria (600W), rim light (800W)

### Etapa 9 — Render
- Motor WORKBENCH (garantido em headless, sem GPU)
- Resolução 1024×1024 PNG
- Sombreamento de material com especular

### Etapa 10 — Exportação
- Ficheiro `.blend` de origem
- Exportação GLB com geometria, materiais, esqueleto, pesos e morph targets

### Etapa 11 — Validação
- Validação do GLB com `pygltflib`
- Relatório com contagem de meshes, materiais, texturas, nós, skins e animações

### Etapa 12 — Artefactos
- `character_preview.png` — imagem de pré-visualização
- `character.blend` — ficheiro Blender de origem
- `character.glb` — modelo exportado
- `character_report.json` — relatório de execução

---

## 6. Modalidades de Geração

### Modalidade A — Geração do Zero
O workflow gera a base humana através do MPFB2 e executa todas as etapas de refinamento, vestuário, cabelo, materiais, rigging e exportação.

### Modalidade B — Aperfeiçoamento de Malha Existente
Quando for fornecido um modelo de origem, o sistema pode importá-lo e executar as operações compatíveis, preservando o original e evitando alterações destrutivas.

---

## 7. Qualidade Visual

A qualidade visual é avaliada separadamente em:

| Área | Abordagem |
|---|---|
| Anatomia | MPFB2 HumanService com morfologias paramétricas |
| Rosto | Morfologias faciais MPFB2 |
| Pele | PBR + Subsurface Scattering |
| Olhos | AssetService MPFB2 / olhos anatómicos programáticos |
| Cabelo | 48 cards de geometria |
| Vestuário | Geometria própria com pregas |
| Rigging | 20 ossos + pesos automáticos |
| Exportação | GLB com skins e morph targets |

---

## 8. Limitações Conhecidas

- O runner do GitHub Actions não possui GPU. O render é feito com WORKBENCH (CPU).
- Os shaders procedurais complexos do Blender (como SSS em Cycles) não são preservados na exportação GLB — o baking é necessário para texturas PBR completas.
- O cabelo em partículas não é exportado pelo formato glTF. São usados hair cards.
- A qualidade de um gerador paramétrico é diferente da qualidade de escultura manual ou scans fotogramétricos. O pipeline aproxima-se da qualidade profissional mas não substitui trabalho manual de artista.

---

## 9. Desempenho

O workflow utiliza cache para:
- Blender 4.2.9 LTS (~200 MB)
- Repositório MPFB2
- System assets do MakeHuman

Versões e commits são fixados para garantir reprodutibilidade.

---

## 10. Como Executar

1. Fazer fork ou clone deste repositório
2. Ir a **Actions → Character Production — MPFB2 + Blender 4.2 LTS**
3. Clicar em **Run workflow**
4. Aguardar a execução (~15–30 minutos na primeira vez, menos com cache)
5. Descarregar os artefactos em **Artifacts → character-mpfb2-v1**

---

## 11. Resultado Final

Cada execução produz:

- ✅ Personagem humano tridimensional
- ✅ Corpo anatomicamente convincente
- ✅ Cabelo em cards de geometria
- ✅ Vestuário com geometria própria
- ✅ Materiais PBR
- ✅ Esqueleto com 20 ossos
- ✅ Pesos de deformação
- ✅ Ficheiro GLB
- ✅ Ficheiro BLEND de origem
- ✅ Imagem de pré-visualização
- ✅ Relatório de validação com métricas

---

## 12. Objetivo Final

Criar um processo automatizado que aproveite o trabalho já realizado pela comunidade de desenvolvimento 3D — combinando as melhores ferramentas disponíveis para que o Blender produza personagens de elevada qualidade, com rapidez, precisão e o mínimo possível de intervenção manual.

> *Não reinventar algoritmos que já existem. Combinar as melhores ferramentas disponíveis.*
