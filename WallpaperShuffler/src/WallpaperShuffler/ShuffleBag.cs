using Newtonsoft.Json;
using Newtonsoft.Json.Converters;

namespace WallpaperShuffler
{
    /// <summary>Per-file row status. A file is shown again only after every other file has been shown.</summary>
    [JsonConverter(typeof(StringEnumConverter))]
    public enum FileStatus
    {
        Unused,
        Used
    }

    /// <summary>Everything persisted to state.json: settings plus the file table.</summary>
    public class ShuffleBagState
    {
        [JsonProperty("folder")]
        public string? Folder { get; set; }

        [JsonProperty("fitMode")]
        [JsonConverter(typeof(StringEnumConverter))]
        public WallpaperFitMode FitMode { get; set; } = WallpaperFitMode.Fill;

        /// <summary>Full image path -> status. Acts as the "files" table.</summary>
        [JsonProperty("files")]
        public Dictionary<string, FileStatus> Files { get; set; } = new(StringComparer.OrdinalIgnoreCase);

        [JsonProperty("lastShown")]
        public string? LastShown { get; set; }
    }

    /// <summary>
    /// Shuffle bag backed by a status table. Each call:
    ///   1. Sync the table with disk (delete missing rows, insert new files as Unused).
    ///   2. Query Unused. If none, reset every row to Unused.
    ///   3. Pick one Unused row at random, mark it Used, record it as LastShown.
    /// </summary>
    public class ShuffleBag
    {
        private readonly string _stateFilePath;
        private ShuffleBagState _state = new();
        private readonly Random _random = new();
        private static readonly string[] SupportedExtensions = { ".jpg", ".jpeg", ".png", ".bmp" };

        public ShuffleBag(string stateFilePath)
        {
            _stateFilePath = stateFilePath;
            LoadState();
        }

        /// <summary>Folder from the last Sync, or null if never synced.</summary>
        public string? Folder => _state.Folder;

        public string? LastShown => _state.LastShown;

        public WallpaperFitMode FitMode
        {
            get => _state.FitMode;
            set
            {
                if (_state.FitMode == value)
                    return;
                _state.FitMode = value;
                SaveState();
            }
        }

        public int TotalImages => _state.Files.Count;

        public int GetRemainingImagesInCycle()
        {
            return _state.Files.Count(kv => kv.Value == FileStatus.Unused);
        }

        /// <summary>
        /// Reconcile the file table with the folder on disk without changing any status.
        /// Switching to a different folder discards the old table.
        /// Returns false if the folder does not exist.
        /// </summary>
        public bool Sync(string folder)
        {
            if (!Directory.Exists(folder))
                return false;

            var fullFolder = Path.GetFullPath(folder);

            if (!string.Equals(_state.Folder, fullFolder, StringComparison.OrdinalIgnoreCase))
            {
                _state.Files.Clear();
                _state.LastShown = null;
                _state.Folder = fullFolder;
            }

            var onDisk = ScanFolder(fullFolder);

            // DELETE rows whose file is gone.
            foreach (var missing in _state.Files.Keys.Where(p => !onDisk.Contains(p)).ToList())
                _state.Files.Remove(missing);

            // INSERT new files as Unused.
            foreach (var path in onDisk)
                _state.Files.TryAdd(path, FileStatus.Unused);

            SaveState();
            return true;
        }

        public string? GetNextImage(string folder)
        {
            if (!Sync(folder))
                return null;

            if (_state.Files.Count == 0)
                return null;

            var pool = UnusedFiles();

            if (pool.Count == 0)
            {
                // Cycle complete: UPDATE files SET status = Unused.
                foreach (var key in _state.Files.Keys.ToList())
                    _state.Files[key] = FileStatus.Unused;

                pool = UnusedFiles();

                // Don't open the new cycle with the image that is on screen right now.
                if (pool.Count > 1 && _state.LastShown != null)
                    pool.RemoveAll(p => string.Equals(p, _state.LastShown, StringComparison.OrdinalIgnoreCase));
            }

            var pick = pool[_random.Next(pool.Count)];
            _state.Files[pick] = FileStatus.Used;
            _state.LastShown = pick;

            SaveState();
            return pick;
        }

        private List<string> UnusedFiles()
        {
            return _state.Files
                .Where(kv => kv.Value == FileStatus.Unused)
                .Select(kv => kv.Key)
                .ToList();
        }

        private static HashSet<string> ScanFolder(string folder)
        {
            return Directory.EnumerateFiles(folder)
                .Where(f => SupportedExtensions.Contains(Path.GetExtension(f).ToLowerInvariant()))
                .Select(Path.GetFullPath)
                .ToHashSet(StringComparer.OrdinalIgnoreCase);
        }

        private void LoadState()
        {
            if (!File.Exists(_stateFilePath))
                return;

            try
            {
                var json = File.ReadAllText(_stateFilePath);
                _state = JsonConvert.DeserializeObject<ShuffleBagState>(json) ?? new();
            }
            catch
            {
                _state = new();
            }

            // Deserialization builds a dictionary with the default comparer; restore case-insensitive keys.
            _state.Files = new Dictionary<string, FileStatus>(_state.Files, StringComparer.OrdinalIgnoreCase);
        }

        private void SaveState()
        {
            var json = JsonConvert.SerializeObject(_state, Formatting.Indented);
            File.WriteAllText(_stateFilePath, json);
        }
    }
}
