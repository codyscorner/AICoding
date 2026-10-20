using System.Windows.Forms;
using Microsoft.Win32;

namespace WallpaperShuffler
{
    /// <summary>
    /// Resident tray instance. Owns the shuffle bag, the tray icon, and the (lazily created)
    /// settings window. Changes the wallpaper:
    ///   - on launch when started with --tray (the Run key at logon),
    ///   - on every SessionUnlock (lock screen, Windows Hello, resume-with-lock),
    ///   - on "Change Now" from the tray menu or the settings window.
    /// Everything runs on the UI thread; SystemEvents delivers SessionSwitch there because
    /// WinForms keeps a message loop alive.
    /// </summary>
    public class TrayApplication : ApplicationContext
    {
        /// <summary>Named event a second launch sets to ask the running instance to show settings.</summary>
        public const string ShowSettingsEventName = "WallpaperShuffler_ShowSettings";

        private readonly ShuffleBag _shuffleBag;
        private readonly NotifyIcon _trayIcon;
        private readonly EventWaitHandle _showSettingsEvent;
        private readonly Thread _showSettingsListener;
        private readonly Control _marshal = new();   // hidden control used only to BeginInvoke onto the UI thread
        private SettingsForm? _settingsForm;
        private bool _exiting;

        public TrayApplication(bool applyOnStart, bool showSettingsOnStart)
        {
            _shuffleBag = new ShuffleBag(AppPaths.StateFile);
            _marshal.CreateControl();

            _trayIcon = new NotifyIcon
            {
                Icon = AppPaths.LoadIcon() ?? SystemIcons.Application,
                Text = $"Wallpaper Shuffler v{AppPaths.Version}",
                Visible = true,
                ContextMenuStrip = BuildMenu()
            };
            _trayIcon.DoubleClick += (s, e) => ShowSettings();

            SystemEvents.SessionSwitch += OnSessionSwitch;

            _showSettingsEvent = new EventWaitHandle(false, EventResetMode.AutoReset, ShowSettingsEventName);
            _showSettingsListener = new Thread(ListenForShowSettings) { IsBackground = true, Name = "ShowSettingsListener" };
            _showSettingsListener.Start();

            if (applyOnStart)
                ApplyNext("launch");

            if (showSettingsOnStart)
                ShowSettings();
        }

        private ContextMenuStrip BuildMenu()
        {
            var menu = new ContextMenuStrip();
            menu.Items.Add("Change Now", null, (s, e) => ApplyNext("tray menu"));
            menu.Items.Add("Settings...", null, (s, e) => ShowSettings());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Exit", null, (s, e) => ExitApplication());
            return menu;
        }

        private void OnSessionSwitch(object sender, SessionSwitchEventArgs e)
        {
            if (e.Reason == SessionSwitchReason.SessionUnlock || e.Reason == SessionSwitchReason.SessionLogon)
                ApplyNext(e.Reason.ToString());
        }

        /// <summary>Pick the next image and set it. Returns null on success, else a user-facing error.</summary>
        public string? ApplyNext(string trigger)
        {
            try
            {
                var folder = _shuffleBag.Folder ?? AppPaths.DefaultFolder;
                var next = _shuffleBag.GetNextImage(folder);
                if (next == null)
                    return $"No images found in \"{folder}\".";

                if (!WallpaperApi.SetWallpaper(next, _shuffleBag.FitMode))
                    return $"Windows refused to set \"{Path.GetFileName(next)}\".";

                _settingsForm?.RefreshStatus();
                return null;
            }
            catch (Exception ex)
            {
                Program.LogError($"[{trigger}] {ex.Message}");
                return ex.Message;
            }
        }

        public ShuffleBag ShuffleBag => _shuffleBag;

        public void ShowSettings()
        {
            if (_settingsForm == null || _settingsForm.IsDisposed)
            {
                _settingsForm = new SettingsForm(this);
                _settingsForm.FormClosing += (s, e) =>
                {
                    // Closing the window hides to tray; Exit in the tray menu really quits.
                    if (!_exiting && e.CloseReason == CloseReason.UserClosing)
                    {
                        e.Cancel = true;
                        _settingsForm.Hide();
                    }
                };
            }

            _settingsForm.Show();
            if (_settingsForm.WindowState == FormWindowState.Minimized)
                _settingsForm.WindowState = FormWindowState.Normal;
            _settingsForm.Activate();
        }

        private void ListenForShowSettings()
        {
            while (!_exiting)
            {
                _showSettingsEvent.WaitOne();
                if (_exiting)
                    break;
                try { _marshal.BeginInvoke(new Action(ShowSettings)); } catch { }
            }
        }

        private void ExitApplication()
        {
            _exiting = true;
            SystemEvents.SessionSwitch -= OnSessionSwitch;
            _trayIcon.Visible = false;
            _trayIcon.Dispose();
            try { _showSettingsEvent.Set(); } catch { }
            _settingsForm?.Close();
            ExitThread();
        }
    }
}
