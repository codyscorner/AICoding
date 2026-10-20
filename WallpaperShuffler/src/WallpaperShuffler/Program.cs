using System.Windows.Forms;

namespace WallpaperShuffler
{
    internal static class Program
    {
        private static Mutex? _instanceMutex;
        private const string MutexName = "WallpaperShuffler_Mutex";

        /// <summary>
        /// Launch modes:
        ///   --tray           Run key at logon: start in the tray, change wallpaper now, change again on every unlock.
        ///   (no args)        Open settings. If a tray instance is already running, ask it to show its window instead.
        ///   --apply / --next One-shot headless change for scripts; exits immediately.
        /// </summary>
        [STAThread]
        static void Main(string[] args)
        {
            AppPaths.SetTaskbarIdentity();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool headless = args.Any(a => a == "--apply" || a == "--next");
            bool tray = args.Any(a => a == RunKeyManager.LaunchArgument);

            if (headless)
            {
                ApplyOnce();
                return;
            }

            if (!AcquireMutex())
            {
                // A tray instance is already running: hand it the request to show settings.
                try
                {
                    using var evt = EventWaitHandle.OpenExisting(TrayApplication.ShowSettingsEventName);
                    evt.Set();
                }
                catch { }
                return;
            }

            try
            {
                Application.Run(new TrayApplication(applyOnStart: tray, showSettingsOnStart: !tray));
            }
            catch (Exception ex)
            {
                LogError($"Fatal: {ex}");
                MessageBox.Show($"Error: {ex.Message}", "Wallpaper Shuffler Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                ReleaseMutex();
            }
        }

        private static void ApplyOnce()
        {
            try
            {
                var shuffleBag = new ShuffleBag(AppPaths.StateFile);
                var folder = shuffleBag.Folder ?? AppPaths.DefaultFolder;

                var nextImage = shuffleBag.GetNextImage(folder);
                if (nextImage == null)
                {
                    LogError($"No images found in \"{folder}\"");
                    return;
                }

                if (!WallpaperApi.SetWallpaper(nextImage, shuffleBag.FitMode))
                    LogError($"SystemParametersInfo failed for \"{nextImage}\"");
            }
            catch (Exception ex)
            {
                LogError($"Error applying wallpaper: {ex.Message}");
            }
        }

        private static bool AcquireMutex()
        {
            try
            {
                _instanceMutex = new Mutex(true, MutexName, out bool createdNew);
                if (!createdNew)
                {
                    _instanceMutex.Dispose();
                    _instanceMutex = null;
                    return false;
                }
                return true;
            }
            catch
            {
                return true;
            }
        }

        private static void ReleaseMutex()
        {
            try
            {
                _instanceMutex?.ReleaseMutex();
                _instanceMutex?.Dispose();
            }
            catch { }
        }

        public static void LogError(string message)
        {
            try
            {
                File.AppendAllText(AppPaths.ErrorLog, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} - {message}\n");
            }
            catch { }
        }
    }
}
