#!/usr/bin/env python3
import argparse
import fnmatch
import os
import re
import sys
import yaml
from pathlib import Path

VALID_IDS = {
    "core-service", "api-contract", "web-client", "android-bridge", 
    "cast-sender-receiver", "media-routing", "config-state", 
    "utility-middleware", "operations-release"
}

SUPPORTED_EXTENSIONS = {'.py', '.ts', '.js', '.java', '.html', '.sh'}
IN_SCOPE_DIRS = ["daemon/castcast", "src/app", "android/app"]

SYNC_HEADER_PATTERN = re.compile(
    r"^(# |// |<!-- )synchronization-map: section=(?P<section>[^;]+); role=(?P<role>[^;]+); boundaries=(?P<boundaries>[^;]+); doc=(?P<doc>[^\s>]+)( -->)?$",
    re.IGNORECASE
)

def is_excluded(path_str, excludes):
    path_str = str(Path(path_str).as_posix())
    for ex in excludes:
        ex = str(Path(ex).as_posix())
        if fnmatch.fnmatch(path_str, ex):
            return True
        if ex.startswith("**/") and fnmatch.fnmatch(path_str, ex[3:]):
            return True
        if ex.endswith("/**") and fnmatch.fnmatch(path_str, ex[:-3]):
            return True
    return False

def get_comment_syntax(file_path):
    ext = os.path.splitext(file_path)[1]
    if ext in {'.py', '.sh'}:
        return '# ', ''
    elif ext in {'.ts', '.js', '.java'}:
        return '// ', ''
    elif ext in {'.html'}:
        return '<!-- ', ' -->'
    return None, None

def construct_header(prefix, suffix, section, role, boundaries):
    if isinstance(boundaries, list):
        b_str = ",".join(boundaries)
    else:
        b_str = boundaries
    return f"{prefix}synchronization-map: section={section}; role={role}; boundaries={b_str}; doc=docs/SYNCHRONIZATION_MAP.md{suffix}"

def validate_ids(section, boundaries):
    if section not in VALID_IDS:
        return False
    for b in boundaries:
        if b not in VALID_IDS:
            return False
    return True

def process_file(file_path, expected_metadata, action, dry_run=False):
    prefix, suffix = get_comment_syntax(file_path)
    if not prefix:
        return False, "Unsupported extension"
        
    expected_header = construct_header(prefix, suffix, expected_metadata['section'], expected_metadata['role'], expected_metadata['boundaries'])
    
    try:
        with open(file_path, 'rb') as f:
            raw_content = f.read()
    except Exception as e:
        return False, str(e)
        
    bom = b''
    if raw_content.startswith(b'\xef\xbb\xbf'):
        bom = b'\xef\xbb\xbf'
        raw_content = raw_content[3:]
        
    try:
        content = raw_content.decode('utf-8')
    except UnicodeDecodeError:
        return False, "Not valid UTF-8"
        
    with open(file_path, 'r', encoding='utf-8', newline='') as f:
        lines = f.readlines()
        
    header_idx = -1
    existing_meta = None
    
    # check for conflicting metadata (any line containing synchronization-map but not matching our pattern)
    # Actually, we should check if there's any text saying "synchronization-map" that we didn't parse properly.
    for i, line in enumerate(lines):
        if "synchronization-map:" in line.lower():
            m = SYNC_HEADER_PATTERN.match(line.strip())
            if m:
                if header_idx != -1:
                    # Multiple headers found, that's a conflict
                    return False, f"Conflicting existing metadata: multiple headers found"
                header_idx = i
                existing_meta = m.groupdict()
            else:
                return False, f"Conflicting existing metadata: malformed header at line {i+1}"
                
    if action == "check":
        if not existing_meta:
            return False, "Missing header"
        actual_header = lines[header_idx].strip()
        if actual_header != expected_header:
            return False, "Conflicting/Incorrect header"
        return True, "OK"
        
    if existing_meta:
        actual_header = lines[header_idx].strip()
        if actual_header == expected_header:
            return True, "Unchanged"
        else:
            if action == "dry-run" or dry_run:
                return True, "Will update header"
            else:
                # Replace the existing header
                lines.pop(header_idx)
    else:
        if action == "dry-run" or dry_run:
            return True, "Will add header"
            
    # Apply (insert new header)
    insert_idx = 0
    if lines and lines[0].startswith('#!'):
        insert_idx = 1
        
    newline_char = '\n'
    if lines:
        if lines[0].endswith('\r\n'):
            newline_char = '\r\n'
        elif lines[0].endswith('\n'):
            newline_char = '\n'
            
    lines.insert(insert_idx, expected_header + newline_char)
    
    with open(file_path, 'wb') as f:
        if bom:
            f.write(bom)
        for line in lines:
            f.write(line.encode('utf-8'))
            
    # Preserve executable bit
    os.chmod(file_path, os.stat(file_path).st_mode)
            
    return True, "Updated header" if existing_meta else "Added header"

def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    
    if args.check:
        action = "check"
    elif args.dry_run:
        action = "dry-run"
    else:
        action = "apply"
        
    try:
        with open("docs/synchronization-inventory.yaml", "r", encoding="utf-8") as f:
            inventory = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading inventory: {e}", file=sys.stderr)
        sys.exit(1)
        
    excludes = inventory.get("defaults", {}).get("exclude", [])
    files = inventory.get("files", {})
    
    errors = 0
    
    # 1. Process files in inventory
    for file_path, meta in files.items():
        if is_excluded(file_path, excludes):
            continue
            
        if not validate_ids(meta.get("section"), meta.get("boundaries", [])):
            print(f"FAIL: {file_path} - Unknown map IDs in section or boundaries", file=sys.stderr)
            errors += 1
            continue
            
        if not os.path.exists(file_path):
            print(f"WARN: {file_path} from inventory does not exist.")
            continue
            
        success, msg = process_file(file_path, meta, action)
        if success:
            if action == "dry-run":
                print(f"OK (dry-run): {file_path} - {msg}")
            elif action == "apply":
                if msg != "Unchanged":
                    print(f"OK: {file_path} - {msg}")
        else:
            print(f"FAIL: {file_path} - {msg}", file=sys.stderr)
            errors += 1
            
    # 2. Check for in-scope files absent from manifest
    in_scope_absent = []
    for d in IN_SCOPE_DIRS:
        if not os.path.exists(d):
            continue
        for root, dirs, filenames in os.walk(d):
            for f in filenames:
                ext = os.path.splitext(f)[1]
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                path_str = os.path.join(root, f)
                path_str = str(Path(path_str).as_posix())
                if is_excluded(path_str, excludes):
                    continue
                if path_str not in files:
                    in_scope_absent.append(path_str)
                    
    if in_scope_absent:
        if action == "check":
            print("\nFAIL: The following in-scope files are missing from the manifest:", file=sys.stderr)
            for p in in_scope_absent:
                print(f"  - {p}", file=sys.stderr)
            errors += 1
        else:
            print("\nReport: The following in-scope files are missing from the manifest:")
            for p in in_scope_absent:
                print(f"  - {p}")
                
    if errors > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
