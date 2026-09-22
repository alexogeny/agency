---
name: sudo-gui
description: Run explicitly authorized administrator operations through a native macOS authorization dialog or Linux KDE sudo askpass, with an optional task-specific message and no automatic retry.
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

Check `uname -s` before selecting platform-specific behavior.

On macOS, use `sudo-gui --prompt "Reason for this operation" -- sudo COMMAND`
for one elevated command. `--dry-run` previews it without requesting access.
The tool passes the prompt and quoted command as arguments to a fixed
AppleScript, using `do shell script ... with administrator privileges`.
macOS owns the authentication dialog; the tool never receives a password.
The OS may replace the requested prompt with generic system text. Do not
promise the reason will appear inside the authentication dialog.
One native authorization request is made; the OS controls attempts within its
dialog. Cancellation returns 130 and is not automatically retried.

For `sudo-gui -- ./approved-workflow.sh`, the workflow remains the normal user;
only PATH-resolved `sudo` calls request native authorization. Absolute
`/usr/bin/sudo` calls bypass this adapter. Stop the workflow on failure. After
one failed or cancelled authorization, later proxy calls are refused. Each
successful privileged command uses the OS authorization context; a later
command may prompt again. Do not claim this creates a reusable sudo timestamp.
Native commands use buffered text output and have no interactive stdin/TTY.
Run interactive installers in a visible terminal instead. Sudo flags such as
`-u`, `-S`, `-n`, or `-v` are deliberately unsupported by the macOS proxy.

Do not promise Touch ID: native Authorization Services and sudo's PAM stack
are different mechanisms. Touch ID for ordinary sudo requires the system's
`pam_tid.so` configuration and an eligible session. Never change
`/etc/pam.d/sudo` or `sudo_local` merely to run this helper; configuring that
authentication policy requires a separate explicit user request. Do not collect
a password in a custom dialog or use it as AppleScript's `password` argument.

On Linux with KDE:

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
