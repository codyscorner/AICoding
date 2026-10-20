using System.Drawing;
using System.Runtime.InteropServices;

namespace WallpaperShuffler
{
    /// <summary>Portable layout: every file the app owns sits next to the EXE.</summary>
    internal static class AppPaths
    {
        public const string Version = "1.1.0";

        public const string DefaultFolder = @"D:\Pictures\Wallpaper\Seasonal\Halloween 26";

        public static string ExePath =>
            Environment.ProcessPath ?? System.Windows.Forms.Application.ExecutablePath;

        public static string ExeFolder =>
            Path.GetDirectoryName(ExePath) ?? AppContext.BaseDirectory;

        public static string StateFile => Path.Combine(ExeFolder, "state.json");

        public static string ErrorLog => Path.Combine(ExeFolder, "error.log");

        /// <summary>Taskbar identity so Windows groups the window under this app's icon.</summary>
        public const string AppUserModelId = "codyscorner.WallpaperShuffler";

        [DllImport("shell32.dll", SetLastError = true)]
        private static extern int SetCurrentProcessExplicitAppUserModelID([MarshalAs(UnmanagedType.LPWStr)] string appId);

        public static void SetTaskbarIdentity()
        {
            try { SetCurrentProcessExplicitAppUserModelID(AppUserModelId); } catch { }
        }

        /// <summary>Window/title-bar icon from the embedded resource (the EXE icon only covers Explorer and shortcuts).</summary>
        public static Icon? LoadIcon()
        {
            try
            {
                using var stream = typeof(AppPaths).Assembly.GetManifestResourceStream("app_icon.ico");
                return stream == null ? null : new Icon(stream);
            }
            catch { return null; }
        }
    }
}
