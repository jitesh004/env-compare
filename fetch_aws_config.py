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


def fetch_ecs_service_config(cluster_names, use_custom_identifier=False):
    """
    Fetches the configuration of ECS services for specified cluster names.
    Returns services with indexed keys.
    """
    ecs_client = boto3.client(service_name='ecs', region_name='us-east-1')
    all_service_configs = {}
    service_index = 0

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
                    service_index += 1
                    service_config.pop('events', None)
                    service_config.pop('deployments', None)
                    service_name = service_config.get('serviceName')
                    service_key = f"{cluster_name}/{service_name}"
                    
                    # Store with indexed key and include original service key in config
                    if use_custom_identifier:
                        all_service_configs[f"service_{service_index}"] = {
                            "compareIdentifier": service_key,
                            **service_config
                        }
                    else:
                        all_service_configs[service_key] = service_config

        return all_service_configs
    except Exception as e:
        print(f"Error fetching ECS service configurations: {e}")
        sys.exit(1)


def fetch_rds_config(identifier, use_instance_ids=False):
    """
    Fetches RDS configurations either by instance IDs or ApplicationShortName.
    Returns instances with indexed keys or instance names as keys based on mode.
    """
    rds_client = boto3.client('rds', region_name='us-east-1')
    filtered_instances = {}
    instance_index = 0

    try:
        paginator = rds_client.get_paginator('describe_db_instances')
        for page in paginator.paginate():
            for instance in page['DBInstances']:
                should_include = False
                if use_instance_ids:
                    # Using specific instance IDs - use indexed keys
                    should_include = instance['DBInstanceIdentifier'] in identifier
                    if should_include:
                        instance_index += 1
                        instance_id = instance['DBInstanceIdentifier']
                        filtered_instances[f"rds_db_instance_{instance_index}"] = {
                            "compareIdentifier": instance_id,
                            **instance
                        }
                else:
                    # Using ApplicationShortName - use instance names as keys
                    tag_list = instance.get('TagList', [])
                    for tag in tag_list:
                        if tag['Key'] == 'ApplicationShortName' and tag['Value'] == identifier:
                            filtered_instances[instance['DBInstanceIdentifier']] = instance
                            break

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
            if (next_token):
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


def fetch_lambda_config(identifier, use_function_names=False):
    """
    Fetches Lambda function configurations either by function names or ApplicationShortName.
    Returns functions with indexed keys or function names as keys based on the mode.
    """
    lambda_client = boto3.client(service_name='lambda', region_name='us-east-1')
    all_lambda_configs = {}
    function_index = 0

    try:
        if use_function_names:
            # Fetch specific functions by name - use indexed keys
            for function_name in identifier:
                function_index += 1
                try:
                    function_config = lambda_client.get_function(FunctionName=function_name)
                    if 'Code' in function_config:
                        del function_config['Code']
                    
                    all_lambda_configs[f"lambda_function_{function_index}"] = {
                        "compareIdentifier": function_name,
                        **function_config["Configuration"]
                    }
                    
                except lambda_client.exceptions.ResourceNotFoundException:
                    print(f"Lambda function not found: {function_name}")
                    continue
                except Exception as e:
                    print(f"Error fetching configuration for Lambda function {function_name}: {e}")
                    continue
        else:
            # Fetch all functions and filter by ApplicationShortName tag - use function names as keys
            paginator = lambda_client.get_paginator('list_functions')
            for page in paginator.paginate():
                for function in page['Functions']:
                    try:
                        # Get function tags
                        tags_response = lambda_client.list_tags(Resource=function['FunctionArn'])
                        tags = tags_response.get('Tags', {})
                        
                        # Check if function has matching ApplicationShortName tag
                        if tags.get('ApplicationShortName') == identifier:
                            function_config = lambda_client.get_function(FunctionName=function['FunctionName'])
                            if 'Code' in function_config:
                                del function_config['Code']
                            
                            # Use function name as key instead of indexed key
                            all_lambda_configs[function['FunctionName']] = {
                                **function_config["Configuration"]
                            }
                            

                    except Exception as e:
                        print(f"Error processing Lambda function {function['FunctionName']}: {e}")
                        continue

        if not all_lambda_configs:
            print(f"No Lambda functions found for {'function names' if use_function_names else 'ApplicationShortName'} = {identifier}")
            
        return all_lambda_configs
    except Exception as e:
        print(f"Error fetching Lambda configurations: {e}")
        sys.exit(1)


def fetch_elb_config(identifier, use_lb_names=False):
    """
    Fetches the configuration of EC2 load balancers either by load balancer names or ApplicationShortName.
    Returns load balancers with indexed keys or load balancer names as keys based on the mode.
    """
    elb_client = boto3.client('elbv2', region_name='us-east-1')
    all_elb_configs = {}
    elb_index = 0

    try:
        if use_lb_names:
            # Fetch specific load balancers by name - use indexed keys
            for lb_name in identifier:
                elb_index += 1
                try:
                    lb_details = elb_client.describe_load_balancers(Names=[lb_name])
                    for lb_config in lb_details['LoadBalancers']:
                        all_elb_configs[f"elb_{elb_index}"] = {
                            "compareIdentifier": lb_name,
                            **lb_config
                        }
                except elb_client.exceptions.LoadBalancerNotFoundException:
                    print(f"Load balancer not found: {lb_name}")
                    continue
                except Exception as e:
                    print(f"Error fetching configuration for load balancer {lb_name}: {e}")
                    continue
        else:
            # Fetch all load balancers and filter by ApplicationShortName tag - use load balancer names as keys
            paginator = elb_client.get_paginator('describe_load_balancers')
            for page in paginator.paginate():
                for lb in page['LoadBalancers']:
                    try:
                        # Get load balancer tags
                        tags_response = elb_client.describe_tags(ResourceArns=[lb['LoadBalancerArn']])
                        tags = tags_response.get('TagDescriptions', [])[0].get('Tags', [])
                        
                        # Check if load balancer has matching ApplicationShortName tag
                        for tag in tags:
                            if tag['Key'] == 'ApplicationShortName' and tag['Value'] == identifier:
                                all_elb_configs[lb['LoadBalancerName']] = lb
                                break

                    except Exception as e:
                        print(f"Error processing load balancer {lb['LoadBalancerName']}: {e}")
                        continue

        if not all_elb_configs:
            print(f"No EC2 load balancers found for {'load balancer names' if use_lb_names else 'ApplicationShortName'} = {identifier}")
            
        return all_elb_configs
    except Exception as e:
        print(f"Error fetching EC2 load balancer configurations: {e}")
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
                output_data['ecs'] = fetch_ecs_service_config(ecs_clusters, use_custom_identifier=True)
            
            # Fetch RDS configurations if rds array is not empty
            rds_instances = env_config.get('rds', [])
            if rds_instances:
                output_data['rds'] = fetch_rds_config(rds_instances, use_instance_ids=True)
            
            # Fetch Lambda configurations if lambda array is not empty
            lambda_functions = env_config.get('lambda', [])
            if lambda_functions:
                output_data['lambda'] = fetch_lambda_config(lambda_functions, use_function_names=True)
            else:
                output_data['lambda'] = fetch_lambda_config(ApplicationShortName, use_function_names=False)

            # Fetch Parameter Store configurations if parameterStore is true
            if env_config.get('parameterStore') is True:
                output_data['parameterStore'] = fetch_parameter_store_config(ApplicationShortName)
            
            # Fetch EC2 load balancer configurations if elb array is not empty
            elb_names = env_config.get('elb', [])
            if elb_names:
                output_data['elb'] = fetch_elb_config(elb_names, use_lb_names=True)
            else:
                output_data['elb'] = fetch_elb_config(ApplicationShortName, use_lb_names=False)
        else:
            # Fall back to original behavior
            cluster_name, cluster_arn = find_team_cluster(team_tag_key='ApplicationShortName', 
                                                        team_tag_value=ApplicationShortName)
            output_data = {
                'ecs': fetch_ecs_service_config([cluster_name], use_custom_identifier=False) if cluster_arn else {},
                'rds': fetch_rds_config(ApplicationShortName, use_instance_ids=False),
                'lambda': fetch_lambda_config(ApplicationShortName, use_function_names=False),
                'parameterStore': fetch_parameter_store_config(ApplicationShortName),
                'elb': fetch_elb_config(ApplicationShortName, use_lb_names=False)
            }

        # Write to the output file
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=4, cls=DateTimeEncoder)

        print(f"All configurations successfully written to {output_file}")

    except Exception as e:
        print(f"Error fetching configurations: {e}")
        sys.exit(1)
