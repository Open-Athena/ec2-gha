import importlib.resources
from dataclasses import dataclass, field
from os import environ
from string import Template
import json

import boto3
from botocore.exceptions import ClientError
from gha_runner import gh
from gha_runner.clouddeployment import CreateCloudInstance
from gha_runner.helper.workflow_cmds import output
from copy import deepcopy

from ec2_gha.defaults import AUTO, RUNNER_REGISTRATION_TIMEOUT


@dataclass
class StartAWS(CreateCloudInstance):
    """Class to start GitHub Actions runners on AWS.

    Parameters
    ----------
    image_id : str
        The ID of the AMI to use.
    instance_type : str
        The type of instance to use.
    region_name : str
        The name of the region to use.
    repo : str
        The repository to use.
    cloudwatch_logs_group : str
        CloudWatch Logs group name for streaming runner logs. Defaults to an empty string.
    gh_runner_tokens : list[str]
        A list of GitHub runner tokens. Defaults to an empty list.
    home_dir : str
        The home directory of the user. If not provided, will be inferred from the AMI.
    iam_instance_profile : str
        The name of the IAM role to use. Defaults to an empty string.
    key_name : str
        The name of the EC2 key pair to use for SSH access. Defaults to an empty string.
    labels : str
        A comma-separated list of labels to apply to the runner. Defaults to an empty string.
    max_instance_lifetime : str
        Maximum instance lifetime in minutes before automatic shutdown. Defaults to "360" (6 hours).
    root_device_size : int
        The size of the root device. Defaults to 0 which uses the default.
    runner_initial_grace_period : str
        Grace period in seconds before terminating if no jobs have started. Defaults to "180".
    runner_grace_period : str
        Grace period in seconds before terminating instance after last job completes. Defaults to "60".
    runner_poll_interval : str
        How often (in seconds) to check termination conditions. Defaults to "10".
    script : str
        The script to run on the instance. Defaults to an empty string.
    security_group_id : str
        The ID of the security group to use. Defaults to an empty string.
    ssh_pubkey : str
        SSH public key to add to authorized_keys. Defaults to an empty string.
    subnet_id : str
        The ID of the subnet to use. Defaults to an empty string.
    tags : list[dict[str, str]]
        A list of tags to apply to the instance. Defaults to an empty list.
    userdata : str
        Custom user data script to prepend to the runner setup. Defaults to an empty string.

    """

    image_id: str
    instance_type: str
    region_name: str
    repo: str
    cloudwatch_logs_group: str = ""
    gh_runner_tokens: list[str] = field(default_factory=list)
    home_dir: str = ""
    iam_instance_profile: str = ""
    instance_name: str = ""
    key_name: str = ""
    labels: str = ""
    max_instance_lifetime: str = "360"
    root_device_size: int = 0
    runner_grace_period: str = "60"
    runner_initial_grace_period: str = "180"
    runner_poll_interval: str = "10"
    runner_release: str = ""
    script: str = ""
    security_group_id: str = ""
    ssh_pubkey: str = ""
    subnet_id: str = ""
    tags: list[dict[str, str]] = field(default_factory=list)
    userdata: str = ""

    def _build_aws_params(self, user_data_params: dict, idx: int = None) -> dict:
        """Build the parameters for the AWS API call.

        Parameters
        ----------
        user_data_params : dict
            A dictionary of parameters to pass to the user

        Returns
        -------
        dict
            A dictionary of parameters for the AWS API call.

        """
        params = {
            "ImageId": self.image_id,
            "InstanceType": self.instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "UserData": self._build_user_data(**user_data_params),
            "InstanceInitiatedShutdownBehavior": "terminate",
        }
        if self.subnet_id != "":
            params["SubnetId"] = self.subnet_id
        if self.security_group_id and self.security_group_id.strip():
            params["SecurityGroupIds"] = [self.security_group_id.strip()]
        if self.iam_instance_profile != "":
            params["IamInstanceProfile"] = {"Name": self.iam_instance_profile}
        if self.key_name != "":
            params["KeyName"] = self.key_name
        # Add default tags if not already present
        default_tags = []
        existing_keys = {tag["Key"] for tag in self.tags}
        import os

        # Add Name tag if not provided
        if "Name" not in existing_keys:
            # Build template variables
            template_vars = {}

            # Get repository name (just the basename)
            if os.environ.get("GITHUB_REPOSITORY"):
                template_vars["repo"] = os.environ["GITHUB_REPOSITORY"].split("/")[-1]
            else:
                template_vars["repo"] = "unknown"

            # Get workflow full name (e.g., "Test pip install")
            template_vars["workflow"] = os.environ.get("GITHUB_WORKFLOW", "unknown")

            # Get workflow filename stem and ref from GITHUB_WORKFLOW_REF
            workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
            if workflow_ref:
                import re
                # Extract filename and ref from path like "owner/repo/.github/workflows/test.yml@ref"
                m = re.search(r'/(?P<name>[^/@]+)\.(yml|yaml)@(?P<ref>[^@]+)$', workflow_ref)
                if m:
                    # Get the workflow filename stem (e.g., "install" from "install.yaml")
                    template_vars["name"] = m['name']

                    # Clean up the ref - remove "refs/heads/" or "refs/tags/" prefix
                    ref = m['ref']
                    if ref.startswith('refs/heads/'):
                        ref = ref[11:]
                    elif ref.startswith('refs/tags/'):
                        ref = ref[10:]
                    template_vars["ref"] = ref
                else:
                    template_vars["name"] = "unknown"
                    template_vars["ref"] = "unknown"
            else:
                template_vars["name"] = "unknown"
                template_vars["ref"] = "unknown"

            # Get run number
            template_vars["run_number"] = os.environ.get("GITHUB_RUN_NUMBER", "unknown")

            # Add instance index if provided (for multi-instance launches)
            if idx is not None:
                template_vars["idx"] = str(idx)

            # Apply the instance name template
            from string import Template
            name_template = Template(self.instance_name)
            name_value = name_template.safe_substitute(**template_vars)

            default_tags.append({"Key": "Name", "Value": name_value})

        # Add repository tag if available
        if "Repository" not in existing_keys and os.environ.get("GITHUB_REPOSITORY"):
            default_tags.append({"Key": "Repository", "Value": os.environ["GITHUB_REPOSITORY"]})

        # Add workflow tag if available
        if "Workflow" not in existing_keys and os.environ.get("GITHUB_WORKFLOW"):
            default_tags.append({"Key": "Workflow", "Value": os.environ["GITHUB_WORKFLOW"]})

        # Add run URL tag if available
        if "URL" not in existing_keys and os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_RUN_ID"):
            gha_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
            default_tags.append({"Key": "URL", "Value": gha_url})

        # Combine user tags with default tags
        all_tags = self.tags + default_tags

        if len(all_tags) > 0:
            specs = {"ResourceType": "instance", "Tags": all_tags}
            params["TagSpecifications"] = [specs]

        return params

    def _build_user_data(self, **kwargs) -> str:
        """Build the user data script.

        Parameters
        ----------
        kwargs : dict
            A dictionary of parameters to pass to the template.

        Returns
        -------
        str
            The user data script as a string.

        """
        # Import log constants to inject into template
        from ec2_gha.log_constants import (
            LOG_PREFIX_JOB_STARTED,
            LOG_PREFIX_JOB_COMPLETED,
        )

        # Add log constants to the kwargs
        kwargs['log_prefix_job_started'] = LOG_PREFIX_JOB_STARTED
        kwargs['log_prefix_job_completed'] = LOG_PREFIX_JOB_COMPLETED

        template = importlib.resources.files("ec2_gha").joinpath("templates/user-script.sh.templ")
        with template.open() as f:
            template_content = f.read()

        try:
            parsed = Template(template_content)
            runner_script = parsed.substitute(**kwargs)
            return runner_script
        except Exception as e:
            raise Exception("Error parsing user data template") from e

    def _modify_root_disk_size(self, client, params: dict) -> dict:
        """Modify the root disk size of the instance.

        Parameters
        ----------
        client
            The EC2 client object.
        params : dict
            The parameters for the instance.

        Returns
        -------
        dict
            The modified parameters

        Raises
        ------
        botocore.exceptions.ClientError
           If the user does not have permissions to describe images.
        """
        try:
            client.describe_images(ImageIds=[self.image_id], DryRun=True)
        except ClientError as e:
            # This is the case where we DO have access
            if "DryRunOperation" in str(e):
                image_options = client.describe_images(ImageIds=[self.image_id])
                root_device_name = image_options["Images"][0]["RootDeviceName"]
                block_devices = deepcopy(image_options["Images"][0]["BlockDeviceMappings"])
                for idx, block_device in enumerate(block_devices):
                    if block_device["DeviceName"] == root_device_name:
                        if self.root_device_size > 0:
                            block_devices[idx]["Ebs"]["VolumeSize"] = self.root_device_size
                            params["BlockDeviceMappings"] = block_devices
                        break
            else:
                raise e
        return params

    def create_instances(self) -> dict[str, str]:
        """Create instances on AWS.

        Creates and registers instances on AWS using the provided parameters.

        Returns
        -------
        dict[str, str]
            A dictionary of instance IDs and labels.
        """
        if not self.gh_runner_tokens:
            raise ValueError("No GitHub runner tokens provided, cannot create instances.")
        if not self.runner_release:
            raise ValueError("No runner release provided, cannot create instances.")
        if not self.image_id:
            raise ValueError("No image ID provided, cannot create instances.")
        if not self.instance_type:
            raise ValueError("No instance type provided, cannot create instances.")
        if not self.region_name:
            raise ValueError("No region name provided, cannot create instances.")
        ec2 = boto3.client("ec2", region_name=self.region_name)

        # Use AUTO to let the instance detect its own home directory
        if not self.home_dir:
            self.home_dir = AUTO
        id_dict = {}
        for idx, token in enumerate(self.gh_runner_tokens):
            label = gh.GitHubInstance.generate_random_label()
            # Combine user labels with the generated runner label
            labels = f"{self.labels},{label}" if self.labels else label

            user_data_params = {
                "cloudwatch_logs_group": self.cloudwatch_logs_group,
                "github_workflow": environ.get("GITHUB_WORKFLOW", ""),
                "github_run_id": environ.get("GITHUB_RUN_ID", ""),
                "github_run_number": environ.get("GITHUB_RUN_NUMBER", ""),
                "homedir": self.home_dir,
                "labels": labels,
                "max_instance_lifetime": self.max_instance_lifetime,
                "repo": self.repo,
                "runner_grace_period": self.runner_grace_period,
                "runner_initial_grace_period": self.runner_initial_grace_period,
                "runner_poll_interval": self.runner_poll_interval,
                "runner_registration_timeout": environ.get("INPUT_RUNNER_REGISTRATION_TIMEOUT", "").strip() or RUNNER_REGISTRATION_TIMEOUT,
                "runner_release": self.runner_release,
                "script": self.script,
                "ssh_pubkey": self.ssh_pubkey,
                "token": token,
                "userdata": self.userdata,
            }
            params = self._build_aws_params(user_data_params, idx=idx)
            if self.root_device_size > 0:
                params = self._modify_root_disk_size(ec2, params)
            result = ec2.run_instances(**params)
            instances = result["Instances"]
            id = instances[0]["InstanceId"]
            id_dict[id] = label
        return id_dict

    def wait_until_ready(self, ids: list[str], **kwargs):
        """Wait until instances are running.

        Waits until the instances are running before continuing.

        Parameters
        ----------
        ids : list[str]
            A list of instance IDs to wait for.
        kwargs : dict
            A dictionary of custom configuration options for the waiter.

        """
        ec2 = boto3.client("ec2", self.region_name)
        waiter = ec2.get_waiter("instance_running")
        # Pass custom config for the waiter
        if kwargs:
            waiter.wait(InstanceIds=ids, WaiterConfig=kwargs)
        # Otherwise, use the default config
        else:
            waiter.wait(InstanceIds=ids)

    def set_instance_mapping(self, mapping: dict[str, str]):
        """Set the instance mapping.

        Sets the instance mapping for the runner to be used by the stop action.

        Parameters
        ----------
        mapping : dict[str, str]
            A dictionary of instance IDs and labels.

        """
        github_labels = list(mapping.values())
        output("mapping", json.dumps(mapping))
        output("instances", json.dumps(github_labels))

        # For single instance use, output simplified values
        if len(mapping) == 1:
            instance_id = list(mapping.keys())[0]
            label = list(mapping.values())[0]
            output("instance-id", instance_id)
            output("label", label)
