# Changelog

## v1.0.1
- Added an app icon (`app_icon.ico`, generated with IconMaker: violet clipboard with ticks on navy; 16/32/48/256 px).
- Icon now shows on the taskbar (own `AppUserModelID`, so Windows no longer groups it under python.exe), the title bar, and every dialog (app-level icon).
- Icon is embedded in `TodoList.exe` (Explorer / desktop) and the build script sets the desktop shortcut's `IconLocation` explicitly.
- Bundled icon is now found in PyInstaller's unpack folder when frozen; it was previously looked up next to the EXE, where it never was.

## v1.0.0
- Initial release.
