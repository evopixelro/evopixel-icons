# EvoPixel Icons

Custom icon font for EvoPixel projects

Includes EvoPixel, Minecraft EvoPixel, Rust EvoPixel, Radio EvoPixel and bLeaH icons in one WOFF2 font. Icons inherit the surrounding text color and can be resized with CSS.

## Installation & Basic Usage

Copy the `css` and `webfonts` directories into your website's assets directory, keeping them next to each other.

```html
<link rel="stylesheet" href="assets/css/evopixel-icons.css">

<i class="evopixel-icon minecraft-evopixel" aria-hidden="true"></i>
```

Use `evopixel-icon` together with one of these classes:

| Icon | Class | Codepoint |
| --- | --- | --- |
| EvoPixel | `evopixel` | `U+E002` |
| Minecraft EvoPixel | `minecraft-evopixel` | `U+E001` |
| Rust EvoPixel | `rust-evopixel` | `U+E003` |
| Radio EvoPixel | `radio-evopixel` | `U+E005` |
| bLeaH | `bleah` | `U+E004` |

```css
.evopixel-icon {
  color: #ff5500;
  font-size: 32px;
}
```

For an icon-only button or link, add an accessible label to the button or link. Open `preview.html` to adjust the icon size, color and background, copy CSS classes, and compare the font with its SVG sources.

### CSS Bundles

The font URL is relative to the final stylesheet location. A stylesheet in `assets/css` or `assets/libs` resolves `../webfonts/evopixel-icons.woff2` to `assets/webfonts/evopixel-icons.woff2`.

When combining this CSS into a vendor bundle, include it after other icon libraries and keep the font in the corresponding `webfonts` directory. Publish the updated CSS bundle and font together.

## Updating the Font

Requires Python 3.11 or later. From the repository root, use an activated virtual environment and install the build tool:

```bash
python -m pip install -e ".[dev]"
evopixel-icons build
```

Dependencies and the `evopixel-icons` command are defined in `pyproject.toml`. The existing `python scripts/build.py` command remains available. Use `--root /path/to/evopixel-icons` when running the installed command from another directory.

Edit the vector files in `svgs`. Sources use a `0 0 1024 1024` viewBox and solid, nonzero filled paths. Convert groups, transforms, strokes, clipping and styling to path outlines before rebuilding; unsupported SVG features are reported instead of silently discarded.

For a new icon, add its SVG and an entry in `icons.json`. Keep existing class names and codepoints unchanged, assign a new unused codepoint, and update `project.version` in `pyproject.toml`. The order in `icons.json` controls the CSS rule order without changing the font's glyph order. Update the icon table and preview when adding or renaming icons.

The build writes `css/evopixel-icons.css` and `webfonts/evopixel-icons.woff2`, including a content-based font revision in the CSS URL. It also updates the stylesheet revision in `preview.html` so the preview loads the current build. SVG sources and build tools are not required on the website server.

Validate the committed outputs without rewriting files:

```bash
evopixel-icons check
```

The command exits with a nonzero status for invalid sources or outdated outputs. Builds validate both outputs before writing, skip unchanged files and restore earlier outputs if replacing a later file fails. Keep the pinned font dependencies for reproducible output.

Run the generator checks and formatting checks before publishing changes:

```bash
python -m unittest discover -s tests
ruff check .
ruff format --check .
```

## License

Licensed under the [MIT License](LICENSE).
