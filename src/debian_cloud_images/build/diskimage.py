# SPDX-License-Identifier: GPL-2.0-or-later

import base64
import hashlib
import logging

from os import unlink
from pathlib import Path
import subprocess
from ..utils.bootloader import grub_bios_setup, grub_prep_setup
from ..utils.partition import Partition, PartitionType
from ..utils.tar import split_tar

logger = logging.getLogger(__name__)


class DiskImage:
    directory: Path
    input_filename: Path
    output_filename: Path
    architecture: str
    part_config: Path
    partuuids: dict[str, str]
    partition_table: Partition

    def _read_partition_config(self):
        self.partuuids = {}
        for raw_line in Path(self.part_config).read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = raw_line.split('=')
            if len(fields) != 2:
                logger.error(f'invalid line[{raw_line}]')
                continue
            self.partuuids[fields[0]] = fields[1]

    def _build_image(self):
        logger.info(f'Partitioning {self._working_image}')
        self._read_partition_config()
        part = Partition(self._working_image, 2 * 1024 * 1024 * 1024, self.partuuids['GPT_TABLE_UUID'])

        if self.architecture == 'amd64':
            part_bios_boot = part.add(
                PartitionType.BOOT_AMD64,
                self.partuuids['PARTUUID_BIOS'],
                nr=14,
                size=3 * 1024 * 1024,
            )
        if self.architecture in ['amd64', 'arm64']:
            part_efi_partuuid = self.partuuids['PARTUUID_ESP']
            part_efi = part.add(
                PartitionType.ESP,
                part_efi_partuuid,
                nr=15,
                size=124 * 1024 * 1024,
            )

        if self.architecture == 'ppc64el':
            part_prep = part.add(
                PartitionType.PREP_PPC64EL,
                self.partuuids['PARTUUID_PREP'],
                nr=15,
                size=3 * 1024 * 1024,
            )

        part_root = part.add(
            PartitionType.arch_root_parttype(self.architecture),
            self.partuuids['PARTUUID_ROOT'],
            nr=1,
        )
        logger.info('Writing partition table')
        part.write()
        self.partition_table = part

        assert part_root is not None
        if self.architecture == 'amd64':
            assert part_bios_boot is not None
        elif self.architecture == 'ppc64el':
            assert part_prep is not None
        if self.architecture in ['amd64', 'arm64']:
            assert part_efi is not None

    def _write_bootloader_blocks(self, archive: Path):
        if self.architecture == 'ppc64el':
            grub_prep_setup(self.partition_table, archive, self.partuuids['PARTUUID_PREP'])
        elif self.architecture == 'amd64':
            grub_bios_setup(self.partition_table, archive, self.partuuids['PARTUUID_BIOS'])

    def _write_filesystems(self):
        logger.info('Populating root filesystem')

        root_tar = self.input_filename
        cleanfiles = []

        try:
            if self.architecture in ['amd64', 'arm64']:
                cleanfiles = ['root.tar', 'efi.tar']
                split_tar(self.input_filename,
                          "efi.tar", "root.tar", ['./boot/efi/*'])
                root_tar = "root.tar"
                efi_part = self.partition_table.get(self.partuuids['PARTUUID_ESP'])
                efi_part.mkesp("efi.tar", serial=self.partuuids['ESP_VFAT_SERIAL'])

            part = self.partition_table.get(self.partuuids['PARTUUID_ROOT'])
            part.mke2fs(uuid=self.partuuids['FSUUID_ROOT'],
                        hash_seed=self.partuuids['DIRHASH_ROOT'],
                        content_tar=root_tar,
                        tmpdir=self.directory,
                        )
            self._write_bootloader_blocks(root_tar)
        finally:
            [unlink(f) for f in cleanfiles]

    def __init__(
        self, *,
        directory: Path,
        input_filename: Path,
        output_filename: str='disk.raw',  # noqa:E252
        part_config: Path,
        architecture: str,
    ):
        self.directory = directory
        self.input_filename = input_filename
        self.output_filename = Path(output_filename)
        self.architecture = architecture
        self.part_config = part_config
        self._working_image = Path('{}/.{}.tmp'.format(directory, output_filename)).absolute()

    def __call__(self, run: bool, *, popen=subprocess.Popen) -> str:
        output_hash = hashlib.sha512()
        if run:
            logger.info('Building disk image')
            self._build_image()
            self._write_filesystems()
            self._working_image.rename(self.output_filename)
            with open(self.output_filename, "rb") as f:
                output_digest = base64.b64encode(
                    hashlib.file_digest(f, output_hash.name).digest()).decode()
        else:
            logger.info('Dry run: building disk image')
            output_digest = '000000'

        digest = f'{output_hash.name}:{output_digest}'
        logger.info(f'Image digest: {digest}')
        return digest
