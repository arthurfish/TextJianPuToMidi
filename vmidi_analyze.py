import mido
import argparse


def note_number_to_name(note_number):
    """
    将 MIDI 音符编号转换为音名（例如 60 -> C4）。
    """
    if not 0 <= note_number <= 127:
        return "Invalid Note"

    notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    octave = note_number // 12 - 1
    note_index = note_number % 12
    return f"{notes[note_index]}{octave}"


def analyze_midi_file(midi_path):
    """
    分析一个 MIDI 文件并打印其结构信息。
    """
    try:
        mid = mido.MidiFile(midi_path)
    except FileNotFoundError:
        print(f"错误：文件未找到 '{midi_path}'")
        return
    except Exception as e:
        print(f"读取 MIDI 文件时发生错误: {e}")
        return

    print("=" * 50)
    print(f"开始分析 MIDI 文件: {midi_path}")
    print("=" * 50)

    # 打印文件基本信息
    print(f"\n[文件概览]")
    # MIDI 格式类型 (0: 单轨道, 1: 多轨道同步, 2: 多轨道异步)
    # Vocaloid 通常生成 Type 1 文件
    print(f"  - MIDI 类型: {mid.type}")
    print(f"  - 轨道数量: {len(mid.tracks)}")
    # Ticks per Beat (PPQ - Pulses Per Quarter note)
    # 这是时间分辨率，表示一个四分音符包含多少个 "tick"
    print(f"  - 时间分辨率 (Ticks per Beat): {mid.ticks_per_beat}")
    print("-" * 50)

    # 遍历每个轨道
    for i, track in enumerate(mid.tracks):
        print(f"\n[轨道 {i}]")
        # 轨道名通常在第一个 meta message 中
        print(f"  - 轨道名称: {track.name}")
        print(f"  - 消息数量: {len(track)}")

        # `absolute_time` 用于累计每个事件的发生时间（以 tick 为单位）
        # MIDI 文件中的时间是增量时间 (delta time)
        absolute_time = 0

        # 遍历轨道中的每个消息
        for msg in track:
            absolute_time += msg.time

            # 格式化输出字符串
            output = f"  - 时间: {absolute_time:<6} | "

            # --- 处理 Meta Messages (元信息) ---
            if msg.is_meta:
                if msg.type == 'set_tempo':
                    # 将 tempo (microseconds per beat) 转换为 BPM (beats per minute)
                    bpm = mido.tempo2bpm(msg.tempo)
                    output += f"速度变化: {bpm:.2f} BPM"

                elif msg.type == 'time_signature':
                    output += f"拍号: {msg.numerator}/{msg.denominator}"

                elif msg.type == 'key_signature':
                    output += f"调号: {msg.key}"

                # 这是我们最关心的歌词信息！
                elif msg.type == 'lyrics':
                    # 歌词通常是按音节存储的
                    output += f"歌词: '{msg.text}'"

                elif msg.type == 'track_name':
                    # 轨道名已经在前面显示，这里跳过
                    continue

                elif msg.type == 'end_of_track':
                    output += "轨道结束"

                else:
                    # 打印其他未特别处理的 meta messages
                    output += f"Meta Message: {msg}"

            # --- 处理 Channel Messages (通道消息，如音符、控制器等) ---
            else:
                if msg.type == 'note_on':
                    note_name = note_number_to_name(msg.note)
                    # velocity=0 的 note_on 事件等同于 note_off
                    if msg.velocity == 0:
                        output += f"音符关闭: {note_name} ({msg.note})"
                    else:
                        output += f"音符开启: {note_name} ({msg.note}),力度: {msg.velocity}"

                elif msg.type == 'note_off':
                    note_name = note_number_to_name(msg.note)
                    output += f"音符关闭: {note_name} ({msg.note}),力度: {msg.velocity}"

                elif msg.type == 'control_change':
                    # CC#7=音量, CC#10=声相, CC#11=表情, 在Vocaloid中很常见
                    output += f"控制器变更 (CC): 控制器={msg.control}, 值={msg.value}"

                elif msg.type == 'program_change':
                    output += f"乐器变更: Program={msg.program}"

                elif msg.type == 'pitchwheel':
                    # 弯音轮
                    output += f"弯音轮: Value={msg.pitch}"

                else:
                    # 打印其他未特别处理的 channel messages
                    output += f"Channel Message: {msg}"

            print(output)

    print("\n=" * 50)
    print("分析完成。")
    print("=" * 50)


if __name__ == "__main__":
    # 使用 argparse 创建一个命令行接口
    analyze_midi_file('秋日影.mid')