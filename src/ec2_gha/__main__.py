from ec2_gha.start import StartAWS
from gha_runner.gh import GitHubInstance
from gha_runner.clouddeployment import DeployInstance
from gha_runner.helper.input import EnvVarBuilder, check_required
import os


def main():
    env = dict(os.environ)
    required = ["GH_PAT", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    # Check that everything exists
    check_required(env, required)

    token = os.environ["GH_PAT"]
    # Make a copy of environment variables for immutability
    env = dict(os.environ)

    builder = (
        EnvVarBuilder(env)
        .update_state("INPUT_AWS_SUBNET_ID", "subnet_id")
        .update_state("INPUT_AWS_TAGS", "tags", is_json=True)
        .update_state("INPUT_EC2_HOME_DIR", "home_dir")
        .update_state("INPUT_EC2_IMAGE_ID", "image_id")
        .update_state("INPUT_EC2_INSTANCE_PROFILE", "iam_instance_profile")
        .update_state("INPUT_EC2_INSTANCE_TYPE", "instance_type")
        .update_state("INPUT_EC2_KEY_NAME", "key_name")
        .update_state("INPUT_EC2_ROOT_DEVICE_SIZE", "root_device_size", type_hint=int)
        .update_state("INPUT_EC2_SECURITY_GROUP_ID", "security_group_id")
        .update_state("INPUT_EC2_USERDATA", "userdata")
        .update_state("INPUT_EXTRA_GH_LABELS", "labels")
        .update_state("INPUT_INSTANCE_COUNT", "instance_count", type_hint=int)
        .update_state("INPUT_RUNNER_GRACE_PERIOD", "runner_grace_period")
        .update_state("INPUT_RUNNER_INITIAL_GRACE_PERIOD", "runner_initial_grace_period")
        .update_state("AWS_REGION", "region_name")        # default
        .update_state("INPUT_AWS_REGION", "region_name")  # input override
        .update_state("GITHUB_REPOSITORY", "repo")        # default
        .update_state("INPUT_REPO", "repo")               # input override
    )
    params = builder.params
    repo = params["repo"]
    # This needs to be handled here because the repo is required by the GitHub
    # instance
    if repo is None:
        raise Exception("Repo cannot be empty")

    # Instance count is not a keyword arg for StartAWS, so we remove it
    instance_count = params.pop("instance_count")

    gh = GitHubInstance(token=token, repo=repo)
    # This will create a new instance of StartAWS and configure it correctly
    deployment = DeployInstance(
        provider_type=StartAWS,
        cloud_params=params,
        gh=gh,
        count=instance_count,
    )
    # This will output the instance ids for using workflow syntax
    deployment.start_runner_instances()


if __name__ == "__main__":
    main()
