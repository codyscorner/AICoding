using Microsoft.Win32;
using System.Runtime.InteropServices;

namespace WallpaperShuffler
{
    public enum WallpaperFitMode
    {
        Fill,
        Fit,
        Stretch,
        Center,
        Tile,
        Span
    }

    public class WallpaperApi
    {
        private const uint SPI_SETDESKWALLPAPER = 20;
        private const uint SPIF_UPDATEINIFILE = 0x01;
        private const uint SPIF_SENDCHANGE = 0x02;

        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        private static extern int SystemParametersInfo(uint uAction, uint uParam, string lpvParam, uint fsWinIni);

        public static bool SetWallpaper(string imagePath, WallpaperFitMode fitMode = WallpaperFitMode.Fill)
        {
            if (!File.Exists(imagePath))
                return false;

            SetFitMode(fitMode);

            int retries = 3;
            while (retries > 0)
            {
                try
                {
                    int result = SystemParametersInfo(SPI_SETDESKWALLPAPER, 0, imagePath, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE);
                    if (result != 0)
                        return true;

                    retries--;
                    if (retries > 0)
                        System.Threading.Thread.Sleep(500);
                }
                catch
                {
                    retries--;
                }
            }

            return false;
        }

        private static void SetFitMode(WallpaperFitMode mode)
        {
            const string regPath = @"Control Panel\Desktop";
            using var key = Registry.CurrentUser.OpenSubKey(regPath, true);
            if (key == null)
                return;

            switch (mode)
            {
                case WallpaperFitMode.Fill:
                    key.SetValue("WallpaperStyle", "10", RegistryValueKind.String);
                    key.SetValue("TileWallpaper", "0", RegistryValueKind.String);
                    break;
                case WallpaperFitMode.Fit:
                    key.SetValue("WallpaperStyle", "6", RegistryValueKind.String);
                    key.SetValue("TileWallpaper", "0", RegistryValueKind.String);
                    break;
                case WallpaperFitMode.Stretch:
                    key.SetValue("WallpaperStyle", "2", RegistryValueKind.String);
                    key.SetValue("TileWallpaper", "0", RegistryValueKind.String);
                    break;
                case WallpaperFitMode.Tile:
                    key.SetValue("WallpaperStyle", "0", RegistryValueKind.String);
                    key.SetValue("TileWallpaper", "1", RegistryValueKind.String);
                    break;
                case WallpaperFitMode.Span:
                    key.SetValue("WallpaperStyle", "22", RegistryValueKind.String);
                    key.SetValue("TileWallpaper", "0", RegistryValueKind.String);
                    break;
                default:
                    key.SetValue("WallpaperStyle", "0", RegistryValueKind.String);
                    key.SetValue("TileWallpaper", "0", RegistryValueKind.String);
                    break;
            }
        }
    }
}
