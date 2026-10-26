import io
import json
import unittest

from Tools.agent_work_messages import read_hook_payload


class ChunkedInput(io.StringIO):
    def __init__(self, value, chunk_size):
        super().__init__(value)
        self.chunk_size = chunk_size

    def read(self, size=-1):
        if not 0 < size <= 65536:
            raise AssertionError("hook reader must use bounded reads")
        return super().read(min(size, self.chunk_size))


class HookInputTests(unittest.TestCase):
    def test_small_events_preserve_json_values_across_chunk_boundaries(self):
        payload = {"session_id": "session", "text": 'é😀\n\t\r\b\f"\\/',
                   "values": [None, True, False, -12.5, {"nested": "\\u1234"}]}
        for ensure_ascii in (True, False):
            for chunk_size in (1, 2, 3, 4, 5, 7, 65536):
                with self.subTest(ensure_ascii=ensure_ascii, chunk_size=chunk_size):
                    stream = ChunkedInput(json.dumps(payload, ensure_ascii=ensure_ascii), chunk_size)
                    self.assertEqual(read_hook_payload(stream), payload)

    def test_oversized_strings_are_discarded_without_losing_following_metadata(self):
        payload = {"content": [{"data": "a" * (2 * 1024 * 1024)},
                               {"text": ('\n"\\😀' * 20000)}],
                   "session_id": "after-images", "stop_hook_active": False}
        stream = ChunkedInput(json.dumps(payload), 4093)
        result = read_hook_payload(stream)
        self.assertEqual(result, {**payload, "content": [{"data": None}, {"text": None}]})
        self.assertEqual(stream.tell(), len(stream.getvalue()))

    def test_string_limit_does_not_truncate_retained_registration_text(self):
        payload = {"retained": "a" * 65534, "discarded": "b" * 65535}
        self.assertEqual(read_hook_payload(io.StringIO(json.dumps(payload))),
                         {"retained": payload["retained"], "discarded": None})

    def test_string_limit_counts_utf8_bytes(self):
        payload = {"retained": "é" * 32767, "discarded": "é" * 32768}
        self.assertEqual(read_hook_payload(io.StringIO(json.dumps(payload, ensure_ascii=False))),
                         {"retained": payload["retained"], "discarded": None})

    def test_malformed_input_is_rejected_even_inside_discarded_strings(self):
        for invalid in ('\\q', '\\u123x', '\n', '\\', ''):
            raw = '{"data":"' + "a" * 70000 + invalid
            if invalid not in ('\\', ''):
                raw += '","session_id":"session"}'
            with self.subTest(invalid=repr(invalid)):
                stream = ChunkedInput(raw, 4093)
                with self.assertRaises(ValueError):
                    read_hook_payload(stream)
                self.assertEqual(stream.tell(), len(raw))

    def test_structural_errors_and_non_objects_remain_errors(self):
        for raw in ('[]', 'null', '"text"', '{"x":1,}', '{"x":true false}', '{} {}', '{'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                read_hook_payload(ChunkedInput(raw, 2))

    def test_metadata_limit_drains_remaining_input(self):
        raw = json.dumps({"items": ["a" * 1024] * 1100, "data": "a" * (2 * 1024 * 1024)})
        stream = ChunkedInput(raw, 4093)
        with self.assertRaisesRegex(ValueError, "hook metadata exceeds"):
            read_hook_payload(stream)
        self.assertEqual(stream.tell(), len(raw))


if __name__ == "__main__":
    unittest.main()
