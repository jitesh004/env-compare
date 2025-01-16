import boto3
import json
import sys
from datetime import datetime


class DateTimeEncoder(json.JSONEncoder):
    """
    Custom JSON encoder for handling datetime objects.
    """
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()  # Convert datetime to ISO format
        return super().default(obj)


def find_team_cluster(team_tag_key='ApplicationShortName', team_tag_value=''):
    """
    Finds the ECS cluster ARN for a given ApplicationShortName tag value.
    """
    ecs_client = boto3.client(service_name='ecs', region_name='us-east-1')

    try:
        # List all clusters
        clusters = ecs_client.list_clusters().get('clusterArns', [])

        for cluster_arn in clusters:
            # Fetch tags for the cluster
            tags_response = ecs_client.list_tags_for_resource(resourceArn=cluster_arn)
            tags = tags_response.get('tags', [])

            # Check if the cluster has the desired team tag
            for tag in tags:
                if tag['key'] == team_tag_key and tag['value'] == team_tag_value:
                    return cluster_arn

        print(f"No ECS cluster found for {team_tag_key} = {team_tag_value}")
        return None
    except Exception as e:
        print(f"Error finding ECS cluster: {e}")
        sys.exit(1)


def fetch_ecs_service_config(cluster_arn):
    """
    Fetches the configuration of all ECS services running in the given cluster,
    filters out 'events' and 'deployments' from the service response.
    """
    ecs_client = boto3.client(service_name='ecs', region_name='us-east-1')

    try:
        # Fetch services in the cluster
        services = ecs_client.list_services(cluster=cluster_arn).get('serviceArns', [])
        if not services:
            print(f"No services found in the cluster '{cluster_arn}'.")
            return {}

        all_service_configs = {}

        for service_arn in services:
            service_details = ecs_client.describe_services(cluster=cluster_arn, services=[service_arn])
            service_config = service_details['services'][0] if service_details['services'] else None
            if service_config:
                # Remove 'events' and 'deployments' from the service configuration
                service_config.pop('events', None)
                service_config.pop('deployments', None)
                all_service_configs[service_arn] = service_config

        return all_service_configs
    except Exception as e:
        print(f"Error fetching ECS service configurations: {e}")
        sys.exit(1)


def fetch_rds_config(ApplicationShortName):
    """
    Fetches RDS instances and filters them based on the ApplicationShortName tag in the TagList.
    :param ApplicationShortName: Name of the application (e.g., 'myApp')
    """
    rds_client = boto3.client('rds', region_name='us-east-1')

    try:
        db_instances = rds_client.describe_db_instances().get('DBInstances', [])
        if not db_instances:
            print("No RDS instances found.")
            return {}

        # Filter instances based on ApplicationShortName in their TagList
        filtered_instances = {}
        for instance in db_instances:
            tag_list = instance.get('TagList', [])
            for tag in tag_list:
                if tag['Key'] == 'ApplicationShortName' and tag['Value'] == ApplicationShortName:
                    filtered_instances[instance['DBInstanceIdentifier']] = instance
                    break

        if not filtered_instances:
            print(f"No RDS instances found for ApplicationShortName = {ApplicationShortName}.")

        return filtered_instances
    except Exception as e:
        print(f"Error fetching RDS configurations: {e}")
        sys.exit(1)


def fetch_parameter_store_config(ApplicationShortName):
    """
    Fetches Parameter Store configurations under a specific ApplicationShortName.
    Automatically constructs the full path using the ApplicationShortName.
    """
    ssm_client = boto3.client('ssm', region_name='us-east-1')
    parameters = []

    # Construct the Parameter Store path
    parameter_path = f'/{ApplicationShortName}/'

    try:
        next_token = None
        while True:
            # Pass NextToken only if it has a valid value
            if next_token:
                response = ssm_client.get_parameters_by_path(Path=parameter_path, Recursive=True, NextToken=next_token)
            else:
                response = ssm_client.get_parameters_by_path(Path=parameter_path, Recursive=True)

            parameters.extend(response.get('Parameters', []))
            next_token = response.get('NextToken')

            if not next_token:
                break

        if not parameters:
            print(f"No parameters found under path '{parameter_path}'.")
            return {}

        # Extract and return parameters as a dictionary
        return {param['Name']: param['Value'] for param in parameters}
    except Exception as e:
        print(f"Error fetching Parameter Store configurations for {ApplicationShortName}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python fetch_aws_config.py <ApplicationShortName> <output_file>")
        sys.exit(1)

    ApplicationShortName = sys.argv[1]
    output_file = sys.argv[2]

    try:
        # Fetch ECS Configurations
        cluster_arn = find_team_cluster(team_tag_key='ApplicationShortName', team_tag_value=ApplicationShortName)
        ecs_config = fetch_ecs_service_config(cluster_arn) if cluster_arn else {}

        # Fetch RDS Configurations
        rds_config = fetch_rds_config(ApplicationShortName)

        # Fetch Parameter Store Configurations
        parameter_store_config = fetch_parameter_store_config(ApplicationShortName)

        # Combine all configurations into a single output
        output_data = {
            'ecs': ecs_config,
            'rds': rds_config,
            'parameterStore': parameter_store_config
        }

        # Write to the output file
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=4, cls=DateTimeEncoder)

        print(f"All configurations successfully written to {output_file}")

    except Exception as e:
        print(f"Error fetching configurations: {e}")
        sys.exit(1)
