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
        # List all clusters with pagination
        clusters = []
        paginator = ecs_client.get_paginator('list_clusters')
        for page in paginator.paginate():
            clusters.extend(page.get('clusterArns', []))

        for cluster_arn in clusters:
            # Fetch tags for the cluster
            tags_response = ecs_client.list_tags_for_resource(resourceArn=cluster_arn)
            tags = tags_response.get('tags', [])

            # Check if the cluster has the desired team tag
            for tag in tags:
                if tag['key'] == team_tag_key and tag['value'] == team_tag_value:
                    cluster_name = cluster_arn.split('/')[-1]  # Extract cluster name from ARN
                    return cluster_name, cluster_arn

        print(f"No ECS cluster found for {team_tag_key} = {team_tag_value}")
        return None
    except Exception as e:
        print(f"Error finding ECS cluster: {e}")
        sys.exit(1)


def load_env_config(env_index):
    """
    Load environment configuration from aws_env_config.json file by index.
    Returns None if file doesn't exist or is empty.
    
    Args:
        env_index: Index of environment to load (0, 1, etc.)
    """
    try:
        with open('aws_env_config.json', 'r') as f:
            content = f.read().strip()
            if not content:
                return None
            config = json.loads(content)
            envs = config.get('envs', [])
            return envs[env_index] if 0 <= env_index < len(envs) else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def fetch_ecs_service_config(cluster_names):
    """
    Fetches the configuration of ECS services for specified cluster names.
    Returns services with indexed keys.
    """
    ecs_client = boto3.client(service_name='ecs', region_name='us-east-1')
    all_service_configs = {}
    service_index = 1

    try:
        for cluster_name in cluster_names:
            # Get cluster ARN
            clusters = ecs_client.list_clusters()['clusterArns']
            cluster_arn = next((arn for arn in clusters if cluster_name in arn), None)
            
            if not cluster_arn:
                print(f"Cluster not found: {cluster_name}")
                continue

            # Fetch services in the cluster with pagination
            services = []
            paginator = ecs_client.get_paginator('list_services')
            for page in paginator.paginate(cluster=cluster_arn):
                services.extend(page.get('serviceArns', []))

            if not services:
                print(f"No services found in cluster '{cluster_name}'")
                continue

            # Describe services in chunks of 10 (AWS API limit)
            for i in range(0, len(services), 10):
                service_chunk = services[i:i + 10]
                service_details = ecs_client.describe_services(cluster=cluster_arn, services=service_chunk)
                
                for service_config in service_details['services']:
                    service_config.pop('events', None)
                    service_config.pop('deployments', None)
                    service_name = service_config.get('serviceName')
                    service_key = f"{cluster_name}/{service_name}"
                    
                    # Store with indexed key and include original service key in config
                    all_service_configs[f"service_{service_index}"] = {
                        "compareIdentifier": service_key,
                        **service_config
                    }
                    service_index += 1

        return all_service_configs
    except Exception as e:
        print(f"Error fetching ECS service configurations: {e}")
        sys.exit(1)


def fetch_rds_config(identifier, use_instance_ids=False):
    """
    Fetches RDS configurations either by instance IDs or ApplicationShortName.
    Returns instances with indexed keys.
    """
    rds_client = boto3.client('rds', region_name='us-east-1')
    filtered_instances = {}
    instance_index = 1

    try:
        paginator = rds_client.get_paginator('describe_db_instances')
        for page in paginator.paginate():
            for instance in page['DBInstances']:
                should_include = False
                if use_instance_ids:
                    should_include = instance['DBInstanceIdentifier'] in identifier
                else:
                    # Filter by ApplicationShortName tag
                    tag_list = instance.get('TagList', [])
                    for tag in tag_list:
                        if tag['Key'] == 'ApplicationShortName' and tag['Value'] == identifier:
                            should_include = True
                            break

                if should_include:
                    instance_id = instance['DBInstanceIdentifier']
                    # Store with indexed key and include original instance ID in config
                    filtered_instances[f"rds_db_instance_{instance_index}"] = {
                        "compareIdentifier": instance_id,
                        **instance
                    }
                    instance_index += 1

        if not filtered_instances:
            print(f"No RDS instances found for {'instance IDs' if use_instance_ids else 'ApplicationShortName'} = {identifier}")

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
        print("Usage: python fetch_aws_config.py <ApplicationShortName> <output_file> <env_index>")
        sys.exit(1)

    ApplicationShortName = sys.argv[1]
    output_file = sys.argv[2]
    env_index = int(sys.argv[3]) if len(sys.argv) > 3 else None

    try:
        # Load environment configuration
        env_config = load_env_config(env_index) if env_index is not None else None
        output_data = {}

        if env_config:
            # Fetch ECS configurations if ecs array is not empty
            ecs_clusters = env_config.get('ecs', [])
            if ecs_clusters:
                output_data['ecs'] = fetch_ecs_service_config(ecs_clusters)
            
            # Fetch RDS configurations if rds array is not empty
            rds_instances = env_config.get('rds', [])
            if rds_instances:
                output_data['rds'] = fetch_rds_config(rds_instances, use_instance_ids=True)
            
            # Fetch Parameter Store configurations if parameterStore is true
            if env_config.get('parameterStore') is True:
                output_data['parameterStore'] = fetch_parameter_store_config(ApplicationShortName)
        else:
            # Fall back to original behavior
            cluster_name, cluster_arn = find_team_cluster(team_tag_key='ApplicationShortName', 
                                                        team_tag_value=ApplicationShortName)
            output_data = {
                'ecs': fetch_ecs_service_config([cluster_name]) if cluster_arn else {},
                'rds': fetch_rds_config(ApplicationShortName, use_instance_ids=False),
                'parameterStore': fetch_parameter_store_config(ApplicationShortName)
            }

        # Write to the output file
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=4, cls=DateTimeEncoder)

        print(f"All configurations successfully written to {output_file}")

    except Exception as e:
        print(f"Error fetching configurations: {e}")
        sys.exit(1)
