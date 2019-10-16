import logging

from .base import BaseCommand
from ..utils import argparse_ext
from ..utils.libcloud.compute.ec2 import ExEC2NodeDriver


class Ec2Publisher:
    compute_cls = ExEC2NodeDriver

    def __init__(self, key, secret, region, ami_id, permission_public=True):
        self.key = key
        self.secret = secret
        self.region = region
        self.ami_id = ami_id
        self.permission_public = permission_public

        self.__compute = None

    def __call__(self):
        logging.info("Looking for %s in %s", self.ami_id, self.region)
        images = self.compute.list_images(ex_owner='self',
                                          ex_image_ids=[self.ami_id])
        if images:
            logging.info("Found %s", images[0].id)
            self.compute.ex_publish_ami(images[0])
        else:
            logging.warning("No matching images")

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
        if self.__compute is None:
            regions = {x.name for x in self.compute_cls(key=self.key, secret=self.secret, region='us-east-1').ex_list_regions()}
            if self.region not in regions:
                raise RuntimeError('Unknown region %s' % self.region)

            self.__compute = self.compute_cls(key=self.key, secret=self.secret, region=self.region)
        return self.__compute


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
            metavar='REGION',
            dest='region',
            help='Region for image release',
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

    def __init__(self, *, access_key_id=None, access_secret_key=None, region=None, ami_id=None, **kw):
        super().__init__(**kw)

        self.publisher = Ec2Publisher(
            key=access_key_id,
            secret=access_secret_key,
            region=region,
            ami_id=ami_id,
        )

    def __call__(self):
        self.publisher()
