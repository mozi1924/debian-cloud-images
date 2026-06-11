# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import dataclasses
import enum
import logging
import subprocess
import tarfile
import tempfile
from os import unlink, close
from pathlib import Path
from typing import BinaryIO
from subprocess import run
from tempfile import mkstemp
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


def mkimage(location: Path, size: int):
    cmd = ['dd',
           'if=/dev/zero',
           f'of={location}',
           'bs=1k',
           f'count={size}',
           'conv=sync',
           ]
    logger.info(f'EXEC {cmd}')
    subprocess.run(cmd, check=True)


@dataclasses.dataclass
class PartitionTypeEntry:
    uuid: UUID


class PartitionType(PartitionTypeEntry, enum.Enum):
    ESP = UUID('c12a7328-f81f-11d2-ba4b-00a0c93ec93b')
    ROOT_AMD64 = UUID('4f68bce3-e8cd-4db1-96e7-fbcaf984b709')
    BOOT_AMD64 = UUID('21686148-6449-6e6f-744e-656564454649')
    ROOT_ARM64 = UUID('b921b045-1df0-41c3-af44-4c6f280d3fae')
    ROOT_LOONG64 = UUID('77055800-792c-4f94-b39a-98c91b762bb6')
    ROOT_PPC64EL = UUID('c31c45e6-3f39-412e-80fb-4809c4980599')
    PREP_PPC64EL = UUID('9e1a2d38-c612-4316-aa26-8b49521e5a8b')
    ROOT_RISCV64 = UUID('72ec70a6-cf74-40e6-bd49-4bda08e8f224')
    ROOT_S390 = UUID('08a7acea-624c-4a20-91e8-6e0fa67d23f9')

    @staticmethod
    def arch_root_parttype(arch: str):
        if arch == 'amd64':
            return PartitionType.ROOT_AMD64
        elif arch == 'arm64':
            return PartitionType.ROOT_ARM64
        elif arch == 'ppc64el':
            return PartitionType.ROOT_PPC64EL
        elif arch == 'loong64':
            return PartitionType.ROOT_LOONG64
        elif arch == 'riscv64':
            return PartitionType.ROOT_RISCV64
        elif arch == 's390':
            return PartitionType.ROOT_S390
        else:
            raise NotImplementedError(f'Unknown/unsupported architecture {arch}')


@dataclasses.dataclass
class PartitionEntry:
    SECTOR_SIZE = 512

    file: Path
    type_: PartitionType
    uuid: UUID
    nr: int
    start: int
    size: int

    @property
    def start_sector(self) -> int:
        return self.start // self.SECTOR_SIZE

    def copy_in(self, fsrc: BinaryIO) -> None:
        with self.file.open('rb+') as fdst:
            fsrc.seek(0)
            fdst.seek(self.start)

            fsrc_read = fsrc.read
            fdst_write = fdst.write
            while True:
                buf = fsrc_read(16 * 1024 * 1024)
                if not buf:
                    break
                fdst_write(buf)

    def copy_in_bytes(self, src: bytes) -> None:
        if len(src) > self.size:
            raise ValueError

        with self.file.open('rb+') as fdst:
            fdst.seek(self.start)
            fdst.write(src)

    # construct a vfat filesystem populated with the contents of the
    # /boot/efi/ directory within the given tar archive
    def mkesp(self, content_tar, serial=None, tmpdir='/tmp'):
        sz = self.size // 1024
        offset = self.start // 1024
        fd, fs_img = mkstemp(dir=tmpdir)
        close(fd)
        try:
            mkimage(fs_img, sz)
            cmd = ['mformat', '-i', fs_img]
            if serial:
                cmd += ['-N', serial]
            cmd += ['::']
            logger.info(f'EXEC {cmd}')
            subprocess.run(cmd, check=True)

            with tempfile.TemporaryDirectory() as tmpdirname:
                p = Path(content_tar)
                with tarfile.open(p) as tar:
                    tar.extractall(path=tmpdirname, filter='fully_trusted')
                    tar.close()
                cmd = ['mcopy', '-s', '-p', '-Q', '-m',
                       '-i', fs_img, f'{tmpdirname}/boot/efi/EFI', '::']
                logger.info(f'EXEC {cmd}')
                subprocess.run(cmd, check=True)

            cmd = ['dd',
                   f'if={fs_img}',
                   f'of={self.file}',
                   'bs=1k',
                   f'seek={offset}',
                   'conv=notrunc',
                   ]
            logger.info(f'EXEC {cmd}')
            subprocess.run(cmd, check=True)
        finally:
            unlink(fs_img)

    def mke2fs(self, uuid=None, hash_seed=None, content_tar=None, tmpdir='/tmp'):
        sz = self.size // 1024
        offset = self.start // 1024
        fd, fs_img = mkstemp(dir=tmpdir)
        close(fd)
        try:
            mkimage(fs_img, sz)
            cmd = ['mke2fs', '-j']
            if uuid:
                cmd += ['-U', uuid]
            if hash_seed:
                cmd += ['-E', f'hash_seed={hash_seed}']
            if content_tar:
                cmd += ['-d', content_tar]
            cmd += [fs_img]

            logger.info(f'EXEC {cmd}')
            subprocess.run(cmd, check=True)

            cmd = ['dd',
                   f'if={fs_img}',
                   f'of={self.file}',
                   'bs=1k',
                   f'seek={offset}',
                   'conv=notrunc',
                   ]
            logger.info(f'EXEC {cmd}')
            subprocess.run(cmd, check=True)
        finally:
            unlink(fs_img)

    @property
    def _format_sfdisk(self) -> str:
        start = self.start // self.SECTOR_SIZE
        size = self.size // self.SECTOR_SIZE
        return f'p{self.nr} : start={start}, size={size}, type={self.type_.uuid!s}, uuid={self.uuid!s}'


@dataclasses.dataclass
class Partition:
    ALIGN = 1024 * 1024

    file: Path
    size: int
    gpt_uuid: UUID = dataclasses.field(default_factory=uuid4)
    entries: list[PartitionEntry] = dataclasses.field(init=False, default_factory=list)

    def _get_start(self) -> int:
        if e := self.entries:
            return e[-1].start + e[-1].size
        return self.ALIGN

    def _get_size(self, start: int, size: int | None) -> int:
        if size is not None:
            if start + size + self.ALIGN >= self.size:
                raise ValueError('Partition too large')
            return size
        return self.size - self.ALIGN - start

    def add(
        self,
        type_: PartitionType,
        uuid: UUID,
        nr: int,
        size: int | None = None,
    ) -> PartitionEntry:
        start = self._get_start()
        size = self._get_size(start, size)

        entry = PartitionEntry(self.file, type_, uuid, nr, start, size)
        self.entries.append(entry)
        return entry

    def get(self, uuid: str | UUID):
        if isinstance(uuid, str):
            assert UUID(uuid)
        else:
            assert isinstance(uuid, UUID)
        try:
            return next(part for part in self.entries if part.uuid == str(uuid))
        except StopIteration as e:
            raise LookupError(f"No partition with uuid={uuid}") from e

    @property
    def _format_sfdisk(self) -> str:
        ret = [
            'label: gpt',
            'unit: sectors',
            'sector-size: 512',
            f'label-id: {self.gpt_uuid}',
        ] + [
            i._format_sfdisk for i in self.entries
        ]
        return '\n'.join(ret) + '\n'

    def write(self) -> None:
        with self.file.open('ab') as f:
            f.truncate(self.size)
        run(
            [
                'sfdisk',
                str(self.file),
            ],
            check=True,
            input=self._format_sfdisk.encode('ascii'),
        )
