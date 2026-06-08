#!/usr/bin/env python
"""
Script de execução do industrial-flow sem necessidade de instalação do pacote.
"""

import sys
from pathlib import Path

# Adiciona a raiz do repositório ao sys.path para permitir a importação do pacote industrial_flow
repo_root = Path(__file__).parent.resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from industrial_flow.cli import app
except ImportError as e:
    print(f"Erro ao importar a CLI do industrial-flow: {e}", file=sys.stderr)
    print("Certifique-se de que instalou as dependências listadas em requirements.txt.", file=sys.stderr)
    print("Execute: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    app()
