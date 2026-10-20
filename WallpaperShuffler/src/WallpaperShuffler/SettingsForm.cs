using System.Windows.Forms;

namespace WallpaperShuffler
{
    public class SettingsForm : Form
    {
        private readonly TrayApplication _app;
        private readonly ShuffleBag _shuffleBag;
        private string _currentFolder;

        private static readonly Color NavyDark = Color.FromArgb(20, 30, 48);
        private static readonly Color NavyMedium = Color.FromArgb(30, 45, 70);
        private static readonly Color NavyLight = Color.FromArgb(200, 210, 230);
        private static readonly Color AccentBlue = Color.FromArgb(100, 150, 255);

        private TextBox _folderTextBox = null!;
        private Button _browseButton = null!;
        private ComboBox _fitModeCombo = null!;
        private Button _changeNowButton = null!;
        private CheckBox _runAtLoginCheckbox = null!;
        private Label _statusLabel = null!;

        public SettingsForm(TrayApplication app)
        {
            _app = app;
            _shuffleBag = app.ShuffleBag;
            _currentFolder = _shuffleBag.Folder ?? AppPaths.DefaultFolder;

            BackColor = NavyDark;
            ForeColor = NavyLight;
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            var mainLayout = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                Padding = new Padding(15),
                RowCount = 7,
                ColumnCount = 2,
                BackColor = NavyDark
            };
            for (int i = 0; i < 6; i++)
                mainLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            mainLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            mainLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            mainLayout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));

            mainLayout.Controls.Add(CreateLabel("Image Folder:"), 0, 0);

            _folderTextBox = new TextBox
            {
                Text = _currentFolder,
                ReadOnly = true,
                Dock = DockStyle.Fill,
                BackColor = NavyMedium,
                ForeColor = NavyLight,
                BorderStyle = BorderStyle.FixedSingle,
                Margin = new Padding(0, 0, 5, 0)
            };
            mainLayout.Controls.Add(_folderTextBox, 0, 1);

            _browseButton = CreateButton("Browse");
            _browseButton.Click += (s, e) => BrowseFolder();
            mainLayout.Controls.Add(_browseButton, 1, 1);

            mainLayout.Controls.Add(CreateLabel("Fit Mode:"), 0, 2);

            _fitModeCombo = new ComboBox
            {
                DataSource = Enum.GetValues(typeof(WallpaperFitMode)),
                BackColor = NavyMedium,
                ForeColor = NavyLight,
                DropDownStyle = ComboBoxStyle.DropDownList,
                Width = 150
            };
            _fitModeCombo.SelectedItem = _shuffleBag.FitMode;
            _fitModeCombo.SelectedIndexChanged += (s, e) =>
            {
                if (_fitModeCombo.SelectedItem is WallpaperFitMode mode)
                    _shuffleBag.FitMode = mode;
            };
            mainLayout.Controls.Add(_fitModeCombo, 0, 3);

            _changeNowButton = CreateButton("Change Now");
            _changeNowButton.Click += (s, e) => ChangeNow();
            mainLayout.Controls.Add(_changeNowButton, 1, 3);

            mainLayout.Controls.Add(CreateLabel("Start in tray at login (changes wallpaper at login and every unlock):"), 0, 4);

            _runAtLoginCheckbox = new CheckBox
            {
                AutoSize = true,
                BackColor = NavyDark,
                ForeColor = NavyLight,
                Checked = RunKeyManager.IsEnabled()
            };
            _runAtLoginCheckbox.CheckedChanged += (s, e) => ToggleRunAtLogin();
            mainLayout.Controls.Add(_runAtLoginCheckbox, 0, 5);

            _statusLabel = CreateLabel("");
            _statusLabel.ForeColor = AccentBlue;
            mainLayout.Controls.Add(_statusLabel, 0, 6);
            mainLayout.SetColumnSpan(_statusLabel, 2);

            Controls.Add(mainLayout);

            Text = $"Wallpaper Shuffler v{AppPaths.Version}";
            Width = 500;
            Height = 350;
            StartPosition = FormStartPosition.CenterScreen;
            Icon = AppPaths.LoadIcon();
        }

        private Label CreateLabel(string text)
        {
            return new Label
            {
                Text = text,
                AutoSize = true,
                BackColor = NavyDark,
                ForeColor = NavyLight,
                Margin = new Padding(0, 5, 0, 5)
            };
        }

        private Button CreateButton(string text)
        {
            var button = new Button
            {
                Text = text,
                Width = 100,
                Height = 32,
                BackColor = AccentBlue,
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 10),
                Cursor = Cursors.Hand
            };
            button.FlatAppearance.BorderSize = 0;
            return button;
        }

        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            RunKeyManager.UpdatePathIfNeeded(AppPaths.ExePath);
            SyncAndRefresh();
        }

        /// <summary>Reconcile the file table with disk (no status changes) and refresh the status line.</summary>
        private void SyncAndRefresh()
        {
            if (!_shuffleBag.Sync(_currentFolder))
            {
                _statusLabel.Text = "Folder not found.";
                return;
            }
            UpdateStatusLabel();
        }

        private void BrowseFolder()
        {
            using var dialog = new FolderBrowserDialog
            {
                Description = "Select a folder containing wallpaper images",
                SelectedPath = _currentFolder
            };

            if (dialog.ShowDialog() == DialogResult.OK)
            {
                _currentFolder = dialog.SelectedPath;
                _folderTextBox.Text = _currentFolder;
                SyncAndRefresh();
            }
        }

        private void ChangeNow()
        {
            if (!Directory.Exists(_currentFolder))
            {
                MessageBox.Show("Selected folder does not exist.", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            _shuffleBag.Sync(_currentFolder);
            var error = _app.ApplyNext("settings window");
            if (error != null)
                MessageBox.Show(error, "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            UpdateStatusLabel();
        }

        private void ToggleRunAtLogin()
        {
            if (_runAtLoginCheckbox.Checked)
                RunKeyManager.Enable(AppPaths.ExePath);
            else
                RunKeyManager.Disable();
            UpdateStatusLabel();
        }

        /// <summary>Called by the tray app after an unlock/menu change so an open window stays current.</summary>
        public void RefreshStatus()
        {
            if (!IsDisposed && IsHandleCreated)
                UpdateStatusLabel();
        }

        private void UpdateStatusLabel()
        {
            var remaining = _shuffleBag.GetRemainingImagesInCycle();
            var total = _shuffleBag.TotalImages;
            var last = _shuffleBag.LastShown != null ? Path.GetFileName(_shuffleBag.LastShown) : "(none)";
            _statusLabel.Text = $"Remaining in cycle: {remaining} of {total}\nLast shown: {last}";
        }
    }
}
