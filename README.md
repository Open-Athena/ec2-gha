# ec2-gha
This repository contains the code to start a GitHub Actions runner on an AWS EC2 instance.

## Inputs
| Input                 | Description                                                                                                         | Required for start | Default |
|-----------------------|---------------------------------------------------------------------------------------------------------------------|------------------- |---------|
| aws_region            | The AWS region name to use for your runner. Defaults to AWS_REGION                                                  | true               |         |
| aws_subnet_id         | The AWS subnet ID to use for your runner. Will use the account default subnet if not specified.                     | false              | The default AWS subnet ID |
| aws_tags              | The AWS tags to use for your runner, formatted as a JSON list. See `README` for more details.                       | false              |         |
| ec2_home_dir          | The AWS AMI home directory to use for your runner. Will not start if not specified.                                 | true               |         |
| ec2_image_id          | The machine AMI to use for your runner. This AMI can be a default but should have docker installed in the AMI.      | true               |         |
| ec2_instance_profile  | Optional instance profile for EC2 runner instances.                                                       | false              |         |
| ec2_instance_type     | The type of instance to use for your runner. For example: t2.micro, t4g.nano, etc. Will not start if not specified. | true               |         |
| ec2_key_name          | Name of the EC2 key pair to use for SSH access.                                                                     | false              |         |
| ec2_root_device_size  | The root device size in GB to use for your runner.                                                                  | false              | The AMI default root disk size |
| ec2_security_group_id | The AWS security group ID to use for your runner. Will use the account default security group if not specified.     | false              | The default AWS security group |
| ec2_userdata          | User data script to run on instance startup. Use this to configure the instance before the runner starts.           | false              |         |
| extra_gh_labels       | Any extra GitHub labels to tag your runners with. Passed as a comma-separated list with no spaces.                  | false              |         |
| gh_timeout            | The timeout in seconds to wait for the runner to come online as seen by the GitHub API. Defaults to 1200 seconds.   | false              | 1200    |
| instance_count        | The number of instances to create, defaults to 1                                                                    | false              | 1       |
| repo                  | The repo to run against. Will use the current repo if not specified.                                                | false    | The repo the runner is running in |

## Outputs
| Name | Description |
| ---- | ----------- |
| mapping | A JSON object mapping instance IDs to unique GitHub runner labels. This is used in conjunction with the `instance_mapping` input when stopping. |
| instances | A JSON list of the GitHub runner labels to be used in the 'runs-on' field |
| label | The single runner label (only available when instance_count=1) |
| instance-id | The EC2 instance ID (only available when instance_count=1) |

## Example usage

```yaml
name: Start AWS GHA Runner
on:
  workflow_run:
jobs:
  start-aws-runner:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    outputs:
      mapping: ${{ steps.aws-start.outputs.mapping }}
      instances: ${{ steps.aws-start.outputs.instances }}
    steps:
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE }}
          aws-region: us-east-1
      - name: Create cloud runner
        id: aws-start
        uses: Open-Athena/ec2-gha@v1.0.0
        with:
          ec2_image_id: ami-0f7c4a792e3fb63c8
          ec2_instance_type: g4dn.xlarge
          ec2_home_dir: /home/ubuntu
        env:
          GH_PAT: ${{ secrets.GH_PAT }}
```

[Open-Athena/ec2] also shows [example usage][ec2 example] of `ec2_userdata`, to automatically shut down the instance.

[Open-Athena/ec2]: https://github.com/Open-Athena/ec2
[ec2 example]: https://github.com/Open-Athena/ec2/blob/94e815ac681ba5836ce07cda894d53d3dd900afd/.github/workflows/runner.yml#L83
