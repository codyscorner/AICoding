"""File-type presets and masks (copied from Burn List Creator; same convention as FolderSync / File Copy Move Manager):
a preset is a name -> comma-separated wildcard string, and a mask is comma-separated
wildcards (`*.mp4, *.mkv`) where a bare `mp4` or `.pdf` means `*.mp4` / `*.pdf`.

A *selection* is a list of strings; each is a preset name (case-insensitive) or a mask.
An empty selection, "All Files", `*.*` or `*` matches everything. "Other" matches files
that belong to no preset (handy for the leftovers disc).
"""
import fnmatch
import os
import re

# Presets copied from FolderSync / File Copy Move Manager, plus archive-minded extras:
# camera RAW + PSD under Images, m2ts/mts/vob under Videos. `.ts` lives under Videos only
# (it is Code in the other apps) so a video disc never swallows TypeScript sources.
PRESETS = {
    "All Files": "*.*",
    "Archives": "*.zip, *.rar, *.7z, *.tar, *.gz, *.bz2, *.xz, *.iso",
    "Audio": "*.mp3, *.wav, *.flac, *.aac, *.ogg, *.wma, *.m4a, *.opus, *.aiff, *.alac",
    "Code": "*.py, *.js, *.html, *.css, *.java, *.cpp, *.c, *.h, *.cs, *.php, *.rb, *.go, *.rs, *.swift",
    "Data": "*.json, *.xml, *.csv, *.yaml, *.yml, *.sql, *.db, *.sqlite, *.mdb",
    "Documents": "*.pdf, *.doc, *.docx, *.xls, *.xlsx, *.ppt, *.pptx, *.txt, *.rtf, *.odt, *.ods, *.odp",
    "Images": "*.jpg, *.jpeg, *.png, *.gif, *.bmp, *.tiff, *.tif, *.webp, *.svg, *.ico, *.raw, *.heic, *.heif, "
              "*.jfif, *.avif, *.psd, *.dng, *.cr2, *.cr3, *.nef, *.arw, *.orf, *.rw2",
    "Videos": "*.mp4, *.avi, *.mkv, *.mov, *.wmv, *.flv, *.webm, *.m4v, *.mpeg, *.mpg, *.3gp, *.ts, "
              "*.m2ts, *.mts, *.vob",
}
OTHER = "other"
_ALL = {"*.*", "*"}
_EXT_ONLY = re.compile(r"\*\.([^*?\[\].]+)$")          # "*.mp4" -> fast extension lookup


def parse_mask(mask: str) -> list:
    """'*.mp4, mkv, .pdf' -> ['*.mp4', '*.mkv', '*.pdf'] (lowercase)."""
    out = []
    for part in mask.split(","):
        p = part.strip().lower()
        if not p:
            continue
        if "*" not in p and "?" not in p:
            p = "*." + p.lstrip(".")
        out.append(p)
    return out


class Matcher:
    """Callable: matcher(filename) -> bool."""

    def __init__(self, selection=None, presets=None):
        presets = {k.lower(): v for k, v in (presets or PRESETS).items()}
        known: list = []
        for name, mask in presets.items():
            if name != "all files":
                known += parse_mask(mask)
        self._known_exts, self._known_globs = self._split(known)

        globs, self._other, self._all = [], False, not selection
        for item in selection or []:
            key = item.strip().lower()
            if key == OTHER:
                self._other = True
            elif key in presets:
                globs += parse_mask(presets[key])
            else:
                globs += parse_mask(item)
        if any(g in _ALL for g in globs):
            self._all = True
        self._exts, self._globs = self._split(globs)

    @staticmethod
    def _split(globs):
        exts, rest = set(), []
        for g in globs:
            m = _EXT_ONLY.fullmatch(g)
            if m:
                exts.add(m.group(1))
            else:
                rest.append(g)
        return exts, rest

    def __call__(self, name: str) -> bool:
        if self._all:
            return True
        n = name.lower()
        ext = os.path.splitext(n)[1].lstrip(".")
        if ext in self._exts or any(fnmatch.fnmatchcase(n, g) for g in self._globs):
            return True
        return self._other and ext not in self._known_exts \
            and not any(fnmatch.fnmatchcase(n, g) for g in self._known_globs)
