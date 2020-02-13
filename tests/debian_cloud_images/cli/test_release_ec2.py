from debian_cloud_images.cli.release_ec2 import (
    Ec2Publisher,
    ReleaseEc2Command,
)


class TestCommand:

    def test__init__(self):
        c = ReleaseEc2Command(
            access_key_id='access-key',
            access_secret_key='secret-key',
            ami_id='ami-0123456',
            region='us-east-1',
        )

        assert isinstance(c.publisher, Ec2Publisher)
        assert c.publisher.key == 'access-key'
        assert c.publisher.secret == 'secret-key'
        assert c.publisher.ami_id == 'ami-0123456'
        assert c.publisher.region == 'us-east-1'
