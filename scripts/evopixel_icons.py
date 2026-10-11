"""Build the EvoPixel icon font and its companion stylesheet."""

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont, TTLibError

FAMILY = "EvoPixel Icons"
UNITS_PER_EM = 1024
ASCENT = 896
DESCENT = -128
FONT_TIMESTAMP = 3874435200  # 2026-10-10 in the OpenType epoch, for reproducible builds.
SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"


def load_project(root: Path) -> tuple[str, list[dict]]:
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream).get("project", {})
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("pyproject.toml: project.version must use major.minor.patch")
    if int(version.split(".")[0]) > 32767:
        raise ValueError("pyproject.toml: major version exceeds the OpenType revision range")

    manifest = json.loads((root / "icons.json").read_text(encoding="utf-8"))
    icons = manifest.get("icons") if isinstance(manifest, dict) else None
    if not isinstance(icons, list) or not icons:
        raise ValueError("icons.json: icons must be a non-empty list")

    names, codepoints = set(), set()
    for index, icon in enumerate(icons, start=1):
        context = f"icons.json: icon {index}"
        if not isinstance(icon, dict):
            raise ValueError(f"{context} must be an object")
        name, codepoint, label = (icon.get(field) for field in ("name", "codepoint", "label"))
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise ValueError(f"{context}: name must be a lowercase CSS class name")
        if name == "evopixel-icon" or name in names:
            raise ValueError(f"{context}: reserved or duplicate name {name!r}")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{context}: label must be non-empty text")
        if not isinstance(codepoint, str) or not re.fullmatch(
            r"[Ee][0-9A-Fa-f]{3}|[Ff][0-8][0-9A-Fa-f]{2}", codepoint
        ):
            raise ValueError(f"{context}: codepoint must be a private-use value from E000 to F8FF")
        value = int(codepoint, 16)
        if value in codepoints:
            raise ValueError(f"{context}: duplicate codepoint {codepoint}")
        names.add(name)
        codepoints.add(value)
    return version, icons


def load_glyph(file: Path):
    try:
        svg = ET.parse(file).getroot()
        if svg.tag != SVG_NAMESPACE + "svg":
            raise ValueError("expected an SVG document with the SVG namespace")
        viewbox = re.split(r"[\s,]+", svg.attrib.get("viewBox", "").strip())
        if [float(value) for value in viewbox] != [0, 0, UNITS_PER_EM, UNITS_PER_EM]:
            raise ValueError("expected a 0 0 1024 1024 viewBox")
        paths = list(svg)
        if not paths or any(element.tag != SVG_NAMESPACE + "path" for element in paths):
            raise ValueError("convert shapes and groups to filled paths first")

        # Font outlines cannot reproduce SVG styling, clipping or inherited transforms.
        unsupported = {
            "transform",
            "style",
            "stroke",
            "opacity",
            "fill-opacity",
            "display",
            "visibility",
            "clip-path",
            "mask",
            "filter",
        }
        for element in [svg, *paths]:
            attributes = unsupported.intersection(element.attrib)
            if attributes:
                raise ValueError("flatten unsupported attributes: " + ", ".join(sorted(attributes)))
            fill = element.attrib.get("fill", "currentColor").strip().lower()
            if fill == "none" or fill.startswith("url("):
                raise ValueError("use solid filled paths")
            if element.attrib.get("fill-rule", "nonzero") != "nonzero":
                raise ValueError("convert even-odd fills to nonzero path winding")

        pen = TTGlyphPen(None)
        transformed = TransformPen(Cu2QuPen(pen, max_err=1), (1, 0, 0, -1, 0, ASCENT))
        for element in paths:
            data = element.attrib.get("d", "")
            if not data.strip():
                raise ValueError("path data must not be empty")
            parse_path(data, transformed)
        glyph = pen.glyph()
        if glyph.numberOfContours <= 0:
            raise ValueError("the icon has no drawable contours")
        return glyph
    except (ET.ParseError, ValueError, TypeError, KeyError, AssertionError, OverflowError) as error:
        raise ValueError(f"{file.name}: {error}") from error


def build_font(root: Path, version: str, icons: list[dict]) -> bytes:
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    character_map = {}
    # CSS order must not change glyph IDs or the resulting font bytes.
    for icon in sorted(icons, key=lambda item: int(item["codepoint"], 16)):
        name = icon["name"]
        glyphs[name] = load_glyph(root / "svgs" / (name + ".svg"))
        character_map[int(icon["codepoint"], 16)] = name

    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(list(glyphs))
    builder.setupCharacterMap(character_map)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(
        {
            name: (UNITS_PER_EM, min(glyph.xMin, 32) if hasattr(glyph, "xMin") else 0)
            for name, glyph in glyphs.items()
        }
    )
    builder.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    builder.setupNameTable(
        {
            "familyName": FAMILY,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{FAMILY} Regular {version}",
            "fullName": FAMILY,
            "psName": "EvoPixelIcons-Regular",
            "version": "Version " + version,
            "copyright": "Copyright EvoPixel and bLeaH",
        }
    )
    builder.setupOS2(
        sTypoAscender=ASCENT,
        sTypoDescender=DESCENT,
        sTypoLineGap=0,
        usWinAscent=ASCENT,
        usWinDescent=-DESCENT,
    )
    builder.setupPost()
    builder.font.recalcTimestamp = False
    builder.font["head"].created = FONT_TIMESTAMP
    builder.font["head"].modified = FONT_TIMESTAMP
    builder.font["head"].fontRevision = float(".".join(version.split(".")[:2]))
    builder.font.flavor = "woff2"
    stream = io.BytesIO()
    builder.save(stream)
    result = stream.getvalue()
    with TTFont(io.BytesIO(result), checkChecksums=2) as font:
        if font.getBestCmap() != character_map:
            raise ValueError("generated font does not match the icon manifest")
    return result


def build_css(icons: list[dict], font: bytes) -> bytes:
    revision = hashlib.sha256(font).hexdigest()[:12]
    css = f"""@font-face {{
  font-family: "EvoPixel Icons";
  font-style: normal;
  font-weight: 400;
  font-display: block;
  src: url("../webfonts/evopixel-icons.woff2?v={revision}") format("woff2");
}}
.evopixel-icon {{
  display: inline-block;
  font-family: "EvoPixel Icons";
  font-style: normal;
  font-variant: normal;
  font-weight: 400;
  line-height: 1;
  text-rendering: auto;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}
"""
    for icon in icons:
        codepoint = int(icon["codepoint"], 16)
        css += f'.{icon["name"]}:before {{\n  content: "\\{codepoint:x}";\n}}\n'
    return css.encode("utf-8")


def stage_file(target: Path, contents: bytes) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="." + target.name + ".", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
        temporary.chmod(mode)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def write_outputs(outputs: dict[Path, bytes]) -> None:
    staged, backups, committed = {}, {}, []
    preserved = set()
    try:
        for target, contents in outputs.items():
            previous = target.read_bytes() if target.exists() else None
            if previous == contents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            staged[target] = stage_file(target, contents)
            backups[target] = stage_file(target, previous) if previous is not None else None
        for target, temporary in staged.items():
            os.replace(temporary, target)
            committed.append(target)
    except OSError as write_error:
        # Restore earlier outputs if replacing a later file fails.
        unrestored = []
        for target in reversed(committed):
            try:
                if backups[target] is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backups[target], target)
            except OSError:
                preserved.add(backups[target])
                unrestored.append(f"{target} (backup: {backups[target]})")
        if unrestored:
            raise OSError("Could not restore outputs: " + "; ".join(unrestored)) from write_error
        raise
    finally:
        for temporary in [*staged.values(), *backups.values()]:
            if temporary is not None and temporary not in preserved:
                temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None, *, default_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("build", "check"), default="build")
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root or Path.cwd(),
        help="project directory containing pyproject.toml, icons.json and svgs",
    )
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    try:
        version, icons = load_project(root)
        font = build_font(root, version, icons)
        outputs = {
            root / "webfonts" / "evopixel-icons.woff2": font,
            root / "css" / "evopixel-icons.css": build_css(icons, font),
        }
        preview = root / "preview.html"
        if preview.is_file():
            revision = hashlib.sha256(outputs[root / "css" / "evopixel-icons.css"]).hexdigest()[:12]
            markup, count = re.subn(
                r'href="css/evopixel-icons\.css(?:\?v=[a-f0-9]+)?"',
                f'href="css/evopixel-icons.css?v={revision}"',
                preview.read_text(encoding="utf-8"),
            )
            if count != 1:
                raise ValueError("preview.html: expected one EvoPixel Icons stylesheet link")
            outputs[preview] = markup.encode("utf-8")
        if arguments.command == "check":
            outdated = [
                path.relative_to(root).as_posix()
                for path, contents in outputs.items()
                if not path.is_file() or path.read_bytes() != contents
            ]
            if outdated:
                print("Outdated or missing outputs: " + ", ".join(outdated), file=sys.stderr)
                return 1
            print(f"Verified {len(icons)} icons; generated font and CSS are up to date.")
        else:
            write_outputs(outputs)
            print(
                f"Built {len(icons)} icons: css/evopixel-icons.css "
                "and webfonts/evopixel-icons.woff2"
            )
        return 0
    except (OSError, ValueError, TTLibError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
