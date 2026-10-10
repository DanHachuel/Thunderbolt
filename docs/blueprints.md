# Blueprints de Personalidade + Formatos Remotion — Guia

## Dois conceitos separados (0.9.76)

| Conceito | O que define | Onde vive |
|---|---|---|
| **Blueprint de personalidade** | *Quem o canal é* — tom, estilo, vocabulário, referências (MILITAR, FINANCE USA, Cocomelon…) | `storage/blueprints/` (semeado de `seed/blueprints/`) |
| **Formato Remotion** | *O formato do JSON que o LLM deve produzir* para cada composição Remotion | `packages/remotion/schemas/*.schema.json` |

O modo Remotion combina os dois: a personalidade vem do canal (ou do dropdown
da UI) e o formato é escolhido na UI. Os restantes modos (`pexels`,
`text_to_images`, `web_images`, `full_ia`) continuam a usar apenas os
blueprints de personalidade.

## Loader (`hermes_ui/blueprint_loader.py`)

- `list_personality_blueprints()` / `load_personality_blueprint(id)` —
  personalidades; ignora e remove (migração) qualquer ficheiro de formato
  que esteja na biblioteca.
- `list_remotion_formats()` / `load_remotion_format(format_id)` — formatos, lidos
  apenas de `packages/remotion/schemas/`.
- `find_placeholders()` / `render_blueprint_prompt()` — substituição de
  `{{placeholders}}` (ex.: `{{language}}`) em runtime.
- `build_remotion_system_prompt(personality, format_def)` — concatena o
  conteúdo do blueprint de personalidade com os `constraints` e o
  `output_schema` do formato; nada mais.

## Formato de um `*.schema.json`

Campos obrigatórios: `format_id`, `composition_id`, `fps`, `width`, `height`,
`constraints` (regras estruturais), `output_schema`, `reference_example`
(exemplo estrutural, não few-shot de personalidade), `remotion_mapping`.

Não pertencem ao formato: `system_instructions`, `style_guide`,
`generation_instructions`, `domain`, `version` — esses campos pertencem à
personalidade do canal.

## Como adicionar um novo formato

1. Criar `packages/remotion/schemas/<format_id>.schema.json`.
2. Criar a composição em `packages/remotion/src/compositions/<Nome>.tsx`.
3. Registar em `packages/remotion/src/Root.tsx` com `calculateMetadata` que
   espelha exactamente o layout de Sequences do componente.
4. Criar o modelo Pydantic em `hermes_ui/schemas/<formato>.py` e registar no
   `SCHEMAS` de `hermes_ui/schemas/__init__.py` (chave = `format_id`).
5. Adicionar os ramos de extração/injecção em `hermes_ui/blueprint_assets.py`
   (chave = `format_id`).
6. Adicionar testes em `tests/test_blueprint_loader.py` e
   `tests/test_blueprint_assets.py`.

## Validação

Cada formato tem um modelo Pydantic correspondente. Após o LLM devolver o
JSON, o Thunderbolt valida com `SCHEMAS[format_id].model_validate(...)`. Se
falhar, tenta 1x com o erro anexado ao prompt. Se falhar de novo, a tarefa é
marcada como erro.

## Geração de Assets

- **Imagens**: `extract_image_prompts()` encontra todos os prompts; o pool de
  imagem do sistema gera cada uma em paralelo (4 workers); guardadas em
  `storage/tasks/<task_id>/images/`.
- **TTS**: `extract_tts_segments()` encontra todos os textos; gerados em
  série pela cadeia TTS do sistema; guardados em `storage/tasks/<task_id>/audio/`.
- **Injecção**: `inject_assets()` adiciona `imageUrl`/`audioUrl` nas posições
  correctas de cada formato, sem alterar a estrutura original.

## inputProps e duração

Os inputProps para o Remotion são o JSON validado + os paths dos assets
injectados. O `composition_id` do formato determina qual composição renderiza.
O `calculateMetadata` do Remotion é a única fonte de verdade para
`durationInFrames` — o Thunderbolt nunca calcula durações próprias.

## Limitações

- Timeout total: 20 minutos por tarefa.
- Imagens: 4 workers paralelos máximo.
- TTS: série (para preservar ordem e evitar rate limits).
- Se um asset falhar após retries, a tarefa é marcada como erro.

## Preparação para @remotion/lambda

A arquitectura é portável: os formatos, schemas e wrapper não mudam. Apenas
`run_remotion_render()` precisa ser adaptado para chamar a API Lambda em vez
do subprocesso local.
