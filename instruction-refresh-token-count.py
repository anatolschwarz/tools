#!/usr/bin/env python3
"""Platform token-log helper for instruction-refresh-counter.sh.

Command interface:

    instruction-refresh-token-count.py anchor --platform PLATFORM --log-file PATH
    instruction-refresh-token-count.py scan --platform PLATFORM --log-file PATH \
        --cursor CURSOR_B64

``anchor`` establishes a cursor at the last complete JSONL record without
counting existing events. ``scan`` processes complete records after the given
cursor.

Successful output is exactly one whitespace-delimited line:

    v1 DELTA EVENT_COUNT CURSOR_B64 STATUS

All fields contain no whitespace. DELTA and EVENT_COUNT are non-negative
decimal integers. CURSOR_B64 is an opaque URL-safe Base64 value owned by the
helper. STATUS is one of:

    anchored   anchor completed
    ok         scan completed normally
    restarted  the transcript or cursor could not be continued
    compacted  Claude context compaction was detected

Errors produce no standard output, write one message to standard error, and
exit nonzero. Exit status 2 is reserved for invalid command-line usage; other
failures use status 1.

The helper reads transcripts and calculates deltas. It does not own session
state, thresholds, resets, instruction loading, locking, or refresh output.
"""

import argparse
import base64
import binascii
import json
import os
import re
import sys


PROTOCOL_VERSION = "v1"
VALID_STATUSES = frozenset({"anchored", "ok", "restarted", "compacted"})
CURSOR_VERSION = 1
SUPPORTED_PLATFORMS = ("codex", "claude")
CURSOR_FIELDS = {
    "codex": frozenset({"offset", "device", "inode"}),
    "claude": frozenset({
        "offset", "device", "inode", "last_prompt", "last_message_id"
    }),
}
CODEX_TOKEN_COUNT_MARKER = re.compile(rb'"type"\s*:\s*"token_count"')
CLAUDE_PROMPT_FIELDS = (
    "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"
)
SYNTHETIC_MODEL = "<synthetic>"


class HelperError(Exception):
    """A transcript, cursor, or protocol error safe to show to the caller."""


def non_negative_integer(value, field, line_number):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HelperError(
            f"line {line_number}: {field} must be a non-negative integer"
        )
    return value


def validate_cursor_fields(platform, fields):
    if set(fields) != CURSOR_FIELDS[platform]:
        raise HelperError("cursor has an invalid schema")

    for field in ("offset", "device", "inode"):
        value = fields[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HelperError(
                f"cursor {field} must be a non-negative integer"
            )

    if platform == "claude":
        last_prompt = fields["last_prompt"]
        if last_prompt is not None and (
                isinstance(last_prompt, bool)
                or not isinstance(last_prompt, int)
                or last_prompt < 0):
            raise HelperError(
                "cursor last_prompt must be null or a non-negative integer"
            )
        last_message_id = fields["last_message_id"]
        if last_message_id is not None and not isinstance(
                last_message_id, str):
            raise HelperError(
                "cursor last_message_id must be null or a string"
            )


def encode_cursor(platform, **fields):
    validate_cursor_fields(platform, fields)
    cursor_payload = {
        "version": CURSOR_VERSION,
        "platform": platform,
        **fields,
    }
    payload = json.dumps(
        cursor_payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_cursor(cursor, expected_platform):
    try:
        encoded = cursor.encode("ascii")
        payload = base64.b64decode(encoded, altchars=b"-_", validate=True)
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, binascii.Error,
            json.JSONDecodeError) as exc:
        raise HelperError("cursor is not valid URL-safe Base64 JSON") from exc

    if not isinstance(decoded, dict) \
            or "version" not in decoded \
            or "platform" not in decoded:
        raise HelperError("cursor has an invalid schema")
    if decoded["version"] != CURSOR_VERSION:
        raise HelperError("cursor version is not supported")
    if decoded["platform"] != expected_platform:
        raise HelperError("cursor belongs to another platform")
    fields = {
        key: value for key, value in decoded.items()
        if key not in {"version", "platform"}
    }
    validate_cursor_fields(expected_platform, fields)
    return fields


def open_log(path):
    try:
        handle = open(path, "rb")
    except OSError as exc:
        raise HelperError(f"cannot open token log: {exc}") from exc
    try:
        if not os.path.isfile(path):
            raise HelperError("token log is not a regular file")
        return handle
    except Exception:
        handle.close()
        raise


def last_complete_offset(handle, size):
    if size == 0:
        return 0

    handle.seek(size - 1)
    if handle.read(1) == b"\n":
        return size

    block_size = 65536
    search_end = size
    while search_end > 0:
        search_start = max(0, search_end - block_size)
        handle.seek(search_start)
        block = handle.read(search_end - search_start)
        newline = block.rfind(b"\n")
        if newline >= 0:
            return search_start + newline + 1
        search_end = search_start
    return 0


def anchor_codex(log_file):
    with open_log(log_file) as handle:
        log_stat = os.fstat(handle.fileno())
        offset = last_complete_offset(handle, log_stat.st_size)
    return 0, 0, encode_cursor(
        "codex", offset=offset, device=log_stat.st_dev,
        inode=log_stat.st_ino
    ), "anchored"


def codex_token_event_delta(entry, line_number):
    if not isinstance(entry, dict) or entry.get("type") != "event_msg":
        return None

    payload = entry.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None

    info = payload.get("info")
    if not isinstance(info, dict):
        raise HelperError(f"line {line_number}: token_count info is missing")
    usage = info.get("last_token_usage")
    if not isinstance(usage, dict):
        raise HelperError(
            f"line {line_number}: last_token_usage is missing"
        )

    input_tokens = non_negative_integer(
        usage.get("input_tokens"), "input_tokens", line_number
    )
    cached_input_tokens = non_negative_integer(
        usage.get("cached_input_tokens"), "cached_input_tokens", line_number
    )
    output_tokens = non_negative_integer(
        usage.get("output_tokens"), "output_tokens", line_number
    )
    delta = input_tokens - cached_input_tokens + output_tokens
    if delta < 0:
        raise HelperError(
            f"line {line_number}: cached_input_tokens exceeds the supported "
            "input/output token calculation"
        )
    return delta


def scan_codex(log_file, cursor):
    try:
        cursor_state = decode_cursor(cursor, "codex")
    except HelperError:
        cursor_state = None

    with open_log(log_file) as handle:
        log_stat = os.fstat(handle.fileno())
        size = log_stat.st_size
        if cursor_state is None \
                or cursor_state["device"] != log_stat.st_dev \
                or cursor_state["inode"] != log_stat.st_ino \
                or cursor_state["offset"] > size:
            new_offset = last_complete_offset(handle, size)
            return 0, 0, encode_cursor(
                "codex", offset=new_offset, device=log_stat.st_dev,
                inode=log_stat.st_ino
            ), "restarted"

        offset = cursor_state["offset"]

        handle.seek(offset)
        chunk = handle.read(size - offset)

    complete_end = chunk.rfind(b"\n")
    if complete_end < 0:
        return 0, 0, encode_cursor(
            "codex", offset=offset, device=log_stat.st_dev,
            inode=log_stat.st_ino
        ), "ok"

    complete_chunk = chunk[:complete_end + 1]
    delta = 0
    event_count = 0
    for relative_line, raw_line in enumerate(complete_chunk.splitlines(), 1):
        try:
            line = raw_line.decode("utf-8")
            entry = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if CODEX_TOKEN_COUNT_MARKER.search(raw_line):
                raise HelperError(
                    f"token_count record {relative_line} after cursor is not "
                    "valid JSON"
                ) from exc
            continue

        event_delta = codex_token_event_delta(entry, relative_line)
        if event_delta is not None:
            delta += event_delta
            event_count += 1

    next_offset = offset + complete_end + 1
    return delta, event_count, encode_cursor(
        "codex", offset=next_offset, device=log_stat.st_dev,
        inode=log_stat.st_ino
    ), "ok"


def claude_response_prompt(entry, last_message_id):
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None, last_message_id
    if entry.get("isSidechain") is True:
        return None, last_message_id

    message = entry.get("message")
    if not isinstance(message, dict):
        return None, last_message_id
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None, last_message_id
    # Transport-error placeholder written by Claude Code. Its usage fields are
    # zero, so counting it would read as compaction and reset the counter.
    if message.get("model") == SYNTHETIC_MODEL:
        return None, last_message_id

    message_id = message.get("id")
    if message_id is not None:
        if message_id == last_message_id:
            return None, last_message_id
        last_message_id = message_id

    prompt = 0
    for field in CLAUDE_PROMPT_FIELDS:
        value = usage.get(field, 0)
        if isinstance(value, int):
            prompt += value
    return prompt, last_message_id


def decode_json_record(raw_line):
    try:
        return json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def claude_anchor_cursor(handle, log_stat):
    complete_offset = last_complete_offset(handle, log_stat.st_size)
    last_prompt = None
    last_message_id = None
    handle.seek(0)
    while handle.tell() < complete_offset:
        raw_line = handle.readline(complete_offset - handle.tell())
        entry = decode_json_record(raw_line)
        if entry is None:
            continue
        prompt, last_message_id = claude_response_prompt(
            entry, last_message_id
        )
        if prompt is not None:
            last_prompt = prompt

    return encode_cursor(
        "claude", offset=complete_offset, device=log_stat.st_dev,
        inode=log_stat.st_ino, last_prompt=last_prompt,
        last_message_id=last_message_id
    )


def anchor_claude(log_file):
    with open_log(log_file) as handle:
        log_stat = os.fstat(handle.fileno())
        cursor = claude_anchor_cursor(handle, log_stat)
    return 0, 0, cursor, "anchored"


def scan_claude(log_file, cursor):
    try:
        cursor_state = decode_cursor(cursor, "claude")
    except HelperError:
        cursor_state = None

    with open_log(log_file) as handle:
        log_stat = os.fstat(handle.fileno())
        size = log_stat.st_size
        if cursor_state is None \
                or cursor_state["device"] != log_stat.st_dev \
                or cursor_state["inode"] != log_stat.st_ino \
                or cursor_state["offset"] > size:
            new_cursor = claude_anchor_cursor(handle, log_stat)
            return 0, 0, new_cursor, "restarted"

        offset = cursor_state["offset"]
        last_prompt = cursor_state["last_prompt"]
        last_message_id = cursor_state["last_message_id"]
        handle.seek(offset)
        chunk = handle.read(size - offset)

    complete_end = chunk.rfind(b"\n")
    if complete_end < 0:
        return 0, 0, encode_cursor(
            "claude", offset=offset, device=log_stat.st_dev,
            inode=log_stat.st_ino, last_prompt=last_prompt,
            last_message_id=last_message_id
        ), "ok"

    delta = 0
    response_count = 0
    status = "ok"
    complete_chunk = chunk[:complete_end + 1]
    for raw_line in complete_chunk.splitlines():
        entry = decode_json_record(raw_line)
        if entry is None:
            continue
        prompt, last_message_id = claude_response_prompt(
            entry, last_message_id
        )
        if prompt is None:
            continue

        if last_prompt is None:
            pass
        elif prompt < last_prompt:
            delta = 0
            status = "compacted"
        else:
            delta += prompt - last_prompt
        last_prompt = prompt
        response_count += 1

    next_offset = offset + complete_end + 1
    return delta, response_count, encode_cursor(
        "claude", offset=next_offset, device=log_stat.st_dev,
        inode=log_stat.st_ino, last_prompt=last_prompt,
        last_message_id=last_message_id
    ), status


def emit_result(delta, event_count, cursor, status):
    if status not in VALID_STATUSES:
        raise HelperError("internal status is invalid")
    print(f"{PROTOCOL_VERSION} {delta} {event_count} {cursor} {status}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Parse instruction-refresh token transcript events."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    anchor_parser = subparsers.add_parser("anchor")
    anchor_parser.add_argument(
        "--platform", choices=SUPPORTED_PLATFORMS, required=True
    )
    anchor_parser.add_argument("--log-file", required=True)

    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument(
        "--platform", choices=SUPPORTED_PLATFORMS, required=True
    )
    scan_parser.add_argument("--log-file", required=True)
    scan_parser.add_argument("--cursor", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.platform == "codex" and args.command == "anchor":
            result = anchor_codex(args.log_file)
        elif args.platform == "codex":
            result = scan_codex(args.log_file, args.cursor)
        elif args.command == "anchor":
            result = anchor_claude(args.log_file)
        else:
            result = scan_claude(args.log_file, args.cursor)
        emit_result(*result)
    except HelperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
