import os
import tempfile
import unittest
import yaml
import subprocess
import shutil

class TestSyncScripts(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.scripts_dir = os.path.abspath("scripts")
        
        self.inventory_path = os.path.join(self.test_dir, "docs", "synchronization-inventory.yaml")
        os.makedirs(os.path.dirname(self.inventory_path))
        
        self.inventory = {
            "version": 1,
            "defaults": {
                "exclude": ["dist/**", "node_modules/**"]
            },
            "files": {
                "daemon/castcast/test1.py": {
                    "section": "core-service",
                    "role": "orchestrator",
                    "boundaries": ["api-contract"]
                },
                "src/app/index.html": {
                    "section": "web-client",
                    "role": "ui",
                    "boundaries": ["api-contract"]
                },
                "android/app/test.java": {
                    "section": "android-bridge",
                    "role": "plugin",
                    "boundaries": ["config-state"]
                }
            }
        }
        with open(self.inventory_path, "w") as f:
            yaml.dump(self.inventory, f)
            
        os.makedirs(os.path.join(self.test_dir, "daemon/castcast"))
        os.makedirs(os.path.join(self.test_dir, "src/app"))
        os.makedirs(os.path.join(self.test_dir, "android/app"))
        
        self.py_file = os.path.join(self.test_dir, "daemon/castcast/test1.py")
        with open(self.py_file, "w") as f:
            f.write("#!/usr/bin/env python3\nprint('hello')\n")
            
        self.html_file = os.path.join(self.test_dir, "src/app/index.html")
        with open(self.html_file, "w") as f:
            f.write("<!DOCTYPE html>\n<html></html>\n")
            
        self.java_file = os.path.join(self.test_dir, "android/app/test.java")
        with open(self.java_file, "w") as f:
            f.write("class Test {}\n")
            
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
    def run_script(self, script_name, args):
        cmd = ["python3", os.path.join(self.scripts_dir, script_name)] + args
        return subprocess.run(cmd, cwd=self.test_dir, capture_output=True, text=True)

    def test_apply_and_check(self):
        res = self.run_script("apply_sync_headers.py", ["--apply"])
        self.assertEqual(res.returncode, 0, res.stderr)
        
        with open(self.py_file, "r") as f:
            lines = f.readlines()
        self.assertEqual(lines[0], "#!/usr/bin/env python3\n")
        self.assertTrue(lines[1].startswith("# synchronization-map: section=core-service;"))
        self.assertEqual(lines[2], "print('hello')\n")
        
        with open(self.html_file, "r") as f:
            lines = f.readlines()
        self.assertTrue(lines[0].startswith("<!-- synchronization-map: section=web-client;"))
        
        with open(self.java_file, "r") as f:
            lines = f.readlines()
        self.assertTrue(lines[0].startswith("// synchronization-map: section=android-bridge;"))
        
        # Now run check script
        res_check = self.run_script("check_sync_headers.py", [])
        self.assertEqual(res_check.returncode, 0, res_check.stderr)

    def test_missing_file_check(self):
        self.run_script("apply_sync_headers.py", ["--apply"])
        
        # Create a new in-scope file not in inventory
        with open(os.path.join(self.test_dir, "daemon/castcast/untracked.py"), "w") as f:
            f.write("print('untracked')\n")
            
        res_check = self.run_script("check_sync_headers.py", [])
        self.assertNotEqual(res_check.returncode, 0)
        self.assertIn("missing from the manifest", res_check.stderr)

if __name__ == "__main__":
    unittest.main()
