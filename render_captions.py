#!/usr/bin/env python3
"""Render word-by-word captions into a transparent 4K .mov for Premiere Pro.

Reads caption_word_timing.csv (one row per word: chunk, word, glue, onset_sec,
chunk_end_sec) and draws each caption line in Caveat Brush, white, with an
alpha channel. Words appear one at a time on their onset frame; the line
clears at chunk_end_sec or when the next line starts.

Usage:
  python3 render_captions.py [--format animation|prores] [--limit SECONDS]
                             [--csv caption_word_timing.csv] [--font CaveatBrush-Regular.ttf]
                             [--out OUTPUT.mov]

Formats (both 2160x3840, 23.976 fps, with alpha):
  animation  QuickTime Animation (RLE). Lossless and small, because frames that
             don't change are stored as almost nothing.
  prores     ProRes 4444. The format from the original chat; about 1.2 GB for
             the full interview.
"""
import argparse, collections, csv, os, shutil, subprocess, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 2160, 3840
FPS_NUM, FPS_DEN = 24000, 1001
FPS = FPS_NUM / FPS_DEN
FONT_PX = 180
BASELINE_Y = 2308                      # 60.1% of frame height, measured from the reference reel
BAND_UP, BAND_DOWN = 380, 140

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--csv', default=os.path.join(HERE, 'caption_word_timing.csv'))
ap.add_argument('--font', default=os.path.join(HERE, 'CaveatBrush-Regular.ttf'))
ap.add_argument('--format', choices=['animation', 'prores'], default='animation')
ap.add_argument('--out')
ap.add_argument('--limit', type=float, help='only render the first N seconds (for a quick test)')
ap.add_argument('--gop', type=int, default=240, help='animation format: keyframe interval in frames')
args = ap.parse_args()
OUT = args.out or f"Jed_captions_4K_{'animation' if args.format == 'animation' else 'prores4444'}.mov"
ft = ImageFont.truetype(args.font, FONT_PX)

# ---- read timing ----
chunks = collections.OrderedDict()
for r in csv.DictReader(open(args.csv, encoding='utf-8-sig')):
    c = chunks.setdefault(int(r['chunk']), dict(words=[], end=float(r['chunk_end_sec'])))
    c['words'].append(dict(text=r['word'], glue=bool(int(r['glue'])), frame=round(float(r['onset_sec']) * FPS)))
chunk_list = list(chunks.values())

# frame-accurate schedule
for ci, c in enumerate(chunk_list):
    fr = [w['frame'] for w in c['words']]
    for k in range(1, len(fr)):
        if fr[k] <= fr[k - 1]: fr[k] = fr[k - 1] + 1
    for w, f in zip(c['words'], fr): w['frame'] = f
    c['start'] = fr[0]
    c['endf'] = max(round(c['end'] * FPS), fr[-1] + 1)
for ci in range(len(chunk_list) - 1):
    chunk_list[ci]['endf'] = min(chunk_list[ci]['endf'], chunk_list[ci + 1]['start'])
    assert chunk_list[ci]['endf'] > chunk_list[ci]['words'][-1]['frame'], ci

limit_f = round(args.limit * FPS) if args.limit else None

# ---- run-length timeline: (state_key, n_frames); state_key None = blank ----
runs, cur = [], 0
def add(key, upto):
    global cur
    if limit_f is not None: upto = min(upto, limit_f)
    if upto > cur: runs.append((key, upto - cur)); cur = upto
for ci, c in enumerate(chunk_list):
    if limit_f is not None and c['start'] >= limit_f: break
    add(None, c['start'])
    for k, w in enumerate(c['words']):
        nxt = c['words'][k + 1]['frame'] if k + 1 < len(c['words']) else c['endf']
        add((ci, k + 1), nxt)
total_frames = cur
print('total frames', total_frames, 'duration %.2fs' % (total_frames / FPS), 'runs', len(runs), flush=True)

# ---- layout + drawing ----
def layout(words):
    text, xs = '', []
    for i, w in enumerate(words):
        xs.append(ft.getlength(text))
        text += w['text'] + (' ' if (i < len(words) - 1 and not w['glue']) else '')
    return xs, ft.getlength(text)

frame = np.zeros((H, W, 4), np.uint8); frame[..., :3] = 255
band_slice = slice(BASELINE_Y - BAND_UP, BASELINE_Y + BAND_DOWN)

def state_bytes(key):
    if key is not None:
        ci, nvis = key
        words = chunk_list[ci]['words']
        xs, total = layout(words)
        x0 = (W - total) / 2
        band = Image.new('L', (W, BAND_UP + BAND_DOWN), 0)
        d = ImageDraw.Draw(band)
        for w, x in zip(words[:nvis], xs):
            d.text((x0 + x, BAND_UP), w['text'], font=ft, fill=255, anchor='ls')
        frame[band_slice, :, 3] = np.asarray(band)
    out = frame.tobytes()
    frame[band_slice, :, 3] = 0
    return out

RAW_IN = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba',
          '-s', f'{W}x{H}', '-r', f'{FPS_NUM}/{FPS_DEN}', '-i', '-']

if args.format == 'animation':
    # every frame goes through the encoder; repeated frames cost a few bytes each
    p = subprocess.Popen(RAW_IN + ['-c:v', 'qtrle', '-pix_fmt', 'argb', '-g', str(args.gop),
                                   '-video_track_timescale', str(FPS_NUM), OUT], stdin=subprocess.PIPE)
    done_f = 0
    for i, (key, n) in enumerate(runs):
        b = state_bytes(key)
        for _ in range(n): p.stdin.write(b)
        done_f += n
        if i % 50 == 0: print(f'frames {done_f} / {total_frames}', flush=True)
    p.stdin.close(); assert p.wait() == 0
else:
    # encode each distinct caption state once, then repeat the encoded frames by stream copy
    uniq, seen = [], {}
    for key, n in runs:
        if key not in seen: seen[key] = len(uniq); uniq.append(key)
    print('unique states', len(uniq), flush=True)
    work = tempfile.mkdtemp(prefix='_states', dir=os.path.dirname(os.path.abspath(OUT)))
    p = subprocess.Popen(RAW_IN + ['-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le',
                                   '-c:v', 'prores_aw', '-profile:v', '4', '-vendor', 'apl0',
                                   '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                                   '-f', 'segment', '-segment_time', '0.04', '-segment_format', 'mov',
                                   '-reset_timestamps', '1', work + '/s_%05d.mov'], stdin=subprocess.PIPE)
    for i, key in enumerate(uniq):
        p.stdin.write(state_bytes(key))
        if i % 50 == 0: print('encoded', i, '/', len(uniq), flush=True)
    p.stdin.close(); assert p.wait() == 0
    nfiles = len([f for f in os.listdir(work) if f.startswith('s_')])
    assert nfiles == len(uniq), (nfiles, len(uniq))
    with open(work + '/list.txt', 'w') as fh:
        for key, n in runs:
            fh.write(f"file '{work}/s_{seen[key]:05d}.mov'\n" * n)
    subprocess.check_call(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
                           '-i', work + '/list.txt', '-c', 'copy', '-video_track_timescale', str(FPS_NUM), OUT])
    shutil.rmtree(work)
print('done', OUT, '%.1f MB' % (os.path.getsize(OUT) / 1e6), flush=True)
