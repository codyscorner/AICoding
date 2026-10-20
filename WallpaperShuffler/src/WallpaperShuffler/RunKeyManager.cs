using Microsoft.Win32;

namespace WallpaperShuffler
{
    /// <summary>
    /// HKCU Run key: launches the EXE with --tray at logon (no admin needed). The tray instance
    /// changes the wallpaper on launch and again on every workstation unlock.
    /// </summary>
    public static class RunKeyManager
    {
        private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string ValueName = "WallpaperShuffler";
        public const string LaunchArgument = "--tray";

        public static void Enable(string exePath)
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, true);
            key?.SetValue(ValueName, Command(exePath), RegistryValueKind.String);
        }

        public static void Disable()
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, true);
            key?.DeleteValue(ValueName, false);
        }

        public static bool IsEnabled()
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath);
            return key?.GetValue(ValueName) != null;
        }

        /// <summary>Rewrites the command if the EXE moved or the value still uses the old --apply argument.</summary>
        public static void UpdatePathIfNeeded(string exePath)
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, true);
            if (key == null)
                return;

            var current = key.GetValue(ValueName) as string;
            if (current != null && current != Command(exePath))
                key.SetValue(ValueName, Command(exePath), RegistryValueKind.String);
        }

        private static string Command(string exePath) => $"\"{exePath}\" {LaunchArgument}";
    }
}
