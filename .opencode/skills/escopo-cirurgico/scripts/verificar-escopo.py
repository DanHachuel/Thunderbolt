#!/usr/bin/env python3
"""
Auditoria de Escopo: Verifica o git status e alerta se arquivos restritos 
foram modificados sem justificativa.
Uso: python scripts/verificar-escopo.py
"""
import subprocess
import sys

# AGENTS.md (regra 3): zero mojibake. A consola do Windows (cp1252) nao imprime
# os emojis dos relatorios - reconfiguramos a saida antes de qualquer print.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

ARQUIVOS_PROIBIDOS_UI = ["install.mjs", "requirements.txt", "package.json", "pipeline_worker.py"]
ARQUIVOS_PROIBIDOS_BACKEND = ["cli.mjs"] # Exemplo: não mexer no launcher em tarefas de backend

def get_modified_files():
    try:
        result = subprocess.run(["git", "diff", "--name-only", "HEAD"], capture_output=True, text=True)
        return [f for f in result.stdout.split("\n") if f]
    except Exception as e:
        print(f"Erro ao rodar git diff: {e}")
        return []

def main():
    modified = get_modified_files()
    if not modified:
        print("✅ Nenhum arquivo modificado.")
        return

    print(f"🔍 Analisando {len(modified)} arquivos modificados...")
    
    alertas = []
    if any("app/main.py" in f or "pages/" in f for f in modified):
        for proibido in ARQUIVOS_PROIBIDOS_UI:
            if any(proibido in f for f in modified):
                alertas.append(f"⚠️  Tarefa de UI detectada, mas o arquivo restrito '{proibido}' foi alterado.")

    if alertas:
        print("\n🚨 VIOLAÇÕES DE ESCOPO DETECTADAS:")
        for a in alertas:
            print(a)
        print("\nReverta essas alterações antes do commit ou justifique.")
        sys.exit(1)
    else:
        print("\n✅ SUCESSO: Nenhuma violação de escopo óbvia detectada.")
        sys.exit(0)

if __name__ == "__main__":
    main()