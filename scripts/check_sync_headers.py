#!/usr/bin/env python3
import subprocess
import sys
import os

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    apply_script = os.path.join(script_dir, 'apply_sync_headers.py')
    result = subprocess.run([sys.executable, apply_script, '--check'])
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
