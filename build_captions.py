#!/usr/bin/env python3
"""Build phrase-level English captions timed to Premiere's word-level Korean SRT.

The SRT gives one Korean word per cue, on the timeline's clock. Each worksheet row
(Korean sentence + approved English translation) is matched to its SRT words, the
English is split into single caption lines, and each line is timed to the Korean
words it covers: it appears when she starts that stretch and clears when she stops.

Usage:
  python3 build_captions.py TIMELINE.srt MAKEUP.xlsx MASSAGE.xlsx [OUT_DIR]

Writes captions.csv (the renderer's input), captions_english.srt and a review
listing (captions_review.txt) to OUT_DIR (default: current folder). Hand-made
decisions (line breaks, pinned line starts, corrections) are read from
project/settings.py, or from the file named by $CAPTION_SETTINGS.
"""
import csv, difflib, os, re, runpy, sys
import openpyxl
from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRT, XLSX_MAKEUP, XLSX_MASSAGE = sys.argv[1:4]
OUT_DIR = sys.argv[4] if len(sys.argv) > 4 else '.'
FONT = os.path.join(HERE, 'CaveatBrush-Regular.ttf')
W, FONT_PX = 2160, 180
MAXW = 0.76 * W                       # widest caption line, in pixels at 4K
FPS = 24000 / 1001
SECTION_SPLIT = 400.0                 # seconds; makeup interview before, massage demo after
FILLERS = {'어', '음', '아'}
HOLD, CLOSE_GAP, MIN_DUR = 0.3, 0.5, 1.0   # seconds
ft = ImageFont.truetype(FONT, FONT_PX)

# ---- project settings (hand-made decisions; see README) ----
# CUE_ROW: SRT cue -> worksheet row it belongs to (None = filler); EN_EDIT: English used instead of
# the worksheet's; EN_ONLY: rows spoken in English, with their timeline (start, end); LINE_SPLIT:
# each row's English as lines separated by ' / '; LINE_START: (section, row, first words) -> SRT cue
# the line starts on; TIME_SPLIT: rows whose lines are spread over the row by length.
SETTINGS = os.environ.get('CAPTION_SETTINGS', os.path.join(HERE, 'project', 'settings.py'))
_cfg = runpy.run_path(SETTINGS) if os.path.exists(SETTINGS) else {}
CUE_ROW = _cfg.get('CUE_ROW', {})
EN_EDIT = _cfg.get('EN_EDIT', {})
EN_ONLY = _cfg.get('EN_ONLY', {})
LINE_SPLIT = _cfg.get('LINE_SPLIT', {})
LINE_START = _cfg.get('LINE_START', {})
TIME_SPLIT = _cfg.get('TIME_SPLIT', set())


def parse_srt(path):
    text = open(path, encoding='utf-8-sig').read().replace('\r\n', '\n')
    cues = []
    for m in re.finditer(r'(\d+)\n(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)\n(.*?)(?:\n\n|\n*$)', text, re.S):
        g = m.groups()
        s = int(g[1]) * 3600 + int(g[2]) * 60 + int(g[3]) + int(g[4]) / 1000
        e = int(g[5]) * 3600 + int(g[6]) * 60 + int(g[7]) + int(g[8]) / 1000
        cues.append(dict(cue=int(g[0]), s=s, e=e, ko=g[9].strip()))
    return cues


def read_rows(path):
    rows = []
    for r in openpyxl.load_workbook(path).active.iter_rows(values_only=True):
        if isinstance(r[0], (int, float)):
            rows.append(dict(n=int(r[0]), ko=str(r[3] or '').strip(), en=str(r[5] or '').strip()))
    return rows


def norm(s):
    return ''.join(c for c in s.lower() if ('가' <= c <= '힣') or c.isalnum())


def assign_rows(cues, rows, fixes):
    """Match each SRT word to a worksheet row by aligning the Korean text character by character."""
    S, smap, R, rmap = '', [], '', []
    for k, c in enumerate(cues):
        t = norm(c['ko']); S += t; smap += [k] * len(t)
    for j, r in enumerate(rows):
        t = norm(r['ko']); R += t; rmap += [j] * len(t)
    votes = [dict() for _ in cues]
    for a, b, n in difflib.SequenceMatcher(None, S, R, autojunk=False).get_matching_blocks():
        for d in range(n):
            v = votes[smap[a + d]]; v[rmap[b + d]] = v.get(rmap[b + d], 0) + 1
    out, prev = [], 0
    for k, c in enumerate(cues):
        j = max(votes[k], key=votes[k].get) if votes[k] else prev
        prev = j = max(j, prev)
        row = rows[j]['n']
        if c['cue'] in fixes: row = fixes[c['cue']]
        if row is not None: out.append(dict(c, row=row))
    return out


def tokenize(text):
    toks = [dict(text=m.group(), a=m.start(), b=m.end()) for m in re.finditer(r'[^\s—]*—|[^\s—]+', text)]
    for i, t in enumerate(toks):
        t['glue'] = i + 1 < len(toks) and toks[i + 1]['a'] == t['b']
    return toks


def line_text(toks):
    return ''.join(t['text'] + ('' if t['glue'] or i == len(toks) - 1 else ' ') for i, t in enumerate(toks))


def eng_syl(tok):
    t = re.sub(r"[^A-Za-z0-9']", '', tok).lower()
    if not t: return 1
    if t.isdigit(): return 1 if len(t) == 1 else 3
    n = len(re.findall(r'[aeiouy]+', t))
    if t.endswith('e') and not t.endswith('le') and n > 1: n -= 1
    return max(1, n)


def ends_clause(tok):
    t = tok.rstrip('”’"\'')
    if t.endswith(('.', '?', '!', '…')): return 2
    if t.endswith((',', ';', ':', '—')): return 1
    return 0


NEXT_OK = {'and', 'but', 'so', 'or', 'because', 'when', 'while', 'that', 'who', 'which', 'where', 'to', 'for',
           'with', 'in', 'on', 'at', 'from', 'about', 'before', 'after', 'like', 'than', 'if', 'into', 'without', 'is'}
END_BAD = {'a', 'an', 'the', 'my', 'your', 'our', 'their', 'his', 'her', 'its', 'this', 'these', 'those', 'to', 'of',
           'for', 'with', 'in', 'on', 'at', 'from', 'by', 'and', 'or', 'but', 'so', 'i', "i'm", "i've", "i'd", 'we',
           "we're", 'you', "you're", 'is', 'are', 'was', 'be', 'can', 'will', 'more', 'very', 'how', 'what', 'who',
           'that', 'it', 'just', 'probably', 'about', 'any', 'some', 'every', 'one', 'all', 'as', 'than', 'up'}


def bare(tok):
    return re.sub(r"[^a-z0-9']", '', tok.lower().replace('\u2019', "'"))


def break_lines(toks):
    """Split a row's English into single lines, preferring breaks at punctuation and phrase boundaries."""
    n, INF = len(toks), float('inf')
    best, back = [0.0] + [INF] * n, [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(j):
            width = ft.getlength(line_text(toks[i:j]))
            if width > MAXW and j - i > 1: continue
            last = j == n
            slack = max(0.0, (MAXW - width) / MAXW)
            cost = 2.5 + (0.6 if last else 1.5) * slack ** 2
            if j - i == 1 and n > 2: cost += 3.0
            if not last:
                end, nxt = toks[j - 1]['text'], bare(toks[j]['text'])
                c = ends_clause(end)
                if c == 2: cost -= 2.0
                elif c == 1: cost -= 1.2
                elif bare(end) in END_BAD: cost += 2.5
                elif nxt in NEXT_OK: cost -= 0.6
                else: cost += 0.6
                if end.startswith('\u201c') and '\u201d' not in end: cost += 4.0
                # never end a line on a sentence start ("anything. Now,")
                if i < j - 1 and ends_clause(toks[j - 2]['text']) == 2: cost += 3.0
            if best[i] + cost < best[j]: best[j], back[j] = best[i] + cost, i
    cuts, j = [], n
    while j > 0: cuts.append((back[j], j)); j = back[j]
    return [toks[i:j] for i, j in reversed(cuts)]


def ko_syl(w):
    return max(1, sum(1 for c in w if '가' <= c <= '힣') + 2 * sum(1 for c in w if c.isdigit()))


def ko_clause_end(w):
    return w.endswith(('고', '서', '데', '요', '다', '면', '며', '지만', '니까', '까', '죠', '고요'))


def split_row(section, row, words, lines):
    """Choose the Korean word each English line starts on (index into words).

    Boundaries follow the English/Korean proportion, prefer pauses and clause endings
    in the Korean, and avoid giving a line less time than it takes to read."""
    m, n = len(lines), len(words)
    if m == 1: return [0]
    if n < m: return None              # fewer Korean words than lines: share the time evenly
    wts = [sum(eng_syl(t['text']) for t in L) + (0.8 if ends_clause(L[-1]['text']) else 0) for L in lines]
    target = [sum(wts[:j]) / sum(wts) for j in range(1, m)]
    ks = [ko_syl(w['ko']) for w in words]
    cum = [sum(ks[:i]) / sum(ks) for i in range(n)]            # fraction spoken before word i
    need = [max(0.9, len(line_text(L)) / 17) for L in lines]   # seconds to read each line

    def start_cost(j, b):   # line j (>= 1) starts at word b
        pause = words[b]['s'] - words[b - 1]['e']
        return (abs(cum[b] - target[j - 1]) * m - 0.35 * min(pause / 0.6, 1.0)
                - (0.15 if ko_clause_end(words[b - 1]['ko']) else 0))

    def short(j, dur):
        return 4.0 * max(0.0, need[j] - dur) / need[j]

    cue_idx = {w['cue']: k for k, w in enumerate(words)}
    fixed = {}
    for j, L in enumerate(lines):
        for (sec, r, head), cue in LINE_START.items():
            if sec == section and r == row and line_text(L).startswith(head): fixed[j] = cue_idx[cue]
    ok = lambda j, b: fixed.get(j, b) == b

    INF = float('inf')
    D = [[INF] * n for _ in range(m)]; P = [[0] * n for _ in range(m)]
    for b in range(1, n):
        if ok(1, b): D[1][b] = start_cost(1, b) + short(0, words[b]['s'] - words[0]['s'])
    for j in range(2, m):
        for b in range(j, n):
            if not ok(j, b): continue
            for p in range(j - 1, b):
                c = D[j - 1][p] + start_cost(j, b) + short(j - 1, words[b]['s'] - words[p]['s'])
                if c < D[j][b]: D[j][b], P[j][b] = c, p
    last = lambda b: D[m - 1][b] + short(m - 1, words[-1]['e'] + HOLD - words[b]['s'])
    b = min(range(m - 1, n), key=last)
    assert last(b) < INF, (section, row, 'pinned line starts are out of order')
    starts = [b]
    for j in range(m - 1, 1, -1): b = P[j][b]; starts.append(b)
    starts = [0] + starts[::-1]
    assert starts == sorted(set(starts)), (section, row, starts)
    return starts


def trim(ws_):
    """Drop fillers at the edges of a line's Korean span when a pause separates them."""
    a, b = 0, len(ws_)
    while b - a > 1 and ws_[a]['ko'] in FILLERS and ws_[a + 1]['s'] - ws_[a]['e'] > 0.25: a += 1
    while b - a > 1 and ws_[b - 1]['ko'] in FILLERS and ws_[b - 1]['s'] - ws_[b - 2]['e'] > 0.25: b -= 1
    return ws_[a:b]


cues = parse_srt(SRT)
captions = []
for section, path, sel in (('makeup', XLSX_MAKEUP, lambda c: c['s'] < SECTION_SPLIT),
                           ('massage', XLSX_MASSAGE, lambda c: c['s'] >= SECTION_SPLIT)):
    rows = read_rows(path)
    words = assign_rows([c for c in cues if sel(c)], rows, CUE_ROW.get(section, {}))
    for r in rows:
        en = EN_EDIT.get((section, r['n']), r['en'])
        if not en: continue
        if (section, r['n']) in LINE_SPLIT:
            parts = [t.strip() for t in LINE_SPLIT[(section, r['n'])].split(' / ')]
            assert re.sub(r'\s', '', ''.join(parts)) == re.sub(r'\s', '', en), (section, r['n'], 'line split changes the wording')
            lines = [tokenize(t) for t in parts]
        else:
            lines = break_lines(tokenize(en))
        for L in lines:
            assert ft.getlength(line_text(L)) <= MAXW or len(L) == 1, (section, r['n'], line_text(L), 'too wide')
        rw = [w for w in words if w['row'] == r['n']]
        if (section, r['n']) in EN_ONLY:
            s, e = EN_ONLY[(section, r['n'])]
            spans = [(s + (e - s) * j / len(lines), s + (e - s) * (j + 1) / len(lines), []) for j in range(len(lines))]
        else:
            assert rw, (section, r['n'], 'no Korean words for this row')
            rw_t = trim(rw)
            starts = None if (section, r['n']) in TIME_SPLIT else split_row(section, r['n'], rw_t, lines)
            if starts is None and (section, r['n']) in TIME_SPLIT:
                s, e = rw_t[0]['s'], rw_t[-1]['e']
                cl = [len(line_text(L)) for L in lines]
                cuts = [s + (e - s) * sum(cl[:j]) / sum(cl) for j in range(len(lines) + 1)]
                spans = [(cuts[j], cuts[j + 1], rw_t) for j in range(len(lines))]
            elif starts is None:   # more lines than words: share the row's time evenly
                s, e = rw_t[0]['s'], rw_t[-1]['e']
                spans = [(s + (e - s) * j / len(lines), s + (e - s) * (j + 1) / len(lines), rw_t) for j in range(len(lines))]
            else:
                spans = []
                for j, a in enumerate(starts):
                    seg = trim(rw_t[a:(starts[j + 1] if j + 1 < len(starts) else len(rw_t))])
                    spans.append((seg[0]['s'], seg[-1]['e'], seg))
        for L, (s, e, seg) in zip(lines, spans):
            captions.append(dict(section=section, row=r['n'], text=line_text(L), s=s, speech_end=e,
                                 ko=' '.join(w['ko'] for w in seg)))

# ---- display timing: hold briefly after speech, close short gaps, keep a minimum duration ----
captions.sort(key=lambda c: c['s'])
for k, c in enumerate(captions):
    nxt = captions[k + 1]['s'] if k + 1 < len(captions) else None
    end = max(c['speech_end'] + HOLD, c['s'] + MIN_DUR)
    if nxt is not None:
        if nxt - c['speech_end'] < CLOSE_GAP: end = nxt
        end = min(end, nxt)
    c['e'] = end
for c in captions:
    c['start_frame'], c['end_frame'] = round(c['s'] * FPS), round(c['e'] * FPS)
for a, b in zip(captions, captions[1:]):
    assert a['end_frame'] <= b['start_frame'] and a['start_frame'] < a['end_frame'], (a, b)

def srt_time(t):
    ms = round(t * 1000)
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'

os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, 'captions.csv'), 'w', newline='', encoding='utf-8') as fh:
    wr = csv.writer(fh)
    wr.writerow(['caption', 'section', 'row', 'start_sec', 'end_sec', 'text'])
    for k, c in enumerate(captions, 1):
        wr.writerow([k, c['section'], c['row'], f"{c['start_frame'] / FPS:.3f}", f"{c['end_frame'] / FPS:.3f}", c['text']])
with open(os.path.join(OUT_DIR, 'captions_english.srt'), 'w', encoding='utf-8') as fh:
    for k, c in enumerate(captions, 1):
        fh.write(f"{k}\n{srt_time(c['start_frame'] / FPS)} --> {srt_time(c['end_frame'] / FPS)}\n{c['text']}\n\n")
with open(os.path.join(OUT_DIR, 'captions_review.txt'), 'w', encoding='utf-8') as fh:
    for k, c in enumerate(captions, 1):
        fh.write(f"{k:3d} {c['section'][:3]} r{c['row']:<2} {c['s']:7.2f}-{c['e']:7.2f} ({c['e'] - c['s']:4.1f}s) "
                 f"{c['text']:<40} | {c['ko']}\n")
print(len(captions), 'captions written to', os.path.abspath(OUT_DIR))
