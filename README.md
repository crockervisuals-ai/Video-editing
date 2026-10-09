# Interview captions

English captions for two videos cut together in one Premiere timeline: the makeup-artist
interview, followed by the massage demonstration. They render as a transparent 4K vertical video
(2160x3840, 23.976 fps) in Caveat Brush, one line at a time. Frame 0 of the video is the start of
the timeline, so the clip goes at the very start of the sequence, scaled to 50% in a 1080p
sequence.

## How the timing works

`build_captions.py` reads three inputs:

- Premiere's Korean transcript, exported as SRT. It has one word per cue, on the timeline's clock.
- The two translation worksheets (`.xlsx`), which hold the Korean sentences and the approved
  English for each row.

It matches every Korean word to its worksheet row, splits each row's English into single caption
lines, and times each line to the Korean words it covers. A line appears when that stretch of
speech starts and clears when it ends.

```
python3 build_captions.py project/timeline.srt project/makeup.xlsx project/massage.xlsx OUT_DIR
```

This writes `captions.csv` (the renderer's input), `captions_english.srt` (the same captions for
styling in Premiere) and `captions_review.txt` (each caption next to the Korean it is timed to).
The hand-made decisions live in `project/settings.py`. Git ignores the `project/` folder, along with
the SRT and worksheets kept there, because this repository is public and they hold the client's
translation. The settings are:

- `LINE_SPLIT`: where each row's English breaks into lines.
- `LINE_START`: lines pinned to a specific Korean word.
- `CUE_ROW`: SRT words moved to a different row.
- `EN_ONLY`: lines spoken in English, which are missing from the Korean SRT.

## Rendering

You need Python 3 with Pillow, numpy and openpyxl (`pip install pillow numpy openpyxl`) and ffmpeg.
`CaveatBrush-Regular.ttf` must be next to the scripts.

```
python3 render_captions.py --csv OUT_DIR/captions.csv               # Animation codec, a few tens of MB
python3 render_captions.py --csv OUT_DIR/captions.csv --format prores   # ProRes 4444, several GB
python3 render_captions.py --csv OUT_DIR/captions.csv --limit 20    # first 20 seconds only
```

Both formats show the same picture with an alpha channel. Animation is lossless and small, because
frames that don't change take almost no space.

To adjust a caption, edit its `start_sec`, `end_sec` or `text` in `captions.csv` and re-render.
