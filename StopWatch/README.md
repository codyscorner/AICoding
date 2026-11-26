# Stopwatch & Timer

A desktop stopwatch and countdown timer with an aqua theme and audio chime alert, built with Python, PyQt6, and pygame (for the chime audio).

## Features

**Stopwatch tab**
- Start / Stop / Reset
- Lap recording with split times (up to 50 laps)
- Session start timestamp logged
- HH:MM:SS.cs display

**Timer tab**
- Set hours, minutes, and seconds via spinboxes
- Start / Pause / Reset
- Plays a looping chime (`TimerChime.mp3`) when time expires
- "STOP ALARM" button to silence the chime
- Falls back to a system bell + dialog if audio is unavailable

## Requirements

```
Python 3.x
pygame  (for audio)
```

```bash
pip install pygame
```

## Usage

```bash
python stopwatch.py
```

## Version History

| Version | Notes |
|---------|-------|
| v1.0.0 | Initial release |
| v1.1.2 | Timer spinbox labels now read "Hours=HH", "Minutes=MM", "Seconds=SS" instead of bare HH / MM / SS |
