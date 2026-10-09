# S3 Browser — Changelog

## v1.0.9 (2026-10-08)
- Added an app icon (`app_icon.ico`, generated with IconMaker: glowing cyan cloud over a folder with up/down arrows on navy; 16/32/48/256 px). Previously the window, taskbar and EXE all showed the default icon.
- The icon shows on the taskbar (own `AppUserModelID`, so Windows no longer groups it under python.exe), the title bar and every dialog (app-level icon), and is embedded in the EXE for Explorer, desktop shortcuts and the Start menu (`S3Browser.spec` `icon=`).
- The icon is also bundled as data and resolved through PyInstaller's unpack folder when frozen.

## v1.0.8 (2026-09-04)
- Downloads now skip files you already have. If the destination has a file with the same name, the app compares size and MD5 against the object's S3 ETag (RunPod stores the plain content MD5 - verified against a 44MB video) and skips the download when they match, so re-grabbing a batch of clips never leaves `name (1).mp4` duplicates. Different content under the same name is still saved as `name (N).ext`.
- Objects with a composite multipart ETag (`...-N`, only seen on multi-GB model files) can't be compared without the bytes: those download under a new name, then the copy is hashed and deleted if it turns out identical.
- The end-of-transfer dialog now lists both skipped-identical and renamed files.

## v1.0.7 (2026-09-04)
- `config.json` (profile/region/endpoint/bucket) now lives next to the EXE (`P:\Apps\VibeCoded\S3 Browser\config.json`; project root when run from source) instead of the hidden `%APPDATA%\S3Browser\` folder, so it is always easy to find. An existing AppData config is copied over automatically on first launch (the old file is left in place). Credentials stay in `~/.aws/credentials` as before.
- Settings dialog now shows the full path of the settings file.

## v1.0.6 (2026-09-04)
- Downloads no longer overwrite existing local files. If the destination already has a file with the same name, the download is saved as `name (1).ext`, `name (2).ext`, ... (first free number) instead. Applies to single-file and recursive folder downloads. Previously the download went straight through boto3's `download_file`, which silently replaced whatever was on disk.
- After a transfer, a dialog lists every file that was renamed this way (original name -> saved name) so you know which ones to look at.

## v1.0.5 (2026-08-28)
- Fixed connection settings (bucket/region/endpoint/profile) never being saved to disk — `save_config` existed but was never called, so OK in the Settings dialog only updated the running process and every restart fell back to `config.json`'s last saved state or the built-in defaults. Present since v1.0.0; masked by long-running app instances. Credentials were unaffected (always written to `~/.aws/credentials`).

## v1.0.4 (2026-08-28)
- Large multipart uploads no longer look frozen (or worse, silently restart) while RunPod merges the uploaded chunks server-side (`.s3compat-merge-*.tmp` in the console):
  - Progress dialog now switches to "All data sent — waiting on S3 to merge <file>" once every byte is on the wire, with a note that no transfer progress is shown during the merge
  - During the merge wait, a background poller lists the destination folder every 5s and reports whether the `.s3compat-merge-*.tmp` file is still present (with its size and elapsed time), so you can see the merge is alive
  - boto3 `read_timeout` raised from the 60s default to 30 minutes so the client waits out the merge instead of timing out on `CompleteMultipartUpload` and re-uploading the whole file
  - Upload retries now `HeadObject` the key first and skip the re-upload when the object already landed at the expected size (e.g. the merge finished but the response was lost)

## v1.0.3 (2026-08-07)
- Transfer retries bumped from 3 attempts (flat 1s delay) to 6 attempts with exponential backoff (1s/2s/4s/8s/16s) — RunPod's transient 403 on `HeadObject` during downloads was still outlasting the old fixed 1s retry window on some days

## v1.0.2 (2026-08-06)
- Fixed Size/Type/Last Modified columns being stuck at their initial width — Qt's default `stretchLastSection` was locking the last column, now all three are freely drag-resizable with sensible starting widths
- Window title now shows the app version (`S3 Browser v1.0.2`)

## v1.0.1 (2026-08-06)
- Upload/download of individual files now retries up to 3 times (1s apart) before reporting a failure — RunPod's endpoint was seen returning a transient `403 Forbidden` on the SDK's internal `HeadObject` call during folder downloads even though the object was perfectly accessible on retry

## v1.0.0 (2026-08-06)
- Initial release: PyQt6 file-explorer-style browser for RunPod's S3-compatible storage
- Breadcrumb navigation, sortable table (name/size/type/modified) with folder/file icons
- Upload files or whole folders (drag-and-drop from Explorer, or toolbar dialogs), preserving nested folder structure
- Download files or folders (recursive) to a chosen local destination, with a byte-accurate progress dialog
- New folder, rename (copy+delete, works on files and folders), delete (multi-select, confirmation prompt)
- Right-click context menu; F2 rename, Delete key, F5 refresh shortcuts
- Settings dialog to change bucket/region/endpoint/profile and update AWS credentials without leaving the app
- Credentials are stored only in the local AWS credentials file (`~/.aws/credentials`), never duplicated into the app's own config
- Connected to bucket `zyg8x1wtwr` on RunPod datacenter `us-ca-2` (`https://s3api-us-ca-2.runpod.io`)

### RunPod S3 compatibility fixes found during testing
- RunPod's endpoint rejects the bulk `DeleteObjects` API with `307 Temporary Redirect` — the client deletes objects one at a time (`delete_object`) instead
- RunPod's backend leaves empty "ghost" directory nodes behind after all files inside are deleted (`DeleteObject` on the folder key fails with `InvalidArgument: directory not empty` even when `ListObjectsV2` shows it as empty) — folder deletes now also walk and delete every nested directory path bottom-up as a best-effort cleanup so no empty folders are left behind
