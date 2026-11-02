"""Bounded file hashing and incremental JSON input for local command-line tools."""
import codecs
import hashlib
import json
import re

CHUNK_BYTES = 65536
_STRING_SPECIAL = re.compile(r'["\\\x00-\x1f]')


def file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK_BYTES), b''):
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


class JsonReader:
    def __init__(self, stream):
        self.stream = stream
        self.buffer = ''
        self.position = 0
        self.eof = False

    def error(self, message):
        raise json.JSONDecodeError(message, '', 0)

    def peek(self):
        if self.position == len(self.buffer) and not self.eof:
            self.buffer = self.stream.read(CHUNK_BYTES)
            self.position = 0
            self.eof = not self.buffer
        return self.buffer[self.position:self.position + 1]

    def take(self):
        value = self.peek()
        self.position += bool(value)
        return value

    def space(self):
        while self.peek() and self.peek() in ' \r\n\t':
            self.position += 1

    def expect(self, value):
        self.space()
        if self.take() != value:
            self.error('Expected ' + repr(value))

    def string(self, keep=True):
        self.expect('"')
        parts = ['"'] if keep else None
        while self.peek():
            match = _STRING_SPECIAL.search(self.buffer, self.position)
            end = match.start() if match else len(self.buffer)
            if keep:
                parts.append(self.buffer[self.position:end])
            self.position = end
            if not match:
                continue
            char = self.take()
            if keep:
                parts.append(char)
            if char == '"':
                return json.loads(''.join(parts)) if keep else None
            if char != '\\':
                self.error('Control character in JSON string')
            escape = self.take()
            if not escape or escape not in '"\\/bfnrtu':
                self.error('Invalid JSON escape')
            if keep:
                parts.append(escape)
            if escape == 'u':
                digits = ''.join(self.take() for _ in range(4))
                if len(digits) != 4 or any(c not in '0123456789abcdefABCDEF' for c in digits):
                    self.error('Invalid Unicode escape')
                if keep:
                    parts.append(digits)
        self.error('Unterminated JSON string')

    def value(self, keep=True, fields=None, depth=0):
        if depth > 256:
            self.error('JSON nesting exceeds 256 levels')
        self.space()
        char = self.peek()
        if char == '"':
            return self.string(keep)
        if char == '{':
            self.take()
            result = {} if keep else None
            self.space()
            if self.peek() == '}':
                self.take()
                return result
            while True:
                key = self.string(keep)
                self.expect(':')
                selected = keep and (fields is None or key in fields)
                value = self.value(selected, depth=depth + 1)
                if selected:
                    result[key] = value
                self.space()
                end = self.take()
                if end == '}':
                    return result
                if end != ',':
                    self.error('Expected object separator')
        if char == '[':
            self.take()
            result = [] if keep else None
            self.space()
            if self.peek() == ']':
                self.take()
                return result
            while True:
                value = self.value(keep, depth=depth + 1)
                if keep:
                    result.append(value)
                self.space()
                end = self.take()
                if end == ']':
                    return result
                if end != ',':
                    self.error('Expected array separator')
        token = []
        while self.peek() and self.peek() not in ' \t\r\n,]}':
            token.append(self.take())
            if len(token) > 8192:
                self.error('JSON scalar exceeds input budget')
        raw = ''.join(token)
        try:
            value = json.loads(raw)
        except ValueError:
            self.error('Invalid JSON value')
        return value if keep else None

    def finish(self):
        self.space()
        if self.peek():
            self.error('Extra data after JSON value')

    def records(self, path=(), depth=0):
        if depth > 256:
            self.error('JSON nesting exceeds 256 levels')
        self.space()
        if path:
            self.expect('{')
            found = False
            self.space()
            if self.peek() == '}':
                self.take()
            else:
                while True:
                    key = self.string()
                    self.expect(':')
                    if key == path[0]:
                        if found:
                            self.error('Duplicate records key')
                        found = True
                        yield from self.records(path[1:], depth + 1)
                    else:
                        self.value(False, depth=depth + 1)
                    self.space()
                    end = self.take()
                    if end == '}':
                        break
                    if end != ',':
                        self.error('Expected object separator')
            if not found:
                self.error('JSON records key does not exist: ' + path[0])
            return
        char = self.take()
        if char not in '[{':
            self.error('JSON records must be an array or object')
        end = ']' if char == '[' else '}'
        self.space()
        if self.peek() == end:
            self.take()
            return
        while True:
            if char == '{':
                self.string(False)
                self.expect(':')
            value = self.value(depth=depth + 1)
            if isinstance(value, dict):
                yield value
            del value
            self.space()
            separator = self.take()
            if separator == end:
                return
            if separator != ',':
                self.error('Expected records separator')


def load_json(stream, fields=None):
    reader = JsonReader(stream)
    result = reader.value(fields=fields)
    reader.finish()
    return result


def iter_json_records(stream, records_key=None):
    reader = JsonReader(stream)
    yield from reader.records(tuple(records_key.split('.')) if records_key else ())
    reader.finish()


def load_json_digest(path, fields=None):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        class HashedReader:
            def __init__(self):
                self.decoder = None
                self.finished = False

            def read(self, size):
                while not self.finished:
                    raw = stream.read(size)
                    digest.update(raw)
                    if self.decoder is None:
                        self.decoder = codecs.getincrementaldecoder(json.detect_encoding(raw))()
                    self.finished = not raw
                    text = self.decoder.decode(raw, final=self.finished)
                    if text:
                        return text
                return ''
        result = load_json(HashedReader(), fields)
    return result, digest.hexdigest()
