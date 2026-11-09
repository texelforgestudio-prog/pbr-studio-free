#!/usr/bin/env python3
"""PBR Studio All-in-One installer.

Usage:   python install_pbr_studio.py --comfy "C:\\path\\to\\ComfyUI"        (or /path/to/ComfyUI)
Options: --dry-run (show what would happen)   --skip-clone (do not git clone the other custom nodes)

What it does: 1) copies PBR_Studio_Nodes into ComfyUI/custom_nodes
              2) copies the 4 workflows into ComfyUI/user/default/workflows/PBR_Studio (they appear in the Workflows panel)
              3) git-clones ComfyUI-DepthAnythingV2 and ComfyUI-seamless-tiling (seamless tiling is only needed by 01 and 05) (if git is installed)
It does NOT download models (they are large; see START_HERE.md) and does NOT run pip for you.
"""
import argparse, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPOS = [("ComfyUI-DepthAnythingV2", "https://github.com/kijai/ComfyUI-DepthAnythingV2"),
         ("ComfyUI-seamless-tiling", "https://github.com/spinagon/ComfyUI-seamless-tiling")]


def find_comfy(path):
    for cand in (path, os.path.join(path, "ComfyUI")):
        if os.path.isdir(os.path.join(cand, "custom_nodes")):
            return os.path.abspath(cand)
    return None


def main():
    ap = argparse.ArgumentParser(description="Install PBR Studio All-in-One into ComfyUI")
    ap.add_argument("--comfy", required=True, help="path to your ComfyUI folder (the one containing custom_nodes)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-clone", action="store_true")
    a = ap.parse_args()
    root = find_comfy(a.comfy)
    if not root:
        sys.exit("ERROR: could not find a 'custom_nodes' folder in %r. Point --comfy at your ComfyUI folder." % a.comfy)
    do = (lambda msg: print("[dry-run] " + msg)) if a.dry_run else (lambda msg: print(msg))

    src_nodes = os.path.join(HERE, "custom_nodes", "PBR_Studio_Nodes")
    dst_nodes = os.path.join(root, "custom_nodes", "PBR_Studio_Nodes")
    do("copy %s -> %s" % (src_nodes, dst_nodes))
    if not a.dry_run:
        shutil.copytree(src_nodes, dst_nodes, dirs_exist_ok=True)

    wf_src = os.path.join(HERE, "workflows"); wf_dst = os.path.join(root, "user", "default", "workflows", "PBR_Studio")
    do("copy workflows -> %s" % wf_dst)
    if not a.dry_run:
        os.makedirs(wf_dst, exist_ok=True)
        for f in sorted(os.listdir(wf_src)):
            if f.endswith(".json"):
                shutil.copy2(os.path.join(wf_src, f), os.path.join(wf_dst, f))

    if not a.skip_clone:
        if shutil.which("git") is None:
            print("git not found: install git, or clone these manually into custom_nodes:")
            for n, u in REPOS: print("   git clone %s" % u)
        else:
            for name, url in REPOS:
                dst = os.path.join(root, "custom_nodes", name)
                if os.path.isdir(dst): print("already installed: %s" % name); continue
                do("git clone %s" % url)
                if not a.dry_run:
                    r = subprocess.run(["git", "clone", "--depth", "1", url, dst])
                    if r.returncode != 0: print("WARNING: clone of %s failed, clone it manually." % url)

    req = os.path.join(root, "custom_nodes", "ComfyUI-DepthAnythingV2", "requirements.txt")
    portable = os.path.join(os.path.dirname(root), "python_embeded", "python.exe")
    py = '"%s"' % portable if os.path.exists(portable) else "python   (use the Python that runs ComfyUI)"
    print("\nNEXT STEPS\n1) Install the Depth Anything requirements with ComfyUI's Python:\n   %s -m pip install -r \"%s\"" % (py, req))
    print("2) Download the models for the workflows you want (links in START_HERE.md).")
    print("3) Restart ComfyUI, open the Workflows panel > PBR_Studio, press R to refresh models.")


if __name__ == "__main__":
    main()
