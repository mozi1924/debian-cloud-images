import logging

from .base import BaseCommand
from ..utils import argparse_ext
from ..utils.libcloud.compute.ec2 import ExEC2NodeDriver


class Ec2Publisher:
    compute_cls = ExEC2NodeDriver

    def __init__(self, key, secret, regions, ami_id, permission_public=True):
        self.key = key
        self.secret = secret
        self.regions = regions
        self.ami_id = ami_id
        self.permission_public = permission_public

        self.__compute = None

    def __call__(self):
        compute_regions = self.compute_regions()
        for region, compute in compute_regions.items():
            logging.info("Looking for %s in %s", self.ami_id, region)
            region_images = compute.list_images(ex_owner='self',
                                                ex_image_ids=[self.ami_id])
            if len(region_images) == 1:
                logging.info("Found %s", region_images[0].id)
                compute.ex_publish_ami(region_images[0])
            elif len(region_images) == 0:
                logging.warning("No matching images")
            else:
                raise RuntimeError("Multiple matching images in %s! %d" % (region, len(region_images)))

    def generate_permissions(self, name):
        if self.permission_public:
            return {f'{name}.Add.1.Group': 'all'}
        else:
            return {f'{name}.Remove.1.Group': 'all'}

    @property
    def name(self):
        return self.ami_id

    @property
    def compute(self):
        ret = self.__compute
        if ret is None:
            ret = self.__compute = {
                r.name: self.compute_cls(key=self.key, secret=self.secret, region=r.name)
                for r in self.compute_cls(key=self.key, secret=self.secret, region='us-east-1').ex_list_regions()
            }
        return ret

    def compute_regions(self):
        if self.regions:
            if 'all' in self.regions:
                # All regions specified, use complete list
                return self.compute

            # Explicit regions specified
            return {r: v for r, v in self.compute.items() if r in self.regions}

        return {r: v for r, v in self.compute.items()}


class ReleaseEc2Command(BaseCommand):
    argparser_name = 'release-ec2'
    argparser_help = 'release Amazon EC2 AMIs by marking them public'
    argparser_usage = '%(prog)s AMI_ID'

    @classmethod
    def _argparse_register(cls, parser, config):
        super()._argparse_register(parser, config)

        parser.add_argument(
            metavar='AMI_ID',
            dest='ami_id',
            help='Operate on AMIs with the specified ID',

        )
        parser.add_argument(
            '--region',
            action=argparse_ext.ConfigAppendAction,
            config=config,
            config_key='ec2-regions',
            dest='regions',
            help='Regions to copy snapshot and image to or "all"\n    (default: all)',
            nargs='+',
        )
        parser.add_argument(
            '--access-key-id',
            action=argparse_ext.ActionEnv,
            env='AWS_ACCESS_KEY_ID',
        )
        parser.add_argument(
            '--access-secret-key',
            action=argparse_ext.ActionEnv,
            env='AWS_SECRET_ACCESS_KEY',
        )

    def __init__(self, *, access_key_id=None, access_secret_key=None, regions=[], ami_id=None, **kw):
        super().__init__(**kw)

        self.publisher = Ec2Publisher(
            key=access_key_id,
            secret=access_secret_key,
            regions=regions,
            ami_id=ami_id,
        )

    def __call__(self):
        self.publisher()
