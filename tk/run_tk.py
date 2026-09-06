#!/usr/bin/env python
"""
Script de execução da interface Tkinter do industrial-flow para Windows.
"""

import sys
from pathlib import Path

# Adiciona a raiz do repositório ao sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from tk.app import main

if __name__ == "__main__":
    main()
