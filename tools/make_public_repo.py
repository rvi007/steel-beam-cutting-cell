"""
Builds the PUBLIC showcase repository (github.com/rvi007/beam-cell) from this private one:
the readable pages, pictures, video and PDFs - and no source code, CAD files or tools.

    python3 tools/make_public_repo.py ../beam-cell        # then commit and push in ../beam-cell

What goes public is listed below; everything else stays private. The script refuses to finish
if a page links to a file that isn't copied, or if any code file slipped in.
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "tools", "public_page")   # README, LICENSE, request forms for the public page
DOCS = ["MACHINE.md", "SAFETY.md", "SENSORS.md", "PLASMA.md", "UK_CODES.md", "NC1_FILES.md", "PROTOTYPE.md", "SCALE_MODEL.md", "ASSISTANT.md",
        "Prototype_Shopping_List.pdf", "Prototype_Assembly.pdf", "prototype_bom.csv"]
FOLDERS = ["docs/images", "docs/video"]
DROP_SECTIONS = {"MACHINE.md": ["Code map"]}      # sections about the code itself
NOTE = ("\n> Files and commands written `like this` are in the private source code - "
        "[request access](https://github.com/rvi007/beam-cell/issues/new?template=request-access.yml) to get it.\n")
CODE = (".py", ".js", ".mjs", ".html", ".css", ".step", ".glb", ".nc1", ".toml", ".service", ".sh")


def strip_sections(text, titles):
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        m = re.match(r"(#+) (.*)", line)
        if m:
            skip = m.group(2).strip() in titles
        if not skip:
            out.append(line)
    return "".join(out)


def main(dest):
    dest = os.path.abspath(dest)
    if os.path.abspath(ROOT) == dest:
        sys.exit("give a different folder for the public repository")
    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(dest):                   # start clean, but keep its own git history
        if name != ".git":
            p = os.path.join(dest, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    shutil.copytree(PUBLIC, dest, dirs_exist_ok=True)
    os.makedirs(os.path.join(dest, "docs"), exist_ok=True)
    for name in DOCS:
        src, dst = os.path.join(ROOT, "docs", name), os.path.join(dest, "docs", name)
        if name.endswith(".md"):
            with open(src) as fh:
                text = strip_sections(fh.read(), DROP_SECTIONS.get(name, []))
            title, _, rest = text.partition("\n")              # the note goes under the page title
            text = title + "\n" + NOTE + rest
            with open(dst, "w") as fh:
                fh.write(text)
        else:
            shutil.copy2(src, dst)
    for folder in FOLDERS:
        shutil.copytree(os.path.join(ROOT, folder), os.path.join(dest, folder), dirs_exist_ok=True)

    problems = []
    for base, _, files in os.walk(dest):
        if ".git" in base.split(os.sep):
            continue
        for f in files:
            path = os.path.join(base, f)
            if f.endswith(CODE):
                problems.append(f"code file copied: {os.path.relpath(path, dest)}")
            if f.endswith(".md"):
                with open(path) as fh:
                    for link in re.findall(r"\]\(([^)#\s]+)", fh.read()):
                        if "://" not in link and not os.path.exists(os.path.normpath(os.path.join(base, link))):
                            problems.append(f"{os.path.relpath(path, dest)}: broken link {link}")
    if problems:
        sys.exit("NOT ready:\n  " + "\n  ".join(problems))
    size = sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(dest) if ".git" not in b for f in fs)
    print(f"public repository ready in {dest} ({size / 1e6:.1f} MB) - commit and push it")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "beam-cell"))
