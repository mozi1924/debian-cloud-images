# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import logging
import struct
import subprocess
import tarfile

from ..utils.partition import Partition
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)


def dd(of: Path, start: int, data: bytes, log_data: str = 'data'):
    if log_data:
        logger.info(f'Writing {log_data} to {of} at {start}')
    cmd = ['dd', f'of={of}', 'bs=1k',
           f'seek={start // 1024}',
           'conv=notrunc',
           ]
    logger.info(f'EXEC {cmd}')
    subprocess.run(cmd, input=data, check=True)


def grub_prep_setup(disk: Partition, archive: Path, partuuid: str | UUID):
    # imgname is relative in the tar file
    p = disk.get(partuuid)
    grub_img = './boot/grub/powerpc-ieee1275/core.elf'
    with tarfile.open(name=archive) as t:
        fd = t.extractfile(grub_img)
        if not fd:
            raise RuntimeError(f'{grub_img} not found in archive')
        data = fd.read()
    logger.info(f'Writing {grub_img} to {p}')
    dd(p.file, p.start, data, grub_img)


# much of the following function was borrowed from cli/build_diskimage.py
# TODO: de-dupe
def grub_bios_setup(disk: Partition, archive: Path, partuuid: str | UUID):
    boot_path = './boot/grub/i386-pc/boot.img'
    core_path = './boot/grub/i386-pc/core.img'

    with tarfile.open(name=archive) as t:
        fd = t.extractfile(boot_path)
        assert fd is not None
        boot_img = bytearray(fd.read(440))
        fd = t.extractfile(core_path)
        assert fd is not None
        core_img = bytearray(fd.read())

    # Ideally this is not hardcoded. This value is the sector location
    # of the BIOS boot partition, which is determined in
    # util/partition.py
    BIOS_BOOT_START_SECTOR = 2048

    # Patch absolute location of core.img start into boot.img
    GRUB_BOOT_MACHINE_KERNEL_SECTOR = 0x5c
    boot_img[GRUB_BOOT_MACHINE_KERNEL_SECTOR:GRUB_BOOT_MACHINE_KERNEL_SECTOR + 4] = \
        struct.pack('<L', BIOS_BOOT_START_SECTOR)

    # Original comment:
    # FIXME: can this be skipped?
    GRUB_BOOT_MACHINE_BOOT_DRIVE = 0x64
    boot_img[GRUB_BOOT_MACHINE_BOOT_DRIVE] = 0xff

    # Original comment:
    # If DEST_DRIVE is a hard disk, enable the workaround, which is
    # for buggy BIOSes which don't pass boot drive correctly. Instead,
    # they pass 0x00 or 0x01 even when booted from 0x80.
    GRUB_BOOT_MACHINE_DRIVE_CHECK = 0x66
    boot_img[GRUB_BOOT_MACHINE_DRIVE_CHECK] = 0x90
    boot_img[GRUB_BOOT_MACHINE_DRIVE_CHECK + 1] = 0x90

    logger.info('Writing grub boot.img')
    dd(disk.file, 0, bytes(boot_img), "boot.img")

    # Patch absolute location of remaining core.img into start of itself
    GRUB_BOOT_MACHINE_LIST_SIZE = 12
    GRUB_BOOT_MACHINE_LIST_OFFSET = 0x200 - GRUB_BOOT_MACHINE_LIST_SIZE
    core_img[GRUB_BOOT_MACHINE_LIST_OFFSET:GRUB_BOOT_MACHINE_LIST_OFFSET + 8] = \
        struct.pack('<Q', BIOS_BOOT_START_SECTOR + 1)

    logger.info(f'Writing grub core.img to partition {partuuid}')
    dd(disk.file, disk.get(partuuid).start, bytes(core_img), "core.img")
