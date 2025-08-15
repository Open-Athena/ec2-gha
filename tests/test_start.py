from unittest.mock import patch, mock_open, Mock

import pytest
from botocore.exceptions import WaiterError, ClientError
from moto import mock_aws

from ec2_gha.start import StartAWS


@pytest.fixture(scope="function")
def aws():
    with mock_aws():
        params = {
            "gh_runner_tokens": ["testing"],
            "home_dir": "/home/ec2-user",
            "image_id": "ami-0772db4c976d21e9b",
            "instance_type": "t2.micro",
            "region_name": "us-east-1",
            "repo": "omsf-eco-infra/awsinfratesting",
            "runner_grace_period": "120",
            "runner_release": "testing",
        }
        yield StartAWS(**params)


def test_build_user_data(aws, snapshot):
    """Test that template parameters are correctly substituted using snapshot testing"""
    params = {
        "cloudwatch_logs_group": "",  # Empty = disabled
        "github_run_id": "123456789",
        "github_run_number": "42",
        "github_workflow": "test-workflow",
        "homedir": "/home/test-user",
        "labels": "test-label",
        "max_instance_lifetime": "360",
        "repo": "test-org/test-repo",
        "runner_grace_period": "60",
        "runner_release": "https://example.com/runner.tar.gz",
        "script": "echo 'test script'",
        "ssh_pubkey": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC test@host",
        "token": "test-token-xyz",
        "userdata": "echo 'custom userdata'",
    }
    user_data = aws._build_user_data(**params)

    # Verify all substitutions happened (no template variables remain)
    template_vars = [ f'${k}' for k in params ]
    for var in template_vars:
        assert var not in user_data, f"Template variable {var} was not substituted"

    # Use snapshot to verify the entire output
    assert user_data == snapshot


def test_build_user_data_with_cloudwatch(aws, snapshot):
    """Test user data with CloudWatch Logs enabled using snapshot testing"""
    params = {
        "cloudwatch_logs_group": "/aws/ec2/github-runners",
        "github_run_id": "123456789",
        "github_run_number": "42",
        "github_workflow": "test-workflow",
        "homedir": "/home/test-user",
        "labels": "test-label",
        "max_instance_lifetime": "360",
        "repo": "test-org/test-repo",
        "runner_grace_period": "30",
        "runner_initial_grace_period": "120",
        "runner_release": "https://example.com/runner.tar.gz",
        "script": "echo 'test script'",
        "ssh_pubkey": "",
        "token": "test-token-xyz",
        "userdata": "",
    }
    user_data = aws._build_user_data(**params)

    # Verify all substitutions happened (no template variables remain)
    template_vars = [ f'${k}' for k in params ]
    for var in template_vars:
        assert var not in user_data, f"Template variable {var} was not substituted"

    # Use snapshot to verify the entire output
    assert user_data == snapshot


def test_build_user_data_missing_params(aws):
    """Test that missing required parameters raise an exception"""
    params = {
        "homedir": "/home/ec2-user",
        "repo": "omsf-eco-infra/awsinfratesting",
        "script": "echo 'Hello, World!'",
        "token": "test",
        "cloudwatch_logs_group": "",
        # Missing: labels, runner_release
    }
    with pytest.raises(Exception):
        aws._build_user_data(**params)


@pytest.fixture(scope="function")
def complete_params():
    params = {
        "gh_runner_tokens": ["test"],
        "home_dir": "/home/ec2-user",
        "iam_instance_profile": "test",
        "image_id": "ami-0772db4c976d21e9b",
        "instance_type": "t2.micro",
        "labels": "",
        "region_name": "us-east-1",
        "repo": "omsf-eco-infra/awsinfratesting",
        "root_device_size": 100,
        "runner_release": "test.tar.gz",
        "security_group_id": "test",
        "subnet_id": "test",
        "tags": [
            {"Key": "Name", "Value": "test"},
            {"Key": "Owner", "Value": "test"},
        ],
    }
    yield params


@patch.dict('os.environ', {
    'GITHUB_REPOSITORY': 'Open-Athena/ec2-gha',
    'GITHUB_WORKFLOW': 'CI',
    'GITHUB_SERVER_URL': 'https://github.com',
    'GITHUB_RUN_ID': '16725250800'
})
def test_build_aws_params(complete_params):
    user_data_params = {
        "cloudwatch_logs_group": "",
        "github_run_id": "16725250800",
        "github_run_number": "1",
        "github_workflow": "CI",
        "homedir": "/home/ec2-user",
        "labels": "label",
        "max_instance_lifetime": "360",
        "repo": "omsf-eco-infra/awsinfratesting",
        "runner_grace_period": "120",
        "runner_initial_grace_period": "180",
        "runner_release": "test.tar.gz",
        "script": "echo 'Hello, World!'",
        "ssh_pubkey": "",
        "token": "test",
        "userdata": "",
    }
    aws = StartAWS(**complete_params)
    params = aws._build_aws_params(user_data_params)

    # Test structure without checking exact UserData content
    assert params["ImageId"] == "ami-0772db4c976d21e9b"
    assert params["InstanceType"] == "t2.micro"
    assert params["MinCount"] == 1
    assert params["MaxCount"] == 1
    assert params["SubnetId"] == "test"
    assert params["SecurityGroupIds"] == ["test"]
    assert params["IamInstanceProfile"] == {"Name": "test"}
    assert params["InstanceInitiatedShutdownBehavior"] == "terminate"
    assert "UserData" in params
    assert params["TagSpecifications"] == [
        {
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": "test"},
                {"Key": "Owner", "Value": "test"},
                {"Key": "repository", "Value": "Open-Athena/ec2-gha"},
                {"Key": "workflow", "Value": "CI"},
                {"Key": "gha_url", "Value": "https://github.com/Open-Athena/ec2-gha/actions/runs/16725250800"},
            ],
        }
    ]


def test_modify_root_disk_size(complete_params):
    mock_client = Mock()

    # Mock image data with all device mappings
    mock_image_data = {
        "Images": [{
            "RootDeviceName": "/dev/sda1",
            "BlockDeviceMappings": [
                {
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "VolumeSize": 50,
                        "VolumeType": "gp3",
                        "Encrypted": False
                    },
                    "DeviceName": "/dev/sda1"
                },
                {
                    "DeviceName": "/dev/sdb",
                    "VirtualName": "ephemeral0"
                },
                {
                    "DeviceName": "/dev/sdc",
                    "VirtualName": "ephemeral1"
                }
            ]
        }]
    }

    def mock_describe_images(**kwargs):
        if kwargs.get('DryRun', False):
            raise ClientError(
                error_response={"Error": {"Code": "DryRunOperation"}},
                operation_name="DescribeImages"
            )
        return mock_image_data

    mock_client.describe_images = mock_describe_images
    aws = StartAWS(**complete_params)
    out = aws._modify_root_disk_size(mock_client, {})
    # Expected output should preserve all devices, only modifying root volume size
    expected_output = {
        "BlockDeviceMappings": [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "DeleteOnTermination": True,
                    "VolumeSize": 100,
                    "VolumeType": "gp3",
                    "Encrypted": False
                }
            },
            {
                "DeviceName": "/dev/sdb",
                "VirtualName": "ephemeral0"
            },
            {
                "DeviceName": "/dev/sdc",
                "VirtualName": "ephemeral1"
            }
        ]
    }
    assert out == expected_output


def test_modify_root_disk_size_permission_error(complete_params):
    mock_client = Mock()

    # Mock permission denied error
    mock_client.describe_images.side_effect = ClientError(
        error_response={'Error': {'Code': 'AccessDenied'}},
        operation_name='DescribeImages'
    )

    aws = StartAWS(**complete_params)

    with pytest.raises(ClientError) as exc_info:
        aws._modify_root_disk_size(mock_client, {})

    assert 'AccessDenied' in str(exc_info.value)


def test_modify_root_disk_size_no_change(complete_params):
    mock_client = Mock()
    complete_params["root_device_size"] = 0

    mock_image_data = {
        "Images": [{
            "RootDeviceName": "/dev/sda1",
            "BlockDeviceMappings": [
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {
                        "VolumeSize": 50,
                        "VolumeType": "gp3"
                    }
                },
                {
                    "DeviceName": "/dev/sdb",
                    "VirtualName": "ephemeral0"
                }
            ]
        }]
    }

    def mock_describe_images(**kwargs):
        if kwargs.get('DryRun', False):
            raise ClientError(
                error_response={'Error': {'Code': 'DryRunOperation'}},
                operation_name='DescribeImages'
            )
        return mock_image_data

    mock_client.describe_images = mock_describe_images

    aws = StartAWS(**complete_params)
    input_params = {}
    result = aws._modify_root_disk_size(mock_client, input_params)

    # With root_device_size = 0, no modifications should be made
    assert result == input_params


def test_create_instance_with_labels(aws):
    aws.labels = "test"
    ids = aws.create_instances()
    assert len(ids) == 1


def test_create_instances(aws):
    ids = aws.create_instances()
    assert len(ids) == 1


def test_create_instances_missing_release(aws):
    aws.runner_release = ""
    with pytest.raises(
        ValueError, match="No runner release provided, cannot create instances."
    ):
        aws.create_instances()


def test_create_instances_missing_home_dir(aws):
    aws.home_dir = ""
    with pytest.raises(
        ValueError, match="No home directory provided, cannot create instances."
    ):
        aws.create_instances()


def test_create_instances_missing_tokens(aws):
    aws.gh_runner_tokens = []
    with pytest.raises(
        ValueError,
        match="No GitHub runner tokens provided, cannot create instances.",
    ):
        aws.create_instances()


def test_create_instances_missing_image_id(aws):
    aws.image_id = ""
    with pytest.raises(
        ValueError, match="No image ID provided, cannot create instances."
    ):
        aws.create_instances()


def test_create_instances_missing_instance_type(aws):
    aws.instance_type = ""
    with pytest.raises(
        ValueError, match="No instance type provided, cannot create instances."
    ):
        aws.create_instances()


def test_create_instances_missing_region_name(aws):
    aws.region_name = ""
    with pytest.raises(
        ValueError, match="No region name provided, cannot create instances."
    ):
        aws.create_instances()


def test_wait_until_ready(aws):
    ids = aws.create_instances()
    params = {
        "MaxAttempts": 1,
        "Delay": 5,
    }
    ids = list(ids)
    aws.wait_until_ready(ids, **params)


def test_wait_until_ready_dne(aws):
    # This is a fake instance id
    ids = ["i-xxxxxxxxxxxxxxxxx"]
    params = {
        "MaxAttempts": 1,
        "Delay": 5,
    }
    with pytest.raises(WaiterError):
        aws.wait_until_ready(ids, **params)


@pytest.mark.slow
def test_wait_until_ready_dne_long(aws):
    # This is a fake instance id
    ids = ["i-xxxxxxxxxxxxxxxxx"]
    # Runs with the default parameters
    with pytest.raises(WaiterError):
        aws.wait_until_ready(ids)


def test_set_instance_mapping(aws, monkeypatch):
    monkeypatch.setenv("GITHUB_OUTPUT", "mock_output_file")
    mapping = {"i-xxxxxxxxxxxxxxxxx": "test"}
    mock_file = mock_open()

    with patch("builtins.open", mock_file):
        aws.set_instance_mapping(mapping)

    # Should be called 4 times for single instance (mapping, instances, instance-id, label)
    assert mock_file.call_count == 4
    assert all(call[0][0] == "mock_output_file" for call in mock_file.call_args_list)


def test_set_instance_mapping_multiple(aws, monkeypatch):
    monkeypatch.setenv("GITHUB_OUTPUT", "mock_output_file")
    mapping = {"i-xxxxxxxxxxxxxxxxx": "test1", "i-yyyyyyyyyyyyyyyyy": "test2"}
    mock_file = mock_open()

    with patch("builtins.open", mock_file):
        aws.set_instance_mapping(mapping)

    # Should be called 2 times for multiple instances (mapping, instances only)
    assert mock_file.call_count == 2
    assert all(call[0][0] == "mock_output_file" for call in mock_file.call_args_list)
