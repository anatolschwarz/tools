#!/usr/bin/env python3
"""Platform token-log helper for the instruction-refresh counter.

Command interface:

    instruction-refresh-token-count.py anchor --platform PLATFORM --log-file PATH
    instruction-refresh-token-count.py scan --platform PLATFORM --log-file PATH \
        --cursor CURSOR_B64

``anchor`` establishes a cursor at the last complete JSONL record without
counting existing events. ``scan`` processes complete records after the given
cursor.

Successful output is exactly one whitespace-delimited line:

    v3 DELTA EVENT_COUNT CURSOR_B64 STATUS OCCUPANCY_SCHEMA_VERSION \
        USED_TOKENS CONTEXT_WINDOW MAX_TURN_BURN \
        LAST_COMPLETED_TURN_TOKENS PROJECTED_USAGE WOULD_TRIGGER

All fields contain no whitespace. DELTA and EVENT_COUNT are non-negative
decimal integers. CURSOR_B64 is an opaque URL-safe Base64 value owned by the
helper. LAST_COMPLETED_TURN_TOKENS is either a non-negative decimal integer or
``none``. STATUS is one of:

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
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass


PROTOCOL_VERSION = "v3"
VALID_STATUSES = frozenset({"anchored", "ok", "restarted", "compacted"})
OCCUPANCY_STATE_VERSION = 1
SUPPORTED_PLATFORMS = ("codex", "claude")
CURSOR_VERSIONS = {
    "codex": 3,
    "claude": 1,
}
CURSOR_FIELDS = {
    "codex": frozenset({
        "offset", "device", "inode", "boundary_digest", "task_active",
        "pending_sample"
    }),
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


@dataclass(frozen=True)
class InstructionRefreshScan:
    delta: int
    event_count: int
    cursor: str
    status: str


@dataclass(frozen=True)
class OccupancyTokenSample:
    line_number: int
    used_tokens: int
    context_window: int


@dataclass(frozen=True)
class ContextOccupancyScan:
    schema_version: int
    used_tokens: int
    context_window: int
    max_turn_burn: int
    last_completed_turn_tokens: int | None
    projected_usage: int
    would_trigger: bool
    latest_sample_line: int

    def state_namespace(self):
        return {
            "context_occupancy": {
                "schema_version": self.schema_version,
                "used_tokens": self.used_tokens,
                "context_window": self.context_window,
                "max_turn_burn": self.max_turn_burn,
                "last_completed_turn_tokens": (
                    self.last_completed_turn_tokens
                ),
                "projected_usage": self.projected_usage,
                "would_trigger": self.would_trigger,
            }
        }


@dataclass(frozen=True)
class CombinedCodexScan:
    instruction_refresh: InstructionRefreshScan
    context_occupancy: ContextOccupancyScan


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

    if platform == "codex":
        boundary_digest = fields["boundary_digest"]
        if not isinstance(boundary_digest, str) or re.fullmatch(
                r"[0-9a-f]{64}", boundary_digest) is None:
            raise HelperError(
                "cursor boundary_digest must be a SHA-256 hexadecimal digest"
            )
        if not isinstance(fields["task_active"], bool):
            raise HelperError("cursor task_active must be a boolean")
        pending_sample = fields["pending_sample"]
        if pending_sample is not None:
            if not fields["task_active"]:
                raise HelperError(
                    "cursor pending_sample requires an active task"
                )
            if not isinstance(pending_sample, dict) or set(pending_sample) != {
                    "used_tokens", "context_window"}:
                raise HelperError("cursor pending_sample has an invalid schema")
            used_tokens = pending_sample["used_tokens"]
            context_window = pending_sample["context_window"]
            if isinstance(used_tokens, bool) or not isinstance(
                    used_tokens, int) or used_tokens < 0:
                raise HelperError(
                    "cursor pending_sample used_tokens must be a "
                    "non-negative integer"
                )
            if isinstance(context_window, bool) or not isinstance(
                    context_window, int) or context_window <= 0:
                raise HelperError(
                    "cursor pending_sample context_window must be a "
                    "positive integer"
                )
    elif platform == "claude":
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
        "version": CURSOR_VERSIONS[platform],
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
    if decoded["platform"] != expected_platform:
        raise HelperError("cursor belongs to another platform")
    if decoded["version"] != CURSOR_VERSIONS[expected_platform]:
        raise HelperError("cursor version is not supported")
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


def codex_boundary_digest(handle, offset):
    digest_start = max(0, offset - 64)
    handle.seek(digest_start)
    boundary = handle.read(offset - digest_start)
    return hashlib.sha256(boundary).hexdigest()


def codex_cursor_continues(handle, log_stat, complete_offset, cursor_state):
    if cursor_state is None \
            or cursor_state["device"] != log_stat.st_dev \
            or cursor_state["inode"] != log_stat.st_ino \
            or cursor_state["offset"] > complete_offset:
        return False

    offset = cursor_state["offset"]
    if offset > 0:
        handle.seek(offset - 1)
        if handle.read(1) != b"\n":
            return False
    return cursor_state["boundary_digest"] == codex_boundary_digest(
        handle, offset
    )


def anchor_codex(log_file):
    rebuilt = scan_codex(log_file, "")
    return CombinedCodexScan(
        instruction_refresh=InstructionRefreshScan(
            delta=0,
            event_count=0,
            cursor=rebuilt.instruction_refresh.cursor,
            status="anchored",
        ),
        context_occupancy=rebuilt.context_occupancy,
    )


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


def codex_occupancy_sample(entry, line_number):
    if not isinstance(entry, dict) or entry.get("type") != "event_msg":
        return None

    payload = entry.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None

    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("last_token_usage")
    if not isinstance(usage, dict):
        return None

    used_tokens = usage.get("total_tokens")
    context_window = info.get("model_context_window")
    if isinstance(used_tokens, bool) or not isinstance(used_tokens, int) \
            or used_tokens < 0:
        return None
    if isinstance(context_window, bool) or not isinstance(context_window, int) \
            or context_window <= 0:
        return None

    return OccupancyTokenSample(
        line_number=line_number,
        used_tokens=used_tokens,
        context_window=context_window,
    )


def scan_codex(
        log_file, cursor, occupancy_used_tokens=None,
        occupancy_context_window=None,
        occupancy_max_turn_burn=0,
        occupancy_last_completed_turn_tokens=None):
    try:
        cursor_state = decode_cursor(cursor, "codex")
    except HelperError:
        cursor_state = None

    with open_log(log_file) as handle:
        log_stat = os.fstat(handle.fileno())
        size = log_stat.st_size
        complete_offset = last_complete_offset(handle, size)
        cursor_continues = codex_cursor_continues(
            handle, log_stat, complete_offset, cursor_state
        )
        scan_offset = cursor_state["offset"] if cursor_continues else 0
        status = "ok" if cursor_continues else "restarted"
        handle.seek(scan_offset)
        complete_chunk = handle.read(complete_offset - scan_offset)
        next_boundary_digest = codex_boundary_digest(handle, complete_offset)

    delta = 0
    event_count = 0
    latest_sample = None
    pending_sample_state = cursor_state["pending_sample"] \
        if cursor_continues else None
    pending_turn_sample = (
        OccupancyTokenSample(
            line_number=0,
            used_tokens=pending_sample_state["used_tokens"],
            context_window=pending_sample_state["context_window"],
        )
        if pending_sample_state is not None else None
    )
    task_active = cursor_state["task_active"] if cursor_continues else False
    use_persisted_occupancy = cursor_continues \
        and occupancy_used_tokens is not None \
        and occupancy_context_window is not None
    previous_completed_used_tokens = occupancy_last_completed_turn_tokens \
        if use_persisted_occupancy else None
    max_turn_burn = occupancy_max_turn_burn \
        if use_persisted_occupancy else 0
    for relative_line, raw_line in enumerate(complete_chunk.splitlines(), 1):
        try:
            line = raw_line.decode("utf-8")
            entry = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if cursor_continues and CODEX_TOKEN_COUNT_MARKER.search(raw_line):
                raise HelperError(
                    f"token_count record {relative_line} after cursor is not "
                    "valid JSON"
                ) from exc
            continue

        payload = entry.get("payload") if isinstance(entry, dict) else None
        payload_type = payload.get("type") \
            if isinstance(payload, dict) else None
        if payload_type == "task_started":
            task_active = True
            pending_turn_sample = None

        occupancy_sample = codex_occupancy_sample(entry, relative_line)
        if occupancy_sample is not None:
            task_active = True
            latest_sample = occupancy_sample
            pending_turn_sample = occupancy_sample

        if payload_type == "task_complete":
            if pending_turn_sample is not None:
                if previous_completed_used_tokens is not None:
                    turn_burn = max(
                        0,
                        pending_turn_sample.used_tokens
                        - previous_completed_used_tokens,
                    )
                    max_turn_burn = max(max_turn_burn, turn_burn)
                previous_completed_used_tokens = pending_turn_sample.used_tokens
            pending_turn_sample = None
            task_active = False

        if cursor_continues:
            event_delta = codex_token_event_delta(entry, relative_line)
            if event_delta is not None:
                delta += event_delta
                event_count += 1

    instruction_refresh = InstructionRefreshScan(
        delta=delta,
        event_count=event_count,
        cursor=encode_cursor(
            "codex", offset=complete_offset,
            device=log_stat.st_dev,
            inode=log_stat.st_ino,
            boundary_digest=next_boundary_digest,
            task_active=task_active,
            pending_sample=(
                {
                    "used_tokens": pending_turn_sample.used_tokens,
                    "context_window": pending_turn_sample.context_window,
                }
                if pending_turn_sample is not None else None
            ),
        ),
        status=status,
    )
    if latest_sample is None:
        used_tokens = occupancy_used_tokens if use_persisted_occupancy else 0
        context_window = (
            occupancy_context_window if use_persisted_occupancy else 0
        )
        projected_usage = used_tokens + 2 * max_turn_burn
        context_occupancy = ContextOccupancyScan(
            schema_version=OCCUPANCY_STATE_VERSION,
            used_tokens=used_tokens,
            context_window=context_window,
            max_turn_burn=max_turn_burn,
            last_completed_turn_tokens=previous_completed_used_tokens,
            projected_usage=projected_usage,
            would_trigger=(
                context_window > 0 and projected_usage >= context_window
            ),
            latest_sample_line=0,
        )
    else:
        projected_usage = latest_sample.used_tokens + 2 * max_turn_burn
        context_occupancy = ContextOccupancyScan(
            schema_version=OCCUPANCY_STATE_VERSION,
            used_tokens=latest_sample.used_tokens,
            context_window=latest_sample.context_window,
            max_turn_burn=max_turn_burn,
            last_completed_turn_tokens=previous_completed_used_tokens,
            projected_usage=projected_usage,
            would_trigger=projected_usage >= latest_sample.context_window,
            latest_sample_line=latest_sample.line_number,
        )
    return CombinedCodexScan(
        instruction_refresh=instruction_refresh,
        context_occupancy=context_occupancy,
    )


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


def emit_result(delta, event_count, cursor, status, context_occupancy=None):
    if status not in VALID_STATUSES:
        raise HelperError("internal status is invalid")
    if context_occupancy is None:
        context_occupancy = ContextOccupancyScan(
            schema_version=OCCUPANCY_STATE_VERSION,
            used_tokens=0,
            context_window=0,
            max_turn_burn=0,
            last_completed_turn_tokens=None,
            projected_usage=0,
            would_trigger=False,
            latest_sample_line=0,
        )
    would_trigger = "true" if context_occupancy.would_trigger else "false"
    last_completed_turn_tokens = context_occupancy.last_completed_turn_tokens
    if last_completed_turn_tokens is None:
        last_completed_turn_tokens = "none"
    print(
        f"{PROTOCOL_VERSION} {delta} {event_count} {cursor} {status} "
        f"{context_occupancy.schema_version} "
        f"{context_occupancy.used_tokens} "
        f"{context_occupancy.context_window} "
        f"{context_occupancy.max_turn_burn} "
        f"{last_completed_turn_tokens} "
        f"{context_occupancy.projected_usage} {would_trigger}"
    )


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
    scan_parser.add_argument("--occupancy-used-tokens", type=int)
    scan_parser.add_argument("--occupancy-context-window", type=int)
    scan_parser.add_argument("--occupancy-max-turn-burn", type=int)
    scan_parser.add_argument(
        "--occupancy-last-completed-turn-tokens", type=int
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.command == "scan":
            occupancy_values = (
                args.occupancy_used_tokens,
                args.occupancy_context_window,
                args.occupancy_max_turn_burn,
            )
            if any(value is None for value in occupancy_values) \
                    and any(value is not None for value in occupancy_values):
                raise HelperError(
                    "occupancy used tokens, context window, and max turn burn "
                    "must be supplied together"
                )
            if any(value is not None and value < 0
                   for value in occupancy_values):
                raise HelperError(
                    "occupancy state arguments must be non-negative"
                )
            if args.occupancy_context_window == 0:
                raise HelperError(
                    "occupancy context window must be positive"
                )
            if args.occupancy_last_completed_turn_tokens is not None \
                    and args.occupancy_last_completed_turn_tokens < 0:
                raise HelperError(
                    "last completed turn tokens must be non-negative"
                )
        context_occupancy = None
        if args.platform == "codex":
            if args.command == "anchor":
                combined_result = anchor_codex(args.log_file)
            else:
                combined_result = scan_codex(
                    args.log_file,
                    args.cursor,
                    occupancy_used_tokens=args.occupancy_used_tokens,
                    occupancy_context_window=args.occupancy_context_window,
                    occupancy_max_turn_burn=(
                        args.occupancy_max_turn_burn
                        if args.occupancy_max_turn_burn is not None else 0
                    ),
                    occupancy_last_completed_turn_tokens=(
                        args.occupancy_last_completed_turn_tokens
                    ),
                )
            instruction_refresh = combined_result.instruction_refresh
            context_occupancy = combined_result.context_occupancy
            result = (
                instruction_refresh.delta,
                instruction_refresh.event_count,
                instruction_refresh.cursor,
                instruction_refresh.status,
            )
        elif args.command == "anchor":
            result = anchor_claude(args.log_file)
        else:
            result = scan_claude(args.log_file, args.cursor)
        emit_result(*result, context_occupancy=context_occupancy)
    except HelperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
