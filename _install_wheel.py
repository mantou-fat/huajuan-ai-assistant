# -*- coding: utf-8 -*-
"""手动下载并解包 lark-oapi wheel 到 .pkgs（绕过 pip 的临时目录问题）"""
import json, os, sys, zipfile, io
import requests

ROOT = r"D:\python"
PKGS = os.path.join(ROOT, ".pkgs")
os.makedirs(PKGS, exist_ok=True)

def get_json(url):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()

def download_wheel(name):
    data = get_json("https://pypi.org/pypi/%s/json" % name)
    ver = data["info"]["version"]
    files = data["releases"][ver]
    whl = [f for f in files if f["packagetype"] == "bdist_wheel"]
    if not whl:
        raise RuntimeError("no wheel for %s %s" % (name, ver))
    # 优先匹配当前解释器/平台
    import sysconfig
    tag = "cp%d%d" % (sys.version_info.major, sys.version_info.minor)
    def score(f):
        fn = f["filename"]
        s = 0
        if tag in fn:
            s += 3
        if "win_amd64" in fn:
            s += 2
        if "py3-none-any" in fn:
            s += 1
        return -s
    whl.sort(key=score)
    f = whl[0]
    print("downloading", f["filename"], f["size"], "bytes")
    r = requests.get(f["url"], timeout=180)
    r.raise_for_status()
    return f["filename"], r.content

def install_wheel(filename, content):
    z = zipfile.ZipFile(io.BytesIO(content))
    z.extractall(PKGS)
    # 读取依赖
    deps = []
    for n in z.namelist():
        if n.endswith(".dist-info/METADATA"):
            meta = z.read(n).decode("utf-8", "replace")
            for line in meta.splitlines():
                if line.startswith("Requires-Dist:"):
                    dep = line.split(":", 1)[1].strip().split(";")[0].strip()
                    deps.append(dep)
            break
    print("installed", filename, "into", PKGS)
    if deps:
        print("requires:", deps)
    return deps

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "lark-oapi"
    fn, content = download_wheel(name)
    install_wheel(fn, content)
