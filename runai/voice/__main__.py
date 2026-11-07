"""Voice demo: `python -m runai.voice --file audio.wav`, `--mic` or `--keyboard`.

Print one JSON event per line; `--mission-id` also logs commands in `traces/`.
"""

import argparse
import asyncio
import json
import sys

from runai.tracing import TraceWriter
from runai.voice.audio import file_stream, microphone_stream
from runai.voice.commands import CommandDetector, command_from_text
from runai.voice.live import stream_voice_events
from runai.voice.models import CommandEvent, TranscriptEvent, VoiceEvent


def _emit(event: VoiceEvent, writer: TraceWriter | None, show_partials: bool) -> None:
    if getattr(event, "is_final", True) or show_partials:
        print(event.model_dump_json(), flush=True)
    if writer and isinstance(event, CommandEvent):
        writer.write(event.to_trace_event())


async def _run_audio(args: argparse.Namespace, writer: TraceWriter | None) -> None:
    audio = microphone_stream() if args.mic else file_stream(args.file)
    detector = CommandDetector()
    async for event in stream_voice_events(audio.chunks, sample_rate=audio.sample_rate):
        _emit(event, writer, args.partials)
        if isinstance(event, TranscriptEvent):
            for command in detector.feed(event):
                _emit(command, writer, args.partials)


def _run_keyboard(writer: TraceWriter | None) -> None:
    print("Type a command (Ctrl+D to quit).", file=sys.stderr)
    for line in sys.stdin:
        event = command_from_text(line)
        if event is None:
            print(json.dumps({"type": "unknown", "text": line.strip()}, ensure_ascii=False), flush=True)
        else:
            _emit(event, writer, show_partials=False)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m runai.voice", description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="Local audio file or URL")
    source.add_argument("--mic", action="store_true", help="Local microphone (requires sounddevice)")
    source.add_argument("--keyboard", action="store_true", help="Keyboard fallback, without Gladia")
    parser.add_argument("--partials", action="store_true", help="Also show partial transcripts")
    parser.add_argument("--mission-id", help="Log commands in traces/<mission-id>.jsonl")
    args = parser.parse_args(argv)

    writer = TraceWriter(args.mission_id) if args.mission_id else None
    if args.keyboard:
        _run_keyboard(writer)
        return
    try:
        asyncio.run(_run_audio(args, writer))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
