"""
Launcher for DnD Notes — compiled into DnD Notes.exe via PyInstaller (--windowed).
Finds system Python, installs Flask + pywebview if needed, then runs app.py.
No console window — errors are shown as Windows message box popups.
"""
import sys
import os
import subprocess
import shutil

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _alert(title, message):
    """Show a Windows message box. Works with --windowed (no console)."""
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # 0x10 = MB_ICONERROR
    else:
        print(f"{title}: {message}")


def find_python():
    """Find the system Python (not the PyInstaller-bundled one)."""
    for candidate in ['python', 'python3', 'py']:
        path = shutil.which(candidate)
        if not path:
            continue
        # Skip if it's this very exe
        if getattr(sys, 'frozen', False):
            if os.path.normcase(path) == os.path.normcase(sys.executable):
                continue
        # Confirm it actually runs
        try:
            subprocess.check_call(
                [path, '--version'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW
            )
            return path
        except Exception:
            continue
    return None


def main():
    # Find app.py next to this exe
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))

    app_path = os.path.join(exe_dir, 'app.py')
    if not os.path.exists(app_path):
        _alert(
            'D&D Notes — Missing File',
            f'Could not find app.py.\n\nExpected it here:\n{app_path}\n\n'
            'Make sure DnD Notes.exe is in the same folder as app.py.'
        )
        sys.exit(1)

    # Find system Python
    python = find_python()
    if not python:
        _alert(
            'D&D Notes — Python Not Found',
            'Python is not installed or not in PATH.\n\n'
            'Download it from: https://python.org\n\n'
            'During install, tick the box: "Add Python to PATH"\n'
            'Then restart your PC and try again.'
        )
        sys.exit(1)

    # Install required packages if not present
    packages = [
        ('flask',     'flask',     'web server'),
        ('pywebview', 'webview',   'app window'),
        ('openai',    'openai',    'AI (OpenAI/Ollama)'),
        ('anthropic', 'anthropic', 'AI (Anthropic)'),
    ]
    for pip_name, import_name, label in packages:
        result = subprocess.call(
            [python, '-c', f'import {import_name}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW
        )
        if result != 0:
            ret = subprocess.call(
                [python, '-m', 'pip', 'install', pip_name, '--quiet'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW
            )
            if ret != 0:
                _alert(
                    'D&D Notes — Install Failed',
                    f'Could not install required package: {pip_name}\n\n'
                    'Check your internet connection and try again.'
                )
                sys.exit(1)

    subprocess.call([python, app_path], creationflags=_NO_WINDOW)


if __name__ == '__main__':
    main()
