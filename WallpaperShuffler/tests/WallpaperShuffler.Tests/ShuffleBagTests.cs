using Xunit;
using WallpaperShuffler;
using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;

namespace WallpaperShuffler.Tests
{
    public class ShuffleBagTests : IDisposable
    {
        private readonly string _testDir;
        private readonly string _stateFile;

        public ShuffleBagTests()
        {
            _testDir = Path.Combine(Path.GetTempPath(), $"ShuffleBagTest_{Guid.NewGuid()}");
            _stateFile = Path.Combine(_testDir, "state.json");
            Directory.CreateDirectory(_testDir);
        }

        public void Dispose()
        {
            if (Directory.Exists(_testDir))
                Directory.Delete(_testDir, true);
        }

        [Fact]
        public void GetNextImage_WithSixImages_ReturnsEachImageOnce()
        {
            var imageDir = CreateTestImages(6);
            var bag = new ShuffleBag(_stateFile);

            var results = new HashSet<string>();
            for (int i = 0; i < 6; i++)
            {
                var next = bag.GetNextImage(imageDir);
                Assert.NotNull(next);
                Assert.DoesNotContain(next, results);
                results.Add(next!);
            }
            Assert.Equal(6, results.Count);
        }

        [Fact]
        public void GetNextImage_AfterCompleteCycle_ResetsAndNeverRepeatsLastShown()
        {
            var imageDir = CreateTestImages(6);
            var bag = new ShuffleBag(_stateFile);

            for (int i = 0; i < 6; i++)
                bag.GetNextImage(imageDir);
            var lastOfFirstCycle = bag.LastShown;
            Assert.Equal(0, bag.GetRemainingImagesInCycle());

            // Second cycle: all six again, and the opener differs from the image on screen.
            var secondCycle = new HashSet<string>();
            for (int i = 0; i < 6; i++)
                secondCycle.Add(bag.GetNextImage(imageDir)!);

            Assert.Equal(6, secondCycle.Count);
            Assert.NotEqual(lastOfFirstCycle, secondCycle.First());
        }

        [Fact]
        public void GetNextImage_RepeatedCycles_NeverShowSameImageBackToBack()
        {
            var imageDir = CreateTestImages(4);
            var bag = new ShuffleBag(_stateFile);

            string? previous = null;
            for (int i = 0; i < 200; i++)
            {
                var next = bag.GetNextImage(imageDir);
                Assert.NotNull(next);
                Assert.NotEqual(previous, next);
                previous = next;
            }
        }

        [Fact]
        public void GetNextImage_WithSingleImage_AlwaysReturnsThatImage()
        {
            var imageDir = CreateTestImages(1);
            var bag = new ShuffleBag(_stateFile);

            var image1 = bag.GetNextImage(imageDir);
            var image2 = bag.GetNextImage(imageDir);
            var image3 = bag.GetNextImage(imageDir);

            Assert.NotNull(image1);
            Assert.Equal(image1, image2);
            Assert.Equal(image2, image3);
        }

        [Fact]
        public void GetNextImage_WithHundredImages_ReturnEachOncePerCycle()
        {
            var imageDir = CreateTestImages(100);
            var bag = new ShuffleBag(_stateFile);

            var firstCycle = new HashSet<string>();
            for (int i = 0; i < 100; i++)
            {
                var next = bag.GetNextImage(imageDir);
                Assert.NotNull(next);
                Assert.DoesNotContain(next, firstCycle);
                firstCycle.Add(next!);
            }
            Assert.Equal(100, firstCycle.Count);
            Assert.Equal(0, bag.GetRemainingImagesInCycle());

            var secondCycleFirst = bag.GetNextImage(imageDir);
            Assert.NotEqual(bag.LastShown, firstCycle.Last());
            Assert.Equal(99, bag.GetRemainingImagesInCycle());
            Assert.Contains(secondCycleFirst!, firstCycle);
        }

        [Fact]
        public void GetNextImage_WhenFileAdded_ShowsNewFileBeforeCycleRestarts()
        {
            var imageDir = CreateTestImages(3);
            var bag = new ShuffleBag(_stateFile);

            bag.GetNextImage(imageDir);
            bag.GetNextImage(imageDir);
            Assert.Equal(1, bag.GetRemainingImagesInCycle());

            var newImagePath = CreateTestImage(imageDir, "new_image.jpg");

            // Two images remain unshown this cycle: the leftover and the new one. Both must appear
            // before any already-shown image comes round again.
            var shown = new HashSet<string> { bag.GetNextImage(imageDir)!, bag.GetNextImage(imageDir)! };

            Assert.Equal(2, shown.Count);
            Assert.Contains(newImagePath, shown);
            Assert.Equal(0, bag.GetRemainingImagesInCycle());
        }

        [Fact]
        public void GetNextImage_WhenFileRemoved_SkipsDeletedFile()
        {
            var imageDir = CreateTestImages(3);
            var bag = new ShuffleBag(_stateFile);

            var first = bag.GetNextImage(imageDir)!;
            var remaining = Directory.GetFiles(imageDir).Where(f => f != first).ToList();
            File.Delete(remaining[0]);

            var second = bag.GetNextImage(imageDir)!;

            Assert.NotEqual(first, second);
            Assert.NotEqual(remaining[0], second);
            Assert.Equal(2, bag.TotalImages);
        }

        [Fact]
        public void GetNextImage_WithEmptyFolder_ReturnsNull()
        {
            var emptyDir = Path.Combine(_testDir, "empty");
            Directory.CreateDirectory(emptyDir);
            var bag = new ShuffleBag(_stateFile);

            Assert.Null(bag.GetNextImage(emptyDir));
        }

        [Fact]
        public void GetNextImage_WithMissingFolder_ReturnsNull()
        {
            var bag = new ShuffleBag(_stateFile);
            var missingDir = Path.Combine(_testDir, "missing");

            Assert.Null(bag.GetNextImage(missingDir));
        }

        [Fact]
        public void GetNextImage_IgnoresUnsupportedFileTypes()
        {
            var imageDir = Path.Combine(_testDir, "images");
            Directory.CreateDirectory(imageDir);
            CreateTestImage(imageDir, "image1.png");
            CreateTestImage(imageDir, "image2.jpg");
            File.WriteAllText(Path.Combine(imageDir, "file.txt"), "test");
            File.WriteAllText(Path.Combine(imageDir, "file.webp"), "test");

            var bag = new ShuffleBag(_stateFile);

            var results = new HashSet<string>();
            for (int i = 0; i < 2; i++)
            {
                var next = bag.GetNextImage(imageDir);
                if (next != null)
                    results.Add(next);
            }

            Assert.Equal(2, results.Count);
            Assert.All(results, r => Assert.True(
                r.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ||
                r.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase)
            ));
        }

        [Fact]
        public void GetNextImage_ExtensionMatchingIsCaseInsensitive()
        {
            var imageDir = Path.Combine(_testDir, "images");
            Directory.CreateDirectory(imageDir);
            CreateTestImage(imageDir, "image1.PNG");
            CreateTestImage(imageDir, "image2.JpG");

            var bag = new ShuffleBag(_stateFile);

            var results = new HashSet<string>();
            for (int i = 0; i < 2; i++)
            {
                var next = bag.GetNextImage(imageDir);
                if (next != null)
                    results.Add(next);
            }

            Assert.Equal(2, results.Count);
        }

        [Fact]
        public void Sync_PopulatesTableWithoutChangingStatus()
        {
            var imageDir = CreateTestImages(5);
            var bag = new ShuffleBag(_stateFile);

            Assert.Equal(0, bag.GetRemainingImagesInCycle());
            Assert.True(bag.Sync(imageDir));
            Assert.Equal(5, bag.GetRemainingImagesInCycle());
            Assert.Equal(5, bag.TotalImages);

            bag.GetNextImage(imageDir);
            Assert.Equal(4, bag.GetRemainingImagesInCycle());

            // A second sync must not reset the used row.
            bag.Sync(imageDir);
            Assert.Equal(4, bag.GetRemainingImagesInCycle());
        }

        [Fact]
        public void State_PersistsAcrossInstances()
        {
            var imageDir = CreateTestImages(4);
            var shown = new HashSet<string>();

            // Each call is a fresh process, as at login.
            for (int i = 0; i < 4; i++)
            {
                var bag = new ShuffleBag(_stateFile);
                bag.FitMode = WallpaperFitMode.Span;
                shown.Add(bag.GetNextImage(imageDir)!);
            }

            Assert.Equal(4, shown.Count);

            var reloaded = new ShuffleBag(_stateFile);
            Assert.Equal(WallpaperFitMode.Span, reloaded.FitMode);
            Assert.Equal(Path.GetFullPath(imageDir), reloaded.Folder);
            Assert.Equal(0, reloaded.GetRemainingImagesInCycle());
        }

        [Fact]
        public void Sync_SwitchingFolder_DiscardsOldTable()
        {
            var dirA = CreateTestImages(3);
            var dirB = Path.Combine(_testDir, "other");
            Directory.CreateDirectory(dirB);
            CreateTestImage(dirB, "b1.jpg");
            CreateTestImage(dirB, "b2.jpg");

            var bag = new ShuffleBag(_stateFile);
            bag.GetNextImage(dirA);
            Assert.Equal(3, bag.TotalImages);

            bag.Sync(dirB);
            Assert.Equal(2, bag.TotalImages);
            Assert.Equal(2, bag.GetRemainingImagesInCycle());
            Assert.Null(bag.LastShown);
        }

        private string CreateTestImages(int count)
        {
            var dir = Path.Combine(_testDir, "images");
            Directory.CreateDirectory(dir);

            for (int i = 0; i < count; i++)
            {
                var ext = i % 2 == 0 ? ".jpg" : ".png";
                CreateTestImage(dir, $"image_{i}{ext}");
            }

            return dir;
        }

        private string CreateTestImage(string dir, string filename)
        {
            var path = Path.Combine(dir, filename);
            File.WriteAllBytes(path, new byte[] { 0xFF, 0xD8, 0xFF, 0xE0 });
            return path;
        }
    }
}
