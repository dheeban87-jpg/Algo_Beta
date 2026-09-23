#!/usr/bin/env python3
"""
COMPLETE SYSTEM DIAGNOSTIC - Find what's wrong
"""

import os
import sys
from pathlib import Path

print("=" * 80)
print("COMPLETE SYSTEM DIAGNOSTIC")
print("=" * 80)
print()

# Check current directory
cwd = Path.cwd()
print(f"Current Directory: {cwd}")
print()

# Check for orchestrator.py files
print("ORCHESTRATOR FILES FOUND:")
orchestrator_paths = [
    Path("/tmp/Algo_Beta/orchestrator.py"),
    Path("/mnt/user-data/outputs/orchestrator.py"),
    Path(cwd / "orchestrator.py")
]

for path in orchestrator_paths:
    if path.exists():
        stat = path.stat()
        size_kb = stat.st_size / 1024
        print(f"  ✅ {path}")
        print(f"     Size: {size_kb:.1f} KB")
        print(f"     Modified: {stat.st_mtime}")
        
        # Check if it has position recovery fix
        with open(path) as f:
            content = f.read()
            has_recovery_check = "POSITION RECOVERY (Startup Check)" in content
            print(f"     Has Recovery Fix: {'✅ YES' if has_recovery_check else '❌ NO'}")
        print()

# Check for phase2_entry_timing.py files  
print("PHASE 2 FILES FOUND:")
phase2_paths = [
    Path("/tmp/Algo_Beta/phase2_entry_timing.py"),
    Path("/mnt/user-data/outputs/phase2_entry_timing.py"),
    Path(cwd / "phase2_entry_timing.py")
]

for path in phase2_paths:
    if path.exists():
        stat = path.stat()
        size_kb = stat.st_size / 1024
        print(f"  ✅ {path}")
        print(f"     Size: {size_kb:.1f} KB")
        print(f"     Modified: {stat.st_mtime}")
        print()

# Check Python path
print("PYTHON IMPORT PATH:")
for i, path in enumerate(sys.path[:5], 1):
    print(f"  {i}. {path}")
print()

print("=" * 80)
print("DIAGNOSIS")
print("=" * 80)
print()
print("If you're running from /tmp/Algo_Beta/:")
print("  ❌ You're using OLD version without fixes")
print("  ✅ FIX: cd to /mnt/user-data/outputs/ and run from there")
print()
print("If you're running from correct directory but Phase 2 missing:")
print("  ❌ Import error or initialization failure")
print("  ✅ FIX: Check logs/phase2.log for errors")
print()

