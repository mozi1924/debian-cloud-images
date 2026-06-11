#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Do most of the work of grub-install

set -euE

[ "$ARCHITECTURE" = "ppc64-le" ] || exit 0

. "${SRCDIR}/partitions"

test -n "$FSUUID_ROOT"

mkosi-chroot cp -r /usr/lib/grub/powerpc-ieee1275 \
             /boot/grub
mkosi-chroot mkdir -p /boot/grub/fonts/
mkosi-chroot cp /usr/share/grub/unicode.pf2 /boot/grub/fonts/
mkosi-chroot grub-editenv /boot/grub/grubenv create

cat <<EOF > "${BUILDROOT}/boot/grub/powerpc-ieee1275/load.cfg"
search.fs_uuid ${FSUUID_ROOT} root
set prefix=(\$root)'/boot/grub'
configfile \$prefix/grub.cfg
EOF

mkosi-chroot grub-mkimage \
             --verbose \
             --directory '/usr/lib/grub/powerpc-ieee1275' \
             --prefix '(,gpt1)/boot/grub' \
             --output '/boot/grub/powerpc-ieee1275/core.elf' \
             --format 'powerpc-ieee1275' \
             --config '/boot/grub/powerpc-ieee1275/load.cfg' \
             --compression 'auto' 'gzio' 'boot' 'bufio' 'cat' 'cmp' 'configfile' 'crypto' 'datetime' 'disk' 'div' 'echo' 'ext2' 'fat' 'fshelp' 'gcry_crc' 'gettext' 'hello' 'help' 'linux' 'loadenv' 'ls' 'minicmd' 'normal' 'part_gpt' 'priority_queue' 'read' 'reboot' 'search' 'search_fs_file' 'sleep' 'terminal' 'test' 'tr' 'true' 'gfxmenu' 'search_fs_uuid' 'cpio'

test -f "${BUILDROOT}/boot/grub/powerpc-ieee1275/core.elf"

cp -v "${BUILDROOT}/boot/grub/powerpc-ieee1275/core.elf" "${BUILDROOT}/boot/grub/grub"

exit 0
