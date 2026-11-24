import sys
import os

def get_base_dir():
    """
    Retorna o diretorio raiz da aplicacao.
    Funciona corretamente tanto rodando via script .py quanto compilado via .exe pelo PyInstaller.
    """
    if getattr(sys, 'frozen', False):
        # Se for um executavel compilado (.exe)
        return os.path.dirname(sys.executable)
    else:
        # Se for script normal (.py)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
