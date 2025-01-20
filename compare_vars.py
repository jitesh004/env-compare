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

# Function to write comparisons to HTML
def write_comparison_to_html(
    file_name, comparison_results, summary, template_path, output_file, env1, env2, missing_in_env=None, file1_path="", file2_path=""
):
    try:
        html_content = ""
        legend_html = ""
        table = ""

        if summary:
            legend_html = f"""
            <hr style="border: 1px solid black; width: 100%; margin-top: 16px;">
            <h3 style="text-decoration: underline;">Comparison Report - {file_name}</h3>
            <p><strong>Comparing Files:</strong> {file1_path} & {file2_path}</p>
            <div style="display: flex; gap: 12px">
                <p><strong><span style="color: #3cc257;">&#9679;</span> Equal Variables:</strong> {summary['equal']}</p>
                <p><strong><span style="color: #d4b022;">&#9679;</span> Undefined Variables:</strong> {summary['undefined']}</p>
                <p><strong><span style="color: rgb(241, 83, 83);">&#9679;</span> Red Variables (Check Required):</strong> {summary['red']}</p>
                <p><strong><span style="color: rgb(26, 179, 230);">&#9679;</span> Blue Variables (Environment Specific):</strong> {summary['blue']}</p>
            </div>
            """
        else:
            legend_html = f"""
                <hr style="border: 1px solid black; width: 100%; margin-top: 16px;">
                <h3 style="text-decoration: underline;">Comparison Report - {file_name}</h3>
            """

        if missing_in_env:
            rows = f"<p style='color:red;'>File <strong>{file_name}</strong> is missing in {missing_in_env.upper()}</p>"
            table = f"""<div>{rows}</div>"""
        else:
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

            table = f"""
            <table>
                <tr>
                    <th>Key</th>
                    <th>{env1.upper()}</th>
                    <th>{env2.upper()}</th>
                    <th>Comparison</th>
                    <th>Status</th>
                </tr>
                {rows}
            </table>
            """

        html_content = f"""{legend_html}{table}"""

        with open("temp.html", "a") as file:
            file.write(html_content)

        logging.info(f"Comparison report successfully written to {output_file}")
    except FileNotFoundError:
        logging.error(f"Template file not found: {template_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error writing to HTML file {output_file}: {str(e)}")
        sys.exit(1)

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
        # Erase previous file data
        with open("temp.html", "w") as file:
            file.write("")

        with open(template_path, "r") as template_file:
            template = template_file.read()
            with open(output_file, "w") as file:
                file.write(template)

        write_summary_to_html(
            output_file, env1, env2, branch_name, commit_id, commit_message
        )

        if isJsonCompare:
            # Compare JSON files
            if not os.path.exists(json_file1_path) or not os.path.exists(json_file2_path):
                logging.error(f"One or both JSON files not found: {json_file1_path}, {json_file2_path}")
                sys.exit(1)

            logging.info(f"Comparing JSON files: {json_file1_path} and {json_file2_path}")
            data1 = parse_json(json_file1_path)
            data2 = parse_json(json_file2_path)

            sections = set(data1.keys()).union(set(data2.keys()))
            tabs_html = '<div class="tabs">'
            content_html = '<div class="tab-content">'
            for section in sections:
                section_id = section.replace("/", "_")
                tabs_html += f'<button class="tab-link" onclick="openTab(event, \'{section_id}\')">{section.upper()}</button>'
                content_html += f'<div id="{section_id}" class="tab-pane">'
                if isinstance(data1.get(section), dict) and all(isinstance(v, dict) for v in data1[section].values()):
                    for key in data1[section].keys() | data2[section].keys():
                        sub_data1 = data1[section].get(key, {})
                        sub_data2 = data2[section].get(key, {})
                        comparison_results, summary = compare_tfvars_data(sub_data1, sub_data2, env1, env2)
                        content_html += f'<button class="accordion">{key}</button>'
                        content_html += f'<div class="panel">'
                        content_html += f'<h3>{section.upper()} - {key}</h3>'
                        content_html += f'<div>{write_comparison_to_html(f"{section}_{key}", comparison_results, summary, template_path, output_file, env1, env2, file1_path=json_file1_path, file2_path=json_file2_path)}</div>'
                        content_html += '</div>'
                else:
                    comparison_results, summary = compare_tfvars_data(data1.get(section, {}), data2.get(section, {}), env1, env2)
                    content_html += f'<h3>{section.upper()}</h3>'
                    content_html += f'<div>{write_comparison_to_html(section, comparison_results, summary, template_path, output_file, env1, env2, file1_path=json_file1_path, file2_path=json_file2_path)}</div>'
                content_html += '</div>'
            tabs_html += '</div>'
            content_html += '</div>'

            with open("temp.html", "a") as file:
                file.write(tabs_html + content_html)

        elif isConfigCompare:
            # Compare .properties files
            env1_path = os.path.join(config_directory_path, env1)
            env2_path = os.path.join(config_directory_path, env2)

            if not os.path.exists(env1_path) or not os.path.exists(env2_path):
                logging.error(f"One or both environment directories not found: {env1_path}, {env2_path}")
                sys.exit(1)

            # Dynamically find all .properties files in both env1 and env2 directories
            env1_files = [f for f in os.listdir(env1_path) if f.endswith(".properties")]
            env2_files = [f for f in os.listdir(env2_path) if f.endswith(".properties")]

            # Union of all files in both env1 and env2
            all_files = set(env1_files).union(set(env2_files))

            # Iterate over all .properties files and compare or handle missing files
            for properties_file in all_files:
                file1_path = os.path.join(env1_path, properties_file)
                file2_path = os.path.join(env2_path, properties_file)

                if properties_file in env1_files and properties_file not in env2_files:
                    logging.warning(f"{properties_file} missing in {env2}")
                    write_comparison_to_html(
                        properties_file,
                        None,
                        None,
                        template_path,
                        output_file,
                        env1,
                        env2,
                        missing_in_env=env2,
                        file1_path=file1_path,
                        file2_path=file2_path,
                    )
                elif properties_file in env2_files and properties_file not in env1_files:
                    logging.warning(f"{properties_file} missing in {env1}")
                    write_comparison_to_html(
                        properties_file,
                        None,
                        None,
                        template_path,
                        output_file,
                        env1,
                        env2,
                        missing_in_env=env1,
                        file1_path=file1_path,
                        file2_path=file2_path,
                    )
                else:
                    logging.info(f"Comparing {properties_file} between {env1} and {env2}")
                    data1 = parse_properties(file1_path)
                    data2 = parse_properties(file2_path)

                    comparison_results, summary = compare_properties_data(
                        data1, data2, env1, env2
                    )
                    write_comparison_to_html(
                        properties_file,
                        comparison_results,
                        summary,
                        template_path,
                        output_file,
                        env1,
                        env2,
                        file1_path=file1_path,
                        file2_path=file2_path,
                    )

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
            write_comparison_to_html(
                "tfvars",
                comparison_results,
                summary,
                template_path,
                output_file,
                env1,
                env2,
                file1_path=file1_path,
                file2_path=file2_path,
            )

        with open("temp.html", "r") as tables:
            table_output = tables.read()
        with open(output_file, "r") as output:
            output_content = output.read()
            html_content = output_content.replace("{body}", table_output)
        with open(output_file, "w") as final_output:
            final_output.write(html_content)

        os.remove("temp.html")

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


