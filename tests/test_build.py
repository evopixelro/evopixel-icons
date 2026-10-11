import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import evopixel_icons as icons
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("pyproject.toml", "icons.json", "preview.html"):
            shutil.copyfile(ROOT / name, self.root / name)
        for name in ("svgs", "css", "webfonts"):
            shutil.copytree(ROOT / name, self.root / name)

    def run_command(self, command="build"):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = icons.main([command, "--root", str(self.root)])
        return status, output.getvalue(), errors.getvalue()

    def outputs(self):
        return {
            name: (self.root / name).read_bytes()
            for name in ("webfonts/evopixel-icons.woff2", "css/evopixel-icons.css", "preview.html")
        }

    def set_manifest(self, manifest):
        (self.root / "icons.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_build_preserves_published_glyphs_and_bytes(self):
        original = self.outputs()
        self.assertEqual(self.run_command()[0], 0)
        self.assertEqual(self.outputs(), original)
        with TTFont(io.BytesIO(original["webfonts/evopixel-icons.woff2"])) as font:
            self.assertEqual(
                font.getBestCmap(),
                {
                    0xE001: "minecraft-evopixel",
                    0xE002: "evopixel",
                    0xE003: "rust-evopixel",
                    0xE004: "bleah",
                    0xE005: "radio-evopixel",
                },
            )

    def test_build_skips_unchanged_files(self):
        paths = [self.root / name for name in self.outputs()]
        timestamps = [file.stat().st_mtime_ns for file in paths]
        self.assertEqual(self.run_command()[0], 0)
        self.assertEqual([file.stat().st_mtime_ns for file in paths], timestamps)

    def test_rule_order_does_not_change_font(self):
        manifest = json.loads((self.root / "icons.json").read_text(encoding="utf-8"))
        manifest["icons"].reverse()
        self.set_manifest(manifest)
        original_font = self.outputs()["webfonts/evopixel-icons.woff2"]
        self.assertEqual(self.run_command()[0], 0)
        self.assertEqual(self.outputs()["webfonts/evopixel-icons.woff2"], original_font)
        css = (self.root / "css/evopixel-icons.css").read_text(encoding="utf-8")
        positions = [css.index("." + item["name"] + ":before") for item in manifest["icons"]]
        self.assertEqual(positions, sorted(positions))

    def test_check_does_not_write_missing_or_outdated_outputs(self):
        font = self.root / "webfonts/evopixel-icons.woff2"
        css = self.root / "css/evopixel-icons.css"
        font.unlink()
        css.write_text("outdated", encoding="utf-8")
        status, _, errors = self.run_command("check")
        self.assertEqual(status, 1)
        self.assertIn("Outdated or missing outputs", errors)
        self.assertFalse(font.exists())
        self.assertEqual(css.read_text(encoding="utf-8"), "outdated")

    def test_check_accepts_current_outputs(self):
        self.assertEqual(self.run_command("check")[0], 0)

    def test_preview_revision_tracks_stylesheet(self):
        preview = self.root / "preview.html"
        markup = preview.read_text(encoding="utf-8")
        preview.write_text(
            markup.replace("evopixel-icons.css?v=", "evopixel-icons.css?v=000"), encoding="utf-8"
        )
        status, _, errors = self.run_command("check")
        self.assertEqual(status, 1)
        self.assertIn("preview.html", errors)
        self.assertEqual(self.run_command()[0], 0)
        revision = hashlib.sha256(self.outputs()["css/evopixel-icons.css"]).hexdigest()[:12]
        self.assertIn(f'evopixel-icons.css?v={revision}"', preview.read_text(encoding="utf-8"))

    def test_build_creates_missing_output_directories(self):
        shutil.rmtree(self.root / "css")
        shutil.rmtree(self.root / "webfonts")
        self.assertEqual(self.run_command()[0], 0)
        self.assertEqual(self.run_command("check")[0], 0)

    def test_invalid_manifests_preserve_outputs(self):
        original = self.outputs()
        cases = [[], {}, {"icons": []}, {"icons": [None]}, {"icons": [{}]}]
        valid = {"name": "evopixel", "label": "EvoPixel", "codepoint": "E002"}
        cases += [{"icons": [valid, valid]}]
        for key, value in [
            ("name", "../outside"),
            ("name", "evopixel-icon"),
            ("codepoint", 57346),
            ("codepoint", "F900"),
            ("codepoint", "0041"),
            ("label", ""),
        ]:
            cases.append({"icons": [{**valid, key: value}]})
        cases.append({"icons": [valid, {**valid, "name": "another-icon"}]})
        for manifest in cases:
            with self.subTest(manifest=manifest):
                self.set_manifest(manifest)
                status, _, errors = self.run_command()
                self.assertEqual(status, 1)
                self.assertIn("Error:", errors)
                self.assertEqual(self.outputs(), original)

    def test_invalid_json_has_a_clear_error(self):
        (self.root / "icons.json").write_text("{", encoding="utf-8")
        status, _, errors = self.run_command()
        self.assertEqual(status, 1)
        self.assertIn("Error:", errors)
        self.assertNotIn("Traceback", errors)

    def test_missing_source_preserves_outputs(self):
        original = self.outputs()
        (self.root / "svgs/evopixel.svg").unlink()
        status, _, errors = self.run_command()
        self.assertEqual(status, 1)
        self.assertIn("evopixel.svg", errors)
        self.assertEqual(self.outputs(), original)

    def test_unsupported_svg_features_are_not_silently_discarded(self):
        file = self.root / "svgs/evopixel.svg"
        original_svg, original = file.read_text(encoding="utf-8"), self.outputs()
        invalid = [
            original_svg.replace("<svg ", '<svg transform="translate(50 0)" ', 1),
            original_svg.replace("<path ", '<path style="display:none" ', 1),
            original_svg.replace("<path ", '<path fill-rule="evenodd" ', 1),
            original_svg.replace('fill="currentColor"', 'fill="none"'),
            original_svg.replace('viewBox="0 0 1024 1024"', 'viewBox="0 0 512 512"'),
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path d=""/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><rect/></svg>',
            "<svg>",
        ]
        for source in invalid:
            with self.subTest(source=source[:100]):
                file.write_text(source, encoding="utf-8")
                status, _, errors = self.run_command()
                self.assertEqual(status, 1)
                self.assertIn("evopixel.svg", errors)
                self.assertEqual(self.outputs(), original)

    def test_cubic_curves_are_converted_to_font_outlines(self):
        file = self.root / "svgs/evopixel.svg"
        file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,1024,1024">'
            '<path d="M100 100 C200 100 200 200 100 200 Z"/></svg>',
            encoding="utf-8",
        )
        self.assertEqual(self.run_command()[0], 0)
        self.assertEqual(self.run_command("check")[0], 0)

    def test_failed_second_write_restores_first_output(self):
        first, second = self.root / "first.css", self.root / "second.css"
        first.write_bytes(b"old first")
        second.write_bytes(b"old second")
        replace = os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("Simulated write failure")
            return replace(source, destination)

        with patch.object(icons.os, "replace", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                icons.write_outputs({first: b"new first", second: b"new second"})
        self.assertEqual(first.read_bytes(), b"old first")
        self.assertEqual(second.read_bytes(), b"old second")
        self.assertEqual(list(self.root.glob(".first.css.*")), [])
        self.assertEqual(list(self.root.glob(".second.css.*")), [])

    def test_failed_rollback_keeps_recovery_copy(self):
        first, second = self.root / "first.css", self.root / "second.css"
        first.write_bytes(b"old first")
        second.write_bytes(b"old second")
        replace = os.replace
        calls = 0

        def fail_after_first(source, destination):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise PermissionError("Simulated storage failure")
            return replace(source, destination)

        with patch.object(icons.os, "replace", side_effect=fail_after_first):
            with self.assertRaisesRegex(OSError, "Could not restore outputs"):
                icons.write_outputs({first: b"new first", second: b"new second"})
        backups = list(self.root.glob(".first.css.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"old first")


if __name__ == "__main__":
    unittest.main()
