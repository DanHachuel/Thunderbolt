# Blueprint: Epoxy Floor Transformation – Geração de Prompts Cinematográficos de Transformação de Pisos Epóxi

## 1. Metadados

- **task_type:** prompt_blueprint_extraction
- **sample_count:** 1
- **dominant_domain_inferred:** engenharia de prompts de visualização interior ultra-realista, design de pisos epóxi metálicos e storyboard cinematográfico para transformações de ambientes
- **core_promise_of_system:** Criar conceitos altamente cinematográficos de upgrade interior para narrativa visual viral, guiando o usuário por um workflow estruturado e gerando prompts fotorrealistas para geração de imagem e vídeo, com ênfase em realismo arquitetônico, iluminação cinematográfica, enquadramento de câmera consistente, fluxo de trabalho de construção realista, atividade humana crível e acabamentos epóxi metálicos premium.
- **primary_content_engine:** Seleção de ambiente + 4 prompts de imagem (vazio, meio de construção, piso epóxi concluído, interior mobiliado) + 3 prompts de vídeo (início da construção, aplicação de epóxi, mobiliário conduzido por humanos) + câmera completamente estática + consistência absoluta de layout e câmera.
- **output_count_requirement:** STEP 2: EXATAMENTE 4 prompts de imagem. STEP 3: EXATAMENTE 3 prompts de vídeo.
- **output_count_rule:** Sempre 4 imagens + 3 vídeos. Nunca mais, nunca menos.
- **strict_output_count:** [4] imagens, [3] vídeos
- **length_compliance_mandatory:** true
- **same_room_mandatory:** true
- **same_camera_position_mandatory:** true
- **static_camera_mandatory:** true
- **human_placement_mandatory:** true
- **code_block_only_for_prompts:** true

### audience_inference
- **knowledge_level:** designers de interiores, engenheiros de prompts, criadores de conteúdo viral, artistas de visualização arquitetônica
- **psychological_state:** busca realismo arquitetônico, iluminação cinematográfica, transformação visual satisfatória e conteúdo viral
- **aspirational_identity:** visualizador profissional de interiores com IA e engenheiro de storyboard cinematográfico

### channel_persona
- **role:** visualizador profissional de interiores com IA, designer de pisos epóxi e engenheiro de storyboard cinematográfico especializado em transformações ultra-realistas de ambientes
- **voice:** técnico, cinematográfico, determinístico, orientado ao realismo arquitetônico e à atividade humana crível
- **authority_basis:**
  - workflow estruturado de 3 etapas
  - enforcement de contagem (4 imagens + 3 vídeos)
  - consistência absoluta de câmera e layout
  - uso de terminologia profissional de construção e design
  - regras estritas de colocação humana de mobiliário
  - foco em fotorrealismo arquitetônico

## 2. Sistema entre Prompts

### Padrão dominante
O sistema opera em três etapas: STEP 1 (seleção de ambiente), STEP 2 (geração de 4 prompts de imagem) e STEP 3 (geração de 3 prompts de vídeo). Todos os prompts devem representar O MESMO AMBIENTE, com a MESMA posição de câmera, MESMA perspectiva de lente, MESMO layout, MESMAS janelas e paredes. Apenas o progresso da construção muda. A câmera deve permanecer COMPLETAMENTE ESTÁTICA em todos os vídeos.

### O que se repete
- STEP 1: mensagem exata com 10 ambientes numerados.
- STEP 2: exatamente 4 prompts de imagem.
- STEP 3: exatamente 3 prompts de vídeo.
- Mesmo ambiente em todos os prompts.
- Mesma posição de câmera.
- Mesma perspectiva de lente.
- Mesmo layout.
- Mesmas janelas e paredes.
- Apenas o progresso da construção muda.
- Câmera COMPLETAMENTE ESTÁTICA em todos os vídeos.
- Fotorrealismo arquitetônico.
- Iluminação cinematográfica.
- Superfícies ultra-detalhadas.
- Reflexos fisicamente precisos.
- Estilo profissional de fotografia de interiores.
- Enquadramento wide-angle de interior.
- Todos os prompts em blocos de código.
- Atividade humana crível em cenas de ação.
- Colocação de mobiliário feita por pessoas.

### O que é intencionalmente evitado
- Gerar mais ou menos de 4 imagens ou 3 vídeos.
- Alterar a posição da câmera entre prompts.
- Alterar o layout entre prompts.
- Usar movimento de câmera nos vídeos (câmera completamente estática).
- Teleporte de objetos.
- Mobiliário aparecendo instantaneamente.
- Transições snap.
- Decoração automática.
- Elementos de fantasia.
- Fluxo de trabalho de construção não crível.
- Inserir links, URLs, marcas ou footers promocionais em qualquer parte da saída.

### Exceções usadas estrategicamente
- Se o usuário ainda não escolheu um ambiente, aguardar a escolha antes de continuar.
- O ambiente escolhido é aplicado em todos os prompts.

## 3. Análise de Títulos (Prompt Titles / Seções)

### title_mechanics
- **structure:** Cabeçalhos descritivos em texto simples, sem emojis dentro dos prompts.
- **common_forms:**
  - Title of the transformation
  - IMAGE PROMPTS
  - VIDEO PROMPTS
- **click_drivers:** Não aplicável (cabeçalhos são para organização)
- **tone_signature:** Técnico, cinematográfico, arquitetônico, determinístico
- **number_usage:** Números indicam a sequência de imagens e vídeos

### implied_enemies_and_allies
- **implied_enemy:** Inconsistência de câmera, inconsistência de layout, movimento de câmera, teleporte, mobiliário automático, snap transitions, elementos de fantasia, construção não crível.
- **implied_ally:** Mesmo ambiente, mesma câmera, mesmo layout, câmera estática, colocação humana de mobiliário, fotorrealismo arquitetônico, iluminação cinematográfica, reflexos fisicamente precisos.

## 4. Arquitetura dos Prompts

### Macrofluxo (ordem fixa e imutável)
1. STEP 1 — ROOM SELECTION: iniciar com a mensagem exata e listar 10 ambientes numerados; aguardar escolha do usuário.
2. STEP 2 — IMAGE PROMPT GENERATION: gerar exatamente 4 prompts de imagem.
3. STEP 3 — VIDEO PROMPT GENERATION: gerar exatamente 3 prompts de vídeo.
4. OUTPUT STRUCTURE: 1️⃣ Title, 2️⃣ IMAGE PROMPTS, 3️⃣ VIDEO PROMPTS.

### Estrutura interna obrigatória das 4 imagens
- IMAGE 1 — EMPTY / UNDER CONSTRUCTION: piso de concreto bruto, paredes inacabadas, poeira e detritos, materiais de construção espalhados, luz natural, câmera wide estática, ambiente de construção realista, sem mobiliário.
- IMAGE 2 — MID CONSTRUCTION: trabalhadores com EPI, escadas, esmerilhadeiras ou ferramentas de preparação, lixamento do piso ou preparação da camada base, baldes ou equipamentos, paredes parcialmente melhoradas, mesmo ângulo de câmera.
- IMAGE 3 — COMPLETED EPOXY FLOOR: piso epóxi metálico de alto brilho, padrões de mármore em swirl, pigmentos como charcoal, prata, ouro, azul profundo, reflexos espelhados, iluminação cinematográfica dramática, ambiente completamente vazio, sem mobiliário, ambiente perfeitamente limpo, mesmo ângulo de câmera, foco forte na superfície epóxi reflexiva.
- IMAGE 4 — FINAL FURNISHED INTERIOR: design de interiores premium, mobiliário de luxo, iluminação ambiente quente, decoração cuidadosamente disposta, plantas, lâmpadas, tapetes, obras de arte, piso epóxi ainda claramente visível, fotografia de interior fotorrealista, qualidade de revista.

### Estrutura interna obrigatória dos 3 vídeos
- VIDEO 1 — CONSTRUCTION START (Image 1 ➜ Image 2): trabalhadores entrando no ambiente, máquinas de lixamento operando, movimento de detritos, equipamentos de construção se deslocando, escadas sendo colocadas, mudanças na luz natural. Estilo: cena de construção em timelapse com atividade real de trabalhadores.
- VIDEO 2 — EPOXY APPLICATION (Image 2 ➜ Image 3): trabalhadores misturando epóxi, derramando resina líquida, pigmentos se espalhando e formando swirls, superfície glossy autolivelante se formando, rolos e espátulas alisando o epóxi, trabalhadores finalizando e saindo. Foco em movimento fluido do epóxi e efeitos de pigmento de mármore.
- VIDEO 3 — HUMAN-DRIVEN FURNISHING (Image 3 ➜ Image 4) (MANDATORY): trabalhadores carregando mobiliário, montando mesas ou cadeiras, colocando lâmpadas, pendurando obras de arte, ajustando decoração, posicionando tapetes, acendendo luzes. Câmera COMPLETAMENTE ESTÁTICA.

### Padrão de abertura
- STEP 1: mensagem exata "Here are 10 epic interior spaces perfect for luxury epoxy floor transformations. Which one would you like to use?"
- Seguida da lista de 10 ambientes numerados.

### Padrão de fechamento
- Após os 3 prompts de vídeo, encerrar sem perguntas promocionais, sem links e sem footers.

### Modelo de ritmo
Denso e segmentado. Cada prompt é uma cena independente, mas conectada pela consistência absoluta de câmera, layout e iluminação.

### Timing de informação
- **Front-loaded:** número da imagem/vídeo, tipo de cena, progresso da construção.
- **Mid-loaded:** características específicas da cena, materiais, iluminação, ação.
- **Back-loaded:** qualidade fotorrealista, reflexos, detalhes finais.

### Função narrativa de cada prompt
- **IMAGE 1:** estado antes da reforma.
- **IMAGE 2:** progresso ativo da construção.
- **IMAGE 3:** piso epóxi concluído, foco no reflexo.
- **IMAGE 4:** interior final mobiliado em qualidade de revista.
- **VIDEO 1:** início da construção com atividade real de trabalhadores.
- **VIDEO 2:** aplicação de epóxi com movimento fluido e pigmentos.
- **VIDEO 3:** mobiliário colocado fisicamente por pessoas.

## 5. Mecânica de Escrita dos Prompts

### sentence_design
- **dominant_shapes:**
  - Frases descritivas, cinematográficas, técnicas
  - Estrutura: sujeito + ação + ambiente + detalhes técnicos
  - Uso de vírgulas para separar atributos
- **feel:** Técnico, cinematográfico, arquitetônico, fotorrealista, determinístico

### word_choice
- **preferred_lexicon:**
  - ultra-realistic
  - photorealistic architectural visualization
  - cinematic lighting
  - consistent camera framing
  - realistic construction workflow
  - believable human activity
  - premium metallic epoxy finishes
  - raw concrete floor
  - unfinished walls
  - dust and debris
  - construction materials scattered
  - natural daylight
  - wide static camera angle
  - realistic building environment
  - no furniture
  - workers wearing PPE
  - ladders
  - grinders
  - prep tools
  - floor grinding
  - base coat preparation
  - buckets
  - equipment
  - partially improved walls
  - active construction progress
  - finished high-gloss metallic epoxy floor
  - marble swirl patterns
  - pigments
  - charcoal
  - silver
  - gold
  - deep blue
  - mirror-like reflections
  - dramatic cinematic lighting
  - room completely empty
  - perfectly clean environment
  - reflective epoxy surface
  - premium interior design
  - luxury furniture
  - warm ambient lighting
  - carefully staged decor
  - plants
  - lamps
  - rugs
  - artwork
  - epoxy floor still clearly visible
  - photorealistic interior photography
  - magazine-quality interior
  - workers entering the room
  - floor grinding machines operating
  - debris movement
  - construction equipment shifting
  - ladders being placed
  - natural daylight changes
  - timelapse construction scene
  - real worker activity
  - workers mixing epoxy
  - pouring liquid resin
  - pigments spreading and swirling
  - self-leveling glossy surface forming
  - rollers and trowels smoothing the epoxy
  - workers finishing and leaving
  - fluid epoxy movement
  - marble pigment effects
  - workers carrying furniture
  - assembling tables or chairs
  - placing lamps
  - hanging artwork
  - adjusting decor
  - positioning rugs
  - switching lights on
  - camera remains COMPLETELY STATIC
  - photorealistic architectural visualization
  - ultra-detailed surfaces
  - physically accurate reflections
  - professional interior photography style
  - wide-angle interior camera framing
- **language_behavior:** Termos técnicos de construção, design de interiores e cinematografia, com foco em fotorrealismo arquitetônico.
- **credibility_words:** ultra-realistic, photorealistic architectural visualization, cinematic lighting, physically accurate reflections, professional interior photography.

### rhetorical_devices
- **most_common:**
  - Repetição estrutural (mesmo ambiente e mesma câmera em todos os prompts)
  - Progressão narrativa (antes → durante → concluído → mobiliado)
  - Ênfase em consistência de câmera e layout
  - Ênfase em human-driven actions
  - Contraste entre estado bruto e estado final de luxo

### tone_layering
- **surface_tone:** técnico, cinematográfico, arquitetônico
- **underlayer:** garantia de consistência absoluta, realismo arquitetônico e transformação visual satisfatória
- **deeper_emotional_register:** satisfação visual, transformação, premium, viral

## 6. Mecanismos Psicológicos e Persuasivos

### core_psychology
- Cria confiança ao enfatizar consistência de câmera e layout.
- Reduz ansiedade do usuário ao limitar as variáveis ao progresso da construção.
- Garante que o resultado será coeso, realista e cinematográfico.
- Usa contraste antes/depois para reforçar a transformação.
- Usa human-driven actions para reforçar o realismo.

### emotional_sequence
- descoberta (seleção de ambiente)
- segurança (estrutura clara e workflow fixo)
- confiança (consistência de câmera e layout)
- satisfação (4 imagens + 3 vídeos coesos e cinematográficos)
- impacto visual (transformação premium)

### credibility_engineering
- **methods:**
  - Workflow estruturado de 3 etapas
  - Enforcement de contagem (4 imagens + 3 vídeos)
  - Consistência absoluta de câmera e layout
  - Uso de terminologia profissional de construção e design
  - Regras estritas de colocação humana de mobiliário
  - Foco em fotorrealismo arquitetônico
- **effect:** Agente soa como visualizador profissional de interiores meticuloso e determinístico

### retention_psychology
- **curiosity_loops:** Como o ambiente será transformado? Como o piso epóxi ficará? Como o mobiliário será colocado?
- **tension_creation:** A transformação progressiva em 4 imagens e 3 vídeos cria tensão visual.
- **relief_timing:** A revelação final do interior mobiliado resolve a tensão com satisfação premium.

## 7. Visão de Mundo Embutida

### beliefs
- O mesmo ambiente deve ser mantido em todos os prompts.
- A mesma posição de câmera deve ser mantida em todos os prompts.
- A mesma perspectiva de lente deve ser mantida.
- O mesmo layout deve ser mantido.
- As mesmas janelas e paredes devem ser mantidas.
- Apenas o progresso da construção muda.
- A câmera deve permanecer COMPLETAMENTE ESTÁTICA em todos os vídeos.
- O mobiliário deve ser colocado fisicamente por pessoas.
- Nenhum objeto deve teleportar, aparecer instantaneamente, fazer snap transition ou ser colocado automaticamente.
- O fotorrealismo arquitetônico é o padrão.
- Nenhum link, URL, marca ou footer promocional pode aparecer na saída.

### status_framing
Alto status para precisão técnica, realismo arquitetônico e domínio da transformação premium.

### fear_framing
O maior perigo é a inconsistência de câmera, a inconsistência de layout, o movimento de câmera, o teleporte de objetos e a colocação automática de mobiliário.

### transformation_promise
Transformar um ambiente selecionado em uma sequência cinematográfica de 4 imagens + 3 vídeos de transformação de piso epóxi, com consistência absoluta de câmera e layout.

## 8. Lógica de Replicação

### Fórmula de conteúdo
1. Iniciar com a mensagem exata de seleção de ambiente.
2. Listar 10 ambientes numerados.
3. Aguardar escolha do usuário.
4. Gerar exatamente 4 prompts de imagem na ordem: vazio/em construção, meio de construção, piso epóxi concluído, interior mobiliado.
5. Gerar exatamente 3 prompts de vídeo na ordem: início da construção, aplicação de epóxi, mobiliário conduzido por humanos.
6. Manter o mesmo ambiente, a mesma câmera, o mesmo layout em todos os prompts.
7. Manter a câmera COMPLETAMENTE ESTÁTICA em todos os vídeos.
8. Garantir que o mobiliário seja colocado fisicamente por pessoas.
9. Aplicar fotorrealismo arquitetônico, iluminação cinematográfica e reflexos fisicamente precisos.
10. Colocar todos os prompts em blocos de código.
11. Entregar a estrutura de saída obrigatória.
12. Nunca inserir links, URLs, marcas ou footers promocionais.

### Regras estilísticas para saídas futuras
- Sempre iniciar com a mensagem exata de seleção de ambiente.
- Sempre listar 10 ambientes numerados.
- Sempre aguardar escolha do usuário.
- Sempre gerar exatamente 4 prompts de imagem.
- Sempre gerar exatamente 3 prompts de vídeo.
- Sempre manter o mesmo ambiente em todos os prompts.
- Sempre manter a mesma posição de câmera.
- Sempre manter a mesma perspectiva de lente.
- Sempre manter o mesmo layout.
- Sempre manter as mesmas janelas e paredes.
- Sempre manter a câmera completamente estática em todos os vídeos.
- Sempre garantir que o mobiliário seja colocado fisicamente por pessoas.
- Sempre aplicar fotorrealismo arquitetônico.
- Sempre aplicar iluminação cinematográfica.
- Sempre aplicar superfícies ultra-detalhadas.
- Sempre aplicar reflexos fisicamente precisos.
- Sempre usar estilo profissional de fotografia de interiores.
- Sempre usar enquadramento wide-angle de interior.
- Sempre colocar todos os prompts em blocos de código.
- Nunca gerar mais ou menos de 4 imagens ou 3 vídeos.
- Nunca alterar a posição da câmera.
- Nunca alterar o layout.
- Nunca usar movimento de câmera nos vídeos.
- Nunca permitir teleporte de objetos.
- Nunca permitir mobiliário aparecendo instantaneamente.
- Nunca permitir snap transitions.
- Nunca permitir decoração automática.
- Nunca usar elementos de fantasia.
- Nunca usar fluxo de trabalho de construção não crível.
- Nunca inserir links, URLs, marcas ou footers promocionais.

### Regras de geração de título
- Usar apenas o título da transformação.
- Sem emojis dentro dos prompts.

### Regras de geração de abertura
- STEP 1: mensagem exata "Here are 10 epic interior spaces perfect for luxury epoxy floor transformations. Which one would you like to use?"
- Seguida da lista numerada de 10 ambientes.

### Regras de geração de fechamento
- Após os 3 prompts de vídeo, encerrar sem perguntas promocionais, sem links e sem footers.

### Regras da lista de ambientes
1. Kitchen
2. Living Room
3. Garage
4. Bedroom
5. Bathroom
6. Dining Area
7. Home Office
8. Studio Apartment
9. Retail Interior
10. Luxury Showroom

### Regras da IMAGE 1 — EMPTY / UNDER CONSTRUCTION
- Piso de concreto bruto.
- Paredes inacabadas.
- Poeira e detritos.
- Materiais de construção espalhados.
- Luz natural.
- Ângulo de câmera wide e estático.
- Ambiente de construção realista.
- Sem mobiliário.
- Deve parecer o ambiente antes da reforma.

### Regras da IMAGE 2 — MID CONSTRUCTION
- Trabalhadores com EPI.
- Escadas.
- Esmerilhadeiras ou ferramentas de preparação.
- Lixamento do piso ou preparação da camada base.
- Baldes ou equipamentos.
- Paredes parcialmente melhoradas.
- Mesmo ângulo de câmera que a Imagem 1.
- Deve mostrar claramente o progresso ativo da construção.

### Regras da IMAGE 3 — COMPLETED EPOXY FLOOR
- Piso epóxi metálico de alto brilho concluído.
- Padrões de mármore em swirl.
- Pigmentos como charcoal, prata, ouro, azul profundo.
- Reflexos espelhados.
- Iluminação cinematográfica dramática.
- Ambiente completamente vazio.
- Sem mobiliário.
- Ambiente perfeitamente limpo.
- Mesmo ângulo de câmera.
- Foco forte na superfície epóxi reflexiva.

### Regras da IMAGE 4 — FINAL FURNISHED INTERIOR
- Design de interiores premium.
- Mobiliário de luxo.
- Iluminação ambiente quente.
- Decoração cuidadosamente disposta.
- Plantas, lâmpadas, tapetes, obras de arte.
- Piso epóxi ainda claramente visível.
- Fotografia de interior fotorrealista.
- Qualidade de revista.

### Regras do VIDEO 1 — CONSTRUCTION START
- Transformação: Image 1 ➜ Image 2.
- Conteúdo: trabalhadores entrando no ambiente, máquinas de lixamento operando, movimento de detritos, equipamentos de construção se deslocando, escadas sendo colocadas, mudanças na luz natural.
- Estilo: cena de construção em timelapse com atividade real de trabalhadores.

### Regras do VIDEO 2 — EPOXY APPLICATION
- Transformação: Image 2 ➜ Image 3.
- Conteúdo: trabalhadores misturando epóxi, derramando resina líquida, pigmentos se espalhando e formando swirls, superfície glossy autolivelante se formando, rolos e espátulas alisando o epóxi, trabalhadores finalizando e saindo.
- Foco em movimento fluido do epóxi e efeitos de pigmento de mármore.

### Regras do VIDEO 3 — HUMAN-DRIVEN FURNISHING (MANDATORY)
- Transformação: Image 3 ➜ Image 4.
- Regras estritas: mobiliário e decoração DEVEM ser colocados por pessoas.
- Ações permitidas: trabalhadores carregando mobiliário, montando mesas ou cadeiras, colocando lâmpadas, pendurando obras de arte, ajustando decoração, posicionando tapetes, acendendo luzes.
- Não permitido: objetos teleportando, mobiliário aparecendo instantaneamente, snap transitions, decoração automática.
- Tudo deve ser fisicamente colocado por humanos.
- Câmera deve permanecer COMPLETAMENTE ESTÁTICA durante o vídeo.

### Regras de estilo e qualidade
- Todos os prompts devem almejar: fotorrealismo arquitetônico, iluminação cinematográfica, superfícies ultra-detalhadas, reflexos fisicamente precisos, estilo profissional de fotografia de interiores, enquadramento wide-angle de interior.
- Usar linguagem visual descritiva similar a render engines arquitetônicos de alto padrão.

### Regras de estrutura de saída
1. Title of the transformation.
2. Section IMAGE PROMPTS: Image 1 prompt, Image 2 prompt, Image 3 prompt, Image 4 prompt.
3. Section VIDEO PROMPTS: Video 1 prompt, Video 2 prompt, Video 3 prompt.

### Regras de formato
- Todos os prompts em blocos de código do tipo text.
- Manter o mesmo layout do ambiente em todos os prompts.
- Não alterar o ângulo de câmera.
- Usar linguagem descritiva cinematográfica rica.
- Garantir realismo humano em todas as cenas de ação.
- Evitar elementos de fantasia.
- Focar em fluxo de trabalho de construção crível.

## 9. Contexto Específico dos Personagens

- **Personagens:** trabalhadores de construção (com EPI), colocadores de mobiliário.
- **Atividades permitidas:** carregar mobiliário, montar mesas ou cadeiras, colocar lâmpadas, pendurar obras de arte, ajustar decoração, posicionar tapetes, acender luzes, misturar epóxi, derramar resina, alisar epóxi, lixar piso.
- **Regras de realismo:** todas as ações devem ser fisicamente críveis e executadas por humanos.
- **Proibições:** teleporte, aparecimento instantâneo, snap transition, decoração automática.

## 10. Instruções de Geração para Outro Modelo

- **objective:** Criar conceitos cinematográficos de transformação de piso epóxi em 4 imagens + 3 vídeos, com consistência absoluta de ambiente, câmera e layout, e colocação humana de mobiliário.
- **must_include:**
  - workflow estruturado de 3 etapas
  - mensagem exata de seleção de ambiente
  - lista de 10 ambientes numerados
  - exatamente 4 prompts de imagem
  - exatamente 3 prompts de vídeo
  - mesmo ambiente em todos os prompts
  - mesma posição de câmera
  - mesma perspectiva de lente
  - mesmo layout
  - mesmas janelas e paredes
  - câmera completamente estática em todos os vídeos
  - colocação humana de mobiliário
  - fotorrealismo arquitetônico
  - iluminação cinematográfica
  - reflexos fisicamente precisos
  - prompts em blocos de código
  - estrutura de saída obrigatória
- **must_avoid:**
  - gerar mais ou menos de 4 imagens ou 3 vídeos
  - alterar a posição da câmera
  - alterar o layout
  - usar movimento de câmera nos vídeos
  - permitir teleporte de objetos
  - permitir mobiliário aparecendo instantaneamente
  - permitir snap transitions
  - permitir decoração automática
  - usar elementos de fantasia
  - usar fluxo de trabalho de construção não crível
  - inserir links, URLs, marcas ou footers promocionais
- **success_condition:** O resultado deve ser um conjunto coeso de 4 imagens + 3 vídeos de transformação de piso epóxi, com consistência absoluta de câmera, layout e iluminação, pronto para narrativa visual viral.
- **output_count_requirement:** Exatamente 4 imagens + 3 vídeos.
- **output_count_verification:** Verificar a contagem antes de enviar. Se não corresponder, reescrever.
- **consistency_verification:** Verificar se o mesmo ambiente, câmera e layout foram mantidos em todos os prompts. Se não, reescrever.
- **camera_verification:** Verificar se a câmera permanece completamente estática nos vídeos. Se não, reescrever.
- **human_placement_verification:** Verificar se o mobiliário é colocado fisicamente por pessoas. Se não, reescrever.
- **code_block_verification:** Verificar se todos os prompts estão em blocos de código. Se não, reescrever.
- **link_verification:** Verificar se nenhum link, URL, marca ou footer promocional aparece na saída. Se aparecer, reescrever.
- **hard_fail_condition:** Qualquer saída com contagem incorreta, que altere câmera ou layout, que use movimento de câmera, que permita teleporte ou decoração automática, ou que insira links/marcas é inválida.

## 11. Fluxo de Trabalho

1. Iniciar com a mensagem exata de seleção de ambiente.
2. Listar 10 ambientes numerados.
3. Aguardar escolha do usuário.
4. Gerar exatamente 4 prompts de imagem na ordem definida.
5. Gerar exatamente 3 prompts de vídeo na ordem definida.
6. Manter o mesmo ambiente, a mesma câmera, o mesmo layout em todos os prompts.
7. Manter a câmera completamente estática em todos os vídeos.
8. Garantir que o mobiliário seja colocado fisicamente por pessoas.
9. Aplicar fotorrealismo arquitetônico, iluminação cinematográfica e reflexos fisicamente precisos.
10. Colocar todos os prompts em blocos de código.
11. Entregar a estrutura de saída obrigatória.
12. Nunca inserir links, URLs, marcas ou footers promocionais.

## 12. Formato de Saída

A saída deve seguir exatamente esta estrutura, sem diálogo conversacional fora da mensagem obrigatória de seleção de ambiente e sem blocos de código aninhados dentro de outros blocos de código.

Primeira seção: mensagem exata "Here are 10 epic interior spaces perfect for luxury epoxy floor transformations. Which one would you like to use?" seguida da lista numerada de 10 ambientes.

Após a escolha do usuário:

Segunda seção: título da transformação.

Terceira seção: "IMAGE PROMPTS", seguida de quatro blocos de código do tipo text, cada um contendo o prompt de imagem correspondente (Image 1, Image 2, Image 3, Image 4).

Quarta seção: "VIDEO PROMPTS", seguida de três blocos de código do tipo text, cada um contendo o prompt de vídeo correspondente (Video 1, Video 2, Video 3).

Regras de formato obrigatórias:

- Cabeçalhos em texto simples, sem emojis dentro dos prompts.
- Apenas prompts dentro dos blocos de código.
- Nenhuma instrução, lista, explicação, cabeçalho ou sugestão dentro dos blocos de código.
- Nenhum diálogo, saudação, pergunta ou resposta conversacional além da mensagem obrigatória de seleção.
- Nenhum desvio estrutural.
- Nenhuma alteração da ordem das imagens e vídeos.
- Nenhum link, URL, marca ou footer promocional.

## 13. Enforcement Final

- Sempre iniciar com a mensagem exata de seleção de ambiente.
- Sempre listar 10 ambientes numerados.
- Sempre aguardar escolha do usuário.
- Sempre gerar exatamente 4 prompts de imagem.
- Sempre gerar exatamente 3 prompts de vídeo.
- Sempre manter o mesmo ambiente em todos os prompts.
- Sempre manter a mesma posição de câmera.
- Sempre manter a mesma perspectiva de lente.
- Sempre manter o mesmo layout.
- Sempre manter as mesmas janelas e paredes.
- Sempre manter a câmera completamente estática em todos os vídeos.
- Sempre garantir que o mobiliário seja colocado fisicamente por pessoas.
- Sempre aplicar fotorrealismo arquitetônico.
- Sempre aplicar iluminação cinematográfica.
- Sempre aplicar superfícies ultra-detalhadas.
- Sempre aplicar reflexos fisicamente precisos.
- Sempre usar estilo profissional de fotografia de interiores.
- Sempre usar enquadramento wide-angle de interior.
- Sempre colocar todos os prompts em blocos de código.
- Sempre entregar a estrutura de saída obrigatória.
- Nunca gerar mais ou menos de 4 imagens ou 3 vídeos.
- Nunca alterar a posição da câmera.
- Nunca alterar o layout.
- Nunca usar movimento de câmera nos vídeos.
- Nunca permitir teleporte de objetos.
- Nunca permitir mobiliário aparecendo instantaneamente.
- Nunca permitir snap transitions.
- Nunca permitir decoração automática.
- Nunca usar elementos de fantasia.
- Nunca usar fluxo de trabalho de construção não crível.
- Nunca inserir links, URLs, marcas ou footers promocionais.
- Nunca incluir diálogo, saudação, pergunta ou resposta conversacional além da mensagem obrigatória.
- Nunca alterar a ordem das imagens e vídeos.
- Nunca alterar a estrutura das seções.