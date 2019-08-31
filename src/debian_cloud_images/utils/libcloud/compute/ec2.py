from libcloud.compute.types import Provider
from libcloud.compute.drivers.ec2 import BaseEC2NodeDriver, EC2Connection, NAMESPACE, VolumeSnapshot
from libcloud.utils.xml import findtext, fixxpath
from enum import Enum


class Permission(Enum):
    PUBLIC = 1
    NONPUBLIC = 2


class ExEC2NodeDriver(BaseEC2NodeDriver):
    connectionCls = EC2Connection
    type = Provider.EC2
    name = 'Amazon EC2'

    def __init__(self, key, secret=None, host=None, region='us-east-1', **kwargs):
        self.signature_version = '4'
        self.region_name = region
        host = host or 'ec2.{}.amazonaws.com'.format(region)
        super().__init__(key=key, secret=secret, host=host, **kwargs)

    def ex_list_regions(self):
        params = {'Action': 'DescribeRegions'}
        response = self.connection.request(self.path, params=params).object
        return self._to_regions(response, 'regionInfo/item')

    def _to_regions(self, object, xpath):
        return [self._to_region(el)
                for el in object.findall(fixxpath(xpath=xpath, namespace=NAMESPACE))]

    def _to_region(self, element):
        name = element.find(fixxpath('regionName', namespace=NAMESPACE)).text
        endpoint = element.find(fixxpath('regionEndpoint', namespace=NAMESPACE)).text
        return ExEC2Region(name, endpoint)

    def ex_copy_snapshot(self, snapshot, description):
        params = {
            'Action': 'CopySnapshot',
            'Description': description,
            'SourceRegion': snapshot.driver.region_name,
            'SourceSnapshotId': snapshot.id,
        }

        response = self.connection.request(self.path, params=params).object

        snapshot_id = findtext(element=response, xpath='snapshotId', namespace=NAMESPACE)

        return VolumeSnapshot(snapshot_id, self)

    def ex_modify_image_attribute(self, image, attributes):
        super().ex_modify_image_attribute(image, attributes)

    def generate_permissions(self, name, perm=Permission.PUBLIC):
        if perm == Permission.PUBLIC:
            op = 'Add'
        else:
            op = 'Remove'
        return {f'{name}.{op}.1.Group': 'all'}

    def ex_publish_ami(self, image):
        self.ex_modify_image_attribute(
            image,
            self.generate_permissions('LaunchPermission'),
        )
        for d in image.extra['block_device_mapping']:
            if 'ebs' in d:
                if 'snapshot_id' in d['ebs']:
                    snapshots = self.list_snapshots(VolumeSnapshot(id=d['ebs']['snapshot_id'], driver=self))
                    self.ex_modify_snapshot_attribute(snapshots[0], self.generate_permissions('CreateVolumePermission'))


class ExEC2Region:
    def __init__(self, name, endpoint):
        self.name, self.endpoint = name, endpoint

    def __str__(self):
        return '<{}("{}", "{}")>'.format(self.__class__.__name__, self.name, self.endpoint)
