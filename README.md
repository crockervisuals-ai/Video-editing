# Jed interview captions

Word-by-word English captions for the Jed makeup-artist interview. They render as a
transparent 4K vertical video (2160x3840, 23.976 fps) in Caveat Brush. The video goes on a track
above the footage in Premiere Pro, scaled to 50% in a 1080p sequence.

`Jed_captions_4K_transparent.mov` is the finished render, about 21.7 MB, in the QuickTime Animation
codec with alpha. Its timing comes from `caption_word_timing.csv`, which was built from Descript's
Korean VTT and uses the translator's English wording.

## Rendering

You need Python 3 with Pillow and numpy (`pip install pillow numpy`) and ffmpeg. From this folder, run:

```
python3 render_captions.py                     # Animation codec, about 20-25 MB
python3 render_captions.py --format prores     # ProRes 4444, about 1.3 GB
python3 render_captions.py --limit 20          # first 20 seconds only, for a quick test
```

Both formats show the same picture with an alpha channel. Animation is lossless and small because
frames that don't change take almost no space. ProRes 4444 was the format in the original chat,
and it was too large to download from there.

To change timing, edit `onset_sec` for a word in the CSV and re-render. Words with the same `chunk`
number share a line, and `chunk_end_sec` is when that line clears.
