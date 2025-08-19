from unittest.mock import patch, mock_open, Mock

import pytest
from botocore.exceptions import WaiterError, ClientError
from moto import mock_aws

from ec2_gha.start import StartAWS
from ec2_gha.defaults import AUTO


@pytest.fixture(scope="function")
def base_aws_params():
    """Base parameters for StartAWS initialization"""
    return {
        "gh_runner_tokens": ["testing"],
        "home_dir": "/home/ec2-user",
        "image_id": "ami-0772db4c976d21e9b",
        "instance_type": "t2.micro",
        "region_name": "us-east-1",
        "repo": "omsf-eco-infra/awsinfratesting",
        "runner_grace_period": "120",
        "runner_release": "testing",
    }


@pytest.fixture(scope="function")
def aws(base_aws_params):
    with mock_aws():
        yield StartAWS(**base_aws_params)


@pytest.fixture(scope="function")
def aws_params_user_data():
    """User data params for AWS params tests"""
    return {
        "cloudwatch_logs_group": "",  # Empty = disabled
        "debug": "",  # Empty = disabled
        "github_run_id": "16725250800",
        "github_run_number": "42",
        "github_workflow": "CI",
        "homedir": "/home/ec2-user",
        "max_instance_lifetime": "360",
        "repo": "omsf-eco-infra/awsinfratesting",
        "runner_grace_period": "61",
        "runner_initial_grace_period": "181",
        "runner_poll_interval": "11",
        "runner_release": "test.tar.gz",
        "runner_registration_timeout": "300",
        "runners_per_instance": "1",
        "runner_tokens": "test",  # Space-delimited tokens
        "runner_labels": "label",  # Pipe-delimited labels
        "script": "echo 'Hello, World!'",
        "ssh_pubkey": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC test@host",
        "userdata": "",
    }


def test_build_user_data(aws, aws_params_user_data, snapshot):
    """Test that template parameters are correctly substituted using snapshot testing"""
    user_data = aws._build_user_data(**aws_params_user_data)
    assert user_data == snapshot


def test_build_user_data_with_cloudwatch(aws, aws_params_user_data, snapshot):
    """Test user data with CloudWatch Logs enabled using snapshot testing"""
    params = aws_params_user_data | {
        "cloudwatch_logs_group": "/aws/ec2/github-runners",
        "runner_grace_period": "61",
        "runner_initial_grace_period": "181",
        "runner_poll_interval": "11",
        "ssh_pubkey": "",
        "userdata": "",
    }
    user_data = aws._build_user_data(**params)
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
def complete_params(base_aws_params):
    """Extended parameters including AWS-specific configurations"""
    return base_aws_params | {
        "gh_runner_tokens": ["test"],
        "iam_instance_profile": "test",
        "labels": "",
        "root_device_size": 100,
        "runner_release": "test.tar.gz",
        "security_group_id": "test",
        "subnet_id": "test",
        "tags": [
            {"Key": "Name", "Value": "test"},
            {"Key": "Owner", "Value": "test"},
        ],
    }


@pytest.fixture(scope="function")
def github_env():
    """Common GitHub environment variables for tests"""
    return {
        'GITHUB_REPOSITORY': 'Open-Athena/ec2-gha',
        'GITHUB_WORKFLOW': 'CI',
        'GITHUB_WORKFLOW_REF': 'Open-Athena/ec2-gha/.github/workflows/test.yml@refs/heads/main',
        'GITHUB_RUN_NUMBER': '42',
        'GITHUB_SERVER_URL': 'https://github.com',
        'GITHUB_RUN_ID': '16725250800'
    }


def test_build_aws_params_with_idx(complete_params, aws_params_user_data, github_env, snapshot):
    """Test _build_aws_params with idx parameter for multi-instance scenarios"""
    with patch.dict('os.environ', github_env):
        user_data_params = aws_params_user_data
        # Remove existing tags to test auto-generated Name tag
        params_without_tags = complete_params.copy()
        params_without_tags['tags'] = []
        # Add instance_name template for testing
        params_without_tags['instance_name'] = '$repo/$name-$idx#$run_number'
        aws = StartAWS(**params_without_tags)

        params = aws._build_aws_params(user_data_params, idx=0)

        # Use snapshot to verify the entire structure including UserData
        assert params == snapshot


def test_build_aws_params(complete_params, aws_params_user_data, github_env, snapshot):
    """Test _build_aws_params without idx parameter"""
    # Slightly modified github_env without WORKFLOW_REF
    env = github_env.copy()
    del env['GITHUB_WORKFLOW_REF']

    with patch.dict('os.environ', env):
        user_data_params = aws_params_user_data | {"github_run_number": "1"}
        aws = StartAWS(**complete_params)
        params = aws._build_aws_params(user_data_params)

        # Use snapshot to verify the entire structure including UserData
        assert params == snapshot


def test_auto_home_dir(complete_params):
    """Test that home_dir is set to AUTO when not provided"""
    params = complete_params.copy()
    params['home_dir'] = ""
    aws = StartAWS(**params)
    aws.gh_runner_tokens = ["test-token"]
    aws.runner_release = "https://example.com/runner.tar.gz"

    with patch("boto3.client") as mock_client:
        mock_ec2 = Mock()
        mock_client.return_value = mock_ec2

        # Mock the run_instances response
        mock_ec2.run_instances.return_value = {
            "Instances": [{"InstanceId": "i-123456"}]
        }

        result = aws.create_instances()

        # Verify home_dir was set to AUTO
        assert aws.home_dir == AUTO
        assert "i-123456" in result


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


def test_create_instances_sets_auto_home_dir(base_aws_params):
    """Test that home_dir is set to AUTO when not provided"""
    params = base_aws_params.copy()
    params['home_dir'] = ""

    with mock_aws():
        aws = StartAWS(**params)
        aws.gh_runner_tokens = ["test-token"]
        aws.runner_release = "https://example.com/runner.tar.gz"

        with patch("boto3.client") as mock_client:
            mock_ec2 = Mock()
            mock_client.return_value = mock_ec2

            # Mock the run_instances response
            mock_ec2.run_instances.return_value = {
                "Instances": [{"InstanceId": "i-123456"}]
            }

            result = aws.create_instances()

            # Verify home_dir was set to AUTO for runtime detection
            assert aws.home_dir == AUTO
            assert "i-123456" in result


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
