import json
import tempfile
import unittest
from pathlib import Path

from scenes import ORDER_SHUFFLE, SceneLibrary


def make(tmp, snippets=("A", "B", "C")):
    lib = SceneLibrary(Path(tmp) / "scenes.json")
    lib.add_tag("bedroom")
    for s in snippets:
        lib.add_snippet("bedroom", s.lower(), s)
    return lib


class SceneTests(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.tmp = self._d.name

    def tearDown(self):
        self._d.cleanup()

    def test_render_uses_current(self):
        lib = make(self.tmp)
        self.assertEqual(lib.render("In {{bedroom}}!")[0], "In A!")
        lib.step("bedroom", 1)
        self.assertEqual(lib.render("In {{bedroom}}!")[0], "In B!")

    def test_missing_tag_reported(self):
        lib = make(self.tmp)
        text, missing = lib.render("{{bedroom}} {{kitchen}}")
        self.assertEqual(text, "A {{kitchen}}")
        self.assertEqual(missing, ["kitchen"])

    def test_step_wraps(self):
        lib = make(self.tmp)
        lib.step("bedroom", -1)
        self.assertEqual(lib.current_index("bedroom"), 2)
        lib.step("bedroom", 1)
        self.assertEqual(lib.current_index("bedroom"), 0)

    def test_advance_sequential_marks_used_and_exhausts(self):
        lib = make(self.tmp)
        self.assertEqual(lib.advance(["bedroom"]), [])
        self.assertEqual(lib.current_index("bedroom"), 1)
        self.assertEqual(lib.advance(["bedroom"]), [])
        self.assertEqual(lib.current_index("bedroom"), 2)
        self.assertEqual(lib.advance(["bedroom"]), ["bedroom"])      # all three used
        self.assertEqual(lib.current_index("bedroom"), 2)            # stays put
        self.assertEqual(lib.used_count("bedroom"), 3)
        lib.reset_used("bedroom")
        self.assertEqual(lib.used_count("bedroom"), 0)

    def test_advance_skips_used_after_manual_jump(self):
        lib = make(self.tmp)
        lib.advance(["bedroom"])          # A used -> B
        lib.set_current("bedroom", 0)     # jump back to the used A
        lib.advance(["bedroom"])          # A already used; next unused is B
        self.assertEqual(lib.current_index("bedroom"), 1)

    def test_advance_shuffle_never_repeats(self):
        lib = make(self.tmp, snippets=tuple("ABCDEFGH"))
        lib.set_options(order=ORDER_SHUFFLE)
        seen = [lib.current_index("bedroom")]
        for _ in range(7):
            self.assertEqual(lib.advance(["bedroom"]), [])
            seen.append(lib.current_index("bedroom"))
        self.assertEqual(sorted(seen), list(range(8)))
        self.assertEqual(lib.advance(["bedroom"]), ["bedroom"])

    def test_delete_current_moves_on(self):
        lib = make(self.tmp)
        lib.set_current("bedroom", 1)
        lib.delete_snippet("bedroom", lib.snippets("bedroom")[1]["id"])
        self.assertEqual(lib.render("{{bedroom}}")[0], "C")

    def test_persists(self):
        lib = make(self.tmp)
        lib.advance(["bedroom"])
        lib.set_options(auto_advance=False)
        again = SceneLibrary(Path(self.tmp) / "scenes.json")
        self.assertEqual(again.current_index("bedroom"), 1)
        self.assertEqual(again.used_count("bedroom"), 1)
        self.assertFalse(again.auto_advance)

    def test_bad_tag_name_refused(self):
        lib = make(self.tmp)
        self.assertFalse(lib.add_tag("two words"))
        self.assertFalse(lib.add_tag("bedroom"))

    def test_import_paste(self):
        lib = make(self.tmp, snippets=())
        n = lib.import_paste("bedroom", "1. Cozy Cabin\n\nWarm room.\n\n2. Loft\n\nBright room.\n")
        self.assertEqual(n, 2)
        self.assertEqual([s["name"] for s in lib.snippets("bedroom")], ["Cozy Cabin", "Loft"])
        self.assertEqual(lib.render("{{bedroom}}")[0], "Warm room.")

    def test_import_placeholder_merges_without_dupes(self):
        p = Path(self.tmp) / "data.json"
        p.write_text(json.dumps({"body": "x", "tags": {
            "bedroom": {"snippets": [{"name": "n", "text": "A"}, {"name": "m", "text": "NEW"}]},
            "lights": {"snippets": [{"name": "", "text": "dim"}]}}}), encoding="utf-8")
        lib = make(self.tmp)
        tags, added = lib.import_placeholder(p)
        self.assertEqual((tags, added), (2, 2))                      # "A" already there
        self.assertEqual(len(lib.snippets("bedroom")), 4)
        self.assertEqual(lib.render("{{lights}}")[0], "dim")


if __name__ == "__main__":
    unittest.main()
