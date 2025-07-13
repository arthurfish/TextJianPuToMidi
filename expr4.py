import re
import mido
import argparse
from pypinyin import pinyin, Style


# =============================================================================
# 1. 中间表示 (IR) 和上下文类 (无改动)
# =============================================================================
class MusicEvent:
    """所有音乐事件的基类，用于类型识别。"""
    pass


class Note(MusicEvent):
    """表示一个音符事件。"""

    def __init__(self, pitch, duration, lyric, start_tick):
        self.pitch, self.duration, self.lyric, self.start_tick = pitch, duration, lyric, start_tick

    def __repr__(self):
        return f"Note(p={self.pitch}, d={self.duration}, l='{self.lyric}', t={self.start_tick})"


class Rest(MusicEvent):
    """表示一个休止符事件。"""

    def __init__(self, duration, start_tick):
        self.duration, self.start_tick = duration, start_tick

    def __repr__(self):
        return f"Rest(d={self.duration}, t={self.start_tick})"


class BPMChange(MusicEvent):
    def __init__(self, bpm): self.bpm = bpm

    def __repr__(self): return f"BPM({self.bpm})"


class KeyChange(MusicEvent):
    def __init__(self, key): self.key = key

    def __repr__(self): return f"Key('{self.key}')"


class TimeSignatureChange(MusicEvent):
    def __init__(self, num, den): self.num, self.den = num, den

    def __repr__(self): return f"TimeSig({self.num}/{self.den})"


# =============================================================================
# 2. 编译器核心类
# =============================================================================
class JianpuCompiler:
    def __init__(self):
        self.context = {
            'bpm': 120,
            'key_signature': 'C',
            'time_signature': (4, 4),
            'ticks_per_beat': 480,
            'current_tick': 0,
        }
        self.scale_intervals = [0, 2, 4, 5, 7, 9, 11]
        self.key_midi_base = {
            'C': 60, 'C#': 61, 'Db': 61, 'D': 62, 'D#': 63, 'Eb': 63,
            'E': 64, 'F': 65, 'F#': 66, 'Gb': 66, 'G': 67, 'G#': 68,
            'Ab': 68, 'A': 57, 'A#': 58, 'Bb': 58, 'B': 59  # A, A#/Bb, B 降低了八度
        }
        self.events = []
        self.note_pattern = re.compile(r'([#b]?)(\d)(\.?)')

    # -------------------------------------------------------------------
    # 辅助工具函数 (无改动)
    # -------------------------------------------------------------------
    def _get_pinyin(self, hanzi):
        if not hanzi or hanzi.isspace(): return ''
        try:
            pinyin_list = pinyin(hanzi, style=Style.NORMAL)
            if pinyin_list and pinyin_list[0]: return pinyin_list[0][0]
        except Exception:
            pass
        return hanzi

    # -------------------------------------------------------------------
    # 解析阶段 (Parsing Stage)
    # -------------------------------------------------------------------
    def _preprocess(self, jianpu_string):
        """步骤 1: 预处理原始简谱字符串 (无改动)"""
        print("--- 步骤 1: 预处理简谱文本 ---")
        logical_units = []
        blocks = re.split(r'(\([^)]+\))', jianpu_string)
        for block in blocks:
            block = block.strip()
            if not block: continue
            if block.startswith('('):
                logical_units.append(('CONTROL', block[1:-1].strip()))
            else:
                lines = [line for line in block.split('\n') if line.strip()]
                if not lines: continue
                for i in range(0, len(lines), 5):
                    chunk = lines[i:i + 5]
                    if len(chunk) < 5: continue
                    parts = [line.split('|')[1:-1] for line in chunk]
                    if not all(p for p in parts): continue
                    num_measures = len(parts[0])
                    if not all(len(p) == num_measures for p in parts): continue
                    measures_parts = list(zip(*parts))
                    for measure_group in measures_parts:
                        if not any(s.strip() for s in measure_group): continue
                        logical_units.append(('MEASURE', measure_group))
        return logical_units

    def _parse_control_info(self, text):
        """解析控制信息 (无改动)"""
        text_upper = text.upper()
        if 'BPM' in text_upper:
            bpm = int(re.search(r'BPM\s*=\s*(\d+)', text_upper).group(1))
            self.context['bpm'] = bpm
            self.events.append(BPMChange(bpm))
        elif '=' in text:
            match = re.search(r'(\d)\s*=\s*([A-G][#B]?)', text_upper)
            if match:
                self.context['key_signature'] = match.group(2)
                self.events.append(KeyChange(self.context['key_signature']))
        elif '/' in text:
            num, den = map(int, text.split('/'))
            self.context['time_signature'] = (num, den)
            self.events.append(TimeSignatureChange(num, den))

    def _parse_measure(self, measure_group):
        """
        【已修正】解析单个小节。
        修正了对休止符 '0' 的处理逻辑。
        """
        high_oct_line, note_line, dur_line, low_oct_line, lyric_line = measure_group

        cursor = 0
        tied_note_event = None

        while cursor < len(note_line):
            match = self.note_pattern.match(note_line, cursor)

            if match:
                token = match.group(0)
                token_len = len(token)
                accidental_char, scale_degree_char, dot_char = match.groups()

                dur_char = dur_line[cursor]
                duration = self._get_duration(dur_char)
                if dot_char:
                    duration = int(duration * 1.5)

                # 【关键修正】在这里区分音符(1-7)和休止符(0)
                if scale_degree_char == '0':
                    # --- 情况A: 这是一个休止符 ---
                    rest = Rest(duration, self.context['current_tick'])
                    self.events.append(rest)
                    tied_note_event = None  # 休止符会中断延音
                else:
                    # --- 情况B: 这是一个音符 ---
                    high_oct_char = high_oct_line[cursor]
                    low_oct_char = low_oct_line[cursor]
                    lyric_char = lyric_line[cursor]

                    tied_note_event = None  # 新音符开始，重置延音状态

                    octave_mod = 0
                    if high_oct_char == '.':
                        octave_mod = 1
                    elif high_oct_char == ':':
                        octave_mod = 2
                    elif low_oct_char == '.':
                        octave_mod = -1
                    elif low_oct_char == ':':
                        octave_mod = -2

                    pitch = self._get_pitch(accidental_char + scale_degree_char, octave_mod)
                    pinyin_lyric = self._get_pinyin(lyric_char.strip())

                    if pitch is not None:
                        note = Note(pitch, duration, pinyin_lyric, self.context['current_tick'])
                        self.events.append(note)
                        tied_note_event = note

                # 统一更新时间和游标
                self.context['current_tick'] += duration
                cursor += token_len

            else:
                # --- 如果不是标准音符/休止符，则处理延音线或空格 ---
                char = note_line[cursor]
                token_len = 1

                if char.isspace():  # 如果是空格，直接跳过
                    cursor += token_len
                    continue

                dur_char = dur_line[cursor]
                lyric_char = lyric_line[cursor]
                duration = self._get_duration(dur_char)

                if char == '-':  # 音高延音线
                    if tied_note_event:
                        tied_note_event.duration += duration
                    else:
                        print(f"警告：在时间 {self.context['current_tick']} 发现了没有前置音符的延音线。")

                elif lyric_char == '-':  # 歌词延音线
                    last_event = self.events[-1] if self.events else None
                    if isinstance(last_event, Note):
                        last_event.duration += duration

                self.context['current_tick'] += duration
                cursor += token_len

    def _get_duration(self, dur_char):
        """根据拍号和时值符号（-、=等）计算ticks数。(无改动)"""
        num, den = self.context['time_signature']
        ticks_per_quarter = self.context['ticks_per_beat']
        ticks_per_beat_in_signature = ticks_per_quarter * (4 / den)

        if dur_char == '-':
            return int(ticks_per_beat_in_signature)
        elif dur_char == '=':
            return int(ticks_per_beat_in_signature / 2)
        elif dur_char == '三':
            return int(ticks_per_beat_in_signature / 4)
        else:
            return int(ticks_per_beat_in_signature * 2)

    def _get_pitch(self, note_char, octave_mod):
        """根据音符字符（如#1, 5）和八度修饰，计算MIDI音高。(无改动)"""
        note_match = re.match(r'([#b]?)(\d)', note_char)
        if not note_match: return None
        accidental_char, scale_degree_char = note_match.groups()
        scale_degree = int(scale_degree_char) - 1
        if not 0 <= scale_degree <= 6: return None
        accidental_mod = 1 if accidental_char == '#' else -1 if accidental_char == 'b' else 0
        tonic_root_pitch = self.key_midi_base[self.context['key_signature']]
        key_offset = tonic_root_pitch - self.key_midi_base['C']
        base_c_pitch = self.key_midi_base['C'] + (octave_mod * 12) + self.scale_intervals[scale_degree]
        pitch = base_c_pitch + key_offset + accidental_mod
        return pitch

    # -------------------------------------------------------------------
    # 后期处理流水线 (Post-processing Pipeline) - (无改动)
    # -------------------------------------------------------------------
    def _post_process_pipeline(self, raw_events):
        timed_events = sorted(
            [e for e in raw_events if isinstance(e, (Note, Rest))],
            key=lambda x: x.start_tick
        )
        if not timed_events: return []

        print("--- 步骤 4: 应用连奏(Legato)后期处理 ---")
        for i in range(len(timed_events)):
            current_event = timed_events[i]
            if isinstance(current_event, Note):
                next_event_start_tick = None
                if i + 1 < len(timed_events):
                    next_event_start_tick = timed_events[i + 1].start_tick
                else:
                    next_event_start_tick = current_event.start_tick + current_event.duration

                new_duration = next_event_start_tick - current_event.start_tick
                overlap_prevention = 2
                current_event.duration = max(0, new_duration - overlap_prevention)

        print("--- 步骤 5: 转换IR为底层MIDI事件 ---")
        midi_event_tuples = []
        for event in timed_events:
            if isinstance(event, Note):
                if event.lyric:
                    midi_event_tuples.append((event.start_tick, 'lyrics', event.lyric, 0))
                midi_event_tuples.append((event.start_tick, 'note_on', event.pitch, 100))
                midi_event_tuples.append((event.start_tick + event.duration, 'note_off', event.pitch, 0))

        midi_event_tuples.sort(key=lambda x: x[0])
        return midi_event_tuples

    # -------------------------------------------------------------------
    # 文件写入 (File Writing) - (无改动)
    # -------------------------------------------------------------------
    def write_midi(self, final_midi_events, filename):
        mid = mido.MidiFile(type=1, ticks_per_beat=self.context['ticks_per_beat'])
        meta_track = mido.MidiTrack()
        meta_track.name = 'Conductor'
        mid.tracks.append(meta_track)
        meta_track.append(mido.MetaMessage('time_signature', numerator=self.context['time_signature'][0],
                                           denominator=self.context['time_signature'][1], time=0))
        meta_track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(self.context['bpm']), time=0))
        meta_track.append(mido.MetaMessage('key_signature', key=self.context['key_signature'], time=0))

        vocal_track = mido.MidiTrack()
        vocal_track.name = 'Vocaloid'
        mid.tracks.append(vocal_track)

        last_tick = 0
        for tick, msg_type, data1, data2 in final_midi_events:
            delta_time = tick - last_tick
            if msg_type == 'lyrics':
                vocal_track.append(mido.MetaMessage('lyrics', text=data1, time=delta_time))
            elif msg_type == 'note_on':
                vocal_track.append(mido.Message('note_on', note=data1, velocity=data2, time=delta_time))
            elif msg_type == 'note_off':
                vocal_track.append(mido.Message('note_off', note=data1, velocity=data2, time=delta_time))
            last_tick = tick

        try:
            mid.save(filename)
            print(f"MIDI文件 '{filename}' 生成成功！")
        except Exception as e:
            print(f"保存MIDI文件时出错: {e}")

    # -------------------------------------------------------------------
    # 总调度函数 (Main Coordinator) - (无改动)
    # -------------------------------------------------------------------
    def convert(self, jianpu_string, output_filename):
        logical_units = self._preprocess(jianpu_string)

        print("--- 步骤 2: 解析逻辑单元生成原始IR ---")
        for unit_type, data in logical_units:
            if unit_type == 'CONTROL':
                self._parse_control_info(data)
            elif unit_type == 'MEASURE':
                self._parse_measure(data)

        print(f"--- 步骤 3: 原始IR已生成 (前5个) ---\n{self.events[:5]}")
        final_midi_events = self._post_process_pipeline(self.events)
        print(f"\n--- 步骤 6: 最终底层MIDI事件列表 (前10个) ---\n{final_midi_events[:10]}...")
        print("\n--- 步骤 7: 写入MIDI文件 ---")
        self.write_midi(final_midi_events, output_filename)


# =============================================================================
# 3. 主程序入口 (无改动)
# =============================================================================
if __name__ == '__main__':
    cli_parser = argparse.ArgumentParser(
        description='将自定义多行简谱格式编译为带拼音歌词的MIDI文件。',
        formatter_class=argparse.RawTextHelpFormatter
    )
    cli_parser.add_argument('input_file', help='包含简谱的文本文件路径。')
    cli_parser.add_argument('output_file', nargs='?', default='output.mid',
                            help='输出的MIDI文件名 (默认为 output.mid)。')
    args = cli_parser.parse_args()

    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            jianpu_content = f.read()

        compiler = JianpuCompiler()
        compiler.convert(jianpu_content, args.output_file)

    except FileNotFoundError:
        print(f"错误：输入文件 '{args.input_file}' 未找到。")
    except Exception as e:
        import traceback

        print(f"发生未知错误: {e}")
        traceback.print_exc()