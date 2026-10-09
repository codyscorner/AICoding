# S3 Browser

PyQt6 file-explorer-style browser for RunPod's S3-compatible network-volume storage. Browse, upload, download, and delete objects on a RunPod volume without the RunPod web console.

## Features

- File-explorer UI: breadcrumb navigation, sortable columns (name / size / type / last modified), folder and file icons
- Upload and download files or whole folders, with progress
- Downloads skip files already present locally when size + MD5 match the S3 ETag (RunPod ETag = content MD5)
- Downloads never overwrite an existing local file — a collision is saved as `name (1).ext` and reported after the transfer
- Transfers retry with exponential backoff (6 attempts, 1s→16s) — works around RunPod's transient `403 Forbidden` on the SDK's internal `HeadObject` call
- App settings (`config.json`) live next to the EXE (portable — runs from a thumb drive); never in `%APPDATA%`
- Credentials stored in the standard AWS credentials file (`~/.aws/credentials`) under their own profile — never in the app config or repo

## RunPod S3 API quirks (learned the hard way)

- RunPod's S3 endpoint can return a transient `403` on `HeadObject` for an object that's perfectly accessible on retry — hence the backoff retries on every transfer
- After `CompleteMultipartUpload`, RunPod merges the uploaded chunks server-side (visible as `.s3compat-merge-*.tmp` in the console) with no response until done — multi-GB files take minutes, so the client uses a 30-minute `read_timeout` and the UI shows a "waiting on S3 to merge" message; upload retries `HeadObject` the key first so a lost merge response never triggers a full re-upload
- Endpoint and region follow the datacenter of the network volume (e.g. `https://s3api-eur-is-1.runpod.io`)

## Layout

| File | Purpose |
|------|---------|
| `run.py` | Entry point |
| `s3_browser/main_window.py` | Explorer UI |
| `s3_browser/s3_client.py` | boto3 wrapper with retry/backoff |
| `s3_browser/workers.py` | Background transfer threads |
| `s3_browser/settings_dialog.py` | Endpoint/credentials setup |
| `s3_browser/config.py` | Config + AWS credentials-file handling |
| `app_icon.ico` | App icon (taskbar, window, EXE) — regenerate with `IconMaker/make_icons.py` |

## Building the EXE

```
pyinstaller S3Browser.spec
```

`S3Browser.spec` is gitignored (`*.spec`), so it exists only on the build machine. If it has to be recreated, it needs `datas=[('app_icon.ico', '.')]` and `icon=['app_icon.ico']` in `EXE(...)` — the first bundles the icon for the window/taskbar, the second embeds it in the EXE for Explorer and shortcuts.

Deployed EXE: `P:\Apps\VibeCoded\S3 Browser\`

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.
