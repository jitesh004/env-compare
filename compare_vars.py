import os
import hcl2
from deepdiff import DeepDiff
import json
import sys
import logging

# Setup Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

def sanitize_id(text):
    """Sanitize text to be used as an ID by replacing invalid characters"""
    return text.replace('/', '-').replace(' ', '-').replace(',', '').replace('(', '').replace(')', '')

# Function to escape HTML characters
def escape_html(text):
    escape_table = {
        "&": "&amp;",
        '"': "&quot;",
        "'": "&#x27;",
        ">": "&gt;",
        "<": "&lt;",
    }
    return "".join(escape_table.get(c, c) for c in text)

# Function to parse .json files
def parse_json(file_path):
    try:
        with open(file_path, "r") as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing JSON file {file_path}: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error processing {file_path}: {str(e)}")
        sys.exit(1)

# Function to parse .tfvars files
def parse_tfvars(file_path):
    try:
        with open(file_path, "r") as file:
            data = hcl2.load(file)
            return data
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error parsing {file_path}: {str(e)}")
        sys.exit(1)

# Function to parse .properties files
def parse_properties(file_path):
    try:
        properties = {}
        with open(file_path, "r") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    properties[key.strip()] = value.strip()
        return properties
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error parsing {file_path}: {str(e)}")
        sys.exit(1)

# Differentiating environment-specific keys
def is_environment_specific(key, env1, env2):
    environment_specific_keys = [
        "account",
        "region",
        "profile",
        "environment",
        "env",
        "url",
        "endpoint",
        "database_name",
        "bucket_name",
        "s3",
        "created",
        "time",
        "arn",
    ]
    environment_indicators = [env1.lower(), env2.lower(), "prod", "staging", "dev"]

    if any(indicator in key.lower() for indicator in environment_indicators):
        return True
    if any(es_key in key.lower() for es_key in environment_specific_keys):
        return True
    return False

# Extract diff
def extract_diff(diff, value1, value2, key_path):
    def format_key(path):
        return (
            path.replace("root.", "")
            .replace("root[", "[")
            .replace("]", "]")
            .replace("'", "")
        )

    def handle_nested_diffs(old_value, new_value, base_key=""):
        diffs = []
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            for k, v in old_value.items():
                if k in new_value and new_value[k] != v:
                    nested_key = f"{base_key}.{k}" if base_key else k
                    diffs.extend(handle_nested_diffs(v, new_value[k], nested_key))
                elif k not in new_value:
                    nested_key = f"{base_key}.{k}" if base_key else k
                    diffs.append(f"{nested_key}: {v} was removed")
            for k, v in new_value.items():
                if k not in old_value:
                    nested_key = f"{base_key}.{k}" if base_key else k
                    diffs.append(f"{nested_key}: {v} was added")
        elif isinstance(old_value, list) and isinstance(new_value, list):
            for i, (old_item, new_item) in enumerate(zip(old_value, new_value)):
                if old_item != new_item:
                    nested_key = f"{base_key}[{i}]" if base_key else str(i)
                    diffs.extend(handle_nested_diffs(old_item, new_item, nested_key))
            if len(old_value) < len(new_value):
                for i in range(len(old_value), len(new_value)):
                    nested_key = f"{base_key}[{i}]" if base_key else str(i)
                    diffs.append(f"{nested_key}: {new_value[i]} was added")
            elif len(old_value) > len(new_value):
                for i in range(len(new_value), len(old_value)):
                    nested_key = f"{base_key}[{i}]" if base_key else str(i)
                    diffs.append(f"{nested_key}: {old_value[i]} was removed")
        else:
            if isinstance(old_value, str) and isinstance(new_value, str):
                old_parts = old_value.split(".")
                new_parts = new_value.split(".")
                differences = [
                    f"{o} => {n}" for o, n in zip(old_parts, new_parts) if o != n
                ]
                diffs.extend([f"{base_key}: {diff}" for diff in differences])
            else:
                diffs.append(f"{base_key}: {old_value} => {new_value}")
        return diffs

    if "values_changed" in diff:
        changes = diff["values_changed"]
        diffs = []
        for path, change in changes.items():
            old_value = change["old_value"]
            new_value = change["new_value"]
            key = format_key(path)
            diffs.extend(handle_nested_diffs(old_value, new_value, key))
        return "\n".join(diffs)
    elif "iterable_item_removed" in diff or "iterable_item_added" in diff:
        diffs = []
        for change_type in ["iterable_item_removed", "iterable_item_added"]:
            if change_type in diff:
                for path, change in diff[change_type].items():
                    key = format_key(path)
                    diffs.append(
                        f"{key}: {change} was {change_type.replace('iterable_item_', '')}"
                    )
        return "\n".join(diffs)
    else:
        return f"{value1} => {value2}"

# Function to compare .tfvars data
def compare_tfvars_data(data1, data2, env1, env2):
    try:
        # Filter out compareIdentifier from both data sets
        data1_filtered = {k: v for k, v in data1.items() if k != 'compareIdentifier'}
        data2_filtered = {k: v for k, v in data2.items() if k != 'compareIdentifier'}
        
        all_keys = set(data1_filtered.keys()).union(set(data2_filtered.keys()))
        all_keys = sorted(all_keys, key=str.lower)
        comparison_results = []
        summary = {"equal": 0, "undefined": 0, "red": 0, "blue": 0}
        
        for key in all_keys:
            value1 = data1_filtered.get(key, "undefined")
            value2 = data2_filtered.get(key, "undefined")
            key_path = key

            if value1 != "undefined" and value2 != "undefined":
                diff = DeepDiff(value1, value2, ignore_order=True)
                if diff:
                    exact_diff = extract_diff(diff, value1, value2, key_path)
                    row_class = (
                        "blue"
                        if is_environment_specific(key_path, env1, env2)
                        else "red"
                    )
                    status = (
                        "Values differ as expected for environments"
                        if row_class == "blue"
                        else "Unexpected difference, please review"
                    )
                    summary["blue" if row_class == "blue" else "red"] += 1
                else:
                    exact_diff = ""
                    row_class = "equal"
                    status = "Equal"
                    summary["equal"] += 1
            elif value1 == "undefined":
                exact_diff = f"{key} is not defined in {env1.upper()}"
                row_class = "yellow"
                status = f"Not defined in {env1.upper()}"
                summary["undefined"] += 1
            else:
                exact_diff = f"{key} is not defined in {env2.upper()}"
                row_class = "yellow"
                status = f"Not defined in {env2.upper()}"
                summary["undefined"] += 1
            comparison_results.append(
                {
                    "key": key,
                    "value1": json.dumps(value1, indent=2),
                    "value2": json.dumps(value2, indent=2),
                    "exact_diff": exact_diff,
                    "row_class": row_class,
                    "status": status,
                }
            )
        return comparison_results, summary
    except Exception as e:
        logging.error(f"Error during comparison: {str(e)}")
        sys.exit(1)

# Function to compare .properties files
def compare_properties_data(data1, data2, env1, env2):
    try:
        all_keys = set(data1.keys()).union(set(data2.keys()))
        all_keys = sorted(all_keys, key=str.lower)
        comparison_results = []
        summary = {"equal": 0, "undefined": 0, "red": 0, "blue": 0}

        for key in all_keys:
            value1 = data1.get(key, "undefined")
            value2 = data2.get(key, "undefined")
            key_path = key

            if value1 != "undefined" and value2 != "undefined":
                diff = DeepDiff(value1, value2, ignore_order=True)
                if diff:
                    exact_diff = extract_diff(diff, value1, value2, key_path)
                    row_class = (
                        "blue"
                        if is_environment_specific(key_path, env1, env2)
                        else "red"
                    )
                    status = (
                        "Values differ as expected for environments"
                        if row_class == "blue"
                        else "Unexpected difference, please review"
                    )
                    summary["blue" if row_class == "blue" else "red"] += 1
                else:
                    exact_diff = ""
                    row_class = "equal"
                    status = "Equal"
                    summary["equal"] += 1
            elif value1 == "undefined":
                exact_diff = f"{key} is not defined in {env1.upper()}"
                row_class = "yellow"
                status = f"Not defined in {env1.upper()}"
                summary["undefined"] += 1
            else:
                exact_diff = f"{key} is not defined in {env2.upper()}"
                row_class = "yellow"
                status = f"Not defined in {env2.upper()}"
                summary["undefined"] += 1

            comparison_results.append(
                {
                    "key": key,
                    "value1": json.dumps(value1, indent=2),
                    "value2": json.dumps(value2, indent=2),
                    "exact_diff": exact_diff,
                    "row_class": row_class,
                    "status": status,
                }
            )

        return comparison_results, summary
    except Exception as e:
        logging.error(f"Error during comparison: {str(e)}")
        sys.exit(1)

# Function to write summary to HTML
def write_summary_to_html(output_file, env1, env2, branch_name, commit_id, commit_message):
    try:
        with open(output_file, "r") as output:
            template = output.read()

        summary_html = f"""
        <h3>Summary</h3>
        <p><strong>Branch:</strong> {escape_html(branch_name)}</p>
        <p><strong>Latest Commit:</strong> {escape_html(commit_id)} - {escape_html(commit_message)}</p>
        <p><strong>Comparing ENVs:</strong> {env1.upper()} & {env2.upper()}</p>
        """
        html_content = template.replace("{summary}", summary_html)

        with open(output_file, "w") as file:
            file.write(html_content)

        logging.info(f"Summary successfully written to {output_file}")
    except Exception as e:
        logging.error(f"Error writing to HTML file {output_file}: {str(e)}")
        sys.exit(1)

def generate_tabs(sections):
    """Generate HTML for tab navigation"""
    tabs_html = ""
    for i, section in enumerate(sections):
        active = 'active' if i == 0 else ''
        tabs_html += f"""
        <li class="nav-item" role="presentation">
            <button class="nav-link {active}" id="tab-{section.lower()}" 
                    data-bs-toggle="tab" data-bs-target="#content-{section.lower()}" 
                    type="button" role="tab">
                {section}
            </button>
        </li>
        """
    return tabs_html

def write_comparison_to_html(
    section_name, subsection_name, comparison_results, summary, 
    template_path, output_file, env1, env2, missing_in_env=None, 
    file1_path="", file2_path=""):
    try:
        if missing_in_env:
            content = f"""
            <div class="alert alert-warning">
                File is missing in {missing_in_env.upper()}
            </div>
            """
        else:
            # Generate comparison table
            rows = ""
            for comparison in comparison_results:
                key = comparison["key"]
                value1 = escape_html(comparison["value1"])
                value2 = escape_html(comparison["value2"])
                exact_diff = escape_html(comparison["exact_diff"]) if comparison["exact_diff"] else ""
                row_class = comparison["row_class"]
                status = comparison["status"]

                rows += f"""
                <tr class="{row_class}">
                    <td>{escape_html(key)}</td>
                    <td><pre>{value1}</pre></td>
                    <td><pre>{value2}</pre></td>
                    <td><pre>{exact_diff}</pre></td>
                    <td class="status">{status}</td>
                </tr>
                """

            # Generate statistics
            stats = f"""
            <div class="comparison-stats">
                <div class="stat-item"><span class="stat-dot equal-dot"></span> Equal: {summary['equal']}</div>
                <div class="stat-item"><span class="stat-dot undefined-dot"></span> Undefined: {summary['undefined']}</div>
                <div class="stat-item"><span class="stat-dot red-dot"></span> Check Required: {summary['red']}</div>
                <div class="stat-item"><span class="stat-dot blue-dot"></span> Environment Specific: {summary['blue']}</div>
            </div>
            """

            content = f"""
            {stats}
            <table class="table table-bordered">
                <thead>
                    <tr>
                        <th>Key</th>
                        <th>{env1.upper()}</th>
                        <th>{env2.upper()}</th>
                        <th>Comparison</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
            """

        accordion_item = f"""
        <div class="accordion-item">
            <h2 class="accordion-header" id="heading-{section_name.lower()}-{subsection_name.lower()}">
                <button class="accordion-button" type="button" data-bs-toggle="collapse" 
                        data-bs-target="#collapse-{section_name.lower()}-{subsection_name.lower()}">
                    {subsection_name}
                </button>
            </h2>
            <div id="collapse-{section_name.lower()}-{subsection_name.lower()}" 
                 class="accordion-collapse collapse" 
                 data-bs-parent="#accordion-{section_name.lower()}">
                <div class="accordion-body">
                    {content}
                </div>
            </div>
        </div>
        """

        with open("temp.html", "a") as file:
            file.write(accordion_item)

    except Exception as e:
        logging.error(f"Error writing to HTML file: {str(e)}")
        sys.exit(1)
        
        
def is_nested_dict(data):
    """Check if the dictionary has nested dictionaries as values"""
    return bool(data) and all(isinstance(v, dict) for v in data.values())

def generate_accordion_item(section, subsection, comparison_results, summary, env1, env2, missing_in_env=None, compare_identifier=None):
    """Generate HTML for an accordion item"""
    # Sanitize the IDs
    accordion_id = f"collapse-{sanitize_id(section.lower())}-{sanitize_id(subsection.lower())}"
    
    # Format the title with compareIdentifier if present
    title = subsection
    if compare_identifier:
        title = f"{subsection} ({compare_identifier})"
    
    if missing_in_env or not comparison_results:
        return f"""
        <div class="accordion-item">
            <h2 class="accordion-header" id="heading-{accordion_id}">
                <button class="accordion-button collapsed" type="button" 
                        data-bs-target="#{accordion_id}" 
                        aria-expanded="false" 
                        aria-controls="{accordion_id}">
                    {title}
                </button>
            </h2>
            <div id="{accordion_id}" class="accordion-collapse collapse">
                <div class="accordion-body">
                    <div class="alert alert-warning">
                        {f"File is missing in {missing_in_env.upper()}" if missing_in_env else "No data available"}
                    </div>
                </div>
            </div>
        </div>
        """

    # Generate table rows
    rows = ""
    for comparison in comparison_results:
        key = comparison["key"]
        value1 = escape_html(comparison["value1"])
        value2 = escape_html(comparison["value2"])
        exact_diff = escape_html(comparison["exact_diff"]) if comparison["exact_diff"] else ""
        row_class = comparison["row_class"]
        status = comparison["status"]

        rows += f"""
        <tr class="{row_class}">
            <td>{escape_html(key)}</td>
            <td><pre>{value1}</pre></td>
            <td><pre>{value2}</pre></td>
            <td><pre>{exact_diff}</pre></td>
            <td class="status">{status}</td>
        </tr>
        """

    # Update the comparison stats section with proper data attributes
    stats_html = f"""
    <div class="comparison-stats">
        <div class="stat-item" data-filter="equal" role="button" title="Click to filter Equal items">
            <span class="stat-dot equal-dot"></span>
            <span>Equal: {summary['equal']}</span>
        </div>
        <div class="stat-item" data-filter="yellow" role="button" title="Click to filter Undefined items">
            <span class="stat-dot undefined-dot"></span>
            <span>Undefined: {summary['undefined']}</span>
        </div>
        <div class="stat-item" data-filter="red" role="button" title="Click to filter Check Required items">
            <span class="stat-dot red-dot"></span>
            <span>Check Required: {summary['red']}</span>
        </div>
        <div class="stat-item" data-filter="blue" role="button" title="Click to filter Environment Specific items">
            <span class="stat-dot blue-dot"></span>
            <span>Environment Specific: {summary['blue']}</span>
        </div>
    </div>
    """

    return f"""
    <div class="accordion-item">
        <h2 class="accordion-header" id="heading-{accordion_id}">
            <button class="accordion-button collapsed" type="button" 
                    data-bs-target="#{accordion_id}" 
                    aria-expanded="false" 
                    aria-controls="{accordion_id}">
                {title}
            </button>
        </h2>
        <div id="{accordion_id}" class="accordion-collapse collapse">
            <div class="accordion-body">
                {stats_html}
                <div class="table-container">
                    <table class="table">
                        <thead>
                            <tr>
                                <th style="width: 20%">Key</th>
                                <th style="width: 20%">{env1.upper()}</th>
                                <th style="width: 20%">{env2.upper()}</th>
                                <th style="width: 25%">Comparison</th>
                                <th style="width: 15%">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    """
    
# Function to handle both .tfvars and .properties comparisons
def main(
    env1,
    env2,
    template_path,
    output_file,
    config_directory_path,
    branch_name,
    commit_id,
    commit_message,
    isConfigCompare,
    isJsonCompare,
    json_file1_path,
    json_file2_path,
):
    try:
        if isJsonCompare:
            data1 = parse_json(json_file1_path)
            data2 = parse_json(json_file2_path)

            # Generate summary without branch and commit info for JSON comparison
            summary_html = f"""
            <h3>Summary</h3>
            <p><strong>Comparing ENVs:</strong> {env1.upper()} & {env2.upper()}</p>
            """

            # Generate tabs
            sections = list(data1.keys())
            tabs_html = generate_tabs(sections)

            # Initialize the output file with the template
            with open(template_path, "r") as template_file:
                template = template_file.read()
                template = template.replace("{tabs}", tabs_html)
                template = template.replace("{summary}", summary_html)
                with open(output_file, "w") as file:
                    file.write(template)

            # Create a string to store all tab content
            all_tab_content = ""

            # Process each section
            for section in sections:
                section_html = f"""
                <div class="tab-pane fade" id="content-{section.lower()}" role="tabpanel">
                    <div class="accordion" id="accordion-{section.lower()}" data-bs-parent="#comparisonTabsContent">
                """

                # Process the section content
                if is_nested_dict(data1[section]):
                    # Handle nested structure (like ecs and rds)
                    for subsection in data1[section].keys():
                        # Get compareIdentifier if it exists
                        compare_identifier = None
                        if isinstance(data1[section][subsection], dict):
                            compare_identifier = data1[section][subsection].get('compareIdentifier')
                            
                        comparison_results, summary = compare_tfvars_data(
                            data1[section][subsection],
                            data2[section].get(subsection, {}),
                            env1,
                            env2
                        )
                        
                        # Generate accordion item HTML with compareIdentifier
                        accordion_item = generate_accordion_item(
                            section,
                            subsection,
                            comparison_results,
                            summary,
                            env1,
                            env2,
                            compare_identifier=compare_identifier
                        )
                        section_html += accordion_item
                else:
                    # Handle flat structure (like parameterStore)
                    # Get compareIdentifier if it exists
                    compare_identifier = data1[section].get('compareIdentifier') if isinstance(data1[section], dict) else None
                    
                    comparison_results, summary = compare_tfvars_data(
                        data1[section],
                        data2.get(section, {}),
                        env1,
                        env2
                    )
                    
                    # Generate accordion item HTML with compareIdentifier
                    accordion_item = generate_accordion_item(
                        section,
                        "Configuration",
                        comparison_results,
                        summary,
                        env1,
                        env2,
                        compare_identifier=compare_identifier
                    )
                    section_html += accordion_item

                # Close section divs
                section_html += "</div></div>"
                all_tab_content += section_html

            # Replace the {body} placeholder with all tab content
            with open(output_file, "r") as file:
                content = file.read()
            
            content = content.replace("{body}", all_tab_content)
            
            with open(output_file, "w") as file:
                file.write(content)

        elif isConfigCompare:
            # Compare .properties files
            env1_path = os.path.join(config_directory_path, env1)
            env2_path = os.path.join(config_directory_path, env2)

            if not os.path.exists(env1_path) or not os.path.exists(env2_path):
                logging.error(f"One or both environment directories not found: {env1_path}, {env2_path}")
                sys.exit(1)

            # Generate summary
            summary_html = f"""
            <h3>Summary</h3>
            <p><strong>Branch:</strong> {escape_html(branch_name)}</p>
            <p><strong>Latest Commit:</strong> {escape_html(commit_id)} - {escape_html(commit_message)}</p>
            <p><strong>Comparing ENVs:</strong> {env1.upper()} & {env2.upper()}</p>
            """

            # Initialize the output file with the template
            with open(template_path, "r") as template_file:
                template = template_file.read()
                template = template.replace("{summary}", summary_html)
                with open(output_file, "w") as file:
                    file.write(template)

            # Dynamically find all .properties files
            env1_files = [f for f in os.listdir(env1_path) if f.endswith(".properties")]
            env2_files = [f for f in os.listdir(env2_path) if f.endswith(".properties")]
            all_files = set(env1_files).union(set(env2_files))

            all_content = ""
            for properties_file in all_files:
                file1_path = os.path.join(env1_path, properties_file)
                file2_path = os.path.join(env2_path, properties_file)

                if properties_file in env1_files and properties_file not in env2_files:
                    all_content += generate_accordion_item(
                        "properties",
                        properties_file,
                        None,
                        None,
                        env1,
                        env2,
                        missing_in_env=env2
                    )
                elif properties_file in env2_files and properties_file not in env1_files:
                    all_content += generate_accordion_item(
                        "properties",
                        properties_file,
                        None,
                        None,
                        env1,
                        env2,
                        missing_in_env=env1
                    )
                else:
                    data1 = parse_properties(file1_path)
                    data2 = parse_properties(file2_path)
                    comparison_results, summary = compare_properties_data(data1, data2, env1, env2)
                    all_content += generate_accordion_item(
                        "properties",
                        properties_file,
                        comparison_results,
                        summary,
                        env1,
                        env2
                    )

            # Replace the {body} placeholder with all content
            with open(output_file, "r") as file:
                content = file.read()
            
            content = content.replace("{body}", f"""
                <div class="accordion" id="accordion-properties">
                    {all_content}
                </div>
            """)
            
            with open(output_file, "w") as file:
                file.write(content)

        else:
            # Compare .tfvars files
            file1_path = f"{config_directory_path}/workspace_vars.{env1.lower()}.tfvars"
            file2_path = f"{config_directory_path}/workspace_vars.{env2.lower()}.tfvars"

            if not os.path.exists(file1_path) or not os.path.exists(file2_path):
                logging.error(f"File not found: {file1_path} or {file2_path}")
                sys.exit(1)

            data1 = parse_tfvars(file1_path)
            data2 = parse_tfvars(file2_path)

            comparison_results, summary = compare_tfvars_data(data1, data2, env1, env2)
            
            # Generate summary
            summary_html = f"""
            <h3>Summary</h3>
            <p><strong>Branch:</strong> {escape_html(branch_name)}</p>
            <p><strong>Latest Commit:</strong> {escape_html(commit_id)} - {escape_html(commit_message)}</p>
            <p><strong>Comparing ENVs:</strong> {env1.upper()} & {env2.upper()}</p>
            """

            # Initialize the output file with the template
            with open(template_path, "r") as template_file:
                template = template_file.read()
                template = template.replace("{summary}", summary_html)
                with open(output_file, "w") as file:
                    file.write(template)

            accordion_content = generate_accordion_item(
                "tfvars",
                "Configuration",
                comparison_results,
                summary,
                env1,
                env2
            )

            # Replace the {body} placeholder with accordion content
            with open(output_file, "r") as file:
                content = file.read()
            
            content = content.replace("{body}", f"""
                <div class="accordion" id="accordion-tfvars">
                    {accordion_content}
                </div>
            """)
            
            with open(output_file, "w") as file:
                file.write(content)

    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        sys.exit(1)
        
        
if __name__ == "__main__":
    if len(sys.argv) < 10:
        logging.error(
            "Usage: python compare_vars.py <env1> <env2> <template_path> <output_file> <config_directory_path> <branch_name> <commit_id> <commit_message> <isConfigCompare> <isJsonCompare> <json_file1_path> <json_file2_path>"
        )
        sys.exit(1)

    env1 = sys.argv[1]
    env2 = sys.argv[2]
    template_path = sys.argv[3]
    output_file = sys.argv[4]
    config_directory_path = sys.argv[5]
    branch_name = sys.argv[6]
    commit_id = sys.argv[7]
    commit_message = sys.argv[8]
    isConfigCompare = sys.argv[9].lower() == "true"
    isJsonCompare = sys.argv[10].lower() == "true"
    json_file1_path = sys.argv[11]
    json_file2_path = sys.argv[12]

    logging.info(
        f"env1: {env1}, env2: {env2}, config_directory_path: {config_directory_path}, template_path: {template_path}, output_file: {output_file}, branch: {branch_name}, commit_id: {commit_id}, commit_message: {commit_message}, isConfigCompare: {isConfigCompare}, isJsonCompare: {isJsonCompare}, json_file1_path: {json_file1_path}, json_file2_path: {json_file2_path}"
    )

    main(
        env1,
        env2,
        template_path,
        output_file,
        config_directory_path,
        branch_name,
        commit_id,
        commit_message,
        isConfigCompare,
        isJsonCompare,
        json_file1_path,
        json_file2_path,
    )


