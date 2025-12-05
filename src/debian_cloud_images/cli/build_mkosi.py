# SPDX-License-Identifier: GPL-2.0-or-later

import argparse
import importlib.resources
import json
import logging
import pathlib
import re

from datetime import datetime
from os import environ
from uuid import UUID, uuid4

from .base import cli, BaseCommand

from .. import resources
from ..build.mkosi import RunMkOSI
from ..build.manifest import CreateManifest
from ..build.tar import RunTar
from ..build.diskimage import DiskImage
from ..utils import argparse_ext


logger = logging.getLogger()


def _argparse_type_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        msg = "Given date ({0}) is not valid. Expected format: 'YYYY-MM-DD'".format(s)
        raise argparse.ArgumentTypeError(msg)


class BuildId:
    re = re.compile(r"^[a-z][a-z0-9-]+$")

    def __init__(self, s):
        r = self.re.match(s)

        if not r:
            raise ValueError('invalid build id value')

        self.id = r.group(0)


class Check:
    def __init__(self):
        self.env = {}
        self.info = {}
        self.profiles = []

    def set_type(self, _type):
        self.type = _type
        self.info['type'] = self.type.name
        self.profiles.append(self.type.name)

    def set_release(self, release):
        self.release = release
        self.info['release'] = self.release.basename
        self.info['release_id'] = self.release.id
        self.info['release_baseid'] = self.release.baseid

    def set_vendor(self, vendor):
        self.vendor = vendor
        self.env['CLOUD_RELEASE_ID'] = self.info['vendor'] = self.vendor.name
        self.profiles.append(self.vendor.name)

    def set_arch(self, arch):
        self.arch = arch
        self.info['arch'] = arch.name

    def set_version(self, version, version_date, build_id):
        self.build_id = self.info['build_id'] = build_id.id

        self.version = self.type.output_version.format(
            version=version,
            date=version_date.strftime('%Y%m%d'),
        )
        self.version_azure = self.type.output_version_azure.format(
            version=version,
            date=version_date.strftime('%Y%m%d'),
        )

        self.env['CLOUD_RELEASE_VERSION'] = self.info['version'] = self.version
        if self.vendor.name == 'azure':
            self.env['CLOUD_RELEASE_VERSION_AZURE'] = self.info['version_azure'] = self.version_azure

    def set_format(self, output_format):
        self.output_format = output_format

    def set_uuid(self, seed: UUID):
        if seed:
            self.uuid = seed
            logger.info(f'Using seed UUID {self.uuid}')
        else:
            self.uuid = uuid4()
            logger.info(f'Generated new seed UUID {self.uuid}')
        self.env['SEED_UUID'] = self.uuid

    def set_source_date_epoch(self):
        sde = self.source_date_epoch = environ.get("SOURCE_DATE_EPOCH")
        if not sde:
            sde = int(datetime.now().timestamp())
            logger.info(f'Generated new SOURCE_DATE_EPOCH {sde}')
            self.env['SOURCE_DATE_EPOCH'] = sde
        else:
            logger.info(f'Using SOURCE_DATE_EPOCH {sde}')

    def check(self):
        True


@cli.register(
    'build-mkosi',
    help='Build Debian images using mkosi',
    arguments=[
        cli.prepare_argument(
            'release_name',
            help='Debian release to build',
            metavar='RELEASE',
        ),
        cli.prepare_argument(
            'vendor_name',
            help='Vendor to build image for',
            metavar='VENDOR',
        ),
        cli.prepare_argument(
            'arch_name',
            help='Architecture or sub-architecture to build image for',
            metavar='ARCH',
        ),
        cli.prepare_argument(
            '--build-id',
            metavar='ID',
            required=True,
            type=BuildId,
        ),
        cli.prepare_argument(
            '--build-type',
            default='dev',
            dest='build_type_name',
            help='Type of image to build',
            metavar='TYPE',
        ),
        cli.prepare_argument(
            '--output-format',
            default='tar',
            required=False,
            dest='output_format',
            help='mkosi format to generate',
        ),
        cli.prepare_argument(
            '--noop',
            action='store_true',
            help='print the commands which would be executed, but do not run them'
        ),
        cli.prepare_argument(
            '--output',
            default='.',
            help='write manifests and images to (default: .)',
            metavar='DIR',
            type=pathlib.Path
        ),
        cli.prepare_argument(
            '--override-name',
            help='override name of output',
        ),
        cli.prepare_argument(
            '--version',
            action=argparse_ext.ActionEnv,
            env='CI_PIPELINE_IID',
            help='version of image',
            metavar='VERSION',
            type=int,
        ),
        cli.prepare_argument(
            '--version-date',
            default=datetime.now(),
            help='date part of version (default: today)',
            type=_argparse_type_date,
        ),
        cli.prepare_argument(
            '--seed-uuid',
            type=UUID,
            dest='seed_uuid',
            required=False,
            metavar='UUID',
        ),
    ],
)
class BuildCommand(BaseCommand):
    def __init__(self, *, release_name=None, vendor_name=None, arch_name=None, version=None, build_id=None, build_type_name=None, localdebs=False, output=None, noop=False, override_name=None, version_date=None, output_format=None, seed_uuid=None, **kw):
        super().__init__(**kw)

        arch = self.config_image.archs.get(arch_name)
        build_type = self.config_image.types.get(build_type_name)
        release = self.config_image.releases.get(release_name)
        vendor = self.config_image.vendors.get(vendor_name)

        if arch is None:
            self.error(
                f'argument ARCH: invalid value: {arch_name}, select one of {", ".join(self.config_image.archs)}'
            )

        if build_type is None:
            self.error(
                f'argument BUILD_TYPE: invalid value: {build_type_name}, select one of {", ".join(self.config_image.types)}'
            )

        if vendor is None:
            self.error(
                f'argument VENDOR: invalid value: {vendor_name}, select one of {", ".join(self.config_image.vendors)}'
            )

        if release is None:
            self.error(
                f'argument RELEASE: invalid value: {release_name}, select one of {", ".join(self.config_image.releases)}'
            )

        self.noop = noop

        self.c = Check()
        self.c.set_type(build_type)
        self.c.set_release(release)
        self.c.set_vendor(vendor)
        self.c.set_arch(arch)
        self.c.set_version(version, version_date, build_id)
        self.c.set_format(output_format)
        self.c.set_uuid(seed_uuid)
        self.c.set_source_date_epoch()
        self.c.check()

        name = override_name or self.c.type.output_name.format(
            build_type=self.c.type.name,
            release=self.c.release.name,
            vendor=self.c.vendor.name,
            arch=self.c.arch.name,
            version=self.c.version,
            build_id=self.c.build_id,
        )

        with importlib.resources.as_file(importlib.resources.files(resources) / 'system_tests') as p_system_tests:
            self.env = self.c.env
            self.env['CLOUD_BUILD_INFO'] = json.dumps(self.c.info)
            self.env['CLOUD_BUILD_NAME'] = name
            self.env['CLOUD_BUILD_OUTPUT_DIR'] = output.resolve()
            self.env['CLOUD_BUILD_SYSTEM_TESTS'] = p_system_tests.as_posix()

            output.mkdir(parents=True, exist_ok=True)

            content_tar = name
            mkosi_dir = output / "mkosi.output"
            image_raw = output / '{}.raw'.format(name)
            image_tar = output / '{}.tar'.format(name)
            part_config = mkosi_dir / '{}.partitions'.format(name)
            manifest_dpkg_status = mkosi_dir / '{}.dpkg-status'.format(name)
            manifest_final = output / '{}.build.json'.format(name)

            self.mkosi = RunMkOSI(
                output_path=mkosi_dir,
                output_file=content_tar,
                image_name=name,
                release=self.c.info['release'],
                profiles=self.c.profiles,
                build_id=name,
                version=self.c.version,
                arch=self.c.arch.name,
                env=self.env,
                output_format=self.c.output_format,
            )

            self.image = DiskImage(
                directory=output,
                input_filename=mkosi_dir / content_tar,
                output_filename=image_raw,
                architecture=self.c.arch.name,
                part_config=part_config,
            )

            self.tar = RunTar(
                input_filename=image_raw,
                output_filename=image_tar,
            )

            self.manifest = CreateManifest(
                dpkg_status=manifest_dpkg_status,
                output_filename=manifest_final,
                info=self.c.info,
            )

    def __call__(self):
        self.mkosi(not self.noop)
        if self.c.output_format == 'tar':
            self.image(not self.noop)
            digest = self.tar(not self.noop)
            self.manifest.write(not self.noop, (digest,))
        info_txt = f"{self.env['CLOUD_BUILD_NAME']}.info"
        info_f = pathlib.Path(self.env['CLOUD_BUILD_OUTPUT_DIR']) / 'mkosi.output' / info_txt
        if not self.noop:
            info_f.rename(f"{self.env['CLOUD_BUILD_OUTPUT_DIR']}/{info_txt}")


if __name__ == '__main__':
    cli.main(BuildCommand)
