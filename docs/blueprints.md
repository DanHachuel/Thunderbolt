# Blueprints Remotion — Guia Completo

## O que é um Blueprint

Um blueprint é um ficheiro JSON auto-contido que descreve um formato de vídeo para o pipeline Remotion. Cada blueprint define: as instruções do LLM, o schema do output, o estilo, exemplos de referência e o mapeamento para a composição Remotion.

### Campos obrigatórios
| Campo | Descrição |
|---|---|
| `blueprint_id` | Identificador único (ex: `quiz_videos`) |
| `composition_id` | Composição Remotion (ex: `Quiz`) |
| `fps` | Frames por segundo (30) |
| `width` × `height` | Dimensões (1920×1080 ou 1080×1920) |
| `system_instructions` | Role + task_description + constraints + critical_instruction |
| `output_schema` | Estrutura do JSON que o LLM deve produzir |
| `style_guide` | Tom, ritmo, hook, vocabulário, avoid |
| `reference_examples` | Few-shot completos (pelo menos 1) |
| `generation_instructions` | must_include, must_avoid, success_condition |
| `remotion_mapping` | composition_id, calculate_metadata, assets_pipeline, required_components |

## Como adicionar um novo Blueprint

1. Criar o JSON em `seed/blueprints/` com todos os campos obrigatórios.
2. Criar a composição em `packages/remotion/src/compositions/<Nome>.tsx`.
3. Registar em `packages/remotion/src/Root.tsx` com `calculateMetadata`.
4. Criar o schema Pydantic em `hermes_ui/schemas/<blueprint_id>.py`.
5. Registar no `SCHEMAS` dict em `hermes_ui/schemas/__init__.py`.
6. Adicionar o mapeamento de assets em `hermes_ui/blueprint_assets.py`.
7. Adicionar testes em `tests/test_blueprint_loader.py`.

## Resolução de Placeholders

O Thunderbolt substitui tokens `{{topic}}`, `{{language}}`, `{{difficulty}}` em todos os campos de texto do blueprint via `render_blueprint_prompt()`. Os valores vêm do formulário da UI.

## Validação

Cada blueprint tem um modelo Pydantic correspondente em `hermes_ui/schemas/`. Após o LLM devolver o JSON, o Thunderbolt valida com `SCHEMAS[blueprint_id].model_validate_json()`. Se falhar, tenta 1x com o erro anexado. Se falhar de novo, marca a tarefa como erro.

## Geração de Assets

- **Imagens**: `extract_image_prompts()` encontra todos os prompts; o provider ativo gera cada imagem em paralelo (ThreadPoolExecutor, max 4 workers); guardadas em `storage/tasks/<task_id>/images/`.
- **TTS**: `extract_tts_segments()` encontra todos os textos; gerados em série; guardados em `storage/tasks/<task_id>/audio/`.
- **Injecção**: `inject_assets()` adiciona `imageUrl` e `audioUrl` em cada cena sem alterar a estrutura original.

## inputProps

Os inputProps para o Remotion são o JSON validado do LLM + os paths dos assets injetados. O `composition_id` do blueprint determina qual composição Remotion renderizar.

## calculateMetadata

O Remotion deriva `durationInFrames` a partir dos props via `calculateMetadata`. O Thunderbolt **nunca** pré-calcula durações — usa os campos `durationInSeconds`, `revealDelaySeconds`, `thinkingDelaySeconds` do JSON.

## Limitações

- Timeout total: 20 minutos por tarefa.
- Imagens: 4 workers paralelos máximo.
- TTS: série (para preservar ordem e evitar rate limits).
- Se um asset falhar após retries, a tarefa é marcada como erro.

## Preparação para @remotion/lambda

A arquitectura é portável: os blueprints, schemas e wrapper não mudam. Apenas `run_remotion_render()` precisa ser adaptado para chamar a API Lambda em vez do subprocesso local.
