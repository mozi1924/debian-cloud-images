# SPDX-License-Identifier: GPL-2.0-or-later

import logging
import pathlib
import os.path
import subprocess

from os import getenv
from typing import Dict, List


dci_path = os.path.join(os.path.dirname(__file__), '../..')
logger = logging.getLogger(__name__)


class RunMkOSI:
    output_dir: pathlib.Path
    output_file: pathlib.Path
    image_name: str
    release: str
    build_id: str
    profiles: List[str]
    size_gb: int
    version: str
    arch: str
    env: Dict[str, str]
    output_format: str

    def __init__(
            self, *,
            output_path: pathlib.Path,
            output_file: pathlib.Path,
            image_name: str,
            release: str,
            build_id: str,
            profiles: List[str],
            version: str,
            arch: str,
            output_format="tar",
            env: Dict[str, str],
    ):
        self.output_dir = output_path
        self.output_file = output_file
        self.image_name = image_name
        self.release = release
        self.build_id = build_id
        self.profiles = profiles
        self.version = version
        self.arch = arch
        self.output_format = output_format
        self.env = env

        p = getenv("MKOSI_PATH")
        if p is not None:
            self.mkosi_path = pathlib.Path(p).absolute()
        else:
            self.mkosi_path = pathlib.Path("mkosi.conf.d")

    def mkosi_arch(self) -> str:
        if self.arch == 'ppc64el':
            return 'ppc64-le'
        elif self.arch == 'amd64':
            return 'x86-64'
        elif self.arch == 'i386':
            return 'x86'
        else:
            return self.arch

    def fix_release(self):
        if self.release.endswith('-backports'):
            self.profiles.append('linux-backports')
            self.release = self.release.removesuffix('-backports')

    def command(self, dci_path: str) -> tuple:
        self.fix_release()
        return (
            'env',
            'PATH=/usr/sbin:/usr/bin',
            f'PYTHONPATH={dci_path}',
        ) + tuple(f'{k}={v}' for k, v in sorted(self.env.items())) + (

            'mkosi',
            '-C', str(self.mkosi_path),
            '--force',
            '--format', self.output_format,
            '--release', self.release,
            '--profile', ','.join(self.profiles),
            '--image-version', self.version,
            '--image-id', self.build_id,
            '--output-directory', str(self.output_dir.resolve()),
            '--output', str(self.output_file),
            '--architecture', self.mkosi_arch(),
            'build',
        )

    def __call__(self, run: bool, *, popen=subprocess.Popen) -> None:
        cmd = self.command(dci_path)

        if run:
            logger.info(f'Running mkosi: {" ".join(cmd)}')

            try:
                process = popen(cmd)
                retcode = process.wait()
                if retcode:
                    raise subprocess.CalledProcessError(retcode, cmd)
            finally:
                process.kill()

        else:
            logger.info(f'Would run mkosi: {" ".join(cmd)}')
