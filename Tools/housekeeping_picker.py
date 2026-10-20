"""Small Linux terminal checkbox picker; selection never performs cleanup."""
import os
import select
import signal
import sys
import termios
import tty
import unicodedata

MAX_SELECTION = 128


def _clean(value):
    text = []
    for character in str(value):
        category = unicodedata.category(character)
        if category.startswith(('C', 'M')) or category in {'Zl', 'Zp'}:
            point = ord(character)
            text.append(f'\\u{point:04x}' if point <= 0xffff else f'\\U{point:08x}')
        else:
            text.append(character)
    return ''.join(text)


def _width(character):
    return 2 if unicodedata.east_asian_width(character) in {'W', 'F'} else 1


def _clip(text, width):
    if width <= 0:
        return ''
    output, used = [], 0
    for character in text:
        used += _width(character)
        if used > width:
            while output and sum(_width(value) for value in output) >= width:
                output.pop()
            return ''.join(output) + '~'
        output.append(character)
    return ''.join(output)


def _middle(text, width):
    if sum(_width(character) for character in text) <= width:
        return text
    if width < 5:
        return _clip(text, width)
    left = (width - 3) // 2
    right = width - 3 - left
    prefix = _clip(text, left).rstrip('~')
    suffix = _clip(text[::-1], right).rstrip('~')[::-1]
    return prefix + '...' + suffix


def _size(value):
    value = max(0, int(value))
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{value} B'
        value /= 1024


def _write(fd, text):
    data = memoryview(text.encode('utf-8', errors='replace'))
    while data:
        data = data[os.write(fd, data):]


def _frame(candidates, labels, reasons, selected, focus, top, columns, rows, colour, status='', refreshable=False):
    columns, rows = columns or 80, rows or 24
    width = max(1, min(columns, 300) - 1)
    height = max(1, min(rows, 100))
    viewport = max(1, height - 6)
    if focus < top:
        top = focus
    elif focus >= top + viewport:
        top = focus - viewport + 1
    top = max(0, min(top, max(0, len(candidates) - viewport)))
    def line(text, style=None):
        text = _clip(text, width)
        return f'\033[{style}m{text}\033[0m' if colour and style else text
    total = sum(max(0, int(candidates[index].get('allocated_bytes', 0))) for index in selected)
    controls = 'Up/Down move  Space toggle  Enter review  '
    controls += 'R refresh  ' if refreshable else ''
    controls += 'q/Esc cancel'
    lines = [line('SELECT CLEANUP TARGETS', '1;38;5;183'),
             line(f'{len(selected)} selected · {_size(total)} observed · nothing removed', '38;5;141'),
             line('-' * width, '38;5;60')]
    visible = []
    for index in range(top, min(top + viewport, len(candidates))):
        item = candidates[index]
        enabled = bool(item.get('selectable'))
        checkbox = '[x]' if index in selected else '[ ]' if enabled else '[-]'
        prefix = f'{">" if index == focus else " "} {checkbox} '
        suffix = f'  {_size(item.get("allocated_bytes", 0))}' if enabled else ' | ' + _clip(reasons[index], max(8, width // 3))
        budget = max(0, width - len(prefix) - sum(_width(c) for c in suffix))
        text = prefix + _middle(labels[index], budget) + suffix
        style = '1;38;5;183;48;5;53' if index == focus else '38;5;141' if enabled else '38;5;245'
        visible.append(line(text, style))
    if not candidates:
        visible.append(line('No project directories to select.'))
    position = f'Rows {top + 1}-{min(top + viewport, len(candidates))} of {len(candidates)}' if candidates else '0 rows'
    reason = reasons[focus] if candidates and not candidates[focus].get('selectable') else (
        'Path: ' + _middle(_clean(candidates[focus].get('path', '')), max(1, width - 6))
        if candidates else 'No selection needed.')
    reason = status or reason
    lines.extend(visible)
    lines.extend([line(position, '38;5;141'), line(reason, '38;5;245'), line(controls, '38;5;183')])
    if height < 7:
        lines = [*visible, line(controls), line(f'{len(selected)} selected · {_size(total)}')]
    return '\033[H' + '\r\n'.join(lines[:height]) + '\033[J', top


def _key(input_fd, resize_fd):
    ready, _, _ = select.select([input_fd, resize_fd], [], [])
    if resize_fd in ready:
        os.read(resize_fd, 65536)
        return 'resize'
    value = os.read(input_fd, 1)
    if not value or value == b'\x04':
        raise EOFError('Project selection cancelled')
    if value in {b'q', b'Q', b'\x03'}:
        raise KeyboardInterrupt
    if value in {b'\r', b'\n'}:
        return 'enter'
    if value == b' ':
        return 'toggle'
    if value in {b'r', b'R'}:
        return 'refresh'
    if value != b'\x1b':
        return None
    if not select.select([input_fd], [], [], 0.1)[0]:
        raise KeyboardInterrupt
    sequence = os.read(input_fd, 1)
    if sequence not in {b'[', b'O'}:
        raise KeyboardInterrupt
    for _ in range(12):
        if not select.select([input_fd], [], [], 0.1)[0]:
            raise KeyboardInterrupt
        following = os.read(input_fd, 1)
        if not following:
            raise EOFError('Project selection cancelled')
        if following in {b'A', b'B'}:
            return 'up' if following == b'A' else 'down'
        if following not in b'0123456789;':
            return None
    return None


def pick_projects(candidates, *, colour=True, initial_selected=(), refresh=None, notice=''):
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    if not (os.isatty(input_fd) and os.isatty(output_fd)):
        raise EOFError('Project selection requires an interactive terminal')
    labels = [_clean(item.get('label', item.get('path', ''))) for item in candidates]
    reasons = [_clean(item.get('reason') or 'Review only; not eligible for automatic removal') for item in candidates]
    initial_paths = set(initial_selected)
    selected = set()
    for index, item in enumerate(candidates):
        if item.get('selectable') and item.get('path') in initial_paths:
            selected.add(index)
            if len(selected) == MAX_SELECTION:
                break
    focus = top = 0
    status = _clean(notice)
    original = termios.tcgetattr(input_fd)
    resize_read, resize_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    previous_handlers = {}
    screen_entered = False
    def resized(signum, frame):
        try:
            os.write(resize_write, b'r')
        except OSError:
            pass
    def cancelled(signum, frame):
        raise KeyboardInterrupt
    try:
        for signum, handler in ((signal.SIGWINCH, resized), (signal.SIGTERM, cancelled), (signal.SIGHUP, cancelled)):
            previous_handlers[signum] = signal.signal(signum, handler)
        tty.setraw(input_fd)
        screen_entered = True
        _write(output_fd, '\033[?1049h\033[?25l')
        redraw = True
        while True:
            if redraw:
                columns, rows = os.get_terminal_size(output_fd)
                frame, top = _frame(candidates, labels, reasons, selected, focus, top, columns, rows, colour, status, refresh is not None)
                _write(output_fd, frame)
                redraw = False
            key = _key(input_fd, resize_read)
            status = ''
            if key == 'enter':
                return [item for index, item in enumerate(candidates) if index in selected and item.get('selectable')]
            if key == 'resize':
                redraw = True
            elif key == 'refresh' and refresh is not None:
                selected_paths = {candidates[index].get('path') for index in selected}
                focused_path = candidates[focus].get('path') if candidates else None
                columns, rows = os.get_terminal_size(output_fd)
                frame, top = _frame(candidates, labels, reasons, selected, focus, top, columns, rows,
                                    colour, 'Checking availability...', True)
                _write(output_fd, frame)
                candidates = refresh()
                labels = [_clean(item.get('label', item.get('path', ''))) for item in candidates]
                reasons = [_clean(item.get('reason') or 'Review only; not eligible for automatic removal') for item in candidates]
                selected = set()
                focus = min(focus, max(0, len(candidates) - 1))
                for index, item in enumerate(candidates):
                    if item.get('path') == focused_path:
                        focus = index
                    if (item.get('selectable') and item.get('path') in selected_paths
                            and len(selected) < MAX_SELECTION):
                        selected.add(index)
                redraw = True
            elif key == 'up' and focus > 0:
                focus -= 1
                redraw = True
            elif key == 'down' and focus + 1 < len(candidates):
                focus += 1
                redraw = True
            elif key == 'toggle' and candidates and candidates[focus].get('selectable'):
                if focus in selected:
                    selected.remove(focus)
                elif len(selected) < MAX_SELECTION:
                    selected.add(focus)
                else:
                    status = f'Selection limit: {MAX_SELECTION}; uncheck an item first.'
                redraw = True
    finally:
        try:
            termios.tcsetattr(input_fd, termios.TCSAFLUSH, original)
        finally:
            try:
                if screen_entered:
                    _write(output_fd, '\033[0m\033[?25h\033[?1049l')
            finally:
                for signum, previous_handler in previous_handlers.items():
                    signal.signal(signum, previous_handler)
                os.close(resize_read)
                os.close(resize_write)
