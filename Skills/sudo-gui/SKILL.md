---
name: sudo-gui
description: Obtain explicitly authorized sudo access through one KDE password dialog and run the approved local workflow in the same authorization context. Use when a Linux task needs sudo, the user has approved that root action, and a KDE graphical session is available.
---

# GUI sudo authorization

Use the installed `sudo-gui` command only after the user explicitly authorizes
the root-requiring operation. It is an authentication transport, not permission
to broaden the task.

Run the approved workflow in the same invocation so sudo's terminal- or
process-scoped timestamp remains usable:

```sh
sudo-gui -- ./install.sh
sudo-gui -- sudo systemctl restart example.service
```

The tool checks for an existing authorization and active PAM lockout first. If
needed, it opens one KDE password dialog, makes one password attempt, clears the
shell variable immediately, and then replaces itself with the requested
command. Never ask the user to put a password in chat, tool arguments, an
environment variable, a file, or captured output.

If the dialog is cancelled, authentication fails, or the tool reports a
lockout, stop. Do not retry automatically or work around PAM. Tell the user the
state and wait for the reported lockout to expire or for them to choose a
visible terminal. On headless or non-KDE sessions, use the normal interactive
terminal flow instead.
