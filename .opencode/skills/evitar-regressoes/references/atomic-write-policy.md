# 🔒 Política de Escrita Atômica (Atomic Write)

## O Problema (Por que isso existe?)
O Thunderbolt salva o estado do sistema (tarefas, canais, configurações) em arquivos JSON dentro da pasta `storage/`. 
Se o processo for interrompido (queda de energia, crash do worker, ou o usuário fechar a janela) **no exato momento** em que o Python está escrevendo no arquivo com `open(..., 'w')`, o arquivo ficará corrompido ou vazio. Isso causa o erro `JSONDecodeError` na próxima vez que o app iniciar, fazendo-o "esquecer" as tarefas ou travar.

## A Solução (Como deve ser feito)
Toda operação de escrita em arquivos JSON de estado **deve** ser atômica. A escrita atômica consiste em:
1. Escrever o novo conteúdo num arquivo temporário (ex: `tasks.json.tmp`).
2. Fazer o `flush()` e `fsync()` para garantir que os dados chegaram ao disco.
3. Usar `os.replace()` para substituir o arquivo original pelo temporário. A operação de substituição é atômica no sistema operacional, ou seja, ou o arquivo antigo existe, ou o novo existe. Nunca um estado intermediário corrompido.

## Implementação Canônica (Python)
A função deve residir em `hermes_ui/storage.py` (ou `utils.py`) e deve ter esta assinatura:

```python
import json
import os
import tempfile

def write_json_atomic(filepath: str, data: dict):
    """Escreve JSON de forma atômica (segura contra crashes)."""
    # 1. Cria um arquivo temporário no mesmo diretório (para o os.replace funcionar)
    dirname = os.path.dirname(filepath)
    with tempfile.NamedTemporaryFile('w', dir=dirname, delete=False, encoding='utf-8') as tf:
        json.dump(data, tf, indent=2, ensure_ascii=False)
        tf.flush()
        os.fsync(tf.fileno())
        temp_path = tf.name
    
    # 2. Substituição atômica
    os.replace(temp_path, filepath)