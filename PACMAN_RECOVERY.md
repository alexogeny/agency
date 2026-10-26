# Pacman low-space recovery

Use this note when a CachyOS or Arch upgrade runs out of space, reports
`Write failed`, leaves files that "exist in filesystem", or fails to build an
initramfs. Do not reboot into a newly installed kernel until its module index and
initramfs have been verified.

## Known-good handoff from 2026-09-22

An upgrade filled the root Btrfs filesystem while extracting Breeze icons,
MediaTek firmware, NVIDIA firmware, and two CachyOS kernels. Pacman recorded the
new package versions even though some files and local ownership lists were
incomplete. Later upgrades therefore appeared current but could not safely build
the new boot images.

Recovery completed successfully with:

```sh
sudo pacman -S --overwrite '*' \
  breeze-icons \
  linux-firmware-mediatek \
  linux-firmware-nvidia \
  linux-cachyos \
  linux-cachyos-lts
```

The overwrite was intentionally limited to five explicit, repository-signed
packages. It repaired an empty `breeze-icons` file list and a truncated
`linux-firmware-nvidia` file list; it was not a general recommendation to ignore
file conflicts.

Before reboot, verification showed:

- `breeze-icons`: 40,003 files, 0 altered;
- `linux-firmware-mediatek`: 160 files, 0 altered;
- `linux-firmware-nvidia`: 620 files, 0 altered;
- module indexes present for `7.2.6-1-cachyos` and
  `6.18.52-1-cachyos-lts`;
- both initramfs images generated successfully and Limine was updated;
- about 15 GiB free on `/` and 2.8 GiB free on `/boot`.

## After reboot

Run:

```sh
uname -r
nvidia-smi
systemctl --failed --no-pager
sudo pacman -Syu
```

Expected results are a current CachyOS kernel, a working NVIDIA query, no
package upgrades left pending, and no new initramfs failure. A failed wireless
regulatory-domain unit may be restarted separately if it remains failed:

```sh
sudo systemctl restart cachyos-iw-set-regdomain.service
systemctl status cachyos-iw-set-regdomain.service --no-pager
```

## Recovery procedure for a future interrupted upgrade

1. Do not repeatedly rerun pacman and do not reboot after an initramfs failure.
2. Free several GiB on the same filesystem as `/`; on Btrfs, logical deletion
   size is not guaranteed physical recovery. Confirm with `df -hT / /boot`.
3. Read the end of `/var/log/pacman.log` and identify packages named beside
   `could not extract`, `problem occurred while upgrading`, or a failed kernel
   build.
4. Check those packages with `pacman -Qkk PACKAGE...`.
5. Check each installed kernel with:

   ```sh
   test -s /usr/lib/modules/KERNEL_RELEASE/modules.dep
   modinfo -k KERNEL_RELEASE btrfs
   ```

6. Normally reinstall only the affected packages. If pacman instead reports
   that their own files "exist in filesystem", first confirm the paths are
   unowned remnants and the cached packages have valid signatures. Use
   `--overwrite` only with an explicit, reviewed package list.
7. Reinstall the affected kernel packages so pacman's `depmod` and initramfs
   hooks run in their normal order. Do not reboot unless the log says image
   generation succeeded for every installed kernel intended for boot.

## Future Agency hardening

Keep this bounded when implementation resumes:

- add a pacman pre-transaction hook that refuses upgrades below a conservative
  root-filesystem headroom threshold and reports cleanup commands;
- add a read-only diagnostic command for recent extraction failures, malformed
  local package file lists, missing `modules.dep`, failed initramfs builds, root
  space, and `/boot` space;
- make any recovery command require explicit package names and verify cached
  package signatures before permitting a scoped overwrite;
- add fixtures for low-space refusal, an empty or truncated local `files`
  database, interrupted firmware extraction, missing depmod metadata, and a
  successful dual-kernel Limine rebuild;
- keep diagnostics and installation code separate from live host repair, and
  never reboot automatically.
