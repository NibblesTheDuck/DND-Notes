"""
Launcher for DnD Notes — compiled into DnD Notes.exe via PyInstaller.
Finds system Python, installs Flask if needed, then runs app.py.
"""
import sys
import os
import subprocess
import shutil


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
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
        print(f"\n  ERROR: Could not find app.py")
        print(f"  Expected it here: {app_path}")
        print(f"\n  Make sure DnD Notes.exe is in the same folder as app.py.")
        input("\n  Press Enter to close.")
        sys.exit(1)

    # Find system Python
    python = find_python()
    if not python:
        print("\n  ERROR: Python is not installed or not in PATH.")
        print("\n  Download it from:  https://python.org")
        print("  During install, check the box:  Add Python to PATH")
        print("  Then restart your PC and try again.")
        input("\n  Press Enter to close.")
        sys.exit(1)

    # Install Flask if not present
    result = subprocess.call(
        [python, '-c', 'import flask'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if result != 0:
        print("  Installing web server (one-time setup)...")
        ret = subprocess.call([python, '-m', 'pip', 'install', 'flask', '--quiet'])
        if ret != 0:
            print("\n  ERROR: Could not install Flask. Check your internet connection.")
            input("\n  Press Enter to close.")
            sys.exit(1)

    print("  Starting D&D Notes...  your browser will open in a moment.")
    print("  Keep this window open while using the app.\n")

    subprocess.call([python, app_path])

    print("\n  Server stopped.")
    input("  Press Enter to close.")


if __name__ == '__main__':
    main()
