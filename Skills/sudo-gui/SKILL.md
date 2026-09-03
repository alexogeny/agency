---
name: sudo-gui
description: Obtain explicitly authorized sudo access through one KDE password dialog and run the approved local workflow in the same authorization context. Use when a Linux task needs sudo, the user has approved that root action, and a KDE graphical session is available.
---

# GUI sudo authorization

Use the installed `sudo-gui` command only after the user explicitly authorizes
the root-requiring operation. It is an authentication transport, not permission
to broaden the task.

Run the approved workflow in the same invocation:

```sh
sudo-gui -- ./install.sh
sudo-gui -- sudo systemctl restart example.service
```

The tool gives the exact requested sudo command a one-attempt KDE askpass
helper. For a script or installer, it temporarily routes PATH-resolved `sudo`
calls through the same helper. Use ordinary `sudo` inside that workflow; do not
add `-n`, which explicitly disables authentication. The workflow must stop if a
sudo command fails.

Sudo uses an existing authorization or a command-specific `NOPASSWD` rule
without opening a dialog. If the exact command needs a password, the askpass
helper checks for an active PAM lockout, opens one KDE password dialog, and
makes one password attempt. The password exists only in the dialog helper's
process memory and travels directly to sudo; it is never placed in arguments,
the environment, a file, or captured output.

If the dialog is cancelled, authentication fails, or the tool reports a
lockout, stop. Do not retry automatically or work around PAM. Tell the user the
state and wait for the reported lockout to expire or for them to choose a
visible terminal. On headless or non-KDE sessions, use the normal interactive
terminal flow instead.
